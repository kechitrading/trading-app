"""Portfolio: positions, Greeks aggregation, margin and P&L (BR-015, FR-013, FR-014). Models only.

The portfolio will implement ``aqta.risk.RiskStateProvider`` to feed the risk engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from aqta.core.trading import Instrument


class Greeks(BaseModel):
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0

    def __add__(self, other: Greeks) -> Greeks:
        return Greeks(
            delta=self.delta + other.delta,
            gamma=self.gamma + other.gamma,
            vega=self.vega + other.vega,
            theta=self.theta + other.theta,
        )


class Position(BaseModel):
    instrument: Instrument
    quantity: int
    average_price: Decimal
    last_price: Decimal
    greeks: Greeks = Field(default_factory=Greeks)  # position-level (already x quantity)
    margin_inr: Decimal = Decimal(0)

    @property
    def unrealised_pnl_inr(self) -> Decimal:
        return (self.last_price - self.average_price) * self.quantity


class PortfolioSnapshot(BaseModel):
    as_of: datetime
    positions: list[Position] = Field(default_factory=list)
    realised_pnl_inr: Decimal = Decimal(0)

    @property
    def net_greeks(self) -> Greeks:
        total = Greeks()
        for p in self.positions:
            total = total + p.greeks
        return total

    @property
    def margin_used_inr(self) -> Decimal:
        return sum((p.margin_inr for p in self.positions), Decimal(0))

    @property
    def unrealised_pnl_inr(self) -> Decimal:
        return sum((p.unrealised_pnl_inr for p in self.positions), Decimal(0))


class PortfolioSource(Protocol):
    """TODO(FR-014, FR-027): built from broker positions, refreshed every 60 s in market hours."""

    async def snapshot(self) -> PortfolioSnapshot: ...


class HedgeSuggester(Protocol):
    """FR-013: at least one hedge with cost and residual max loss."""

    async def suggest(self, positions: Iterable[Position]) -> list[dict[str, object]]: ...


__all__ = ["Greeks", "HedgeSuggester", "PortfolioSnapshot", "PortfolioSource", "Position"]
