"""Paper broker (FR-030): in-memory fills with cost and slippage hooks. Never sends real orders."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from aqta.core.ids import new_id
from aqta.core.trading import OrderRequest, Side
from aqta.execution.ports import (
    BrokerAck,
    BrokerError,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPort,
    BrokerPosition,
)

BPS = Decimal(10_000)


class SlippageModel(Protocol):
    def fill_price(self, order: OrderRequest, base_price: Decimal) -> Decimal: ...


class CostModel(Protocol):
    def costs(self, order: OrderRequest, quantity: int, price: Decimal) -> Decimal: ...


class FixedBpsSlippage:
    """Adverse slippage of ``bps`` basis points. TODO(FR-030): calibrate from paper fills."""

    def __init__(self, bps: Decimal = Decimal(0)) -> None:
        self._bps = bps

    def fill_price(self, order: OrderRequest, base_price: Decimal) -> Decimal:
        sign = 1 if order.side is Side.BUY else -1
        return base_price * (1 + sign * self._bps / BPS)


class ZeroCost:
    """TODO(FR-021, FR-046): brokerage, STT, exchange charges, stamp duty, GST per segment."""

    def costs(self, order: OrderRequest, quantity: int, price: Decimal) -> Decimal:
        return Decimal(0)


@dataclass(slots=True)
class _PaperOrder:
    order: OrderRequest
    algo_tag: str
    status: BrokerOrderStatus
    filled: int = 0
    avg_price: Decimal | None = None
    costs: Decimal = Decimal(0)


class PaperBroker(BrokerPort):
    name = "paper"
    is_live = False

    def __init__(
        self,
        slippage: SlippageModel | None = None,
        costs: CostModel | None = None,
        fill_ratio: Decimal = Decimal(1),
    ) -> None:
        self._slippage = slippage or FixedBpsSlippage()
        self._costs = costs or ZeroCost()
        self._fill_ratio = fill_ratio  # < 1 simulates partial fills
        self._orders: dict[str, _PaperOrder] = {}
        self._positions: dict[tuple[str, str], BrokerPosition] = {}

    @property
    def orders(self) -> dict[str, _PaperOrder]:
        return self._orders

    async def place_order(self, order: OrderRequest, algo_tag: str) -> BrokerAck:
        if not algo_tag:
            raise BrokerError("algo tag missing (FR-028)")
        broker_id = new_id("paper")
        base = order.limit_price or order.reference_price
        if base is None:
            self._orders[broker_id] = _PaperOrder(order, algo_tag, BrokerOrderStatus.REJECTED)
            return BrokerAck(broker_id, accepted=False, message="no price to fill against")
        lots_to_fill = int(order.lots * self._fill_ratio)
        qty = lots_to_fill * order.instrument.lot_size
        price = self._slippage.fill_price(order, base)
        status = (
            BrokerOrderStatus.COMPLETE
            if qty == order.quantity
            else (BrokerOrderStatus.PARTIAL if qty > 0 else BrokerOrderStatus.OPEN)
        )
        paper = _PaperOrder(
            order,
            algo_tag,
            status,
            filled=qty,
            avg_price=price if qty else None,
            costs=self._costs.costs(order, qty, price) if qty else Decimal(0),
        )
        self._orders[broker_id] = paper
        if qty:
            self._apply_position(order, qty, price)
        return BrokerAck(broker_id, accepted=True)

    def _apply_position(self, order: OrderRequest, qty: int, price: Decimal) -> None:
        key = (order.instrument.symbol, order.instrument.exchange.value)
        signed = qty if order.side is Side.BUY else -qty
        current = self._positions.get(key)
        if current is None:
            self._positions[key] = BrokerPosition(key[0], key[1], signed, price)
            return
        new_qty = current.quantity + signed
        self._positions[key] = BrokerPosition(key[0], key[1], new_qty, current.average_price)

    async def get_order(self, broker_order_id: str) -> BrokerOrderSnapshot:
        p = self._get(broker_order_id)
        return BrokerOrderSnapshot(broker_order_id, p.status, p.filled, p.avg_price, p.costs)

    async def cancel_order(self, broker_order_id: str) -> bool:
        p = self._get(broker_order_id)
        if p.status in (BrokerOrderStatus.OPEN, BrokerOrderStatus.PARTIAL):
            p.status = BrokerOrderStatus.CANCELLED
            return True
        return False

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        limit_price: Decimal | None = None,
        quantity: int | None = None,
    ) -> bool:
        p = self._get(broker_order_id)
        if p.status not in (BrokerOrderStatus.OPEN, BrokerOrderStatus.PARTIAL):
            return False
        updates: dict[str, object] = {}
        if limit_price is not None:
            updates["limit_price"] = limit_price
        if quantity is not None:
            updates["quantity"] = quantity
        p.order = p.order.model_copy(update=updates)
        return True

    async def positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def _get(self, broker_order_id: str) -> _PaperOrder:
        try:
            return self._orders[broker_order_id]
        except KeyError:
            raise BrokerError(f"unknown paper order {broker_order_id}") from None
