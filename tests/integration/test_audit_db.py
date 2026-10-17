"""Audit log against real PostgreSQL: trigger blocks tampering; verify detects forced tamper."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from aqta.audit import GENESIS_HASH, SqlAuditLog
from aqta.audit.__main__ import main as audit_cli
from aqta.audit.__main__ import run_verify
from aqta.core.clock import FrozenClock
from aqta.core.db import SessionFactory

pytestmark = pytest.mark.integration


async def _seed(log: SqlAuditLog, clock: FrozenClock, n: int = 3) -> None:
    for i in range(n):
        clock.advance(seconds=1)
        await log.record("test.event", {"i": i, "note": "ünïcode ₹"}, actor="tester")


async def test_record_chains_rows(session_factory: SessionFactory, clock: FrozenClock) -> None:
    log = SqlAuditLog(session_factory, clock)
    first = await log.record("system.start", {"mode": "paper"}, actor="system")
    assert first.prev_hash == GENESIS_HASH
    await _seed(log, clock)
    entries = await log.entries()
    assert len(entries) == 4
    assert entries[1].prev_hash == entries[0].hash
    result = await log.verify()
    assert result.ok, result.errors


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET actor = 'mallory'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
async def test_trigger_rejects_mutation(
    session_factory: SessionFactory, engine: AsyncEngine, clock: FrozenClock, statement: str
) -> None:
    log = SqlAuditLog(session_factory, clock)
    await _seed(log, clock)
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(text(statement))
    assert (await log.verify()).ok


async def test_risk_events_append_only(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO risk_events (occurred_at, event_type, severity, actor) "
                "VALUES (now(), 'test', 'info', 'tester')"
            )
        )
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM risk_events"))


async def test_verify_detects_forced_tamper(
    session_factory: SessionFactory, engine: AsyncEngine, clock: FrozenClock, migrated_db: str
) -> None:
    log = SqlAuditLog(session_factory, clock)
    await _seed(log, clock, n=4)
    assert await run_verify(migrated_db) == 0

    # Simulate a privileged attacker who bypasses the trigger (superuser/table owner).
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
        await conn.execute(text("UPDATE audit_log SET payload = '{\"i\": 42}'::jsonb WHERE id = 2"))
        await conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))

    result = await log.verify()
    assert not result.ok
    assert any("seq=2" in e for e in result.errors)
    assert await run_verify(migrated_db) == 1


async def test_astrology_weight_check_constraint(engine: AsyncEngine) -> None:
    """RULE-014 is also enforced by the database: non-active rules cannot carry weight."""
    with pytest.raises(DBAPIError, match="ck_astrology_rules_weight_zero_unless_active"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO astrology_rules (id, family, origin, status, weight, hypothesis,"
                    " test_plan, approved_at, created_at, updated_at) VALUES ('r1', 'mundane',"
                    " 'seed', 'shadow', 0.5, '{}', '{}', now(), now(), now())"
                )
            )
    with pytest.raises(DBAPIError, match="ck_astrology_rules_weight_needs_approval"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO astrology_rules (id, family, origin, status, weight, hypothesis,"
                    " test_plan, created_at, updated_at) VALUES ('r2', 'mundane', 'seed',"
                    " 'active', 0.5, '{}', '{}', now(), now())"
                )
            )


def test_cli_verify_on_fresh_db(migrated_db: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert audit_cli(["verify", "--database-url", migrated_db]) == 0
    assert "audit chain OK: 0 entries" in capsys.readouterr().out
