from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from factories import RiskRig, make_order

from aqta.core.clock import FrozenClock
from aqta.core.settings import RiskSettings
from aqta.core.trading import OrderType, RiskEffect, Side
from aqta.risk import CheckName, RiskEventType


@pytest.fixture
def rig(clock: FrozenClock) -> RiskRig:
    return RiskRig(clock)


def test_limits_from_defaults(rig: RiskRig) -> None:
    lim = rig.limits
    assert lim.max_loss_per_trade_inr == Decimal("10000")
    assert lim.daily_loss_limit_inr == Decimal("20000")
    assert lim.max_drawdown_inr == Decimal("50000")
    assert lim.margin_cap_inr == Decimal("600000")
    assert lim.max_orders_per_second == 5
    assert rig.engine.limits is lim


async def test_clean_order_passes(rig: RiskRig) -> None:
    decision = await rig.engine.evaluate(make_order())
    assert decision.approved, decision.reasons
    assert decision.failures == ()
    assert rig.events.events == []


async def _failed(rig: RiskRig, **order_kw: object) -> set[CheckName]:
    decision = await rig.engine.evaluate(make_order(**order_kw))
    assert not decision.approved
    return {r.name for r in decision.failures}


async def test_max_loss_per_trade(rig: RiskRig) -> None:
    assert await _failed(rig, max_loss_inr=Decimal("10000.01")) == {CheckName.MAX_LOSS_PER_TRADE}
    ok = await rig.engine.evaluate(make_order(max_loss_inr=Decimal("10000")))
    assert ok.approved


async def test_undefined_risk_blocked(rig: RiskRig) -> None:
    assert await _failed(rig, max_loss_inr=None) == {CheckName.MAX_LOSS_PER_TRADE}


async def test_margin_cap(rig: RiskRig) -> None:
    rig.state.update(margin_used_inr=Decimal("500000"))
    assert await _failed(rig, margin_required_inr=Decimal("100001")) == {CheckName.MARGIN_CAP}
    reducing = await rig.engine.evaluate(
        make_order(margin_required_inr=Decimal("900000"), risk_effect=RiskEffect.REDUCING,
                   side=Side.SELL)
    )
    assert reducing.approved, reducing.reasons


async def test_quantity_and_lots(rig: RiskRig) -> None:
    assert await _failed(rig, quantity=100) == {CheckName.QUANTITY_LOT}
    assert await _failed(rig, quantity=75 * 51) == {CheckName.QUANTITY_LOT}


async def test_price_band(rig: RiskRig) -> None:
    assert await _failed(rig, limit_price=Decimal("26300")) == {CheckName.PRICE_BAND}
    assert await _failed(rig, reference_price=None) == {CheckName.PRICE_BAND}
    market = await rig.engine.evaluate(
        make_order(order_type=OrderType.MARKET, limit_price=None)
    )
    assert market.approved, market.reasons


async def test_open_order_count(rig: RiskRig) -> None:
    rig.state.update(open_order_count=20)
    assert await _failed(rig) == {CheckName.OPEN_ORDERS}


async def test_duplicate_order_and_client_id(rig: RiskRig) -> None:
    first = make_order()
    assert (await rig.engine.evaluate(first)).approved
    assert await _failed(rig, client_order_id=first.client_order_id) >= {CheckName.DUPLICATE}
    # Identical economics, new client id, inside the 30s window -> duplicate.
    assert await _failed(rig) == {CheckName.DUPLICATE}
    rig.clock.advance(seconds=31)
    assert (await rig.engine.evaluate(make_order())).approved


async def test_order_rate_cap(rig: RiskRig) -> None:
    for i in range(5):
        d = await rig.engine.evaluate(make_order(quantity=75 * (i + 1)))
        assert d.approved, d.reasons
    assert await _failed(rig, quantity=75 * 10) == {CheckName.ORDER_RATE}
    rig.clock.advance(timedelta(seconds=1))
    assert (await rig.engine.evaluate(make_order(quantity=75 * 11))).approved


