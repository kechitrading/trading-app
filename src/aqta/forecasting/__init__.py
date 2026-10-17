"""Probabilistic forecasts (BR-019, FR-066..FR-068, RULE-011, NFR-020, NFR-022).

Forecasts are percentile bands and scenarios only, always labelled as estimates. RULE-013: they
inform proposals only through the composite signal and never reach risk or execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

FORECAST_LABEL = "Probabilistic estimate, not a guarantee"  # FR-067
# Q-015 default: the 80% band (p10..p90) should contain 70-90% of outcomes over >= 30 forecasts.
COVERAGE_MIN, COVERAGE_MAX, MIN_MATURED = 0.70, 0.90, 30


class ForecastHorizon(StrEnum):
    INTRADAY = "intraday"
    WEEK = "1w"
    MONTH = "1m"
    QUARTER = "3m"


class Scenario(BaseModel):
    name: str  # base | bull | bear
    path: list[Decimal]
    drivers: list[str] = Field(default_factory=list)


class Forecast(BaseModel):
    symbol: str
    horizon: ForecastHorizon
    model_version: str
    data_snapshot_at: datetime
    target_at: datetime
    p10: Decimal
    p50: Decimal
    p90: Decimal
    scenarios: list[Scenario] = Field(default_factory=list)
    label: str = FORECAST_LABEL

    @model_validator(mode="after")
    def _ordered(self) -> Forecast:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("percentile bands must satisfy p10 <= p50 <= p90")
        return self


class ForecastModel(Protocol):
    version: str

    async def forecast(self, symbol: str, horizon: ForecastHorizon) -> Forecast: ...


class CoverageReport(BaseModel):
    matured: int
    coverage: float | None
    reliable: bool | None  # None until MIN_MATURED forecasts have matured


def band_coverage(outcomes: Sequence[tuple[Forecast, Decimal]]) -> CoverageReport:
    """FR-068: share of actual outcomes inside the 80% band, and the reliability flag."""
    n = len(outcomes)
    if n == 0:
        return CoverageReport(matured=0, coverage=None, reliable=None)
    inside = sum(1 for f, actual in outcomes if f.p10 <= actual <= f.p90)
    coverage = inside / n
    reliable = None if n < MIN_MATURED else COVERAGE_MIN <= coverage <= COVERAGE_MAX
    return CoverageReport(matured=n, coverage=coverage, reliable=reliable)


__all__ = [
    "FORECAST_LABEL",
    "CoverageReport",
    "Forecast",
    "ForecastHorizon",
    "ForecastModel",
    "Scenario",
    "band_coverage",
]
