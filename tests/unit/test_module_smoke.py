"""One smoke test per scaffolded module (ingestion, analysis, forecasting, arbitrage, portfolio,
backtest, learning, reports, llm, astrology ports)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aqta.analysis import LAG_LABEL, InstitutionalPosition
from aqta.arbitrage import ArbitrageOpportunity, Costs, Leg, ScannerKind
from aqta.astrology import MundaneEvent, PlanetPosition
from aqta.backtest import walk_forward
from aqta.core.errors import InvalidTransitionError
from aqta.core.settings import BudgetSettings
from aqta.core.trading import Exchange, Instrument
from aqta.forecasting import FORECAST_LABEL, Forecast, ForecastHorizon, band_coverage
from aqta.ingestion import FeedHealth, check_staleness
from aqta.learning import ChangeStatus, ConfigKind, LearnedChange, advance
from aqta.llm import CostTracker
from aqta.portfolio import Greeks, PortfolioSnapshot, Position
from aqta.reports import DISCLAIMER, Report, ReportType, TemplateRegistry

NOW = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)


def test_ingestion_staleness() -> None:
    assert check_staleness("feed", None, NOW).health is FeedHealth.MISSING
    assert check_staleness("feed", NOW - timedelta(seconds=60), NOW).health is FeedHealth.OK
    stale = check_staleness("feed", NOW - timedelta(seconds=61), NOW)
    assert stale.health is FeedHealth.DEGRADED and stale.age_seconds == 61


def test_analysis_institutional_label() -> None:
    pos = InstitutionalPosition(
        instrument="NIFTY", score=0.3, data_date=date(2026, 10, 19), available_at=NOW
    )
    assert pos.label == LAG_LABEL


def _forecast(p10: str, p50: str, p90: str) -> Forecast:
    return Forecast(
        symbol="NIFTY",
        horizon=ForecastHorizon.WEEK,
        model_version="m0",
        data_snapshot_at=NOW,
        target_at=NOW + timedelta(days=7),
        p10=Decimal(p10),
        p50=Decimal(p50),
        p90=Decimal(p90),
    )


def test_forecasting_bands_and_coverage() -> None:
    f = _forecast("24000", "25000", "26000")
    assert f.label == FORECAST_LABEL
    with pytest.raises(ValueError, match="p10"):
        _forecast("26000", "25000", "24000")
    assert band_coverage([]).coverage is None
    few = band_coverage([(f, Decimal("25500"))] * 10)
    assert few.coverage == 1.0 and few.reliable is None
    inside = [(f, Decimal("25000"))] * 24
    outside = [(f, Decimal("27000"))] * 6
    assert band_coverage(inside + outside).reliable is True  # 80%
    assert band_coverage([(f, Decimal("25000"))] * 30).reliable is False  # 100%: too wide


def test_arbitrage_net_edge() -> None:
    opp = ArbitrageOpportunity(
        kind=ScannerKind.CASH_FUTURES_CALENDAR,
        legs=[
            Leg(symbol="RELIANCE", side="BUY", quantity=500, price=Decimal("2900")),
            Leg(symbol="RELIANCE-FUT", side="SELL", quantity=500, price=Decimal("2920")),
        ],
        gross_edge_inr=Decimal("10000"),
        costs=Costs(
            brokerage=Decimal("100"),
            taxes=Decimal("1500"),
            exchange_charges=Decimal("200"),
            slippage=Decimal("700"),
            funding=Decimal("2500"),
        ),
        capital_inr=Decimal("1450000"),
        liquidity_ok=True,
    )
    assert opp.costs.total == Decimal("5000")
    assert opp.net_edge_inr == Decimal("5000")
    assert opp.meets(Decimal("30")) and not opp.meets(Decimal("40"))


def test_portfolio_aggregation() -> None:
    ins = Instrument(symbol="NIFTY", exchange=Exchange.NSE, lot_size=75)
    snap = PortfolioSnapshot(
        as_of=NOW,
        positions=[
            Position(
                instrument=ins,
                quantity=75,
                average_price=Decimal(100),
                last_price=Decimal(110),
                greeks=Greeks(delta=40, theta=-5),
                margin_inr=Decimal(1000),
            ),
            Position(
                instrument=ins,
                quantity=-75,
                average_price=Decimal(50),
                last_price=Decimal(40),
                greeks=Greeks(delta=-20, vega=3),
                margin_inr=Decimal(500),
            ),
        ],
    )
    assert snap.net_greeks == Greeks(delta=20, gamma=0, vega=3, theta=-5)
    assert snap.margin_used_inr == Decimal(1500)
    assert snap.unrealised_pnl_inr == Decimal(1500)


def test_backtest_walk_forward_has_no_overlap() -> None:
    splits = walk_forward(date(2020, 1, 1), date(2020, 12, 31), train_days=180, test_days=30)
    assert len(splits) == 6
    for s in splits:
        assert s.train_end < s.test_start
    with pytest.raises(ValueError, match="positive"):
        walk_forward(date(2020, 1, 1), date(2020, 2, 1), 0, 5)


def test_learning_change_needs_evidence_and_approval() -> None:
    change = LearnedChange(
        id="c1",
        kind=ConfigKind.SIGNAL_WEIGHTS,
        from_version=1,
        to_version=2,
        payload={"news_sentiment": 0.3},
        proposed_at=NOW,
    )
    with pytest.raises(InvalidTransitionError, match="evidence"):
        advance(change, ChangeStatus.APPROVED, "kashyap")
    with pytest.raises(InvalidTransitionError):
        advance(change, ChangeStatus.APPLIED)
    approved = advance(
        change.model_copy(update={"evidence": {"oos_sharpe": 1.2}}),
        ChangeStatus.APPROVED,
        "kashyap",
    )
    assert approved.approved_by == "kashyap"
    applied = advance(approved, ChangeStatus.APPLIED)
    assert advance(applied, ChangeStatus.ROLLED_BACK).status is ChangeStatus.ROLLED_BACK


def test_reports_carry_disclaimer() -> None:
    report = Report(type=ReportType.PRE_MARKET, title="Brief", generated_at=NOW)
    assert report.disclaimer == DISCLAIMER and "not guarantees" in DISCLAIMER
    reg = TemplateRegistry()
    reg.register(ReportType.PRE_MARKET, "pre_market.md.j2")
    assert reg.get(ReportType.PRE_MARKET) == "pre_market.md.j2"


def test_llm_cost_tracker_alerts_at_80_and_100() -> None:
    tracker = CostTracker.for_ai(BudgetSettings())
    day = date(2026, 10, 5)
    assert tracker.record(day, Decimal("1500")) == []
    (a80,) = tracker.record(day, Decimal("100"))
    assert a80.threshold_pct == 80 and a80.cap_inr == Decimal("2000")
    assert tracker.record(day, Decimal("10")) == []  # alerts fire once per month
    (a100,) = tracker.record(day, Decimal("400"))
    assert a100.threshold_pct == 100 and tracker.over_budget(day)
    assert not tracker.over_budget(date(2026, 11, 1))
    assert (
        CostTracker.for_data(BudgetSettings()).record(day, Decimal("1000"))[-1].threshold_pct == 100
    )


def test_astrology_port_schemas() -> None:
    assert PlanetPosition(body="Saturn", longitude_deg=331.2).retrograde is False
    ev = MundaneEvent(
        on=date(2026, 10, 20), kind="ingress", description="x", rule_id="r", rule_set_version="0"
    )
    assert ev.rule_set_version == "0"
