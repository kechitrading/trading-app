# ADR-0001: Modular monolith with two processes

- Status: Accepted (2026-10-17)

## Context
One user, one AWS host, small ops budget (CON-002, CON-003). The BRD spans many domains (ingestion,
signals, risk, execution, reports, learning), and some of them are safety-critical, so they need
strict boundaries.

## Decision
A single Python codebase (`src/aqta`) deployed as one image with two processes: `api` (FastAPI) and
`worker` (Arq). Modules are packages with a small public API (`__init__.py`). Boundaries are
enforced by import-linter contracts and a module-boundary test. The key contract: `risk`/`execution`
never import analysis modules (RULE-013).

## Consequences
- One deploy, one migration stream, simple local dev (`make dev`).
- Modules can be split into services later if needed, because they already talk through ports.
- Discipline depends on CI contracts, which must stay green.
