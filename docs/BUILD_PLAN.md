# Build plan (BRD-AQTA-001 v1.1, manual execution per CR-003)

Phase 1 never sends orders to the broker. Paper mode simulates fills; in live mode Kashyap places
orders in the Angel One app from a ticket and the system reads them back (read-only). Tasks are
listed in order: each depends only on tasks above it. Target: paper trading from mid-January 2027
(TR-002).

## Stage 1: approval loop and paper P&L (no broker or data keys needed)

| # | Task | BRD IDs | Done when |
|---|---|---|---|
| 1 | Done: dashboard and API MFA (TOTP) | NFR-009, FR-052 | Approving or changing a limit fails without a valid TOTP code. |
| 2 | Proposals in the database; approve/reject/modify endpoints | FR-011, FR-023, FR-024 | Proposals survive a restart; approval after expiry is rejected. |
| 3 | Telegram approve/reject/modify buttons and `/kill` | FR-023, FR-034, NFR-017, FR-052 | Decision in 2 taps or fewer; unlisted accounts ignored and logged. |
| 4 | Shared trading-cost model (brokerage, STT, stamp duty, GST, exchange charges, slippage) | FR-021, FR-030, FR-046 | One model used by paper fills, arbitrage net edge and backtests. |
| 5 | Portfolio and P&L core: positions, live P&L, margin, Greeks aggregation | FR-014, BR-015 | Paper positions show P&L and margin, refreshed every 60 s in market hours. |
| 6 | Paper exits: stop-loss, target, thesis invalidation | FR-081, FR-015 | A paper position closes at the live price with costs when an exit condition is met. |
| 7 | Hypothetical tracking of rejected and expired proposals | FR-082 | Every skipped proposal has a stored P&L to exit. |
| 8 | Trade-event Telegram summaries (proposal, fill, adjustment, exit) | FR-044, FR-026 | Each event sends a summary of 600 characters or fewer within 10 s. |
| 9 | Strategy registry in the database | FR-051 | Strategies, status and approvals survive a restart; changes are audited. |
| 10 | Exception for strategies approved for undefined risk | FR-036, RULE-004 | Approved strategies pass within their own loss cap; others are blocked and logged. |
| 11 | Stale-data alerts and degraded signals | FR-004 | Data stale for more than 60 s alerts and excludes the signal from proposals. |
| 12 | AI and data budget alerts | FR-053, NFR-014 | 80% and 100% alerts are sent once per month. |

## Stage 2: Angel One read-only connection (needs the Angel One keys in `.env`)

| # | Task | BRD IDs | Done when |
|---|---|---|---|
| 13 | Angel One read-only adapter: TOTP login, session refresh, 08:45 IST login alert | FR-029, RULE-016 | The daily session logs in on its own or alerts by 08:45 IST. No order method exists. |
| 14 | Live quotes, option chains and open interest for the watchlist | FR-001 | Quote age is 5 s or less for at least 99% of watchlist instruments. |
| 15 | Order book, trades and positions sync; match orders to proposals | FR-078, FR-026, FR-027 | A ticketed order is matched with live P&L within 60 s of its fill. |
| 16 | Order tickets in Telegram and on the dashboard | FR-077 | Every ticket field is present and passes FR-031 checks. |
| 17 | Mismatch alerts and manual (outside system) trades | FR-079, FR-080, RULE-017 | Differences alert within 60 s; unmatched trades count toward risk limits. |
| 18 | Live exit alerts and manual-mode kill switch | FR-081, FR-084, FR-035 | Exit alerts within 10 s; the kill switch blocks proposals and lists open positions. |

## Stage 3: research, ideas and reports (needs Finnhub and Claude keys)

| # | Task | BRD IDs |
|---|---|---|
| 19 | Exchange daily files: bhavcopy, FII/DII, participant OI, bulk/block deals | FR-002, FR-057, FR-058 |
| 20 | News and speeches ingestion (Finnhub, RSS, official sites) | FR-003 |
| 21 | Claude adapter with cost tracking; news sentiment scoring | FR-006, FR-053, Q-010 |
| 22 | Technical and option analysis features | FR-008, FR-061, FR-062 |
| 23 | Real signal components in the composite signal | FR-009, FR-010, FR-060 |
| 24 | Trade idea generation and ranking by return on margin | FR-011, FR-012, FR-013 |
| 25 | Pre-market brief and post-market review, delivered as Telegram PDF | FR-038, FR-039, FR-045, D-014 |
| 26 | Rationale pack and performance report with the four trade groups | FR-043, FR-042, FR-083 |
| 27 | Arbitrage scanners | FR-017 to FR-022 |
| 28 | Forecasts, fundamentals, institutional map, astrology studies, learning | FR-055 to FR-076, FR-046 to FR-050 |

## Before paper start

- Rollout runbooks and recorded tests of the kill switch, drawdown halt, daily loss limit and
  reconciliation (TR-003, TR-006).
- Kashyap: ask Angel One Q-018 (read-only session needs no static IP; market data cost).

## Deferred by CR-003

Live `BrokerPort` adapter and API order placement (FR-025, FR-028, NFR-004, NFR-010, Q-002, Q-008).
These need a new change request and Kashyap's explicit approval.
