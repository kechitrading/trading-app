"""Audit sinks: the ``AuditSink`` port, a Postgres implementation and an in-memory one for tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy import select, text

from aqta.audit.chain import (
    GENESIS_HASH,
    AuditEntry,
    ChainVerification,
    compute_hash,
    normalize_payload,
    verify_chain,
)
from aqta.audit.models import AuditLogRow
from aqta.core.clock import Clock, SystemClock
from aqta.core.db import SessionFactory, session_scope

# Arbitrary constant: serialises writers so the chain has a single, gap-free order.
AUDIT_ADVISORY_LOCK_KEY = 0x41515441  # "AQTA"


class AuditSink(Protocol):
    async def record(
        self, event_type: str, payload: Mapping[str, Any], actor: str
    ) -> AuditEntry: ...


class SqlAuditLog:
    """Writes hash-chained rows to ``audit_log``. The DB trigger rejects UPDATE/DELETE/TRUNCATE."""

    def __init__(self, session_factory: SessionFactory, clock: Clock | None = None) -> None:
        self._sessions = session_factory
        self._clock = clock or SystemClock()

    async def record(self, event_type: str, payload: Mapping[str, Any], actor: str) -> AuditEntry:
        body = normalize_payload(payload)
        async with session_scope(self._sessions) as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_ADVISORY_LOCK_KEY}
            )
            prev = await session.scalar(
                select(AuditLogRow.hash).order_by(AuditLogRow.id.desc()).limit(1)
            )
            prev_hash = prev or GENESIS_HASH
            occurred_at = self._clock.now()
            row = AuditLogRow(
                occurred_at=occurred_at,
                event_type=event_type,
                actor=actor,
                payload=body,
                prev_hash=prev_hash,
                hash=compute_hash(prev_hash, occurred_at, event_type, actor, body),
            )
            session.add(row)
            await session.flush()
            return row.to_entry()

    async def entries(self) -> list[AuditEntry]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(AuditLogRow).order_by(AuditLogRow.id))).all()
            return [r.to_entry() for r in rows]

    async def verify(self) -> ChainVerification:
        return verify_chain(await self.entries())


class InMemoryAuditLog:
    """Same chaining rules, kept in a list. Used by unit tests and the paper-mode dev fallback."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._entries: list[AuditEntry] = []
        self._lock = asyncio.Lock()

    async def record(self, event_type: str, payload: Mapping[str, Any], actor: str) -> AuditEntry:
        body = normalize_payload(payload)
        async with self._lock:
            prev_hash = self._entries[-1].hash if self._entries else GENESIS_HASH
            occurred_at = self._clock.now()
            entry = AuditEntry(
                seq=len(self._entries) + 1,
                occurred_at=occurred_at,
                event_type=event_type,
                actor=actor,
                payload=body,
                prev_hash=prev_hash,
                hash=compute_hash(prev_hash, occurred_at, event_type, actor, body),
            )
            self._entries.append(entry)
            return entry

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def of_type(self, event_type: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.event_type == event_type]

    def verify(self) -> ChainVerification:
        return verify_chain(self._entries)
