"""Strategy registry and promotion state machine (FR-051, RULE-005, BR-011).

Path: draft -> backtest -> paper -> live, with retire from anywhere and demotion live -> paper.
Skipping a step (e.g. draft -> live) is rejected, and each promotion needs its evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aqta.audit import AuditSink
from aqta.core.clock import Clock
from aqta.core.errors import InvalidTransitionError, NotFoundError
from aqta.core.ids import new_id

MIN_PAPER_PERIOD = timedelta(days=90)  # "3-month paper results" (RULE-005, RULE-009)


class StrategyStatus(StrEnum):
    DRAFT = "draft"
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"
    RETIRED = "retired"


_ALLOWED: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.DRAFT: frozenset({StrategyStatus.BACKTEST, StrategyStatus.RETIRED}),
    StrategyStatus.BACKTEST: frozenset(
        {StrategyStatus.PAPER, StrategyStatus.DRAFT, StrategyStatus.RETIRED}
    ),
    StrategyStatus.PAPER: frozenset(
        {StrategyStatus.LIVE, StrategyStatus.BACKTEST, StrategyStatus.RETIRED}
    ),
    StrategyStatus.LIVE: frozenset({StrategyStatus.PAPER, StrategyStatus.RETIRED}),
    StrategyStatus.RETIRED: frozenset(),
}


class Approval(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor: str
    at: datetime
    note: str = ""


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    backtest_report_id: str | None = None
    backtest_net_of_costs: bool = False
    paper_started_at: datetime | None = None
    paper_ended_at: datetime | None = None
    paper_report_id: str | None = None


class Strategy(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    version: int = 1
    status: StrategyStatus = StrategyStatus.DRAFT
    rule_set: dict[str, Any] = Field(default_factory=dict)  # written rules (RULE-005)
    loss_cap_inr: Decimal | None = None
    undefined_risk_approved: bool = False  # RULE-004: needs explicit per-strategy approval
    evidence: Evidence = Field(default_factory=Evidence)
    approval: Approval | None = None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidTransitionError(message)


def check_promotion(strategy: Strategy, to: StrategyStatus, approval: Approval | None) -> None:
    _require(
        to in _ALLOWED[strategy.status],
        f"strategy {strategy.name}: {strategy.status} -> {to} not allowed (RULE-005)",
    )
    ev = strategy.evidence
    if to is StrategyStatus.BACKTEST:
        _require(bool(strategy.rule_set), "written rule set required before backtest")
    elif to is StrategyStatus.PAPER and strategy.status is StrategyStatus.BACKTEST:
        _require(
            ev.backtest_report_id is not None and ev.backtest_net_of_costs,
            "net-of-cost backtest evidence required before paper (FR-046)",
        )
    elif to is StrategyStatus.LIVE:
        _require(
            ev.paper_started_at is not None
            and ev.paper_ended_at is not None
            and ev.paper_ended_at - ev.paper_started_at >= MIN_PAPER_PERIOD
            and ev.paper_report_id is not None,
            "3 months of paper results required before live (RULE-005, RULE-009)",
        )
        _require(approval is not None, "Kashyap's approval required before live (RULE-005)")
        _require(strategy.loss_cap_inr is not None, "loss cap required before live (FR-051)")


class StrategyRegistry:
    """In-memory registry. TODO(FR-051): persist to the ``strategies`` table."""

    def __init__(self, audit: AuditSink, clock: Clock) -> None:
        self._audit = audit
        self._clock = clock
        self._items: dict[str, Strategy] = {}

    def get(self, strategy_id: str) -> Strategy:
        try:
            return self._items[strategy_id]
        except KeyError:
            raise NotFoundError(f"strategy {strategy_id} not found") from None

    def all(self) -> list[Strategy]:
        return list(self._items.values())

    async def register(self, name: str, rule_set: dict[str, Any], actor: str) -> Strategy:
        strategy = Strategy(id=new_id("strat"), name=name, rule_set=rule_set)
        self._items[strategy.id] = strategy
        await self._audit.record("strategy.registered", {"id": strategy.id, "name": name}, actor)
        return strategy

    async def update(self, strategy: Strategy, actor: str, **changes: Any) -> Strategy:
        """Edit evidence/limits without changing status (status only moves via ``promote``)."""
        if "status" in changes:
            raise InvalidTransitionError("use promote() to change status")
        updated = strategy.model_copy(update=changes)
        self._items[strategy.id] = updated
        await self._audit.record(
            "strategy.updated", {"id": strategy.id, "fields": sorted(changes)}, actor
        )
        return updated

    async def promote(
        self, strategy_id: str, to: StrategyStatus, actor: str, approval: Approval | None = None
    ) -> Strategy:
        current = self.get(strategy_id)
        check_promotion(current, to, approval)
        promoted = current.model_copy(
            update={"status": to, "approval": approval or current.approval}
        )
        self._items[strategy_id] = promoted
        await self._audit.record(
            "strategy.status_changed",
            {"id": strategy_id, "from": current.status.value, "to": to.value,
             "approved_by": approval.actor if approval else None},
            actor,
        )
        return promoted
