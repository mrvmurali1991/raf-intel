#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# RAF Intelligence — Pre-deploy smoke test
#
# Run AFTER `docker compose build` but BEFORE `docker compose up -d`.
# Boots a throwaway backend container, verifies Python imports, then probes
# the /health endpoint.  Exits 0 on green; exits 1 and prints the failure.
#
# Usage:
#   bash scripts/smoke_test.sh
#   IMAGE_TAG=v1.2.3 bash scripts/smoke_test.sh
# ---------------------------------------------------------------------------
set -euo pipefail

IMAGE="raf-backend:${IMAGE_TAG:-latest}"
SMOKE_PORT=18500
CONTAINER_NAME="raf-smoke-$$"
HEALTH_URL="http://localhost:${SMOKE_PORT}/health"
MAX_WAIT=30   # seconds to wait for /health to return 200

cleanup() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "==> [smoke] Image: ${IMAGE}"

# ---------------------------------------------------------------------------
# 1. Import check — runs instantly in a one-shot container, no network needed.
# ---------------------------------------------------------------------------
echo "==> [smoke] Checking Python imports..."

docker run --rm \
  --name "${CONTAINER_NAME}-imports" \
  --entrypoint python \
  -e REDIS_URL="redis://localhost:6379/0" \
  -e RAF_DB_HOST="localhost" \
  -e RAF_DB_PORT="3306" \
  -e RAF_DB_USER="smoke" \
  -e RAF_DB_PASSWORD="smoke" \
  -e RAF_DB_NAME="smoke" \
  -e OPENEMR_DB_HOST="localhost" \
  -e OPENEMR_DB_PORT="3306" \
  -e OPENEMR_DB_USER="smoke" \
  -e OPENEMR_DB_PASSWORD="smoke" \
  -e OPENEMR_DB_NAME="smoke" \
  -e JWT_SECRET="smoke-secret-not-real" \
  -e JWT_REFRESH_SECRET="smoke-refresh-not-real" \
  -e APP_ENV="smoke" \
  -e ENCRYPTION_SALT="smoketest00000000" \
  -e DATA_ENCRYPTION_KEY="smoketest00000000000000000000000" \
  "${IMAGE}" \
  -c "
import sys

failures = []

checks = [
    'from app.main import app',
    'from app.services import attestation_service',
    'from app.services import meat_evidence_service',
    'from app.services import immutable_audit',
    'from app.services import suspect_engine',
    'from app.services.raf import calculator',
]

for stmt in checks:
    try:
        exec(stmt)
        print(f'  OK  {stmt}')
    except Exception as exc:
        print(f'  FAIL {stmt}')
        print(f'       {type(exc).__name__}: {exc}', file=sys.stderr)
        failures.append(stmt)

if failures:
    print(f'\n{len(failures)} import(s) failed — aborting deploy', file=sys.stderr)
    sys.exit(1)

print('All imports OK')
" || {
  echo "[smoke] FAIL: import check failed — see output above"
  exit 1
}

echo "==> [smoke] Imports: PASS"

# ---------------------------------------------------------------------------
# 2. /health endpoint check — boot a short-lived container on SMOKE_PORT.
# ---------------------------------------------------------------------------
echo "==> [smoke] Starting container for /health probe on port ${SMOKE_PORT}..."

docker run --rm -d \
  --name "${CONTAINER_NAME}" \
  -p "${SMOKE_PORT}:8500" \
  -e REDIS_URL="redis://localhost:6379/0" \
  -e RAF_DB_HOST="localhost" \
  -e RAF_DB_PORT="3306" \
  -e RAF_DB_USER="smoke" \
  -e RAF_DB_PASSWORD="smoke" \
  -e RAF_DB_NAME="smoke" \
  -e OPENEMR_DB_HOST="localhost" \
  -e OPENEMR_DB_PORT="3306" \
  -e OPENEMR_DB_USER="smoke" \
  -e OPENEMR_DB_PASSWORD="smoke" \
  -e OPENEMR_DB_NAME="smoke" \
  -e JWT_SECRET="smoke-secret-not-real" \
  -e JWT_REFRESH_SECRET="smoke-refresh-not-real" \
  -e APP_ENV="smoke" \
  -e ENCRYPTION_SALT="smoketest00000000" \
  -e DATA_ENCRYPTION_KEY="smoketest00000000000000000000000" \
  "${IMAGE}" >/dev/null

echo "==> [smoke] Waiting up to ${MAX_WAIT}s for ${HEALTH_URL}..."

elapsed=0
while true; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "${HEALTH_URL}" 2>/dev/null || true)
  if [ "${HTTP_CODE}" = "200" ]; then
    echo "==> [smoke] /health returned 200 after ${elapsed}s"
    break
  fi
  if [ "${elapsed}" -ge "${MAX_WAIT}" ]; then
    echo "[smoke] FAIL: /health did not return 200 within ${MAX_WAIT}s (last code: ${HTTP_CODE})"
    docker logs "${CONTAINER_NAME}" --tail 30 >&2 || true
    exit 1
  fi
  sleep 2
  elapsed=$(( elapsed + 2 ))
done

echo "==> [smoke] /health: PASS"
echo "==> [smoke] All checks passed — safe to docker compose up -d"
