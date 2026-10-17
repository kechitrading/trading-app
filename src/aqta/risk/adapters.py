"""Risk infrastructure adapters: Redis/SQL kill-switch stores and the SQL risk-event sink."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from aqta.core.db import SessionFactory, session_scope
from aqta.core.hashing import to_jsonable
from aqta.risk.events import RiskEvent
from aqta.risk.kill_switch import KillSwitchState
from aqta.risk.models import KillSwitchStateRow, RiskEventRow

KILL_SWITCH_KEY = "aqta:risk:kill_switch"


class RedisKillSwitchStore:
    def __init__(self, redis: Any, key: str = KILL_SWITCH_KEY) -> None:
        self._redis = redis
        self._key = key

    async def get(self) -> KillSwitchState | None:
        raw = await self._redis.get(self._key)
        if raw is None:
            return None
        data = json.loads(raw)
        return KillSwitchState(
            active=bool(data["active"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            actor=str(data["actor"]),
            reason=data.get("reason"),
        )

    async def set(self, state: KillSwitchState) -> None:
        payload = {
            "active": state.active,
            "updated_at": state.updated_at.isoformat(),
            "actor": state.actor,
            "reason": state.reason,
        }
        await self._redis.set(self._key, json.dumps(payload))


class SqlKillSwitchStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

    async def get(self) -> KillSwitchState | None:
        async with self._sessions() as session:
            row = await session.scalar(select(KillSwitchStateRow).where(KillSwitchStateRow.id == 1))
            if row is None:
                return None
            return KillSwitchState(row.active, row.updated_at, row.actor, row.reason)

    async def set(self, state: KillSwitchState) -> None:
        values = {
            "id": 1,
            "active": state.active,
            "updated_at": state.updated_at,
            "actor": state.actor,
            "reason": state.reason,
        }
        stmt = insert(KillSwitchStateRow).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=values)
        async with session_scope(self._sessions) as session:
            await session.execute(stmt)


class SqlRiskEventSink:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

    async def emit(self, event: RiskEvent) -> None:
        async with session_scope(self._sessions) as session:
            session.add(
                RiskEventRow(
                    occurred_at=event.occurred_at,
                    event_type=event.event_type.value,
                    severity=event.severity.value,
                    actor=event.actor,
                    reason=event.reason,
                    details=to_jsonable(event.details),
                )
            )
