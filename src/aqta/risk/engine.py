"""Pre-trade risk pipeline (FR-031). Sits between approval and the broker port (safety rule 3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aqta.core.clock import Clock
from aqta.core.trading import OrderRequest
from aqta.risk.checks import (
    CheckResult,
    DuplicateGuard,
    OrderRateLimiter,
    check_daily_loss,
    check_drawdown,
    check_kill_switch,
    check_margin,
    check_max_loss,
    check_open_orders,
    check_price_band,
    check_quantity,
)
from aqta.risk.events import RiskEvent, RiskEventSink, RiskEventType, Severity
from aqta.risk.halts import RiskHalts
from aqta.risk.kill_switch import KillSwitch
from aqta.risk.limits import RiskLimits
from aqta.risk.state import RiskStateProvider


@dataclass(frozen=True, slots=True)
class RiskDecision:
    client_order_id: str
    results: tuple[CheckResult, ...]

    @property
    def approved(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def reasons(self) -> list[str]:
        return [f"{r.name}: {r.reason}" for r in self.failures]


class PreTradeRiskEngine:
    def __init__(
        self,
        limits: RiskLimits,
        state: RiskStateProvider,
        kill_switch: KillSwitch,
        halts: RiskHalts,
        events: RiskEventSink,
        clock: Clock,
    ) -> None:
        self._limits = limits
        self._state = state
        self._kill_switch = kill_switch
        self._halts = halts
        self._events = events
        self._clock = clock
        self._rate = OrderRateLimiter(limits.max_orders_per_second)
        self._dupes = DuplicateGuard(limits.duplicate_window_seconds)
        # Serialise evaluations so rate/duplicate reservations cannot race.
        self._lock = asyncio.Lock()

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    async def evaluate(self, order: OrderRequest) -> RiskDecision:
        async with self._lock:
            now = self._clock.now()
            snap = await self._state.snapshot()
            await self._halts.observe(snap)
            kill_active = await self._kill_switch.is_active()
            limits = self._limits
            results = (
                check_kill_switch(kill_active),
                check_drawdown(self._halts.drawdown_halted, snap, limits),
                check_daily_loss(order, self._halts.daily_blocked(now), snap, limits),
                check_max_loss(order, limits),
                check_margin(order, snap, limits),
                check_quantity(order, limits),
                check_price_band(order, limits),
                check_open_orders(snap, limits),
                self._dupes.check(order, now),
                self._rate.check(now),
            )
            decision = RiskDecision(order.client_order_id, results)
            if decision.approved:
                self._rate.record(now)
                self._dupes.record(order, now)
            else:
                await self._events.emit(
                    RiskEvent(
                        now,
                        RiskEventType.PRE_TRADE_BLOCKED,
                        Severity.WARNING,
                        actor="risk",
                        reason="; ".join(decision.reasons),
                        details={
                            "client_order_id": order.client_order_id,
                            "proposal_id": order.proposal_id,
                            "failed": [r.name.value for r in decision.failures],
                        },
                    )
                )
            return decision
