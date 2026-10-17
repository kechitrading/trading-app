"""Risk SQL adapters: durable kill-switch state and append-only risk events."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from aqta.core.clock import FrozenClock
from aqta.core.db import SessionFactory
from aqta.risk import KillSwitchState, RiskEvent, RiskEventType, Severity
from aqta.risk.adapters import SqlKillSwitchStore, SqlRiskEventSink

pytestmark = pytest.mark.integration


async def test_sql_kill_switch_store_upserts_single_row(
    session_factory: SessionFactory, engine: AsyncEngine, clock: FrozenClock
) -> None:
    store = SqlKillSwitchStore(session_factory)
    assert await store.get() is None
    await store.set(KillSwitchState(True, clock.now(), "kashyap", "test"))
    clock.advance(seconds=5)
    released = KillSwitchState(False, clock.now(), "kashyap", "done")
    await store.set(released)
    assert await store.get() == released
    async with engine.connect() as conn:
        assert (await conn.scalar(text("SELECT count(*) FROM kill_switch_state"))) == 1


async def test_sql_risk_event_sink(
    session_factory: SessionFactory, engine: AsyncEngine, clock: FrozenClock
) -> None:
    sink = SqlRiskEventSink(session_factory)
    await sink.emit(
        RiskEvent(
            clock.now(),
            RiskEventType.DRAWDOWN_HALT,
            Severity.CRITICAL,
            "risk",
            "dd",
            {"drawdown": "50000"},
        )
    )
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT event_type, details FROM risk_events"))).one()
    assert row.event_type == "drawdown_halt"
    assert row.details == {"drawdown": "50000"}
