"""ORM models for proposals and approvals (FR-011, FR-023, FR-024, FR-043)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aqta.core.db import Base


class ProposalRow(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(20), nullable=False)  # intraday|swing|positional
    strategy_id: Mapped[str | None] = mapped_column(String(64))
    underlying: Mapped[str] = mapped_column(String(40), nullable=False)
    legs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    max_loss_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    margin_required_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    return_on_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # TODO(FR-043, NFR-016): rationale pack, data snapshot and model/rule versions.
    rationale: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # approved|rejected|modified
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # telegram|dashboard|api
    order_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_nonce: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
