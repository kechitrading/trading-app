"""Arq worker settings: ``arq aqta.worker.WorkerSettings``."""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from aqta.audit import SqlAuditLog
from aqta.core.db import create_engine, create_session_factory
from aqta.core.logs import configure_logging, get_logger
from aqta.core.settings import get_settings
from aqta.core.timeutil import IST
from aqta.worker.registry import REGISTRY, cron_jobs

log = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    engine = create_engine(settings.database_url.get_secret_value())
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["audit"] = SqlAuditLog(create_session_factory(engine))
    await ctx["audit"].record(
        "worker.started", {"mode": settings.trading_mode.value, "jobs": [j.name for j in REGISTRY]},
        "worker",
    )
    log.info("worker.started", mode=settings.trading_mode.value)


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [spec.func for spec in REGISTRY]
    cron_jobs: ClassVar[list[Any]] = cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    timezone = IST
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url.get_secret_value())
    max_jobs = 4
    job_timeout = 600
