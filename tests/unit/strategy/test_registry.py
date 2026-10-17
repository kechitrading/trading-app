from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.errors import InvalidTransitionError, NotFoundError
from aqta.strategy import Approval, Evidence, StrategyRegistry, StrategyStatus

S = StrategyStatus


@pytest.fixture
def reg(clock: FrozenClock) -> StrategyRegistry:
    return StrategyRegistry(InMemoryAuditLog(clock), clock)


async def _ready_for_live(reg: StrategyRegistry, clock: FrozenClock) -> str:
    s = await reg.register("iron-condor-weekly", {"entry": "IV rank > 50"}, "kashyap")
    await reg.promote(s.id, S.BACKTEST, "kashyap")
    s = await reg.update(
        reg.get(s.id),
        "kashyap",
        evidence=Evidence(backtest_report_id="bt-1", backtest_net_of_costs=True),
    )
    await reg.promote(s.id, S.PAPER, "kashyap")
    start = clock.now()
    await reg.update(
        reg.get(s.id),
        "kashyap",
        loss_cap_inr=Decimal("10000"),
        evidence=Evidence(
            backtest_report_id="bt-1",
            backtest_net_of_costs=True,
            paper_started_at=start,
            paper_ended_at=start + timedelta(days=90),
            paper_report_id="pp-1",
        ),
    )
    return s.id


@pytest.mark.parametrize("target", [S.LIVE, S.PAPER])
async def test_skip_ahead_from_draft_rejected(
    reg: StrategyRegistry, clock: FrozenClock, target: StrategyStatus
) -> None:
    s = await reg.register("x", {"r": 1}, "kashyap")
    with pytest.raises(InvalidTransitionError, match="RULE-005"):
        await reg.promote(s.id, target, "kashyap", Approval(actor="kashyap", at=clock.now()))


async def test_backtest_needs_written_rules(reg: StrategyRegistry) -> None:
    s = await reg.register("empty", {}, "kashyap")
    with pytest.raises(InvalidTransitionError, match="written rule set"):
        await reg.promote(s.id, S.BACKTEST, "kashyap")


async def test_paper_needs_net_of_cost_backtest(reg: StrategyRegistry) -> None:
    s = await reg.register("x", {"r": 1}, "kashyap")
    await reg.promote(s.id, S.BACKTEST, "kashyap")
    with pytest.raises(InvalidTransitionError, match="backtest evidence"):
        await reg.promote(s.id, S.PAPER, "kashyap")


async def test_full_path_to_live(reg: StrategyRegistry, clock: FrozenClock) -> None:
    sid = await _ready_for_live(reg, clock)
    with pytest.raises(InvalidTransitionError, match="approval"):
        await reg.promote(sid, S.LIVE, "kashyap")
    live = await reg.promote(sid, S.LIVE, "kashyap", Approval(actor="kashyap", at=clock.now()))
    assert live.status is S.LIVE and live.approval is not None
    paused = await reg.promote(sid, S.PAPER, "kashyap")
    assert paused.status is S.PAPER
    retired = await reg.promote(sid, S.RETIRED, "kashyap")
    with pytest.raises(InvalidTransitionError):
        await reg.promote(retired.id, S.DRAFT, "kashyap")
    audit = reg._audit
    assert isinstance(audit, InMemoryAuditLog)
    assert len(audit.of_type("strategy.status_changed")) == 5


async def test_live_needs_three_months_paper_and_loss_cap(
    reg: StrategyRegistry, clock: FrozenClock
) -> None:
    sid = await _ready_for_live(reg, clock)
    s = reg.get(sid)
    short = s.evidence.model_copy(update={"paper_ended_at": clock.now() + timedelta(days=89)})
    await reg.update(s, "kashyap", evidence=short)
    ok = Approval(actor="kashyap", at=clock.now())
    with pytest.raises(InvalidTransitionError, match="3 months"):
        await reg.promote(sid, S.LIVE, "kashyap", ok)
    await reg.update(reg.get(sid), "kashyap", evidence=s.evidence, loss_cap_inr=None)
    with pytest.raises(InvalidTransitionError, match="loss cap"):
        await reg.promote(sid, S.LIVE, "kashyap", ok)


async def test_update_cannot_change_status_and_lookup(reg: StrategyRegistry) -> None:
    s = await reg.register("x", {"r": 1}, "kashyap")
    with pytest.raises(InvalidTransitionError):
        await reg.update(s, "kashyap", status=S.LIVE)
    with pytest.raises(NotFoundError):
        reg.get("missing")
    assert reg.all() == [s]