async def test_rejected_orders_do_not_consume_rate_or_duplicate(rig: RiskRig) -> None:
    for _ in range(10):
        await rig.engine.evaluate(make_order(max_loss_inr=None))
    assert (await rig.engine.evaluate(make_order())).approved


async def test_block_emits_risk_event(rig: RiskRig) -> None:
    await rig.engine.evaluate(make_order(max_loss_inr=None))
    (event,) = rig.events.of_type(RiskEventType.PRE_TRADE_BLOCKED)
    assert event.details["failed"] == ["max_loss_per_trade"]
    assert "FR-036" in (event.reason or "")


async def test_daily_loss_blocks_increasing_only(rig: RiskRig) -> None:
    rig.state.update(day_pnl_inr=Decimal("-20000"))
    assert await _failed(rig) == {CheckName.DAILY_LOSS}
    reducing = await rig.engine.evaluate(
        make_order(risk_effect=RiskEffect.REDUCING, side=Side.SELL)
    )
    assert reducing.approved, reducing.reasons
    assert len(rig.events.of_type(RiskEventType.DAILY_LOSS_BLOCK)) == 1
    # Block stays latched for the day even if P&L recovers...
    rig.state.update(day_pnl_inr=Decimal("0"))
    assert await _failed(rig, quantity=150) == {CheckName.DAILY_LOSS}
    # ...and clears on the next IST trading date.
    rig.clock.advance(days=1)
    assert (await rig.engine.evaluate(make_order(quantity=225))).approved
    assert rig.audit.of_type("risk.daily_loss_block")


async def test_drawdown_halt_blocks_everything_until_logged_reset(rig: RiskRig) -> None:
    rig.state.update(equity_inr=Decimal("950000"))  # 50k below peak of 10L
    assert CheckName.DRAWDOWN_HALT in await _failed(rig)
    assert CheckName.DRAWDOWN_HALT in await _failed(
        rig, risk_effect=RiskEffect.REDUCING, side=Side.SELL
    )
    assert rig.halts.drawdown_halted
    rig.state.update(equity_inr=Decimal("990000"))
    assert CheckName.DRAWDOWN_HALT in await _failed(rig, quantity=150)  # still latched

    with pytest.raises(ValueError, match="reason"):
        await rig.halts.reset_drawdown("kashyap", "  ")
    await rig.halts.reset_drawdown("kashyap", "reviewed losses, resuming at half size")
    assert (await rig.engine.evaluate(make_order(quantity=225))).approved
    assert rig.events.of_type(RiskEventType.DRAWDOWN_RESET)[0].actor == "kashyap"
    assert rig.audit.of_type("risk.drawdown_reset")


async def test_reset_while_still_in_drawdown_rehalts(rig: RiskRig) -> None:
    rig.state.update(equity_inr=Decimal("940000"))
    await rig.engine.evaluate(make_order())
    await rig.halts.reset_drawdown("kashyap", "test")
    assert CheckName.DRAWDOWN_HALT in await _failed(rig, quantity=150)
    assert len(rig.events.of_type(RiskEventType.DRAWDOWN_HALT)) == 2


async def test_kill_switch_blocks_all(rig: RiskRig) -> None:
    await rig.kill_switch.trigger("kashyap", "manual test")
    assert CheckName.KILL_SWITCH in await _failed(rig)
    assert CheckName.KILL_SWITCH in await _failed(
        rig, risk_effect=RiskEffect.REDUCING, side=Side.SELL
    )


def test_custom_limits(clock: FrozenClock) -> None:
    rig = RiskRig(clock, RiskSettings(capital_inr=Decimal("500000"), max_loss_per_trade_pct=Decimal("0.5")))
    assert rig.limits.max_loss_per_trade_inr == Decimal("2500")
