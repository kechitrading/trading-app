"""Analysis suite interfaces (BR-017, BR-018, FR-008, FR-059, FR-061..FR-065). No logic yet.

- option analysis: chain analytics, IV rank, skew, max pain, dealer gamma, payoff (FR-061)
- technical analysis: multi-timeframe trend/momentum/levels (FR-062)
- fundamental analysis: stocks (FR-063), indices and commodities (FR-064)
- institutional positioning map, always labelled lagged/estimated (FR-059, RULE-012)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

LAG_LABEL = "lagged and estimated, not real-time holdings"  # FR-059 / RULE-012


class OptionChainSummary(BaseModel):
    underlying: str
    expiry: date
    as_of: datetime
    pcr: Decimal | None = None
    max_pain: Decimal | None = None
    iv_rank: float | None = Field(default=None, ge=0, le=100)
    atm_iv: float | None = None
    skew_25d: float | None = None
    dealer_gamma_exposure: Decimal | None = None


class TechnicalSnapshot(BaseModel):
    symbol: str
    timeframe: str  # e.g. "5m", "1h", "1d"
    as_of: datetime
    trend: str | None = None
    supports: list[Decimal] = Field(default_factory=list)
    resistances: list[Decimal] = Field(default_factory=list)
    rsi: float | None = None


class FundamentalSnapshot(BaseModel):
    symbol: str
    period: str
    source: str
    metrics: dict[str, Decimal] = Field(default_factory=dict)


class InstitutionalPosition(BaseModel):
    instrument: str
    score: float = Field(ge=-1, le=1)  # accumulation (+) vs distribution (-)
    data_date: date
    available_at: datetime
    components: dict[str, float] = Field(default_factory=dict)
    label: str = LAG_LABEL


class OptionAnalyzer(Protocol):
    async def chain_summary(self, underlying: str, expiry: date) -> OptionChainSummary: ...


class TechnicalAnalyzer(Protocol):
    async def snapshot(self, symbol: str, timeframe: str) -> TechnicalSnapshot: ...


class FundamentalAnalyzer(Protocol):
    async def snapshot(self, symbol: str) -> FundamentalSnapshot: ...


class InstitutionalMap(Protocol):
    async def position(self, instrument: str) -> InstitutionalPosition: ...


__all__ = [
    "LAG_LABEL",
    "FundamentalAnalyzer",
    "FundamentalSnapshot",
    "InstitutionalMap",
    "InstitutionalPosition",
    "OptionAnalyzer",
    "OptionChainSummary",
    "TechnicalAnalyzer",
    "TechnicalSnapshot",
]
