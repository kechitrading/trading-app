"""Kill switch (FR-034, FR-035, NFR-005).

Redis is the fast path read on every order; the DB row is durable. Reads fail closed: if the store
cannot be read, the switch is treated as active and orders are blocked.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aqta.audit import AuditSink
from aqta.core.clock import Clock
from aqta.core.logs import get_logger
from aqta.risk.events import RiskEvent, RiskEventSink, RiskEventType, Severity

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    active: bool
    updated_at: datetime
    actor: str
    reason: str | None = None


class KillSwitchStore(Protocol):
    async def get(self) -> KillSwitchState | None: ...

    async def set(self, state: KillSwitchState) -> None: ...


class InMemoryKillSwitchStore:
    def __init__(self) -> None:
        self.state: KillSwitchState | None = None
        self.fail_reads = False  # test hook

    async def get(self) -> KillSwitchState | None:
        if self.fail_reads:
            raise ConnectionError("store unavailable")
        return self.state

    async def set(self, state: KillSwitchState) -> None:
        self.state = state


OnTrigger = Callable[[KillSwitchState], Awaitable[None]]


class KillSwitch:
    def __init__(
        self,
        fast: KillSwitchStore,
        audit: AuditSink,
        events: RiskEventSink,
        clock: Clock,
        durable: KillSwitchStore | None = None,
    ) -> None:
        self._fast = fast
        self._durable = durable
        self._audit = audit
        self._events = events
        self._clock = clock
        self._on_trigger: list[OnTrigger] = []

    def register_on_trigger(self, callback: OnTrigger) -> None:
        """Execution registers 'cancel all open orders' here (risk never imports execution)."""
        self._on_trigger.append(callback)

    async def state(self) -> KillSwitchState | None:
        try:
            current = await self._fast.get()
        except Exception as exc:
            log.error("kill_switch.read_failed", error=str(exc))
            await self._events.emit(
                RiskEvent(
                    self._clock.now(),
                    RiskEventType.KILL_SWITCH_STORE_ERROR,
                    Severity.CRITICAL,
                    actor="system",
                    reason=f"fast store read failed: {exc}; failing closed",
                )
            )
            return KillSwitchState(True, self._clock.now(), "system", "kill-switch store unreadable")
        if current is None and self._durable is not None:
            current = await self._durable.get()
            if current is not None:
                await self._fast.set(current)  # warm Redis after a restart
        return current

    async def is_active(self) -> bool:
        current = await self.state()
        return current is not None and current.active

    async def trigger(self, actor: str, reason: str) -> KillSwitchState:
        new = KillSwitchState(True, self._clock.now(), actor, reason)
        await self._persist(new)
        await self._audit.record(
            "kill_switch.triggered", {"actor": actor, "reason": reason}, actor=actor
        )
        await self._events.emit(
            RiskEvent(new.updated_at, RiskEventType.KILL_SWITCH_TRIGGERED, Severity.CRITICAL,
                      actor, reason)
        )
        for callback in self._on_trigger:
            try:
                await callback(new)
            except Exception as exc:  # keep going: the switch itself is already active
                log.error("kill_switch.callback_failed", error=str(exc))
        return new

    async def release(self, actor: str, reason: str) -> KillSwitchState:
        if not reason.strip():
            raise ValueError("Releasing the kill switch requires a recorded reason")
        new = KillSwitchState(False, self._clock.now(), actor, reason)
        await self._persist(new)
        await self._audit.record(
            "kill_switch.released", {"actor": actor, "reason": reason}, actor=actor
        )
        await self._events.emit(
            RiskEvent(new.updated_at, RiskEventType.KILL_SWITCH_RELEASED, Severity.WARNING,
                      actor, reason)
        )
        return new

    async def _persist(self, state: KillSwitchState) -> None:
        if self._durable is not None:
            await self._durable.set(state)
        await self._fast.set(state)
