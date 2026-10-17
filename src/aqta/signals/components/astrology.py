"""Astrology components: Sarvatobhadra Chakra (FR-005) and mundane astrology (FR-055, FR-056).

Kept as two separate components with separate weights (BR-009, FR-049). Both always run in shadow
mode: the composite forces their weight to zero unless the governing rule is active, passed the
accuracy gate and was approved (RULE-014, FR-073).
"""

from __future__ import annotations

from aqta.signals.base import ComponentFamily
from aqta.signals.components._stub import StubComponent


class SarvatobhadraComponent(StubComponent):
    def __init__(self) -> None:
        super().__init__(ComponentFamily.ASTROLOGY_SARVATOBHADRA)


class MundaneAstrologyComponent(StubComponent):
    def __init__(self) -> None:
        super().__init__(ComponentFamily.ASTROLOGY_MUNDANE)
