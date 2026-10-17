"""Property-based tests (hypothesis) for the risk pipeline invariants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from factories import RiskRig, make_order
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aqta.core.clock import FrozenClock
from aqta.core.trading import RiskEffect, Side
from aqta.risk import CheckName, OrderRateLimiter, RiskSnapshot

START = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
money = st.decimals(min_value=0, max_value=2_000_000, places=2, allow_nan=False)
signed_money = st.decimals(min_value=-100_000, max_value=100_000, places=2, allow_nan=False)


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[RiskSnapshot, dict[str, object]]:
    equity = draw(st.decimals(min_value=800_000, max_value=1_100_000, places=2))
    snap = RiskSnapshot(
        equity_inr=equity,
        peak_equity_inr=max(equity, draw(st.decimals(min_value=900_000, max_value=1_100_000, places=2))),
        day_pnl_inr=draw(signed_money),
        margin_used_inr=draw(st.decimals(min_value=0, max_value=800_000, places=2)),
        open_order_count=draw(st.integers(min_value=0, max_value=25)),
    )
    ref = draw(st.decimals(min_value=100, max_value=50_000, places=2))
    order = {
        "quantity": 75 * draw(st.integers(min_value=1, max_value=60)) + draw(st.sampled_from([0, 0, 0, 1])),
        "max_loss_inr": draw(st.one_of(st.none(), money)),
        "margin_required_inr": draw(money),
        "reference_price": ref,
        "limit_price": ref * (1 + draw(st.decimals(min_value=Decimal("-0.1"), max_value=Decimal("0.1"), places=4))),
        "risk_effect": draw(st.sampled_from(list(RiskEffect))),
        "side": draw(st.sampled_from(list(Side))),
    }
    return snap, order


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(scenarios())
def test_decision_matches_oracle(scenario: tuple[RiskSnapshot, dict[str, object]]) -> None:
    """Approved iff every limit holds - checked against an independent re-statement of the rules."""
    snap, kw = scenario
    rig = RiskRig(FrozenClock(START))
    rig.state.update(
        equity_inr=snap.equity_inr,
        peak_equity_inr=snap.peak_equity_inr,
        day_pnl_inr=snap.day_pnl_inr,
        margin_used_inr=snap.margin_used_inr,
        open_order_count=snap.open_order_count,
    )
    order = make_order(**kw)
    decision = _run(rig.engine.evaluate(order))
    lim = rig.limits
    increasing = order.risk_effect is RiskEffect.INCREASING
    assert order.limit_price is not None and order.reference_price is not None

    expected = {
        CheckName.DRAWDOWN_HALT: snap.drawdown_inr < lim.max_drawdown_inr,
        CheckName.DAILY_LOSS: (not increasing) or -snap.day_pnl_inr < lim.daily_loss_limit_inr,
        CheckName.MAX_LOSS_PER_TRADE: order.max_loss_inr is not None
        and order.max_loss_inr <= lim.max_loss_per_trade_inr,
        CheckName.MARGIN_CAP: (not increasing)
        or snap.margin_used_inr + order.margin_required_inr <= lim.margin_cap_inr,
        CheckName.QUANTITY_LOT: order.quantity % 75 == 0 and order.quantity // 75 <= lim.max_lots_per_order,
        CheckName.PRICE_BAND: abs(order.limit_price - order.reference_price) / order.reference_price * 100
        <= lim.price_band_pct,
        CheckName.OPEN_ORDERS: snap.open_order_count < lim.max_open_orders,
    }
    got = {r.name: r.passed for r in decision.results}
    for name, passed in expected.items():
        assert got[name] == passed, (name, decision.reasons)
    assert decision.approved == all(expected.values())


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=3000), min_size=1, max_size=60))
def test_rate_limiter_never_exceeds_cap(offsets_ms: list[int]) -> None:
    limiter = OrderRateLimiter(5)
    accepted: list[datetime] = []
    for ms in sorted(offsets_ms):
        now = START + timedelta(milliseconds=ms)
        if limiter.check(now).passed:
            limiter.record(now)
            accepted.append(now)
    for i, t in enumerate(accepted):
        in_window = [u for u in accepted[i:] if u - t < timedelta(seconds=1)]
        assert len(in_window) <= 5


@settings(max_examples=150, deadline=None)
@given(day_pnl=signed_money)
def test_reducing_orders_never_blocked_by_daily_loss(day_pnl: Decimal) -> None:
    rig = RiskRig(FrozenClock(START))
    rig.state.update(day_pnl_inr=day_pnl)
    decision = _run(
        rig.engine.evaluate(make_order(risk_effect=RiskEffect.REDUCING, side=Side.SELL))
    )
    assert next(r for r in decision.results if r.name is CheckName.DAILY_LOSS).passed
