"""Baseline schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-17

Tables: audit_log (append-only, hash-chained), proposals, approvals, orders, risk_events
(append-only), kill_switch_state, strategies, astrology_rules, forecasts, config_versions and the
market_ticks placeholder (Timescale hypertable when the extension is available).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
MONEY = sa.Numeric(18, 2)
PRICE = sa.Numeric(18, 4)

APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION aqta_block_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only (FR-054, NFR-011): % rejected', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
"""


def _append_only(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION aqta_block_mutation();"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION aqta_block_mutation();"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM PUBLIC;")


def upgrade() -> None:
    op.execute(APPEND_ONLY_FN)

    # --- audit_log: FR-054, NFR-011 (retain 5 years; TODO: daily head-hash anchor to S3 Object Lock)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("occurred_at", TZ, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.UniqueConstraint("hash", name="uq_audit_log_hash"),
    )
    op.create_index(
        "ix_audit_log_event_type_occurred_at", "audit_log", ["event_type", "occurred_at"]
    )
    _append_only("audit_log")

    # --- proposals: FR-011, FR-012, FR-023; TODO(FR-043) rationale pack freeze at approval
    op.create_table(
        "proposals",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("horizon", sa.String(20), nullable=False),
        sa.Column("strategy_id", sa.String(64)),
        sa.Column("underlying", sa.String(40), nullable=False),
        sa.Column("legs", JSONB, nullable=False),
        sa.Column("max_loss_inr", MONEY),
        sa.Column("margin_required_inr", MONEY),
        sa.Column("return_on_margin", sa.Numeric(10, 4)),
        sa.Column("valid_until", TZ, nullable=False),
        sa.Column("rationale", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id", name="pk_proposals"),
    )
    op.create_index("ix_proposals_status", "proposals", ["status"])

    # --- approvals: RULE-001, FR-023, FR-024 (single-use nonce, bound to order payload hash)
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("order_payload_hash", sa.String(64), nullable=False),
        sa.Column("token_nonce", sa.String(64), nullable=False),
        sa.Column("issued_at", TZ, nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("consumed_at", TZ),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposals.id"], name="fk_approvals_proposal_id_proposals"
        ),
        sa.UniqueConstraint("token_nonce", name="uq_approvals_token_nonce"),
    )
    op.create_index("ix_approvals_proposal_id", "approvals", ["proposal_id"])

    # --- orders: FR-025..FR-028, FR-030 (mode), algo tag mandatory
    op.create_table(
        "orders",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(64)),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("broker", sa.String(30), nullable=False),
        sa.Column("broker_order_id", sa.String(64)),
        sa.Column("algo_tag", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(60), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("filled_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("limit_price", PRICE),
        sa.Column("avg_fill_price", PRICE),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposals.id"], name="fk_orders_proposal_id_proposals"
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["approvals.id"], name="fk_orders_approval_id_approvals"
        ),
        sa.UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
        sa.CheckConstraint("mode IN ('paper', 'live')", name="mode"),
        sa.CheckConstraint("length(algo_tag) > 0", name="algo_tag"),
    )
    op.create_index("ix_orders_proposal_id", "orders", ["proposal_id"])
    op.create_index("ix_orders_broker_order_id", "orders", ["broker_order_id"])
    op.create_index("ix_orders_state", "orders", ["state"])

    # --- risk_events: FR-031..FR-035 history (append-only)
    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("occurred_at", TZ, nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id", name="pk_risk_events"),
    )
    op.create_index("ix_risk_events_event_type", "risk_events", ["event_type"])
    _append_only("risk_events")

    # --- kill_switch_state: FR-034 durable state (Redis is the fast path)
    op.create_table(
        "kill_switch_state",
        sa.Column("id", sa.Integer, nullable=False, autoincrement=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", TZ, nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text),
        sa.PrimaryKeyConstraint("id", name="pk_kill_switch_state"),
        sa.CheckConstraint("id = 1", name="single_row"),
    )

    # --- strategies: FR-051, RULE-004 (undefined risk per strategy), RULE-005 promotion path
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rule_set", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("loss_cap_inr", MONEY),
        sa.Column(
            "undefined_risk_approved", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("approval", JSONB),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_strategies"),
        sa.UniqueConstraint("name", name="uq_strategies_name"),
        sa.CheckConstraint(
            "status IN ('draft', 'backtest', 'paper', 'live', 'retired')",
            name="status",
        ),
    )

    # --- astrology_rules: FR-075; RULE-014 enforced in the DB as well as in code
    op.create_table(
        "astrology_rules",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("family", sa.String(30), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("weight", sa.Numeric(8, 6), nullable=False, server_default="0"),
        sa.Column("hypothesis", JSONB, nullable=False),
        sa.Column("test_plan", JSONB, nullable=False),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("approved_at", TZ),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_astrology_rules"),
        sa.CheckConstraint(
            "status IN ('candidate', 'shadow', 'active', 'demoted', 'retired')",
            name="status",
        ),
        sa.CheckConstraint(
            "status = 'active' OR weight = 0", name="weight_zero_unless_active"
        ),
        sa.CheckConstraint(
            "weight = 0 OR approved_at IS NOT NULL",
            name="weight_needs_approval",
        ),
    )

    # --- forecasts: FR-066, FR-068, NFR-022 (immutable once stored; actual filled at maturity)
    op.create_table(
        "forecasts",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("symbol", sa.String(60), nullable=False),
        sa.Column("horizon", sa.String(20), nullable=False),
        sa.Column("model_version", sa.String(40), nullable=False),
        sa.Column("data_snapshot_at", TZ, nullable=False),
        sa.Column("target_at", TZ, nullable=False),
        sa.Column("p10", PRICE, nullable=False),
        sa.Column("p50", PRICE, nullable=False),
        sa.Column("p90", PRICE, nullable=False),
        sa.Column("scenarios", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actual", PRICE),
        sa.Column("matured_at", TZ),
        sa.PrimaryKeyConstraint("id", name="pk_forecasts"),
        sa.CheckConstraint("p10 <= p50 AND p50 <= p90", name="band_order"),
    )
    op.create_index("ix_forecasts_symbol", "forecasts", ["symbol"])

    # --- config_versions: FR-047, FR-048 (versioned weights/limits/models; rollback = re-activate)
    op.create_table(
        "config_versions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("approved_at", TZ),
        sa.PrimaryKeyConstraint("id", name="pk_config_versions"),
        sa.UniqueConstraint("kind", "version", name="uq_config_versions_kind_version"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_config_versions_one_active ON config_versions (kind) WHERE active"
    )

    # --- market_ticks: FR-001 placeholder; Timescale hypertable when the extension exists
    op.create_table(
        "market_ticks",
        sa.Column("time", TZ, nullable=False),
        sa.Column("symbol", sa.String(60), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("ltp", PRICE, nullable=False),
        sa.Column("bid", PRICE),
        sa.Column("ask", PRICE),
        sa.Column("volume", sa.BigInteger),
        sa.Column("open_interest", sa.BigInteger),
        sa.PrimaryKeyConstraint("time", "symbol", "exchange", name="pk_market_ticks"),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
                PERFORM create_hypertable('market_ticks', 'time', if_not_exists => TRUE);
            ELSE
                RAISE NOTICE 'timescaledb not available: market_ticks stays a plain table';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    for table in (
        "market_ticks",
        "config_versions",
        "forecasts",
        "astrology_rules",
        "strategies",
        "kill_switch_state",
        "orders",
        "approvals",
        "proposals",
    ):
        op.drop_table(table)
    # Append-only tables need their triggers removed before they can be dropped.
    for table in ("risk_events", "audit_log"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table};")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update_delete ON {table};")
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS aqta_block_mutation();")
