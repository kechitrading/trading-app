#!/usr/bin/env bash
# Redeploy the previous image tag (or an explicit one). Target: done within 10 minutes (NFR-015).
# Usage: rollback.sh [image_tag]
# Migrations are expand-only (backward compatible), so the previous image runs on the newer schema.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/aqta}"
cd "$APP_DIR"
TAG="${1:-$(cat .previous_tag 2>/dev/null || true)}"
if [[ -z "$TAG" ]]; then
  echo "rollback: no previous tag recorded and none given" >&2
  exit 1
fi

export IMAGE_TAG="$TAG"
docker compose -f compose.prod.yml pull api worker
docker compose -f compose.prod.yml up -d --no-deps api worker

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/ready >/dev/null; then
    echo "$TAG" > .deployed_tag
    echo "rollback: healthy on $TAG"
    exit 0
  fi
  sleep 2
done
echo "rollback: $TAG did not become healthy" >&2
exit 1
