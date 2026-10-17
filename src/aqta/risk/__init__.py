"""Risk controls (BR-004, FR-031..FR-037). Safety-critical; mypy strict; >= 95% coverage.

Never imports signals, forecasting, astrology or analysis (RULE-013, import-linter contract).

Public API:
- ``PreTradeRiskEngine.evaluate(order) -> RiskDecision``
- ``KillSwitch`` (trigger/release/is_active, fail-closed)
- ``RiskHalts`` (daily-loss block, drawdown halt + logged reset)
- ``RiskLimits``, ``RiskSnapshot``, ``RiskStateProvider``
"""

from aqta.risk.checks import CheckName, CheckResult, DuplicateGuard, OrderRateLimiter
from aqta.risk.engine import PreTradeRiskEngine, RiskDecision
from aqta.risk.events import (
    InMemoryRiskEventSink,
    RiskEvent,
    RiskEventSink,
    RiskEventType,
    Severity,
)
from aqta.risk.halts import RiskHalts
from aqta.risk.kill_switch import (
    InMemoryKillSwitchStore,
    KillSwitch,
    KillSwitchState,
    KillSwitchStore,
)
from aqta.risk.limits import RiskLimits
from aqta.risk.state import InMemoryRiskState, RiskSnapshot, RiskStateProvider

__all__ = [
    "CheckName",
    "CheckResult",
    "DuplicateGuard",
    "InMemoryKillSwitchStore",
    "InMemoryRiskEventSink",
    "InMemoryRiskState",
    "KillSwitch",
    "KillSwitchState",
    "KillSwitchStore",
    "OrderRateLimiter",
    "PreTradeRiskEngine",
    "RiskDecision",
    "RiskEvent",
    "RiskEventSink",
    "RiskEventType",
    "RiskHalts",
    "RiskLimits",
    "RiskSnapshot",
    "RiskStateProvider",
    "Severity",
]
