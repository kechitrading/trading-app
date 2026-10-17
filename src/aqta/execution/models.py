"""ORM model for orders (FR-025..FR-028). Broker-agnostic: broker name + broker order id."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aqta.core.db import Base


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"))
    mode: Mapped[str] = mapped_column(String(10), nullable=False)  # paper|live
    broker: Mapped[str] = mapped_column(String(30), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    algo_tag: Mapped[str] = mapped_column(String(64), nullable=False)  # FR-028: never null
    symbol: Mapped[str] = mapped_column(String(60), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
