#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Rollback Script
#
# Usage:
#   ./deploy/rollback.sh <git-sha|previous>  [--env-file /path/.env]
#
# Arguments:
#   git-sha    — specific short or full git SHA to roll back to
#   previous   — automatically detect the previously running image tag
#
# What it does:
#   1. Resolves the target image tag
#   2. Verifies the images exist locally (or pulls from registry if configured)
#   3. Optionally reverts DB migrations (requires confirmation)
#   4. Restarts all containers with the target image tag
#   5. Verifies health after rollback
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"
LOG_DIR="${REPO_ROOT}/data/logs/deploy"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/rollback_${TIMESTAMP}.log"
TIMEOUT=180

ENV_FILE="${REPO_ROOT}/.env"
TARGET_TAG=""
REVERT_DB=0

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    --revert-db)  REVERT_DB=1; shift ;;
    -*)           echo "Unknown flag: $1" >&2; exit 1 ;;
    *)            TARGET_TAG="$1"; shift ;;
  esac
done

[[ -z "${TARGET_TAG}" ]] && { echo "Usage: $0 <git-sha|previous> [--env-file path] [--revert-db]" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
mkdir -p "${LOG_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO]  $*"; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN]  $*" >&2; }
die()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2; exit 1; }

notify() {
  local status="$1" message="$2"
  log "Rollback notification: [${status}] ${message}"
  if [[ -n "${WEBHOOK_URL:-}" ]]; then
    local color="warning"
    [[ "$status" == "FAILURE" ]] && color="danger"
    curl -sS -X POST "${WEBHOOK_URL}" \
      -H 'Content-Type: application/json' \
      -d "{\"attachments\":[{\"color\":\"${color}\",\"text\":\"*RAF Rollback [${status}]* ${message}\",\"footer\":\"$(hostname) | $(date)\"}]}" \
      || true
  fi
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
log "=== RAF Intelligence — Rollback ==="
log "Target: ${TARGET_TAG} | Host: $(hostname)"

[[ -f "${ENV_FILE}" ]]     || die ".env not found at ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "docker-compose.prod.yml not found"

command -v docker >/dev/null 2>&1      || die "docker not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not installed"

# ---------------------------------------------------------------------------
# Resolve target tag
# ---------------------------------------------------------------------------
log "--- Step 1: Resolve target tag ---"

if [[ "${TARGET_TAG}" == "previous" ]]; then
  # Look for the second-most-recent raf-backend image (current is latest)
  RESOLVED_TAG=$(docker images --format '{{.Tag}}' raf-backend \
    | grep -v 'latest' \
    | sort -r \
    | sed -n '2p' || echo "")
  [[ -z "${RESOLVED_TAG}" ]] && die "No previous image found for raf-backend. Available tags: $(docker images --format '{{.Tag}}' raf-backend | tr '\n' ' ')"
  log "Resolved 'previous' to tag: ${RESOLVED_TAG}"
  TARGET_TAG="${RESOLVED_TAG}"
fi

# Verify images exist
for img in backend worker frontend; do
  if ! docker image inspect "raf-${img}:${TARGET_TAG}" >/dev/null 2>&1; then
    warn "Image raf-${img}:${TARGET_TAG} not found locally"
    # Attempt to find by git log if TARGET_TAG looks like a SHA
    if git -C "${REPO_ROOT}" cat-file -e "${TARGET_TAG}" 2>/dev/null; then
      die "Image raf-${img}:${TARGET_TAG} does not exist locally. Build the image first or push/pull from a registry."
    fi
    die "Image raf-${img}:${TARGET_TAG} not found. Available: $(docker images --format '{{.Tag}}' raf-${img} | tr '\n' ' ')"
  fi
  log "Found image: raf-${img}:${TARGET_TAG}"
done

# ---------------------------------------------------------------------------
# Record current running tag (for safety)
# ---------------------------------------------------------------------------
CURRENT_TAG=$(docker inspect --format='{{.Config.Image}}' raf-backend 2>/dev/null \
  | sed 's/.*://' || echo "unknown")
log "Currently running tag: ${CURRENT_TAG}"
log "Rolling back to tag:   ${TARGET_TAG}"

# ---------------------------------------------------------------------------
# Optional: DB migration revert
# ---------------------------------------------------------------------------
if [[ $REVERT_DB -eq 1 ]]; then
  log "--- Step 2: DB migration revert ---"
  warn "DB revert is a destructive operation. This will run 'alembic downgrade -1'."
  read -r -p "Type 'yes' to confirm DB downgrade: " confirm
  if [[ "$confirm" != "yes" ]]; then
    log "DB revert cancelled by user"
    REVERT_DB=0
  else
    set -a; source "${ENV_FILE}"; set +a
    log "Running alembic downgrade -1..."
    docker run --rm \
      --network host \
      --env-file "${ENV_FILE}" \
      -e APP_ENV=production \
      -v "${REPO_ROOT}/backend:/app" \
      -w /app \
      python:3.11-slim \
      bash -c "pip install -q alembic mysqlclient pymysql cryptography && alembic downgrade -1" \
      || die "DB downgrade failed — containers NOT restarted. Fix manually."
    log "DB downgrade complete"
  fi
else
  log "--- Step 2: DB migration revert — SKIPPED (use --revert-db to enable) ---"
fi

# ---------------------------------------------------------------------------
# Checkout the target git revision (code)
# ---------------------------------------------------------------------------
log "--- Step 3: Checkout code at ${TARGET_TAG} ---"
if git -C "${REPO_ROOT}" cat-file -e "${TARGET_TAG}" 2>/dev/null; then
  git -C "${REPO_ROOT}" checkout "${TARGET_TAG}" -- . \
    || warn "git checkout failed — proceeding with current code and old images only"
  log "Code checked out at ${TARGET_TAG}"
else
  warn "Target tag '${TARGET_TAG}' is not a known git ref — skipping code checkout"
fi

# ---------------------------------------------------------------------------
# Restart containers with target image tag
# ---------------------------------------------------------------------------
log "--- Step 4: Restart containers with image tag ${TARGET_TAG} ---"
IMAGE_TAG="${TARGET_TAG}" \
  docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" \
  up -d --no-build --remove-orphans \
  || die "docker compose up failed during rollback"

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
wait_healthy() {
  local service="$1"
  local container="raf-${service}"
  local elapsed=0
  log "Waiting for ${container} to become healthy (timeout=${TIMEOUT}s)..."
  while [[ $elapsed -lt $TIMEOUT ]]; do
    local status
    status=$(docker inspect --format='{{.State.Health.Status}}' "${container}" 2>/dev/null || echo "missing")
    case "$status" in
      healthy)
        log "${container}: healthy after ${elapsed}s"
        return 0
        ;;
      unhealthy)
        warn "${container}: unhealthy after rollback"
        docker logs --tail 20 "${container}" 2>&1 || true
        return 1
        ;;
    esac
    sleep 5
    elapsed=$((elapsed + 5))
  done
  warn "${container}: did not become healthy within ${TIMEOUT}s"
  return 1
}

log "--- Step 5: Verify health after rollback ---"
UNHEALTHY=0
for svc in redis backend worker frontend; do
  wait_healthy "$svc" || UNHEALTHY=1
done

if [[ $UNHEALTHY -ne 0 ]]; then
  notify "FAILURE" "Rollback to ${TARGET_TAG} completed but some containers are unhealthy. Manual intervention required."
  die "Rollback health check failed — inspect containers manually"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=== Rollback Complete ==="
log "Rolled back to: ${TARGET_TAG}"
log "Log file:       ${LOG_FILE}"
docker compose -f "${COMPOSE_FILE}" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

notify "ROLLBACK" "Successfully rolled back to image tag \`${TARGET_TAG}\` on $(hostname)"
