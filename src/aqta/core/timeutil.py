"""IST helpers. Rule: store UTC, display and schedule in IST (Asia/Kolkata)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as aware UTC. Naive datetimes are rejected to avoid silent tz bugs."""
    if dt.tzinfo is None:
        raise ValueError("Naive datetime: attach a timezone before storing")
    return dt.astimezone(UTC)


def to_ist(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(IST)


def ist_date(dt: datetime) -> date:
    """Trading date in IST for a UTC instant (daily limits reset on IST dates)."""
    return to_ist(dt).date()


def ist_datetime(d: date, t: time) -> datetime:
    """Combine an IST calendar date and wall time into an aware UTC datetime."""
    return datetime.combine(d, t, tzinfo=IST).astimezone(UTC)


def format_ist(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S IST") -> str:
    return to_ist(dt).strftime(fmt)
