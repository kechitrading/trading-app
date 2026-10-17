"""Arbitrage scanners (BR-005, FR-017..FR-022, NFR-003). Interfaces + net-edge calculator only.

Scanner classes: cash-futures/calendar (FR-017), NSE vs BSE (FR-018), options parity/box/
conversion-reversal (FR-019), MCX basis/calendar (FR-020).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, computed_field

BPS = Decimal(10_000)


class ScannerKind(StrEnum):
    CASH_FUTURES_CALENDAR = "cash_futures_calendar"
    NSE_BSE = "nse_bse"
    OPTIONS_PARITY = "options_parity"
    MCX_BASIS = "mcx_basis"


class Costs(BaseModel):
    """Every cost FR-021 lists, in INR for the whole trade."""

    brokerage: Decimal = Decimal(0)
    taxes: Decimal = Decimal(0)  # STT, stamp duty, GST
    exchange_charges: Decimal = Decimal(0)
    slippage: Decimal = Decimal(0)
    funding: Decimal = Decimal(0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> Decimal:
        return self.brokerage + self.taxes + self.exchange_charges + self.slippage + self.funding


class Leg(BaseModel):
    symbol: str
    side: str
    quantity: int
    price: Decimal


class ArbitrageOpportunity(BaseModel):
    kind: ScannerKind
    legs: list[Leg] = Field(min_length=2)
    gross_edge_inr: Decimal
    costs: Costs
    capital_inr: Decimal = Field(gt=0)
    margin_inr: Decimal = Decimal(0)
    liquidity_ok: bool = False
    hedge: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def net_edge_inr(self) -> Decimal:
        """FR-021 acceptance: net edge equals gross edge minus the listed costs."""
        return self.gross_edge_inr - self.costs.total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def net_edge_bps(self) -> Decimal:
        return self.net_edge_inr / self.capital_inr * BPS

    def meets(self, threshold_bps: Decimal) -> bool:
        """FR-022: alert only when the user-set net-edge threshold is met."""
        return self.liquidity_ok and self.net_edge_bps >= threshold_bps


class ArbitrageScanner(Protocol):
    kind: ScannerKind

    async def scan(self) -> list[ArbitrageOpportunity]: ...


__all__ = [
    "ArbitrageOpportunity",
    "ArbitrageScanner",
    "Costs",
    "Leg",
    "ScannerKind",
]
