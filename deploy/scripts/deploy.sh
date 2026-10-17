#!/usr/bin/env bash
# Deploy IMAGE_TAG on the production host. Called by .github/workflows/deploy.yml over SSH.
# Usage: deploy.sh <image_tag>
# Keeps the previous tag so rollback.sh can restore it within minutes (NFR-015: rollback <= 10 min).
set -euo pipefail

TAG="${1:?usage: deploy.sh <image_tag>}"
APP_DIR="${APP_DIR:-/opt/aqta}"
COMPOSE=(docker compose -f "$APP_DIR/compose.prod.yml")
HEALTH_URL="http://127.0.0.1:8000/ready"
SECRET_ID="${AWS_SECRET_ID:-aqta/prod}"

cd "$APP_DIR"
log() { printf '%s [deploy] %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Postgres container password from Secrets Manager (instance role; never written to git).
install -d -m 700 /run/aqta
aws secretsmanager get-secret-value --region ap-south-1 --secret-id "$SECRET_ID" \
  --query SecretString --output text \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["POSTGRES_PASSWORD"], end="")' \
  > /run/aqta/pg_password
chmod 600 /run/aqta/pg_password

if [[ -f .deployed_tag ]]; then
  cp .deployed_tag .previous_tag
fi

log "pulling ghcr.io/kechitrading/trading-app:$TAG"
export IMAGE_TAG="$TAG"
"${COMPOSE[@]}" pull api worker migrate
log "running migrations"
"${COMPOSE[@]}" run --rm migrate
log "starting services"
"${COMPOSE[@]}" up -d --remove-orphans postgres redis api worker

for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    echo "$TAG" > .deployed_tag
    log "healthy on $TAG"
    exit 0
  fi
  sleep 2
done

log "health check failed for $TAG; rolling back"
"$APP_DIR/rollback.sh"
exit 1
