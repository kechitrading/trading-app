"""ORM model for stored forecasts and their outcomes (FR-066, FR-068, NFR-022)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aqta.core.db import Base


class ForecastRow(Base):
    __tablename__ = "forecasts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(20), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    data_snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    p10: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    p50: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    p90: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    scenarios: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actual: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    matured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
