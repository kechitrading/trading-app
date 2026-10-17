"""Astrology research engine (BR-009, BR-020, FR-005, FR-055, FR-056, FR-070..FR-076).

Everything here runs in shadow mode with zero weight until a rule passes the ASM-013 accuracy gate
and Kashyap approves it (RULE-014). Risk and execution must never import this package (RULE-013).
"""

from aqta.astrology.ports import (
    EphemerisPort,
    MundaneEvent,
    PlanetPosition,
    StudyReport,
    StudyRunner,
)
from aqta.astrology.registry import (
    AstrologyRule,
    GateResult,
    RuleFamily,
    RuleOrigin,
    RuleStatus,
    change_status,
    effective_weight,
)

__all__ = [
    "AstrologyRule",
    "EphemerisPort",
    "GateResult",
    "MundaneEvent",
    "PlanetPosition",
    "RuleFamily",
    "RuleOrigin",
    "RuleStatus",
    "StudyReport",
    "StudyRunner",
    "change_status",
    "effective_weight",
]
