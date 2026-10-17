"""The single registry of scheduled jobs. All times are IST (the worker runs with tz=Asia/Kolkata).

TODO(FR-038): skip exchange holidays via MarketCalendar inside each job (crons only know weekdays).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from arq import cron
from arq.cron import CronJob

from aqta.worker import jobs

WEEKDAYS = {0, 1, 2, 3, 4}  # Monday=0 ... Friday=4
JobFunc = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class JobSpec:
    name: str
    func: JobFunc
    hour: int
    minute: int
    weekday: set[int] | int | None = None
    day: int | None = None
    brd: str = ""


REGISTRY: tuple[JobSpec, ...] = (
    JobSpec("pre_market_brief", jobs.pre_market_brief, 8, 30, WEEKDAYS, brd="FR-038"),
    JobSpec("post_market_review", jobs.post_market_review, 17, 0, WEEKDAYS, brd="FR-039"),
    JobSpec("mcx_wrap", jobs.mcx_wrap, 23, 45, WEEKDAYS, brd="FR-039"),
    JobSpec("monthly_astrology_study", jobs.monthly_astrology_study, 6, 0, day=1, brd="FR-074"),
    JobSpec("weekly_learning_proposal", jobs.weekly_learning_proposal, 10, 0, 5, brd="FR-047"),
)


def cron_jobs(registry: tuple[JobSpec, ...] = REGISTRY) -> list[CronJob]:
    return [
        cron(
            spec.func,  # type: ignore[arg-type]
            name=spec.name,
            hour=spec.hour,
            minute=spec.minute,
            weekday=spec.weekday,
            day=spec.day,
            second=0,
            microsecond=0,
            unique=True,
        )
        for spec in registry
    ]
