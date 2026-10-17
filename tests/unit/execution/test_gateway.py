from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from factories import RiskRig, make_order
from pydantic import SecretStr

from aqta.core.clock import FrozenClock
from aqta.core.errors import SafetyViolationError
from aqta.core.settings import Settings
from aqta.core.trading import OrderRequest, OrderType
from aqta.execution import (
    BrokerAck,
    BrokerError,
    LiveBrokerStub,
    OrderGateway,
    OrderState,
    PaperBroker,
    Stage,
    select_broker,
)
from aqta.proposals import ApprovalTokenService, InMemoryNonceStore

SECRET = "gateway-test-secret-0123456789abcdef"


class Rig(RiskRig):
    def __init__(self, clock: FrozenClock, settings: Settings, broker: PaperBroker | None = None,
                 timeout: float = 5.0) -> None:
        super().__init__(clock)
        self.broker = broker or PaperBroker()
        self.tokens = ApprovalTokenService(SECRET, clock, InMemoryNonceStore())
        self.gateway = OrderGateway(
            settings, self.broker, self.tokens, self.engine, self.audit, clock, timeout
        )
        self.kill_switch.register_on_trigger(self.gateway.on_kill_switch)

    def approve(self, order: OrderRequest) -> str:
        return self.tokens.issue(order, actor="kashyap")


@pytest.fixture
def rig(clock: FrozenClock, settings: Settings) -> Rig:
    return Rig(clock, settings)


async def test_happy_path_paper_fill_is_audited(rig: Rig) -> None:
    order = make_order()
    result = await rig.gateway.submit_order(order, rig.approve(order))
    assert result.accepted and result.stage is None
    assert result.state is OrderState.FILLED
    managed = result.order
    assert managed is not None
    assert managed.algo_tag == "AQTA-UNREGISTERED"
    assert managed.mode == "paper" and managed.broker == "paper"
    assert managed.approved_by == "kashyap"
    assert [e for _, e, _ in managed.history] == ["submit", "ack", "fill"]
    kinds = [e.event_type for e in rig.audit.entries]
    assert kinds == ["order.submitted", "order.acknowledged", "order.filled"]
    assert rig.audit.verify().ok
    (paper,) = rig.broker.orders.values()
    assert paper.algo_tag == "AQTA-UNREGISTERED"


@pytest.mark.parametrize("token", [None, "", "v1.forged.token"])
async def test_no_or_invalid_token_rejected(rig: Rig, token: str | None) -> None:
    result = await rig.gateway.submit_order(make_order(), token)
    assert not result.accepted and result.stage is Stage.APPROVAL
    assert rig.broker.orders == {}
    (entry,) = rig.audit.of_type("order.rejected")
    assert entry.payload["stage"] == "approval"


async def test_expired_token_rejected(rig: Rig) -> None:
    order = make_order()
    token = rig.approve(order)
    rig.clock.advance(seconds=301)
    result = await rig.gateway.submit_order(order, token)
    assert result.stage is Stage.APPROVAL and "expired" in result.reasons[0]
    assert rig.broker.orders == {}


async def test_token_for_other_order_rejected(rig: Rig) -> None:
    approved = make_order()
    result = await rig.gateway.submit_order(
        approved.model_copy(update={"quantity": 750}), rig.approve(approved)
    )
    assert result.stage is Stage.APPROVAL and "order_mismatch" in result.reasons[0]


async def test_replayed_token_rejected(rig: Rig) -> None:
    order = make_order()
    token = rig.approve(order)
    assert (await rig.gateway.submit_order(order, token)).accepted
    again = await rig.gateway.submit_order(order, token)
    assert again.stage is Stage.APPROVAL and "replayed" in again.reasons[0]
    assert len(rig.broker.orders) == 1


async def test_risk_failure_blocks_before_broker(rig: Rig) -> None:
    order = make_order(max_loss_inr=Decimal("50000"))
    result = await rig.gateway.submit_order(order, rig.approve(order))
    assert result.stage is Stage.RISK
    assert any("max_loss_per_trade" in r for r in result.reasons)
    assert rig.broker.orders == {}
    assert rig.audit.of_type("order.rejected")[0].payload["approved_by"] == "kashyap"


async def test_kill_switch_blocks_and_cancels_open_orders(rig: Rig, settings: Settings) -> None:
    partial = Rig(rig.clock, settings, broker=PaperBroker(fill_ratio=Decimal("0.5")))
    order = make_order(quantity=150)
    res = await partial.gateway.submit_order(order, partial.approve(order))
    assert res.state is OrderState.PARTIALLY_FILLED
    assert partial.gateway.open_orders() == [res.order]

    await partial.kill_switch.trigger("kashyap", "panic")
    assert res.order is not None and res.order.state is OrderState.CANCELLED
    assert partial.gateway.open_orders() == []
    assert partial.audit.of_type("order.cancel_requested")[0].payload["confirmed"] is True

    blocked = make_order(quantity=225)
    after = await partial.gateway.submit_order(blocked, partial.approve(blocked))
    assert after.stage is Stage.RISK and any("kill_switch" in r for r in after.reasons)


