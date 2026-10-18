"""Test factories shared by unit and integration tests (on sys.path via pytest ``pythonpath``)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from aqta.core.clock import FrozenClock
from aqta.core.ids import new_id
from aqta.core.settings import RiskSettings
from aqta.core.trading import Exchange, Instrument, OrderRequest, RiskEffect, Segment, Side
from aqta.proposals import Horizon, Proposal, ProposalStatus
from aqta.risk import (
    InMemoryKillSwitchStore,
    InMemoryRiskEventSink,
    InMemoryRiskState,
    KillSwitch,
    PreTradeRiskEngine,
    RiskHalts,
    RiskLimits,
)

NIFTY_FUT = Instrument(
    symbol="NIFTY26OCTFUT", exchange=Exchange.NSE, segment=Segment.FUT, lot_size=75
)


def make_order(**overrides: Any) -> OrderRequest:
    data: dict[str, Any] = {
        "client_order_id": new_id("co"),
        "proposal_id": "prop_1",
        "instrument": NIFTY_FUT,
        "side": Side.BUY,
        "quantity": 75,
        "limit_price": Decimal("25000"),
        "reference_price": Decimal("25000"),
        "max_loss_inr": Decimal("5000"),
        "margin_required_inr": Decimal("150000"),
    }
    data.update(overrides)
    return OrderRequest(**data)


NIFTY_CE = Instrument(
    symbol="NIFTY26OCT25000CE", exchange=Exchange.NSE, segment=Segment.OPT, lot_size=75
)


def make_proposal(clock: FrozenClock, lots: tuple[int, ...] = (2,), **overrides: Any) -> Proposal:
    """A pending proposal. First leg buys futures; any further legs are risk-reducing option
    hedges (sold calls), so leg ordering can be tested."""
    pid = overrides.pop("id", new_id("prop"))
    legs = []
    for i, n in enumerate(lots):
        hedge = i > 0
        legs.append(
            make_order(
                client_order_id=f"{pid}_l{i + 1}",
                proposal_id=pid,
                instrument=NIFTY_CE if hedge else NIFTY_FUT,
                side=Side.SELL if hedge else Side.BUY,
                quantity=75 * n,
                limit_price=Decimal("120") if hedge else Decimal("25000"),
                reference_price=Decimal("120") if hedge else Decimal("25000"),
                risk_effect=RiskEffect.REDUCING if hedge else RiskEffect.INCREASING,
                max_loss_inr=Decimal("1000") * n,
                margin_required_inr=Decimal("20000") * n,
            )
        )
    data: dict[str, Any] = {
        "id": pid,
        "created_at": clock.now(),
        "valid_until": clock.now() + timedelta(minutes=5),
        "horizon": Horizon.INTRADAY,
        "underlying": "NIFTY",
        "legs": tuple(legs),
        "max_loss_inr": Decimal("1000") * sum(lots),
        "margin_required_inr": Decimal("20000") * sum(lots),
        "return_on_margin": Decimal("0.0500"),
        "status": ProposalStatus.PENDING_APPROVAL,
    }
    data.update(overrides)
    return Proposal(**data)


class RiskRig:
    """A fully wired in-memory risk engine for tests."""

    def __init__(self, clock: FrozenClock, risk: RiskSettings | None = None) -> None:
        from aqta.audit import InMemoryAuditLog

        self.clock = clock
        self.limits = RiskLimits.from_settings(risk or RiskSettings())
        self.audit = InMemoryAuditLog(clock)
        self.events = InMemoryRiskEventSink()
        self.state = InMemoryRiskState(self.limits.capital_inr)
        self.ks_store = InMemoryKillSwitchStore()
        self.kill_switch = KillSwitch(self.ks_store, self.audit, self.events, clock)
        self.halts = RiskHalts(self.limits, clock, self.events, self.audit)
        self.engine = PreTradeRiskEngine(
            self.limits, self.state, self.kill_switch, self.halts, self.events, clock
        )
