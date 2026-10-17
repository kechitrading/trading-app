# ADR-0004: PostgreSQL 16 + TimescaleDB as the single datastore

- Status: Accepted (2026-10-17)

## Context
We need relational integrity for proposals, approvals and orders, immutable audit history
(NFR-011), and years of tick/bar history for backtests and studies (NFR-018), on one modest host.

## Decision
PostgreSQL 16 with the TimescaleDB extension, self-hosted in Docker on the EC2 host (Amazon RDS
does not offer TimescaleDB). Time-series tables (`market_ticks` now; bars later) become
hypertables. Append-only tables are protected by triggers that reject UPDATE/DELETE/TRUNCATE.
RULE-014 is also a DB check constraint on `astrology_rules`. The baseline migration creates the
hypertable only when the extension is available, so plain Postgres works for local tests.

## Consequences
- One backup/restore story (nightly `pg_dump` to S3). Compression and retention policies come later.
- We run the database ourselves (patching, disk monitoring).
- A table owner or superuser can still disable triggers. The hash chain makes that detectable
  (`python -m aqta.audit verify`). TODO: anchor the head hash daily outside the DB.
