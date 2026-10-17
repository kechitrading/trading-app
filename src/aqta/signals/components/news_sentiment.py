"""News and speech sentiment per market/sector/instrument with confidence and source links (FR-003, FR-006).

Stub: returns a neutral reading. TODO: implement in the feature ticket for this component.
"""

from __future__ import annotations

from aqta.signals.base import ComponentFamily
from aqta.signals.components._stub import StubComponent


class NewsSentimentComponent(StubComponent):
    def __init__(self) -> None:
        super().__init__(ComponentFamily.NEWS_SENTIMENT)
