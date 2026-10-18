# trading-app

**AQTA: AI Quant Trading Assistant** (BRD-AQTA-001 v1.0). A personal, human-approved, paper-first
quant desk for NSE, BSE and MCX. This repository is the **project skeleton**. The safety-critical
core (risk checks, approval tokens, order gateway, audit log) is implemented and tested. The other
modules are typed interfaces and stubs, ready for feature work.

> Default mode is **PAPER**. No live broker code exists yet (broker: Angel One SmartAPI, Q-005; adapter not built).
> No order can reach a broker without a valid, unexpired, single-use approval token and a passing
> pre-trade risk check. Every step is written to a hash-chained, append-only audit log.

## Quick start (5 commands)

Needs [uv](https://docs.astral.sh/uv/), Docker with Compose, and `make`.

```bash
git clone https://github.com/kechitrading/trading-app.git && cd trading-app
uv sync                       # Python 3.12 venv + all deps (incl. dev tools)
make dev                      # creates .env with random dev secrets, starts api/worker/postgres/redis
curl localhost:8000/health    # {"status":"ok","mode":"paper"}
curl localhost:8000/ready     # {"status":"ready","checks":{"database":"ok","redis":"ok"}}
```

`make dev` runs Alembic migrations before the API and worker start. The API token for
`/api/v1/*` is in your generated `.env` (`API_TOKEN`):

```bash
curl -H "Authorization: Bearer $API_TOKEN" localhost:8000/api/v1/mode
```

## Everyday commands

| Command | What it does |
|---|---|
| `make lint` | ruff, ruff format check, mypy (strict on core/risk/execution/audit/proposals), import-linter |
| `make test` | pytest with coverage gates (risk >= 95%, risk+execution+audit >= 90%) |
| `make test-unit` | unit tests only (no database needed) |
| `make migrate` | `alembic upgrade head` against `DATABASE_URL` |
| `make api` / `make worker` | run the API / Arq worker on the host |
| `make audit-verify` | recompute the audit hash chain; exits non-zero on tamper |
| `make audit-deps` | pip-audit over the locked dependency set |

Integration tests need a disposable Postgres. Set `AQTA_TEST_DATABASE_URL` to run them; otherwise
they are skipped. They drop and recreate the schema.

## Layout

```
src/aqta/
  core/           settings, logging (redacting), IST time + clock, market calendar, db, redis, errors
  api/            FastAPI app factory, routers (/health, /ready, /api/v1/...), auth + MFA hook
  worker/         Arq worker, single job registry, IST crons
  audit/          append-only, SHA-256 hash-chained audit log + `python -m aqta.audit verify`
  risk/           pre-trade checks, daily-loss block, drawdown halt, kill switch   (implemented)
  execution/      BrokerPort, PaperBroker, LiveBrokerStub, order state machine, gateway (implemented)
  proposals/      proposal lifecycle, HMAC approval tokens                          (implemented)
  signals/        component interface, composite with visible contributions, astrology shadow mode
  strategy/       strategy registry + RULE-005 promotion state machine
  notifications/  NotifierPort, Telegram (allowlisted), fake notifier, 600-char summaries
  astrology/ ingestion/ analysis/ forecasting/ arbitrage/ portfolio/ backtest/ learning/ reports/ llm/
                  typed schemas + ports (stubs) referencing BRD IDs
migrations/       Alembic (baseline: append-only triggers, RULE-014 DB checks, Timescale hypertable)
deploy/           Dockerfile, compose (dev/prod), nginx example, deploy/rollback scripts, notes
docs/adr/         architecture decisions; docs/BRD_TRACEABILITY.md maps modules to BRD IDs
```

## Safety rules (summary; see CLAUDE.md)

1. `TRADING_MODE=paper` by default. `live` also needs `LIVE_TRADING_ENABLED=true`, or the app refuses to start.
2. One order path: proposal -> approval token -> risk checks -> broker port -> audit.
3. The audit log is append-only (a DB trigger blocks UPDATE/DELETE/TRUNCATE) and hash-chained.
4. No secrets in code or logs: `.env` is gitignored, production uses AWS Secrets Manager, CI runs gitleaks.
5. Astrology stays in shadow mode with weight 0 until a rule passes the accuracy gate and is approved.
6. Timestamps are stored in UTC and shown/scheduled in IST.

## Deployment

See [deploy/README.md](deploy/README.md). Every merge to `main` deploys automatically to the Mumbai
EC2 host once CI passes. Merges between 08:30 and 23:45 IST on weekdays are held for the nightly
23:50 IST deploy (NFR-015). A failed health check rolls back automatically.
