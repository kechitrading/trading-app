# BRD traceability (BRD-AQTA-001 v1.1)

Status: **Impl** = implemented and tested; **Partial** = some logic plus interfaces; **Stub** =
typed schemas and ports only.

| Module | Status | Serves | Notes |
|---|---|---|---|
| `core.settings` | Impl | RULE-001, RULE-002, RULE-003, RULE-014, FR-030, NFR-008, CON-002, ASM-004 | Paper default, live double opt-in, risk/budget/astrology defaults, `SecretStr` |
| `core.secrets` | Impl | NFR-008 | Env provider (dev), AWS Secrets Manager provider (prod) |
| `core.logs` | Impl | NFR-008 | structlog JSON + redaction processor |
| `core.timeutil`, `core.clock`, `core.market_calendar` | Impl | NFR-012, FR-029, FR-038, FR-039 | UTC storage, IST display, NSE/BSE/MCX sessions, holiday interface |
| `audit` | Impl | FR-054, NFR-011, BR-008 | Append-only trigger, SHA-256 chain, `verify` CLI |
| `risk` | Impl | BR-004, FR-031, FR-032, FR-033, FR-034, FR-036, RULE-002, RULE-003, REG-003, REG-004 | Pre-trade pipeline, daily-loss block, drawdown halt, kill switch; FR-035 auto-triggers TODO |
| `execution` | Impl | BR-003, FR-024, FR-025, FR-026, FR-028, FR-030, RULE-001, RULE-010 | Gateway, paper broker, state machine; FR-027 reconciliation is an interface |
| `proposals` | Impl | FR-011, FR-012, FR-016, FR-023, FR-024 | Lifecycle with validity window; HMAC tokens bound to the order hash |
| `signals` | Partial | BR-009, FR-006, FR-008, FR-009, FR-010, FR-049, FR-056, FR-060, FR-073 | Composite with per-component value/weight/contribution; components are stubs |
| `astrology` | Partial | BR-009, BR-020, FR-005, FR-055, FR-070..FR-076, RULE-007, RULE-014, RULE-015, ASM-013 | Rule registry, gate, effective weight; ephemeris and study runner are ports |
| `strategy` | Impl | BR-011, FR-051, RULE-004, RULE-005, RULE-009 | Promotion state machine; persistence TODO |
| `notifications` | Partial | BR-013, FR-023, FR-026, FR-044, FR-045, FR-052, NFR-017 | Telegram allowlist, fake notifier, 600-char summary; approve buttons TODO; WhatsApp pending Q-003 |
| `worker` | Partial | FR-038, FR-039, FR-047, FR-074, FR-076 | IST crons; jobs are placeholders |
| `api` | Partial | FR-034, FR-052, NFR-001, NFR-009 | Health/ready, mode, kill switch, proposals stub; MFA hook TODO |
| `ingestion` | Stub | BR-001, FR-001..FR-004, FR-057, FR-058, NFR-021 | Ports; FR-004 staleness checker implemented |
| `analysis` | Stub | BR-017, BR-018, FR-059, FR-061..FR-065, RULE-012 | Schemas + analyzer ports |
| `forecasting` | Stub | BR-019, FR-066, FR-067, FR-068, RULE-011, NFR-020, NFR-022 | Band schema, label, coverage/reliability check |
| `arbitrage` | Stub | BR-005, FR-017..FR-022, NFR-003 | Scanner port; net-edge calculator implemented |
| `portfolio` | Stub | BR-015, FR-013, FR-014 | Positions, Greeks aggregation, margin, P&L |
| `backtest` | Stub | BR-011, FR-046 | Engine/cost/slippage ports; walk-forward splitter implemented |
| `learning` | Stub | BR-010, FR-047, FR-048, FR-050, RULE-006 | Change lifecycle (evidence before approval), version store port |
| `reports` | Stub | BR-007, BR-008, FR-038..FR-045, FR-065 | Report types, rationale pack schema, template registry, exporter port |
| `llm` | Stub | FR-053, NFR-014, CON-002, Q-010 | LLM port; monthly cost tracker with 80%/100% alerts implemented |
| `migrations` | Impl | FR-054, NFR-011, RULE-014, FR-001, FR-048 | Baseline schema, triggers, check constraints, hypertable |
| `deploy/`, `.github/workflows` | Impl | NFR-008, NFR-010, NFR-012, NFR-015, CON-003 | Non-root image, Secrets Manager injection, IST deploy freeze, rollback |

## Not yet covered by any module
FR-007 (event calendar), FR-015 (position re-evaluation), FR-029 (broker 2FA login alert),
FR-035 (automatic kill-switch triggers), FR-037 (risk-limit change cooling-off), FR-040/FR-041/
FR-042 report content, NFR-002 state recovery from the broker, and TR-001..TR-008 runbooks.

Added by CR-003 (manual execution, v1.1) and not yet built: FR-077 (order tickets), FR-078
(read-only order sync), FR-079 (mismatch alerts), FR-080 (manual trades), FR-081 (exit alerts and
paper exits), FR-082 (skipped-proposal tracking), FR-083 (four-group performance report), FR-084
(manual-mode kill switch). Deferred by CR-003: FR-025, FR-028, NFR-004, NFR-010.
