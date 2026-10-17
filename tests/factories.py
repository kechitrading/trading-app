"""Test factories shared across unit and integration tests (on sys.path via pytest ``pythonpath``)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from aqta.core.clock import FrozenClock
from aqta.core.ids import new_id
from aqta.core.settings import RiskSettings
from aqta.core.trading import Exchange, Instrument, OrderRequest, Segment, Side
from aqta.risk import (
    InMemoryKillSwitchStore,
    InMemoryRiskEventSink,
    InMemoryRiskState,
    KillSwitch,
    PreTradeRiskEngine,
    RiskHalts,
    RiskLimits,
)

NIFTY_FUT = Instrument(symbol="NIFTY26OCTFUT", exchange=Exchange.NSE, segment=Segment.FUT, lot_size=75)


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
