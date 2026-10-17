from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from aqta.core.clock import FrozenClock, SystemClock
from aqta.core.market_calendar import MarketCalendar, StaticHolidayCalendar
from aqta.core.settings import MarketSessionSettings
from aqta.core.timeutil import IST, ensure_utc, format_ist, ist_date, ist_datetime, to_ist
from aqta.core.trading import Exchange


def test_ist_conversion_round_trip() -> None:
    utc = datetime(2026, 10, 20, 3, 45, tzinfo=UTC)
    ist = to_ist(utc)
    assert ist.hour == 9 and ist.minute == 15
    assert ist.utcoffset() == timedelta(hours=5, minutes=30)
    assert ist_datetime(date(2026, 10, 20), time(9, 15)) == utc
    assert format_ist(utc) == "2026-10-20 09:15:00 IST"


def test_ist_date_rolls_over_before_utc() -> None:
    # 19:00 UTC on the 20th is already the 21st in IST.
    assert ist_date(datetime(2026, 10, 20, 19, 0, tzinfo=UTC)) == date(2026, 10, 21)


def test_naive_datetimes_rejected() -> None:
    with pytest.raises(ValueError, match="Naive"):
        ensure_utc(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="aware"):
        FrozenClock(datetime(2026, 1, 1))


def test_frozen_clock_advances_and_sets() -> None:
    c = FrozenClock(datetime(2026, 1, 1, tzinfo=IST))
    assert c.now().tzinfo is UTC
    c.advance(seconds=5)
    c.advance(timedelta(minutes=1))
    assert c.now() == datetime(2025, 12, 31, 18, 31, 5, tzinfo=UTC)
    c.set(datetime(2027, 1, 1, tzinfo=UTC))
    assert c.now().year == 2027


def test_system_clock_is_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def _at_ist(d: date, h: int, m: int) -> datetime:
    return ist_datetime(d, time(h, m))


def test_market_sessions(clock: FrozenClock) -> None:
    tue = date(2026, 10, 20)
    cal = MarketCalendar(clock)
    assert cal.is_open(Exchange.NSE)  # fixture clock: Tue 10:00 IST
    assert cal.is_open(Exchange.BSE, _at_ist(tue, 15, 30))
    assert not cal.is_open(Exchange.NSE, _at_ist(tue, 9, 14))
    assert not cal.is_open(Exchange.NSE, _at_ist(tue, 15, 31))
    assert cal.is_open(Exchange.MCX, _at_ist(tue, 9, 0))
    assert cal.is_open(Exchange.MCX, _at_ist(tue, 23, 30))
    assert not cal.is_open(Exchange.MCX, _at_ist(tue, 23, 31))
    sat = date(2026, 10, 24)
    assert not cal.is_trading_day(Exchange.NSE, sat)
    assert not cal.is_open(Exchange.NSE, _at_ist(sat, 10, 0))


def test_mcx_close_configurable_and_holidays(clock: FrozenClock) -> None:
    tue = date(2026, 10, 20)
    cal = MarketCalendar(
        clock,
        sessions=MarketSessionSettings(mcx_close=time(23, 55)),
        holidays=StaticHolidayCalendar({Exchange.NSE: [tue]}),
    )
    assert cal.is_open(Exchange.MCX, _at_ist(tue, 23, 50))
    assert not cal.is_open(Exchange.NSE)
    assert cal.is_trading_day(Exchange.MCX, tue)
    assert cal.session(Exchange.MCX).close == time(23, 55)
