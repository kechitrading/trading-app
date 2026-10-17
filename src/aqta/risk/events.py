"""Risk events and the sink port that persists them (risk_events table, alerts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class RiskEventType(StrEnum):
    PRE_TRADE_BLOCKED = "pre_trade_blocked"
    DAILY_LOSS_BLOCK = "daily_loss_block"
    DRAWDOWN_HALT = "drawdown_halt"
    DRAWDOWN_RESET = "drawdown_reset"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
    KILL_SWITCH_RELEASED = "kill_switch_released"
    KILL_SWITCH_STORE_ERROR = "kill_switch_store_error"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class RiskEvent:
    occurred_at: datetime
    event_type: RiskEventType
    severity: Severity
    actor: str
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class RiskEventSink(Protocol):
    async def emit(self, event: RiskEvent) -> None: ...


class InMemoryRiskEventSink:
    def __init__(self) -> None:
        self.events: list[RiskEvent] = []

    async def emit(self, event: RiskEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: RiskEventType) -> list[RiskEvent]:
        return [e for e in self.events if e.event_type is event_type]
