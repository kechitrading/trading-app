"""ORM model for ``audit_log``. Append-only is enforced by a DB trigger (see baseline migration)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aqta.audit.chain import AuditEntry
from aqta.core.db import Base


class AuditLogRow(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_event_type_occurred_at", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    def to_entry(self) -> AuditEntry:
        return AuditEntry(
            seq=self.id,
            occurred_at=self.occurred_at,
            event_type=self.event_type,
            actor=self.actor,
            payload=dict(self.payload),
            prev_hash=self.prev_hash,
            hash=self.hash,
        )
