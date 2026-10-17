"""Trend, volatility, IV, skew, term structure and OI build-up features (FR-008, FR-062).

Stub: returns a neutral reading. TODO: implement in the feature ticket for this component.
"""

from __future__ import annotations

from aqta.signals.base import ComponentFamily
from aqta.signals.components._stub import StubComponent


class QuantTechnicalComponent(StubComponent):
    def __init__(self) -> None:
        super().__init__(ComponentFamily.QUANT_TECHNICAL)
