"""Signal components (stubs until their feature tickets land)."""

from __future__ import annotations

from aqta.signals.components._stub import StubComponent
from aqta.signals.components.astrology import MundaneAstrologyComponent, SarvatobhadraComponent
from aqta.signals.components.fundamental import FundamentalComponent
from aqta.signals.components.institutional_flow import InstitutionalFlowComponent
from aqta.signals.components.news_sentiment import NewsSentimentComponent
from aqta.signals.components.quant_technical import QuantTechnicalComponent


def default_components() -> list[StubComponent]:
    return [
        NewsSentimentComponent(),
        QuantTechnicalComponent(),
        InstitutionalFlowComponent(),
        FundamentalComponent(),
        SarvatobhadraComponent(),
        MundaneAstrologyComponent(),
    ]


__all__ = [
    "FundamentalComponent",
    "InstitutionalFlowComponent",
    "MundaneAstrologyComponent",
    "NewsSentimentComponent",
    "QuantTechnicalComponent",
    "SarvatobhadraComponent",
    "StubComponent",
    "default_components",
]
