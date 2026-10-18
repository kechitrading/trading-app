# CLAUDE.md: rules for AI coding sessions on AQTA

AQTA is a personal trading assistant for Kashyap (BRD-AQTA-001, `docs/BRD_AI-Quant-Trading-Assistant_v1.0.md`,
kept locally and not in git). Read the BRD section for the feature you touch, and cite BRD IDs
(FR-xxx, RULE-xxx) in docstrings and TODOs.

## Non-negotiable safety rules

1. **Paper by default.** `TRADING_MODE` is `paper` | `live`, default `paper`. `live` also needs
   `LIVE_TRADING_ENABLED=true`; `Settings` refuses to load otherwise. Never weaken this.
2. **Never add live-order code without an explicit instruction from Kashyap in the chat.** That
   covers any real `BrokerPort` adapter, broker SDKs, broker credentials, or changes to
   `LiveBrokerStub`. The broker is Angel One SmartAPI (Q-005, decided 2026-10-18); its
   credentials exist only as `SecretStr` settings until Kashyap approves the adapter.
3. **One order path, no bypass.** proposal -> approval token -> `PreTradeRiskEngine.evaluate`
   -> `BrokerPort` -> audit. Only `OrderGateway.submit_order(order, approval_token)` may call
   `place_order`. Tokens are HMAC-signed, expire (default 5 min), are single-use and are bound to the
   order's payload hash (RULE-001, FR-024).
4. **Risk sits between approval and broker** (FR-031). `risk` and `execution` must never import
   `signals`, `forecasting`, `astrology` or `analysis` (RULE-013; enforced by import-linter).
5. **Audit is append-only and hash-chained** (FR-054, NFR-011). Never add UPDATE/DELETE paths for
   `audit_log` or `risk_events`, and never drop their triggers in a migration.
6. **No secrets in code, logs, tests or fixtures** (NFR-008). Use `SecretStr` settings. The log
   redaction processor masks credential-like keys and values. CI runs gitleaks.
7. **Astrology stays in shadow mode with weight 0** (RULE-014) until a rule is `active`, passed the
   ASM-013 gate, and is approved, and the global `ASTROLOGY__SHADOW_MODE` is off. The DB has
   check constraints for this too.
8. **Time:** store UTC (`timestamptz`, aware datetimes only); display and schedule in IST
   (`aqta.core.timeutil`, worker `timezone=IST`). Inject a `Clock` and never call `datetime.now()`
   in domain code.
9. Kill switch reads **fail closed**: if the store cannot be read, treat the switch as active.
10. Changes that loosen a risk limit need FR-037 (two-step confirmation, 24h cooling-off). Ask first.

## Architecture rules

- Modular monolith with two processes (`api`, `worker`) sharing `src/aqta`. See `docs/adr/`.
- Each module's public API is its `__init__.py`; other modules import only from it. Exceptions:
  `aqta.core.*` submodules (the shared kernel), and `aqta.<module>.adapters` imported from the
  composition roots `aqta.api` / `aqta.worker`. `tests/unit/test_module_boundaries.py` enforces this.
- Dependency direction: `api`/`worker` -> services -> domain -> ports. Domain code never imports
  FastAPI/Starlette, `aqta.api` or `aqta.worker` (import-linter). External systems (broker, data,
  LLM, Telegram) sit behind ports with swappable adapters.
- ORM models live in `<module>/models.py`; infrastructure adapters in `<module>/adapters.py`.
  New tables need an Alembic migration. `alembic check` must report no drift.
- Migrations are expand-only within a release (rollback safety, NFR-015).

## Working commands

```bash
uv sync                      # install
make lint                    # ruff + format check + mypy + import-linter
make test                    # full suite + coverage gates (needs AQTA_TEST_DATABASE_URL for integration)
make test-unit               # no DB needed
uv run pytest tests/unit/risk -q
uv run alembic revision -m "..." && uv run alembic upgrade head && uv run alembic check
python -m aqta.audit verify
```

Coverage gates: `risk` >= 95%, `risk`+`execution`+`audit` >= 90%. mypy is strict on `core`,
`risk`, `execution`, `audit` and `proposals`. Property tests (hypothesis) cover risk invariants.
Keep them passing, and add property tests when you change a risk check.

## Style

Python 3.12, ruff (line length 100), Pydantic v2 models (frozen where they are values),
`Decimal` for money, StrEnum for states, small pure functions for rules, conventional commits.
