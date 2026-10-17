from __future__ import annotations

from datetime import datetime

import pytest
from arq.cron import next_cron

from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.timeutil import IST
from aqta.worker import REGISTRY, WorkerSettings, cron_jobs

EXPECTED = {
    "pre_market_brief": (8, 30),
    "post_market_review": (17, 0),
    "mcx_wrap": (23, 45),
    "monthly_astrology_study": (6, 0),
    "weekly_learning_proposal": (10, 0),
}


def test_registry_times_are_ist() -> None:
    assert {j.name: (j.hour, j.minute) for j in REGISTRY} == EXPECTED
    assert WorkerSettings.timezone is IST
    assert {c.name for c in WorkerSettings.cron_jobs} == set(EXPECTED)
    assert len(cron_jobs()) == len(REGISTRY)


def _spec(name: str):  # type: ignore[no-untyped-def]
    return next(j for j in REGISTRY if j.name == name)


@pytest.mark.parametrize(
    ("name", "after", "expected"),
    [
        # Friday 23:50 IST -> next pre-market brief is Monday 08:30 IST.
        (
            "pre_market_brief",
            datetime(2026, 10, 23, 23, 50, tzinfo=IST),
            datetime(2026, 10, 26, 8, 30, tzinfo=IST),
        ),
        (
            "mcx_wrap",
            datetime(2026, 10, 20, 12, 0, tzinfo=IST),
            datetime(2026, 10, 20, 23, 45, tzinfo=IST),
        ),
        (
            "monthly_astrology_study",
            datetime(2026, 10, 20, 12, 0, tzinfo=IST),
            datetime(2026, 11, 1, 6, 0, tzinfo=IST),
        ),
        (
            "weekly_learning_proposal",
            datetime(2026, 10, 20, 12, 0, tzinfo=IST),
            datetime(2026, 10, 24, 10, 0, tzinfo=IST),
        ),
    ],
)
def test_next_run(name: str, after: datetime, expected: datetime) -> None:
    spec = _spec(name)
    nxt = next_cron(
        after,
        weekday=spec.weekday,
        day=spec.day,
        hour=spec.hour,
        minute=spec.minute,
        second=0,
        microsecond=0,
    )
    assert nxt == expected


async def test_jobs_log_and_audit(clock: FrozenClock) -> None:
    audit = InMemoryAuditLog(clock)
    for spec in REGISTRY:
        assert await spec.func({"audit": audit}) == spec.name
    entries = audit.of_type("job.ran")
    assert [e.payload["job"] for e in entries] == [j.name for j in REGISTRY]
    assert all(e.payload["status"] == "placeholder" for e in entries)
