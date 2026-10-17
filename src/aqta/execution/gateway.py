"""The one and only order gateway (safety rules 2 and 3).

Fixed flow: approval token -> pre-trade risk -> broker port -> audit. ``submit_order`` is the only
code path that may call ``BrokerPort.place_order``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from aqta.audit import AuditSink
from aqta.core.clock import Clock
from aqta.core.errors import SafetyViolationError
from aqta.core.ids import new_id
from aqta.core.logs import get_logger
from aqta.core.settings import Settings, TradingMode
from aqta.core.trading import OrderRequest
from aqta.execution.live import LiveBrokerStub
from aqta.execution.paper import PaperBroker
from aqta.execution.ports import BrokerError, BrokerOrderSnapshot, BrokerOrderStatus, BrokerPort
from aqta.execution.states import OrderEvent, OrderState, is_open, next_state
from aqta.proposals import ApprovalClaims, ApprovalTokenError, ApprovalTokenService
from aqta.risk import KillSwitchState, PreTradeRiskEngine

log = get_logger(__name__)
DEFAULT_BROKER_TIMEOUT_S = 5.0


class Stage(StrEnum):
    CONFIG = "config"
    APPROVAL = "approval"
    RISK = "risk"
    BROKER = "broker"


@dataclass(slots=True)
class ManagedOrder:
    id: str
    request: OrderRequest
    algo_tag: str
    mode: TradingMode
    broker: str
    approved_by: str
    created_at: datetime
    state: OrderState = OrderState.NEW
    broker_order_id: str | None = None
    filled_quantity: int = 0
    history: list[tuple[datetime, OrderEvent, OrderState]] = field(default_factory=list)

    def apply(self, event: OrderEvent, at: datetime) -> OrderState:
        self.state = next_state(self.state, event)
        self.history.append((at, event, self.state))
        return self.state


@dataclass(frozen=True, slots=True)
class OrderResult:
    accepted: bool
    client_order_id: str
    stage: Stage | None = None
    reasons: tuple[str, ...] = ()
    order: ManagedOrder | None = None

    @property
    def state(self) -> OrderState | None:
        return self.order.state if self.order else None


def select_broker(settings: Settings) -> BrokerPort:
    """Paper mode always gets the paper broker. Live needs the double opt-in in Settings."""
    if settings.trading_mode is TradingMode.PAPER:
        return PaperBroker()
    if not settings.live_trading_enabled:  # pragma: no cover - Settings already refuses this
        raise SafetyViolationError("live mode without LIVE_TRADING_ENABLED")
    return LiveBrokerStub()


class OrderGateway:
    def __init__(
        self,
        settings: Settings,
        broker: BrokerPort,
        tokens: ApprovalTokenService,
        risk: PreTradeRiskEngine,
        audit: AuditSink,
        clock: Clock,
        broker_timeout_s: float = DEFAULT_BROKER_TIMEOUT_S,
    ) -> None:
        if settings.trading_mode is TradingMode.PAPER and broker.is_live:
            raise SafetyViolationError("paper mode must never be wired to a live broker adapter")
        self._mode = settings.trading_mode
        self._default_tag = settings.algo_tag
        self._broker = broker
        self._tokens = tokens
        self._risk = risk
        self._audit = audit
        self._clock = clock
        self._timeout = broker_timeout_s
        self._orders: dict[str, ManagedOrder] = {}

    @property
    def mode(self) -> TradingMode:
        return self._mode

    @property
    def orders(self) -> dict[str, ManagedOrder]:
        return dict(self._orders)

    def open_orders(self) -> list[ManagedOrder]:
        return [o for o in self._orders.values() if is_open(o.state)]

    async def submit_order(self, order: OrderRequest, approval_token: str | None) -> OrderResult:
        base = {
            "client_order_id": order.client_order_id,
            "proposal_id": order.proposal_id,
            "mode": self._mode.value,
            "broker": self._broker.name,
        }

        algo_tag = order.algo_tag or self._default_tag
        if not algo_tag:
            return await self._reject(order, Stage.CONFIG, ["algo tag missing (FR-028)"], base)

        # 1. Approval (RULE-001, FR-024): valid, unexpired, bound to this payload, single-use.
        try:
            claims = await self._tokens.verify_and_consume(approval_token, order)
        except ApprovalTokenError as exc:
            return await self._reject(order, Stage.APPROVAL, [str(exc)], base)

        # 2. Pre-trade risk (FR-031..FR-034).
        decision = await self._risk.evaluate(order)
        if not decision.approved:
            return await self._reject(
                order, Stage.RISK, decision.reasons, {**base, "approved_by": claims.actor}
            )

        # 3. Broker port.
        managed = self._new_managed(order, algo_tag, claims)
        managed.apply(OrderEvent.SUBMIT, self._clock.now())
        await self._audit_order(
            "order.submitted",
            managed,
            {**base, "algo_tag": algo_tag, "approval_nonce": claims.nonce, "order": order},
        )
        try:
            ack = await asyncio.wait_for(
                self._broker.place_order(order, algo_tag), timeout=self._timeout
            )
        except TimeoutError:
            managed.apply(OrderEvent.TIMEOUT, self._clock.now())
            await self._audit_order("order.timed_out", managed, base)
            return OrderResult(
                False,
                order.client_order_id,
                Stage.BROKER,
                ("broker did not acknowledge in time",),
                managed,
            )
        except BrokerError as exc:
            managed.apply(OrderEvent.REJECT, self._clock.now())
            await self._audit_order("order.rejected", managed, {**base, "reason": str(exc)})
            return OrderResult(False, order.client_order_id, Stage.BROKER, (str(exc),), managed)

        managed.broker_order_id = ack.broker_order_id
        if not ack.accepted:
            managed.apply(OrderEvent.REJECT, self._clock.now())
            await self._audit_order("order.rejected", managed, {**base, "reason": ack.message})
            return OrderResult(False, order.client_order_id, Stage.BROKER, (ack.message,), managed)

        managed.apply(OrderEvent.ACK, self._clock.now())
        await self._audit_order("order.acknowledged", managed, base)
        await self._apply_snapshot(managed, await self._broker.get_order(ack.broker_order_id))
        return OrderResult(True, order.client_order_id, order=managed)

    async def cancel_all_open(self, reason: str, actor: str = "system") -> list[ManagedOrder]:
        """Kill-switch action (FR-034): send cancel requests for every open order."""
        cancelled: list[ManagedOrder] = []
        for managed in self.open_orders():
            if managed.state in (OrderState.CANCEL_PENDING, OrderState.PENDING_SUBMIT):
                continue
            managed.apply(OrderEvent.CANCEL_REQUEST, self._clock.now())
            ok = False
            if managed.broker_order_id is not None:
                try:
                    ok = await self._broker.cancel_order(managed.broker_order_id)
                except Exception as exc:
                    log.error("execution.cancel_failed", order_id=managed.id, error=str(exc))
            if ok:
                managed.apply(OrderEvent.CANCEL_CONFIRM, self._clock.now())
            await self._audit_order(
                "order.cancel_requested", managed, {"reason": reason, "confirmed": ok}, actor
            )
            cancelled.append(managed)
        return cancelled

    async def on_kill_switch(self, state: KillSwitchState) -> None:
        await self.cancel_all_open(f"kill switch: {state.reason}", actor=state.actor)

    async def _apply_snapshot(self, managed: ManagedOrder, snap: BrokerOrderSnapshot) -> None:
        now = self._clock.now()
        if snap.status is BrokerOrderStatus.REJECTED:
            managed.apply(OrderEvent.REJECT, now)
        elif snap.filled_quantity >= managed.request.quantity:
            managed.apply(OrderEvent.FILL, now)
        elif snap.filled_quantity > managed.filled_quantity:
            managed.apply(OrderEvent.PARTIAL_FILL, now)
        else:
            return
        managed.filled_quantity = snap.filled_quantity
        await self._audit_order(
            f"order.{managed.state.value}",
            managed,
            {
                "filled_quantity": snap.filled_quantity,
                "average_price": snap.average_price,
                "costs_inr": snap.costs_inr,
            },
        )

    def _new_managed(
        self, order: OrderRequest, algo_tag: str, claims: ApprovalClaims
    ) -> ManagedOrder:
        managed = ManagedOrder(
            id=new_id("ord"),
            request=order,
            algo_tag=algo_tag,
            mode=self._mode,
            broker=self._broker.name,
            approved_by=claims.actor,
            created_at=self._clock.now(),
        )
        self._orders[managed.id] = managed
        return managed

    async def _reject(
        self, order: OrderRequest, stage: Stage, reasons: list[str], base: dict[str, Any]
    ) -> OrderResult:
        await self._audit.record(
            "order.rejected", {**base, "stage": stage.value, "reasons": reasons}, actor="execution"
        )
        log.warning(
            "execution.order_rejected",
            stage=stage.value,
            reasons=reasons,
            client_order_id=order.client_order_id,
        )
        return OrderResult(False, order.client_order_id, stage, tuple(reasons))

    async def _audit_order(
        self, event: str, managed: ManagedOrder, extra: dict[str, Any], actor: str = "execution"
    ) -> None:
        await self._audit.record(
            event,
            {
                "order_id": managed.id,
                "state": managed.state.value,
                "broker_order_id": managed.broker_order_id,
                **extra,
            },
            actor=actor,
        )