async def test_unfilled_order_stays_acknowledged(clock: FrozenClock, settings: Settings) -> None:
    rig = Rig(clock, settings, broker=PaperBroker(fill_ratio=Decimal(0)))
    order = make_order()
    result = await rig.gateway.submit_order(order, rig.approve(order))
    assert result.accepted and result.state is OrderState.ACKNOWLEDGED


async def test_paper_mode_refuses_live_adapter(settings: Settings, clock: FrozenClock) -> None:
    rig = RiskRig(clock)
    tokens = ApprovalTokenService(SECRET, clock, InMemoryNonceStore())
    with pytest.raises(SafetyViolationError):
        OrderGateway(settings, LiveBrokerStub(), tokens, rig.engine, rig.audit, clock)


async def test_paper_mode_never_touches_live_adapter(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def spy(self: LiveBrokerStub, *a: object, **k: object) -> None:
        calls.append("live")

    monkeypatch.setattr(LiveBrokerStub, "place_order", spy)
    broker = select_broker(settings)
    assert isinstance(broker, PaperBroker) and not broker.is_live
    assert calls == []


def test_live_selection_returns_stub_that_raises() -> None:
    live = Settings(_env_file=None, trading_mode="live", live_trading_enabled=True)  # type: ignore[call-arg]
    broker = select_broker(live)
    assert isinstance(broker, LiveBrokerStub) and broker.is_live
    with pytest.raises(NotImplementedError, match="Q-005"):
        asyncio.run(broker.place_order(make_order(), "tag"))


class _SlowBroker(PaperBroker):
    async def place_order(self, order: OrderRequest, algo_tag: str) -> BrokerAck:
        await asyncio.sleep(1)
        return await super().place_order(order, algo_tag)


class _ErrorBroker(PaperBroker):
    async def place_order(self, order: OrderRequest, algo_tag: str) -> BrokerAck:
        raise BrokerError("exchange down")


async def test_broker_timeout(clock: FrozenClock, settings: Settings) -> None:
    rig = Rig(clock, settings, broker=_SlowBroker(), timeout=0.01)
    order = make_order()
    result = await rig.gateway.submit_order(order, rig.approve(order))
    assert result.stage is Stage.BROKER and result.state is OrderState.TIMED_OUT
    assert rig.audit.of_type("order.timed_out")
    # Timed-out orders count as open (state unknown) and get cancel requests on kill.
    assert rig.gateway.open_orders() == [result.order]
    await rig.gateway.cancel_all_open("test")
    assert result.order is not None and result.order.state is OrderState.CANCEL_PENDING


async def test_broker_error_and_rejection(clock: FrozenClock, settings: Settings) -> None:
    rig = Rig(clock, settings, broker=_ErrorBroker())
    order = make_order()
    result = await rig.gateway.submit_order(order, rig.approve(order))
    assert result.stage is Stage.BROKER and result.state is OrderState.REJECTED

    rig2 = Rig(clock, settings)
    market = make_order(order_type=OrderType.MARKET, limit_price=None)
    # Paper broker cannot fill without any price; bypass risk band check by giving a reference
    # price to risk, then drop it for the broker via a custom subclass.
    class _NoPrice(PaperBroker):
        async def place_order(self, o: OrderRequest, algo_tag: str) -> BrokerAck:
            return await super().place_order(o.model_copy(update={"reference_price": None}), algo_tag)

    rig3 = Rig(clock, settings, broker=_NoPrice())
    res3 = await rig3.gateway.submit_order(market, rig3.approve(market))
    assert res3.stage is Stage.BROKER and res3.state is OrderState.REJECTED
    assert "no price" in res3.reasons[0]
    assert rig2.gateway.orders == {}


async def test_missing_algo_tag_rejected(clock: FrozenClock) -> None:
    no_tag = Settings(_env_file=None, approval_secret=SecretStr(SECRET), algo_tag="")  # type: ignore[call-arg]
    rig = Rig(clock, no_tag)
    order = make_order()
    result = await rig.gateway.submit_order(order, rig.approve(order))
    assert result.stage is Stage.CONFIG and "FR-028" in result.reasons[0]
    assert rig.gateway.mode == "paper"


class _CancelFails(PaperBroker):
    async def cancel_order(self, broker_order_id: str) -> bool:
        raise BrokerError("cancel endpoint down")


async def test_cancel_failure_is_audited_and_order_stays_cancel_pending(
    clock: FrozenClock, settings: Settings
) -> None:
    rig = Rig(clock, settings, broker=_CancelFails(fill_ratio=Decimal(0)))
    order = make_order()
    result = await rig.gateway.submit_order(order, rig.approve(order))
    await rig.kill_switch.trigger("system", "feed outage")
    assert result.order is not None and result.order.state is OrderState.CANCEL_PENDING
    assert rig.audit.of_type("order.cancel_requested")[0].payload["confirmed"] is False
    # Already cancel-pending orders are skipped on a second sweep.
    assert await rig.gateway.cancel_all_open("again") == []
