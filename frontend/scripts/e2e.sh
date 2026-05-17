#!/usr/bin/env bash
# scripts/e2e.sh — Launch dev server, run E2E suite, then tear down.
#
# Usage:
#   bash frontend/scripts/e2e.sh
#   BASE_PORT=3001 bash frontend/scripts/e2e.sh
#
# The script:
#   1. Starts `npm run dev` in the background.
#   2. Waits up to 60 s for http://localhost:<PORT> to respond.
#   3. Runs `npx playwright test --project=e2e`.
#   4. Kills the dev server regardless of test outcome.
#   5. Exits with the playwright exit code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"

PORT="${BASE_PORT:-3001}"
BASE_URL="http://localhost:${PORT}"
MAX_WAIT=60

echo "[e2e.sh] Starting Next.js dev server on port ${PORT}..."
cd "$FRONTEND_DIR"
npm run dev -- --port "$PORT" &>/tmp/raf-dev-server.log &
DEV_PID=$!
echo "[e2e.sh] Dev server PID: ${DEV_PID}"

# Trap to always kill the dev server.
cleanup() {
  echo "[e2e.sh] Stopping dev server (PID ${DEV_PID})..."
  kill "$DEV_PID" 2>/dev/null || true
  wait "$DEV_PID" 2>/dev/null || true
  echo "[e2e.sh] Dev server stopped."
}
trap cleanup EXIT

echo "[e2e.sh] Waiting up to ${MAX_WAIT}s for ${BASE_URL} to respond..."
WAITED=0
until curl -sf "$BASE_URL" -o /dev/null; do
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "[e2e.sh] ERROR: Dev server did not start within ${MAX_WAIT}s."
    echo "[e2e.sh] Dev server log:"
    cat /tmp/raf-dev-server.log | tail -30
    exit 1
  fi
  sleep 2
  WAITED=$((WAITED + 2))
done

echo "[e2e.sh] Dev server is up. Running Playwright E2E suite..."
E2E_BASE_URL="$BASE_URL" npx playwright test --project=e2e
PW_EXIT=$?

echo "[e2e.sh] Playwright exited with code ${PW_EXIT}."
exit "$PW_EXIT"
