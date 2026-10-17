"""Signal component interface (FR-006, FR-008, FR-009, FR-056, FR-059)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ComponentFamily(StrEnum):
    NEWS_SENTIMENT = "news_sentiment"
    QUANT_TECHNICAL = "quant_technical"
    INSTITUTIONAL_FLOW = "institutional_flow"
    FUNDAMENTAL = "fundamental"
    ASTROLOGY_SARVATOBHADRA = "astrology_sarvatobhadra"
    ASTROLOGY_MUNDANE = "astrology_mundane"

    @property
    def is_astrology(self) -> bool:
        return self in (ComponentFamily.ASTROLOGY_SARVATOBHADRA, ComponentFamily.ASTROLOGY_MUNDANE)


class ComponentValue(BaseModel):
    """One component's reading for one instrument. ``value`` is a bias in [-1, 1]."""

    model_config = ConfigDict(frozen=True)

    component: str
    family: ComponentFamily
    value: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    as_of: datetime
    degraded: bool = False  # FR-004: stale/missing data -> excluded from proposals
    evidence: tuple[str, ...] = ()  # source links (FR-010)


class SignalComponent(Protocol):
    name: str
    family: ComponentFamily

    async def compute(self, symbol: str, at: datetime) -> ComponentValue: ...
