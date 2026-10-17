"""Short trade summaries of 600 characters or fewer (FR-044). Mode is always shown (FR-030)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from aqta.core.timeutil import format_ist

MAX_SUMMARY_CHARS = 600
ELLIPSIS = "…"


class TradeEventKind(StrEnum):
    PROPOSAL = "proposal"
    FILL = "fill"
    ADJUSTMENT = "adjustment"
    EXIT = "exit"


class TradeEvent(BaseModel):
    kind: TradeEventKind
    mode: str  # "paper" | "live"
    at: datetime
    proposal_id: str
    symbol: str
    side: str | None = None
    quantity: int | None = None
    price: Decimal | None = None
    max_loss_inr: Decimal | None = None
    margin_inr: Decimal | None = None
    pnl_inr: Decimal | None = None
    valid_until: datetime | None = None
    note: str = ""


def _inr(value: Decimal) -> str:
    return f"Rs {value:,.0f}"


def format_summary(event: TradeEvent, limit: int = MAX_SUMMARY_CHARS) -> str:
    parts = [f"[{event.mode.upper()}] {event.kind.value.upper()} {event.symbol}"]
    if event.side and event.quantity:
        leg = f"{event.side} {event.quantity}"
        if event.price is not None:
            leg += f" @ {event.price}"
        parts.append(leg)
    if event.max_loss_inr is not None:
        parts.append(f"max loss {_inr(event.max_loss_inr)}")
    if event.margin_inr is not None:
        parts.append(f"margin {_inr(event.margin_inr)}")
    if event.pnl_inr is not None:
        parts.append(f"P&L {_inr(event.pnl_inr)}")
    if event.valid_until is not None:
        parts.append(f"valid until {format_ist(event.valid_until, '%H:%M IST')}")
    parts.append(f"id {event.proposal_id} | {format_ist(event.at, '%d-%b %H:%M IST')}")
    if event.kind is TradeEventKind.PROPOSAL:
        parts.append("Proposal only - not an order")
    if event.note:
        parts.append(event.note)
    text = " | ".join(parts)
    if len(text) <= limit:
        return text
    return text[: limit - len(ELLIPSIS)].rstrip() + ELLIPSIS
