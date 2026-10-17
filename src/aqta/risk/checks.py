"""Individual pre-trade checks (FR-031, FR-032, FR-033, FR-034, FR-036).

Each check is a small pure function returning a ``CheckResult``; the engine runs all of them so the
rejection shows every reason at once.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from aqta.core.trading import OrderRequest, RiskEffect
from aqta.risk.limits import HUNDRED, RiskLimits
from aqta.risk.state import RiskSnapshot


class CheckName(StrEnum):
    KILL_SWITCH = "kill_switch"
    DRAWDOWN_HALT = "drawdown_halt"
    DAILY_LOSS = "daily_loss"
    MAX_LOSS_PER_TRADE = "max_loss_per_trade"
    MARGIN_CAP = "margin_cap"
    QUANTITY_LOT = "quantity_lot"
    PRICE_BAND = "price_band"
    OPEN_ORDERS = "open_orders"
    DUPLICATE = "duplicate_order"
    ORDER_RATE = "order_rate"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: CheckName
    passed: bool
    reason: str = ""

    @classmethod
    def ok(cls, name: CheckName) -> CheckResult:
        return cls(name, True)

    @classmethod
    def fail(cls, name: CheckName, reason: str) -> CheckResult:
        return cls(name, False, reason)


def check_kill_switch(active: bool) -> CheckResult:
    if active:
        return CheckResult.fail(CheckName.KILL_SWITCH, "kill switch is active (FR-034)")
    return CheckResult.ok(CheckName.KILL_SWITCH)


def check_drawdown(halted: bool, snap: RiskSnapshot, limits: RiskLimits) -> CheckResult:
    if halted or snap.drawdown_inr >= limits.max_drawdown_inr:
        return CheckResult.fail(
            CheckName.DRAWDOWN_HALT,
            f"drawdown halt: drawdown {snap.drawdown_inr} >= limit {limits.max_drawdown_inr} "
            "or halt not yet reset (FR-033)",
        )
    return CheckResult.ok(CheckName.DRAWDOWN_HALT)


def check_daily_loss(
    order: OrderRequest, blocked: bool, snap: RiskSnapshot, limits: RiskLimits
) -> CheckResult:
    if order.risk_effect is RiskEffect.REDUCING:
        return CheckResult.ok(CheckName.DAILY_LOSS)  # FR-032: risk-reducing orders stay allowed
    if blocked or -snap.day_pnl_inr >= limits.daily_loss_limit_inr:
        return CheckResult.fail(
            CheckName.DAILY_LOSS,
            f"daily loss {-snap.day_pnl_inr} >= limit {limits.daily_loss_limit_inr}; "
            "risk-increasing orders blocked for today (FR-032)",
        )
    return CheckResult.ok(CheckName.DAILY_LOSS)


def check_max_loss(order: OrderRequest, limits: RiskLimits) -> CheckResult:
    if order.max_loss_inr is None:
        # TODO(RULE-004, FR-036): allow strategies explicitly approved for undefined risk.
        return CheckResult.fail(
            CheckName.MAX_LOSS_PER_TRADE, "undefined maximum loss is not allowed (FR-036)"
        )
    if order.max_loss_inr > limits.max_loss_per_trade_inr:
        return CheckResult.fail(
            CheckName.MAX_LOSS_PER_TRADE,
            f"max loss {order.max_loss_inr} > per-trade limit {limits.max_loss_per_trade_inr}",
        )
    return CheckResult.ok(CheckName.MAX_LOSS_PER_TRADE)


def check_margin(order: OrderRequest, snap: RiskSnapshot, limits: RiskLimits) -> CheckResult:
    if order.risk_effect is RiskEffect.REDUCING:
        return CheckResult.ok(CheckName.MARGIN_CAP)
    after = snap.margin_used_inr + order.margin_required_inr
    if after > limits.margin_cap_inr:
        return CheckResult.fail(
            CheckName.MARGIN_CAP, f"margin after order {after} > cap {limits.margin_cap_inr}"
        )
    return CheckResult.ok(CheckName.MARGIN_CAP)


def check_quantity(order: OrderRequest, limits: RiskLimits) -> CheckResult:
    lot = order.instrument.lot_size
    if order.quantity % lot != 0:
        return CheckResult.fail(
            CheckName.QUANTITY_LOT, f"quantity {order.quantity} is not a multiple of lot {lot}"
        )
    if order.lots > limits.max_lots_per_order:
        return CheckResult.fail(
            CheckName.QUANTITY_LOT, f"{order.lots} lots > max {limits.max_lots_per_order}"
        )
    return CheckResult.ok(CheckName.QUANTITY_LOT)


def check_price_band(order: OrderRequest, limits: RiskLimits) -> CheckResult:
    ref = order.reference_price
    if ref is None:
        return CheckResult.fail(CheckName.PRICE_BAND, "reference price required for band check")
    if order.limit_price is None:
        return CheckResult.ok(CheckName.PRICE_BAND)  # market order: priced at reference
    deviation_pct = abs(order.limit_price - ref) / ref * HUNDRED
    if deviation_pct > limits.price_band_pct:
        return CheckResult.fail(
            CheckName.PRICE_BAND,
            f"limit {order.limit_price} is {deviation_pct:.2f}% from reference {ref} "
            f"(band {limits.price_band_pct}%)",
        )
    return CheckResult.ok(CheckName.PRICE_BAND)


def check_open_orders(snap: RiskSnapshot, limits: RiskLimits) -> CheckResult:
    if snap.open_order_count >= limits.max_open_orders:
        return CheckResult.fail(
            CheckName.OPEN_ORDERS,
            f"{snap.open_order_count} open orders >= max {limits.max_open_orders}",
        )
    return CheckResult.ok(CheckName.OPEN_ORDERS)


class OrderRateLimiter:
    """Sliding one-second window. Internal cap at or below 5 orders/sec (FR-031, REG-003)."""

    WINDOW = timedelta(seconds=1)

    def __init__(self, max_per_second: int) -> None:
        self._max = max_per_second
        self._sent: deque[datetime] = deque()

    def _prune(self, now: datetime) -> None:
        while self._sent and now - self._sent[0] >= self.WINDOW:
            self._sent.popleft()

    def check(self, now: datetime) -> CheckResult:
        self._prune(now)
        if len(self._sent) >= self._max:
            return CheckResult.fail(CheckName.ORDER_RATE, f"order rate cap {self._max}/sec reached")
        return CheckResult.ok(CheckName.ORDER_RATE)

    def record(self, now: datetime) -> None:
        self._prune(now)
        self._sent.append(now)


Fingerprint = tuple[str, str, str, int, Decimal | None]


class DuplicateGuard:
    """Rejects a reused client_order_id or an identical order inside the duplicate window."""

    def __init__(self, window_seconds: int) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._seen: dict[Fingerprint, datetime] = {}
        self._client_ids: dict[str, datetime] = {}

    @staticmethod
    def _fingerprint(order: OrderRequest) -> Fingerprint:
        ins = order.instrument
        return (
            f"{ins.exchange}:{ins.symbol}",
            ins.segment,
            order.side,
            order.quantity,
            order.limit_price,
        )

    def _prune(self, now: datetime) -> None:
        # Client ids are kept for a day so a replayed id is caught well beyond the window.
        self._seen = {k: t for k, t in self._seen.items() if now - t < self._window}
        self._client_ids = {
            k: t for k, t in self._client_ids.items() if now - t < timedelta(days=1)
        }

    def check(self, order: OrderRequest, now: datetime) -> CheckResult:
        self._prune(now)
        if order.client_order_id in self._client_ids:
            return CheckResult.fail(
                CheckName.DUPLICATE, f"client_order_id {order.client_order_id} already used"
            )
        if self._fingerprint(order) in self._seen:
            return CheckResult.fail(
                CheckName.DUPLICATE, "identical order inside the duplicate window"
            )
        return CheckResult.ok(CheckName.DUPLICATE)

    def record(self, order: OrderRequest, now: datetime) -> None:
        self._seen[self._fingerprint(order)] = now
        self._client_ids[order.client_order_id] = now
