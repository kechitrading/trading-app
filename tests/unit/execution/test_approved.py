from __future__ import annotations

import pytest

from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.errors import SafetyViolationError
from aqta.core.settings import Settings, TradingMode
from aqta.core.trading import RiskEffect
from aqta.execution import (
    LiveBrokerStub,
    OrderGateway,
    OrderState,
    PaperBroker,
    Stage,
    execute_paper,
    leg_order,
)
from aqta.proposals import ApprovalTokenService, InMemoryNonceStore
from conftest import TEST_APPROVAL_SECRET
from factories import RiskRig, make_proposal


def _gateway(settings: Settings, clock: FrozenClock) -> tuple[OrderGateway, ApprovalTokenService]:
    tokens = ApprovalTokenService(TEST_APPROVAL_SECRET, clock, InMemoryNonceStore())
    rig = RiskRig(clock)
    gw = OrderGateway(settings, PaperBroker(), tokens, rig.engine, InMemoryAuditLog(clock), clock)
    return gw, tokens


def test_reducing_legs_go_first(clock: FrozenClock) -> None:
    p = make_proposal(clock, lots=(2, 2, 2))
    ordered = leg_order(p.legs)
    assert [leg.risk_effect for leg in ordered] == [
        RiskEffect.REDUCING,
        RiskEffect.REDUCING,
        RiskEffect.INCREASING,
    ]
    assert ordered[0].client_order_id == p.legs[1].client_order_id  # stable within a group


async def test_paper_execution_fills_every_leg(settings: Settings, clock: FrozenClock) -> None:
    gw, tokens = _gateway(settings, clock)
    p = make_proposal(clock, lots=(2, 2))
    issued = {leg.client_order_id: tokens.issue(leg, "kashyap") for leg in p.legs}
    results = await execute_paper(gw, p.legs, issued)
    assert [r.accepted for r in results] == [True, True]
    assert all(r.state is OrderState.FILLED for r in results)
    assert results[0].client_order_id == p.legs[1].client_order_id  # hedge first


async def test_paper_execution_stops_at_first_blocked_leg(
    settings: Settings, clock: FrozenClock
) -> None:
    gw, tokens = _gateway(settings, clock)
    p = make_proposal(clock, lots=(2, 2))
    issued = {p.legs[1].client_order_id: tokens.issue(p.legs[1], "kashyap")}  # main leg: none
    results = await execute_paper(gw, p.legs, issued)
    assert [r.accepted for r in results] == [True, False]
    assert results[1].stage is Stage.APPROVAL


async def test_refuses_live_mode(settings: Settings, clock: FrozenClock) -> None:
    live = settings.model_copy(
        update={"trading_mode": TradingMode.LIVE, "live_trading_enabled": True}
    )
    tokens = ApprovalTokenService(TEST_APPROVAL_SECRET, clock, InMemoryNonceStore())
    gw = OrderGateway(
        live, LiveBrokerStub(), tokens, RiskRig(clock).engine, InMemoryAuditLog(clock), clock
    )
    with pytest.raises(SafetyViolationError, match="CR-003"):
        await execute_paper(gw, make_proposal(clock).legs, {})
