"""ORM model for the ``market_ticks`` placeholder (Timescale hypertable when available, FR-001)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from aqta.core.db import Base


class MarketTickRow(Base):
    __tablename__ = "market_ticks"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(60), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(10), primary_key=True)
    ltp: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    open_interest: Mapped[int | None] = mapped_column(BigInteger)
