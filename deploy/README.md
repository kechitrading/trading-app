# Deployment notes

AQTA runs as one Docker image with three roles: `api` (uvicorn), `worker` (arq) and `migrate`
(alembic). Postgres 16 with TimescaleDB and Redis 7 run beside them.

## Local

```bash
make dev   # creates .env with random dev secrets if missing, then docker compose up --build
```

## Production host (one-time setup, not automated here)

- **EC2 in ap-south-1 (Mumbai)** with an **Elastic IP** registered with the broker (NFR-010, REG-001).
  Change the IP at most once per calendar week.
- **Instance role** allowed `secretsmanager:GetSecretValue` on `aqta/prod` only. Nothing else holds AWS keys.
- **Secrets Manager** secret `aqta/prod` is a JSON object whose keys are setting names:
  `DATABASE_URL`, `REDIS_URL`, `API_TOKEN`, `APPROVAL_SECRET`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_ALLOWED_USER_ID`, `POSTGRES_PASSWORD`, and so on. The app reads it at start-up
  (`SECRETS_PROVIDER=aws`). `deploy.sh` copies `POSTGRES_PASSWORD` into `/run/aqta/pg_password` for the DB container.
- **Docker + compose plugin, AWS CLI, nginx, certbot** installed. Run `docker login ghcr.io` once,
  using a read-only (`read:packages`) token.
- Files in `/opt/aqta`: `compose.prod.yml`, `deploy.sh`, `rollback.sh` (copied from `deploy/`).
- **NTP**: chrony on, with Amazon Time Sync (NFR-012).
- **Security group**: 443 from Kashyap's IPs only; 22 from the GitHub deploy path (or use SSM, below).
- Run a nightly `pg_dump` to S3. Audit rows are kept for 5 years (NFR-011).

## Restart behaviour (NFR-002)

Compose `restart: unless-stopped` brings containers back. To survive host reboots, enable Docker
at boot (`systemctl enable docker`). An alternative is a systemd unit:

```ini
# /etc/systemd/system/aqta.service
[Unit]
Description=AQTA stack
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/aqta
EnvironmentFile=/opt/aqta/.image_env
ExecStart=/usr/bin/docker compose -f compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f compose.prod.yml down

[Install]
WantedBy=multi-user.target
```

## Deploys and rollback (NFR-015)

**Merging to `main` deploys automatically.** When CI passes on a push to `main`,
`.github/workflows/deploy.yml` builds and pushes `ghcr.io/kechitrading/trading-app:<sha>`, then
runs `deploy.sh <sha>` over SSH.

| Trigger | Inside 08:30-23:45 IST, Mon-Fri | Outside that window |
|---|---|---|
| CI green on `main` (merge/push) | skipped with a notice; the nightly run deploys it | deploys |
| Nightly 23:50 IST (Mon-Fri) | n/a | deploys `main`'s head if CI passed and it isn't live yet |
| Version tag `v*` | skipped with a notice | deploys (CI must have passed for that commit) |
| Manual run (Actions -> Deploy) | fails, unless `force=true` with a reason (logged as a warning) | deploys or rolls back |

Nothing deploys while the `DEPLOY_HOST` secret is unset: the run is skipped with a notice. Failed
CI never deploys. If the `production` environment has required reviewers, each deploy waits for
your approval in GitHub; without reviewers it is fully automatic.

`deploy.sh` does nothing if the requested tag is already live and healthy. Set
`FORCE_REDEPLOY=1` on the host to override that. It keeps the previous tag, and a failed health
check triggers `rollback.sh` automatically. A manual rollback is the `rollback` action of the
same workflow.

Migrations must stay **expand-only** (add columns/tables; never drop or rename within one release),
so that the previous image can still run after a rollback.

## ECS alternative

If the stack moves to ECS, keep one task definition per role. Inject secrets through the
`secrets:` field (Secrets Manager ARNs) and keep the Elastic IP behind a NAT gateway for broker
egress. Nothing in the application code changes.
