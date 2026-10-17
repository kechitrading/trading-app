"""Market sessions and holiday calendar interface (NSE/BSE 09:15-15:30, MCX 09:00-23:30 IST)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol

from aqta.core.clock import Clock
from aqta.core.settings import MarketSessionSettings
from aqta.core.timeutil import to_ist
from aqta.core.trading import Exchange


@dataclass(frozen=True, slots=True)
class Session:
    open: time
    close: time

    def contains(self, t: time) -> bool:
        return self.open <= t <= self.close


class HolidayCalendar(Protocol):
    def is_holiday(self, exchange: Exchange, day: date) -> bool: ...


class StaticHolidayCalendar:
    """In-memory holiday list. TODO(FR-002): load exchange holiday files yearly."""

    def __init__(self, holidays: dict[Exchange, Iterable[date]] | None = None) -> None:
        self._holidays = {ex: set(days) for ex, days in (holidays or {}).items()}

    def is_holiday(self, exchange: Exchange, day: date) -> bool:
        return day in self._holidays.get(exchange, set())


class MarketCalendar:
    def __init__(
        self,
        clock: Clock,
        sessions: MarketSessionSettings | None = None,
        holidays: HolidayCalendar | None = None,
    ) -> None:
        cfg = sessions or MarketSessionSettings()
        self._clock = clock
        self._holidays = holidays or StaticHolidayCalendar()
        equity = Session(cfg.equity_open, cfg.equity_close)
        self._sessions = {
            Exchange.NSE: equity,
            Exchange.BSE: equity,
            Exchange.MCX: Session(cfg.mcx_open, cfg.mcx_close),
        }

    def session(self, exchange: Exchange) -> Session:
        return self._sessions[exchange]

    def is_trading_day(self, exchange: Exchange, day: date) -> bool:
        return day.weekday() < 5 and not self._holidays.is_holiday(exchange, day)

    def is_open(self, exchange: Exchange, at: datetime | None = None) -> bool:
        local = to_ist(at or self._clock.now())
        return self.is_trading_day(exchange, local.date()) and self.session(exchange).contains(
            local.time()
        )
