"""Absolute risk limits derived from settings (RULE-002, RULE-003, ASM-004)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aqta.core.settings import RiskSettings

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class RiskLimits:
    capital_inr: Decimal
    max_loss_per_trade_inr: Decimal
    daily_loss_limit_inr: Decimal
    max_drawdown_inr: Decimal
    margin_cap_inr: Decimal
    max_open_orders: int
    max_orders_per_second: int
    max_lots_per_order: int
    price_band_pct: Decimal
    duplicate_window_seconds: int

    @classmethod
    def from_settings(cls, s: RiskSettings) -> RiskLimits:
        cap = s.capital_inr
        return cls(
            capital_inr=cap,
            max_loss_per_trade_inr=cap * s.max_loss_per_trade_pct / HUNDRED,
            daily_loss_limit_inr=cap * s.daily_loss_limit_pct / HUNDRED,
            max_drawdown_inr=cap * s.max_drawdown_pct / HUNDRED,
            margin_cap_inr=cap * s.margin_cap_pct / HUNDRED,
            max_open_orders=s.max_open_orders,
            max_orders_per_second=s.max_orders_per_second,
            max_lots_per_order=s.max_lots_per_order,
            price_band_pct=s.price_band_pct,
            duplicate_window_seconds=s.duplicate_window_seconds,
        )
