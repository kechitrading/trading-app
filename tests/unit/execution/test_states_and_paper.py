from __future__ import annotations

from decimal import Decimal

import pytest
from factories import make_order

from aqta.core.errors import InvalidTransitionError
from aqta.core.trading import Side
from aqta.execution import (
    TERMINAL,
    BrokerError,
    BrokerOrderStatus,
    FixedBpsSlippage,
    OrderEvent,
    OrderState,
    PaperBroker,
    ReconciliationReport,
    is_open,
    next_state,
)

S, E = OrderState, OrderEvent


@pytest.mark.parametrize(
    ("path", "final"),
    [
        ([E.SUBMIT, E.ACK, E.FILL], S.FILLED),
        ([E.SUBMIT, E.ACK, E.PARTIAL_FILL, E.PARTIAL_FILL, E.FILL], S.FILLED),
        ([E.SUBMIT, E.REJECT], S.REJECTED),
        ([E.SUBMIT, E.ACK, E.CANCEL_REQUEST, E.CANCEL_CONFIRM], S.CANCELLED),
        ([E.SUBMIT, E.ACK, E.CANCEL_REQUEST, E.FILL], S.FILLED),
        ([E.SUBMIT, E.ACK, E.MODIFY_REQUEST, E.MODIFY_CONFIRM], S.ACKNOWLEDGED),
        ([E.SUBMIT, E.ACK, E.MODIFY_REQUEST, E.MODIFY_REJECT], S.ACKNOWLEDGED),
        ([E.SUBMIT, E.TIMEOUT, E.ACK, E.FILL], S.FILLED),
    ],
)
def test_valid_paths(path: list[OrderEvent], final: OrderState) -> None:
    state = S.NEW
    for event in path:
        state = next_state(state, event)
    assert state is final


@pytest.mark.parametrize(
    ("state", "event"),
    [(S.NEW, E.FILL), (S.FILLED, E.CANCEL_REQUEST), (S.CANCELLED, E.ACK),
     (S.REJECTED, E.ACK), (S.PENDING_SUBMIT, E.FILL), (S.CANCEL_PENDING, E.MODIFY_REQUEST)],
)
def test_invalid_transitions(state: OrderState, event: OrderEvent) -> None:
    with pytest.raises(InvalidTransitionError):
        next_state(state, event)


def test_terminal_and_open() -> None:
    assert TERMINAL == {S.FILLED, S.CANCELLED, S.REJECTED}
    assert not is_open(S.NEW) and not is_open(S.FILLED)
    assert is_open(S.TIMED_OUT) and is_open(S.PARTIALLY_FILLED)


async def test_paper_broker_slippage_positions_cancel_modify() -> None:
    broker = PaperBroker(slippage=FixedBpsSlippage(Decimal(10)), fill_ratio=Decimal("0.5"))
    buy = make_order(quantity=150)
    ack = await broker.place_order(buy, "TAG")
    snap = await broker.get_order(ack.broker_order_id)
    assert snap.status is BrokerOrderStatus.PARTIAL and snap.filled_quantity == 75
    assert snap.average_price == Decimal("25025.0")  # 10 bps adverse on a buy
    sell = await broker.place_order(make_order(side=Side.SELL, quantity=150), "TAG")
    assert (await broker.get_order(sell.broker_order_id)).average_price == Decimal("24975.0")
    (pos,) = await broker.positions()
    assert pos.quantity == 0

    assert await broker.modify_order(ack.broker_order_id, limit_price=Decimal("24900"), quantity=75)
    assert await broker.cancel_order(ack.broker_order_id)
    assert not await broker.cancel_order(ack.broker_order_id)
    assert not await broker.modify_order(ack.broker_order_id, limit_price=Decimal(1))
    with pytest.raises(BrokerError):
        await broker.get_order("missing")
    with pytest.raises(BrokerError, match="FR-028"):
        await broker.place_order(buy, "")


def test_reconciliation_report() -> None:
    assert ReconciliationReport().clean
    assert not ReconciliationReport(["NIFTY qty 75 vs 0"]).clean
