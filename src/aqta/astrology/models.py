"""ORM model for the astrology rule registry (FR-075). DB checks enforce RULE-014."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aqta.core.db import Base


class AstrologyRuleRow(Base):
    __tablename__ = "astrology_rules"
    __table_args__ = (
        CheckConstraint("status = 'active' OR weight = 0", name="weight_zero_unless_active"),
        CheckConstraint("weight = 0 OR approved_at IS NOT NULL", name="weight_needs_approval"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    family: Mapped[str] = mapped_column(String(30), nullable=False)  # sarvatobhadra|mundane
    origin: Mapped[str] = mapped_column(String(20), nullable=False)  # seed|discovered
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    weight: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal(0))
    hypothesis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # RULE-015
    test_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
