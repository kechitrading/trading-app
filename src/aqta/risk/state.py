"""Portfolio state the risk engine needs, behind a port so portfolio/broker can supply it."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    equity_inr: Decimal
    peak_equity_inr: Decimal
    day_pnl_inr: Decimal  # realised + unrealised for the current IST trading day
    margin_used_inr: Decimal
    open_order_count: int

    @property
    def drawdown_inr(self) -> Decimal:
        return max(Decimal(0), self.peak_equity_inr - self.equity_inr)


class RiskStateProvider(Protocol):
    async def snapshot(self) -> RiskSnapshot: ...


class InMemoryRiskState:
    """Mutable state for paper mode and tests. TODO(FR-014, FR-027): feed from portfolio/broker."""

    def __init__(self, capital_inr: Decimal) -> None:
        self._snap = RiskSnapshot(
            equity_inr=capital_inr,
            peak_equity_inr=capital_inr,
            day_pnl_inr=Decimal(0),
            margin_used_inr=Decimal(0),
            open_order_count=0,
        )

    async def snapshot(self) -> RiskSnapshot:
        return self._snap

    def update(self, **changes: Decimal | int) -> RiskSnapshot:
        self._snap = replace(self._snap, **changes)  # type: ignore[arg-type]
        return self._snap
