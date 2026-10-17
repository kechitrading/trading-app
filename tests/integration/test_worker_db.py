"""Worker boot hooks against real PostgreSQL: startup wires the SQL audit log; jobs write to it."""

from __future__ import annotations

from typing import Any

import pytest

from aqta.audit import SqlAuditLog
from aqta.core.settings import get_settings
from aqta.worker import REGISTRY
from aqta.worker.settings import shutdown, startup

pytestmark = pytest.mark.integration


async def test_startup_runs_jobs_and_audits(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    ctx: dict[str, Any] = {}
    try:
        await startup(ctx)
        for spec in REGISTRY:
            await spec.func(ctx)
        audit: SqlAuditLog = ctx["audit"]
        kinds = [e.event_type for e in await audit.entries()]
        assert kinds[0] == "worker.started"
        assert kinds.count("job.ran") == len(REGISTRY)
        assert (await audit.verify()).ok
    finally:
        await shutdown(ctx)
        get_settings.cache_clear()
