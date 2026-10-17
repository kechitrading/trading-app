"""Injectable clock so tests can freeze time and market sessions.

All clocks return timezone-aware UTC datetimes (storage is always UTC; display is IST).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock for tests: stays put until ``advance``/``set`` is called."""

    def __init__(self, at: datetime) -> None:
        self._now = _require_aware(at).astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, at: datetime) -> None:
        self._now = _require_aware(at).astimezone(UTC)

    def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        self._now += delta if delta is not None else timedelta(**kwargs)
        return self._now


def _require_aware(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("Clock datetimes must be timezone-aware")
    return at
