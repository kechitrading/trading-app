"""Stock, index and commodity fundamentals and macro drivers (FR-063, FR-064).

Stub: returns a neutral reading. TODO: implement in the feature ticket for this component.
"""

from __future__ import annotations

from aqta.signals.base import ComponentFamily
from aqta.signals.components._stub import StubComponent


class FundamentalComponent(StubComponent):
    def __init__(self) -> None:
        super().__init__(ComponentFamily.FUNDAMENTAL)
