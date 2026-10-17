"""Data ingestion ports and the staleness checker (BR-001, FR-001..FR-004, FR-057, FR-058).

Adapters (broker feed, NSE/BSE/MCX files, Finnhub, RSS) come later; no network calls here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from aqta.core.trading import Exchange


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: Exchange
    ltp: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    at: datetime  # exchange timestamp, UTC


class NewsItem(BaseModel):
    """FR-003: stored with timestamp, source, URL and a duplicate hash."""

    model_config = ConfigDict(frozen=True)

    source: str
    url: str
    title: str
    published_at: datetime
    dedupe_hash: str
    body: str = ""


class MacroObservation(BaseModel):
    series: str
    value: Decimal
    period: date
    available_at: datetime  # keep data date and availability date (RULE-012, Section 10)


class MarketDataPort(Protocol):
    """FR-001: quotes, option chains and OI from the broker feed."""

    async def quotes(self, symbols: Iterable[str]) -> list[Quote]: ...


class ExchangeDataPort(Protocol):
    """FR-002, FR-057, FR-058: bhavcopy, FII/DII, participant OI, bulk/block deals."""

    async def fetch_daily(self, exchange: Exchange, day: date) -> dict[str, object]: ...


class NewsPort(Protocol):
    """FR-003: RSS, official sites, Finnhub, transcripts."""

    async def latest(self, since: datetime) -> list[NewsItem]: ...


class MacroPort(Protocol):
    async def observations(self, series: str, since: date) -> list[MacroObservation]: ...


class FeedHealth(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    MISSING = "missing"


class FeedStatus(BaseModel):
    feed: str
    health: FeedHealth
    last_seen: datetime | None
    age_seconds: float | None


def check_staleness(
    feed: str, last_seen: datetime | None, now: datetime, max_age: timedelta = timedelta(seconds=60)
) -> FeedStatus:
    """FR-004: a feed older than ``max_age`` (default 60 s) is degraded; never seen is missing."""
    if last_seen is None:
        return FeedStatus(feed=feed, health=FeedHealth.MISSING, last_seen=None, age_seconds=None)
    age = (now - last_seen).total_seconds()
    health = FeedHealth.OK if age <= max_age.total_seconds() else FeedHealth.DEGRADED
    return FeedStatus(feed=feed, health=health, last_seen=last_seen, age_seconds=age)


__all__ = [
    "ExchangeDataPort",
    "FeedHealth",
    "FeedStatus",
    "MacroObservation",
    "MacroPort",
    "MarketDataPort",
    "NewsItem",
    "NewsPort",
    "Quote",
    "check_staleness",
]
