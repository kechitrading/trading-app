"""FII/DII/MF positioning score: lagged and estimated, not real-time holdings.

BRD: FR-059, FR-060, RULE-012.

Stub: returns a neutral reading. TODO: implement in the feature ticket for this component.
"""

from __future__ import annotations

from aqta.signals.base import ComponentFamily
from aqta.signals.components._stub import StubComponent


class InstitutionalFlowComponent(StubComponent):
    def __init__(self) -> None:
        super().__init__(ComponentFamily.INSTITUTIONAL_FLOW)
