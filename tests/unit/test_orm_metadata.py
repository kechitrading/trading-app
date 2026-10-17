"""All ORM models register on the shared metadata with the baseline migration's tables."""

from __future__ import annotations

import importlib

from aqta.core.db import Base

MODEL_MODULES = [
    "aqta.audit.models",
    "aqta.proposals.models",
    "aqta.execution.models",
    "aqta.risk.models",
    "aqta.strategy.models",
    "aqta.astrology.models",
    "aqta.forecasting.models",
    "aqta.learning.models",
    "aqta.ingestion.models",
]


def test_models_cover_baseline_tables() -> None:
    for module in MODEL_MODULES:
        importlib.import_module(module)
    assert set(Base.metadata.tables) == {
        "audit_log",
        "proposals",
        "approvals",
        "orders",
        "risk_events",
        "kill_switch_state",
        "strategies",
        "astrology_rules",
        "forecasts",
        "config_versions",
        "market_ticks",
    }
    orders = Base.metadata.tables["orders"]
    assert orders.c.algo_tag.nullable is False  # FR-028
