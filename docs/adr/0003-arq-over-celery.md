# ADR-0003: Arq (Redis) over Celery for jobs and schedules

- Status: Accepted (2026-10-17)

## Context
The codebase is async end to end (FastAPI, SQLAlchemy async, aiogram). Scheduled jobs are few but
time-critical in IST (pre-market 08:30, post-market 17:00, MCX wrap 23:45, monthly astrology study,
weekly learning proposals). Redis is already needed for the kill-switch fast path and nonces.

## Decision
Use Arq: native asyncio, Redis-backed, cron jobs built in, with the worker `timezone` set to
Asia/Kolkata. All schedules live in one registry (`aqta.worker.registry.REGISTRY`).

## Consequences
- No sync/async bridging and no extra broker (RabbitMQ) to operate.
- Fewer features than Celery (no canvas or chords); acceptable at this scale.
- Crons know weekdays, not exchange holidays, so jobs must consult `MarketCalendar` (TODO in the registry).
