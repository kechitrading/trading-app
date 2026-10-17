"""Backtesting interfaces (BR-011, FR-046, RISK-001): engine, cost/slippage model, walk-forward."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Split:
    train_start: date
    train_end: date  # inclusive
    test_start: date
    test_end: date  # inclusive


def walk_forward(
    start: date, end: date, train_days: int, test_days: int, step_days: int | None = None
) -> list[Split]:
    """Rolling in-sample/out-of-sample windows. Test windows never overlap their training data."""
    if train_days <= 0 or test_days <= 0:
        raise ValueError("train_days and test_days must be positive")
    step = timedelta(days=step_days or test_days)
    splits: list[Split] = []
    cursor = start
    while True:
        train_end = cursor + timedelta(days=train_days - 1)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days - 1)
        if test_end > end:
            break
        splits.append(Split(cursor, train_end, test_start, test_end))
        cursor += step
    return splits


class CostModel(Protocol):
    """Brokerage, taxes, exchange charges per segment. TODO(FR-046)."""

    def cost_inr(self, notional_inr: Decimal, segment: str) -> Decimal: ...


class SlippageModel(Protocol):
    def slippage_inr(self, notional_inr: Decimal, liquidity: float) -> Decimal: ...


class BacktestResult(BaseModel):
    strategy_id: str
    net_pnl_inr: Decimal
    sharpe: float | None
    max_drawdown_inr: Decimal
    in_sample: tuple[date, date]
    out_of_sample: tuple[date, date]
    net_of_costs: bool = True


class BacktestEngine(Protocol):
    async def run(self, strategy_id: str, split: Split) -> BacktestResult: ...


__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CostModel",
    "SlippageModel",
    "Split",
    "walk_forward",
]
