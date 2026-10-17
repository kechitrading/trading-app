"""Shared-kernel trading types used by proposals, risk and execution.

``OrderRequest`` is the exact payload Kashyap approves; its canonical hash binds the approval token
(RULE-001). Keep it free of broker specifics so adapters stay swappable (Q-005).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aqta.core.hashing import sha256_canonical


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"


class Segment(StrEnum):
    CASH = "CASH"
    FUT = "FUT"
    OPT = "OPT"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class ProductType(StrEnum):
    INTRADAY = "INTRADAY"
    CARRY = "CARRY"


class RiskEffect(StrEnum):
    """Whether an order increases or reduces risk (FR-032 keeps reducing orders allowed)."""

    INCREASING = "INCREASING"
    REDUCING = "REDUCING"


PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    exchange: Exchange
    segment: Segment = Segment.CASH
    lot_size: int = Field(default=1, gt=0)
    tick_size: PositiveDecimal = Decimal("0.05")


class OrderRequest(BaseModel):
    """A single order leg as approved. Immutable: any change invalidates the approval token."""

    model_config = ConfigDict(frozen=True)

    client_order_id: str = Field(min_length=1, max_length=64)
    proposal_id: str = Field(min_length=1)
    strategy_id: str | None = None
    instrument: Instrument
    side: Side
    quantity: int = Field(gt=0)
    order_type: OrderType = OrderType.LIMIT
    product: ProductType = ProductType.INTRADAY
    limit_price: PositiveDecimal | None = None
    reference_price: PositiveDecimal | None = None  # last traded price used for price-band check
    risk_effect: RiskEffect = RiskEffect.INCREASING
    # Defined maximum loss of this leg in INR. None means undefined risk (blocked, FR-036).
    max_loss_inr: NonNegativeDecimal | None = None
    margin_required_inr: NonNegativeDecimal = Decimal("0")
    algo_tag: str | None = None  # FR-028; gateway fills the configured tag when absent

    @model_validator(mode="after")
    def _limit_needs_price(self) -> OrderRequest:
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT orders need limit_price")
        return self

    @property
    def lots(self) -> int:
        return self.quantity // self.instrument.lot_size

    def payload_hash(self) -> str:
        """SHA-256 over the canonical JSON of the order. Bound into approval tokens."""
        return sha256_canonical(self.model_dump(mode="json"))
