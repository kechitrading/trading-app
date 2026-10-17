"""Signals: components and the composite signal (BR-009, FR-006..FR-010, FR-049, FR-073).

RULE-013: analysis informs proposals only through this composite; it never reaches risk/execution.
"""

from aqta.signals.base import ComponentFamily, ComponentValue, SignalComponent
from aqta.signals.components import StubComponent, default_components
from aqta.signals.composite import (
    DEFAULT_WEIGHTS,
    CompositeResult,
    Contribution,
    WeightSet,
    combine,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "ComponentFamily",
    "ComponentValue",
    "CompositeResult",
    "Contribution",
    "SignalComponent",
    "StubComponent",
    "WeightSet",
    "combine",
    "default_components",
]
