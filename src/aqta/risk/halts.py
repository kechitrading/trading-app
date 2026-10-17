"""Daily-loss block (FR-032) and drawdown halt with logged reset (FR-033)."""

from __future__ import annotations

from datetime import date, datetime

from aqta.audit import AuditSink
from aqta.core.clock import Clock
from aqta.core.timeutil import ist_date
from aqta.risk.events import RiskEvent, RiskEventSink, RiskEventType, Severity
from aqta.risk.limits import RiskLimits
from aqta.risk.state import RiskSnapshot


class RiskHalts:
    """Tracks the two latched risk states.

    - Daily-loss block latches for the current IST trading date and clears on the next date.
    - Drawdown halt latches until ``reset_drawdown`` is called with a reason. A reset does not
      rebase the high-water mark: if drawdown is still at or above the limit, the next evaluation
      halts again. (Rebasing is a policy decision left to Kashyap; see ADR-0005.)
    """

    def __init__(
        self, limits: RiskLimits, clock: Clock, events: RiskEventSink, audit: AuditSink
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._events = events
        self._audit = audit
        self._daily_block_on: date | None = None
        self._drawdown_halted = False

    def daily_blocked(self, now: datetime | None = None) -> bool:
        return self._daily_block_on == ist_date(now or self._clock.now())

    @property
    def drawdown_halted(self) -> bool:
        return self._drawdown_halted

    async def observe(self, snap: RiskSnapshot) -> None:
        """Latch halts from the latest snapshot and emit events on the transition only."""
        now = self._clock.now()
        if -snap.day_pnl_inr >= self._limits.daily_loss_limit_inr and not self.daily_blocked(now):
            self._daily_block_on = ist_date(now)
            await self._emit(
                RiskEventType.DAILY_LOSS_BLOCK,
                Severity.CRITICAL,
                f"day P&L {snap.day_pnl_inr} hit daily loss limit "
                f"{self._limits.daily_loss_limit_inr}",
            )
        if snap.drawdown_inr >= self._limits.max_drawdown_inr and not self._drawdown_halted:
            self._drawdown_halted = True
            await self._emit(
                RiskEventType.DRAWDOWN_HALT,
                Severity.CRITICAL,
                f"drawdown {snap.drawdown_inr} hit limit {self._limits.max_drawdown_inr}",
            )

    async def reset_drawdown(self, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("Drawdown reset requires a recorded reason (FR-033)")
        self._drawdown_halted = False
        await self._audit.record("risk.drawdown_reset", {"reason": reason}, actor=actor)
        await self._events.emit(
            RiskEvent(self._clock.now(), RiskEventType.DRAWDOWN_RESET, Severity.WARNING, actor,
                      reason)
        )

    async def _emit(self, kind: RiskEventType, severity: Severity, reason: str) -> None:
        await self._audit.record(f"risk.{kind.value}", {"reason": reason}, actor="risk")
        await self._events.emit(RiskEvent(self._clock.now(), kind, severity, "risk", reason))
