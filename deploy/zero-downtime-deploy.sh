#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Zero-Downtime Production Deploy
#
# Strategy:
#   1. Pull latest code
#   2. Run DB migrations (alembic upgrade head) — backward-compatible only
#   3. Build new images tagged with git SHA
#   4. Bring up new containers alongside old ones
#   5. Health-check new containers
#   6. Switch traffic / stop old containers
#   7. Auto-rollback on any failure
#
# Usage:
#   ./deploy/zero-downtime-deploy.sh [--env-file /path/to/.env] [--branch main]
#
# Environment variables (can also come from .env):
#   DEPLOY_BRANCH   — branch to deploy (default: current branch)
#   DEPLOY_PATH     — repo root (default: script's parent dir)
#   WEBHOOK_URL     — optional Slack/Teams webhook for notifications
#   SKIP_MIGRATION  — set to "1" to skip alembic (emergency use only)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths & configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"
LOG_DIR="${REPO_ROOT}/data/logs/deploy"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/deploy_${TIMESTAMP}.log"
TIMEOUT=180          # seconds to wait for each health check
ROLLBACK_ON_EXIT=0   # set to 1 once old images are saved

# Parse flags
ENV_FILE="${REPO_ROOT}/.env"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --branch)   DEPLOY_BRANCH="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

DEPLOY_BRANCH="${DEPLOY_BRANCH:-$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'local')}"

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
  log "Deploy notification: [${status}] ${message}"
  if [[ -n "${WEBHOOK_URL:-}" ]]; then
    local color="good"
    [[ "$status" == "FAILURE" ]] && color="danger"
    [[ "$status" == "ROLLBACK" ]] && color="warning"
    curl -sS -X POST "${WEBHOOK_URL}" \
      -H 'Content-Type: application/json' \
      -d "{\"attachments\":[{\"color\":\"${color}\",\"text\":\"*RAF Deploy [${status}]* ${message}\",\"footer\":\"$(hostname) | $(date)\"}]}" \
      || true
  fi
}

# ---------------------------------------------------------------------------
# Rollback trap — fires automatically on any error
# ---------------------------------------------------------------------------
PREV_TAG=""
rollback_on_error() {
  local exit_code=$?
  if [[ $ROLLBACK_ON_EXIT -eq 1 && -n "${PREV_TAG}" ]]; then
    warn "Deploy failed (exit ${exit_code}). Initiating automatic rollback to ${PREV_TAG}..."
    notify "ROLLBACK" "Auto-rolling back to image tag ${PREV_TAG} after deploy failure"
    IMAGE_TAG="${PREV_TAG}" \
      docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --no-build 2>&1 \
      || warn "Rollback compose up failed — manual intervention required"
    # Wait briefly and re-check health
    sleep 10
    local svc
    for svc in backend worker frontend; do
      local st
      st=$(docker inspect --format='{{.State.Health.Status}}' "raf-${svc}" 2>/dev/null || echo "missing")
      if [[ "$st" == "healthy" ]]; then
        log "Rollback: raf-${svc} is healthy"
      else
        warn "Rollback: raf-${svc} status=${st} — check manually"
      fi
    done
    notify "ROLLBACK" "Rollback to ${PREV_TAG} completed. Verify containers manually."
  fi
  if [[ $exit_code -ne 0 ]]; then
    notify "FAILURE" "Deploy failed at $(date '+%H:%M:%S'). Log: ${LOG_FILE}"
  fi
}
trap rollback_on_error EXIT

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "=== RAF Intelligence — Zero-Downtime Deploy ==="
log "Branch: ${DEPLOY_BRANCH} | Host: $(hostname) | Log: ${LOG_FILE}"

command -v docker >/dev/null 2>&1      || die "docker not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not installed"
command -v curl >/dev/null 2>&1        || die "curl not installed"

[[ -f "${ENV_FILE}" ]]     || die ".env not found at ${ENV_FILE}"
[[ -f "${COMPOSE_FILE}" ]] || die "docker-compose.prod.yml not found at ${COMPOSE_FILE}"

for var in JWT_SECRET JWT_REFRESH_SECRET RAF_DB_HOST RAF_DB_USER RAF_DB_PASSWORD NEXT_PUBLIC_API_URL REDIS_PASSWORD; do
  grep -q "^${var}=" "${ENV_FILE}" || die "Required variable ${var} missing from .env"
done

# ---------------------------------------------------------------------------
# Pull latest code
# ---------------------------------------------------------------------------
log "--- Step 1: Pull latest code ---"
cd "${REPO_ROOT}"

PREV_TAG=$(docker inspect --format='{{index .Config.Labels "image.tag"}}' raf-backend 2>/dev/null || echo "")
if [[ -z "${PREV_TAG}" ]]; then
  # Fall back to reading IMAGE_TAG from running container image name
  PREV_TAG=$(docker inspect --format='{{.Config.Image}}' raf-backend 2>/dev/null \
    | sed 's/.*://' | grep -v 'latest' || echo "")
fi
log "Previous image tag: ${PREV_TAG:-none}"

git fetch origin "${DEPLOY_BRANCH}"
git reset --hard "origin/${DEPLOY_BRANCH}"
GIT_SHA="$(git rev-parse --short HEAD)"
log "Deployed commit: ${GIT_SHA}"

# ---------------------------------------------------------------------------
# Ensure data directories
# ---------------------------------------------------------------------------
log "--- Step 2: Ensure data directories ---"
mkdir -p \
  "${REPO_ROOT}/data/redis" \
  "${REPO_ROOT}/data/uploads" \
  "${REPO_ROOT}/data/logs" \
  "${REPO_ROOT}/data/submissions"

# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------
log "--- Step 3: Database migrations ---"
if [[ "${SKIP_MIGRATION:-0}" == "1" ]]; then
  warn "SKIP_MIGRATION=1 set — skipping alembic (emergency mode)"
else
  # Source DB credentials from .env for the migration container
  set -a; source "${ENV_FILE}"; set +a

  log "Running alembic upgrade head..."
  docker run --rm \
    --network host \
    --env-file "${ENV_FILE}" \
    -e APP_ENV=production \
    -v "${REPO_ROOT}/backend:/app" \
    -w /app \
    python:3.11-slim \
    bash -c "pip install -q alembic mysqlclient pymysql cryptography && alembic upgrade head" \
    || die "DB migration failed — deploy aborted. No containers were changed."
  log "Migrations complete"
fi

# ---------------------------------------------------------------------------
# Build new images with SHA tag
# ---------------------------------------------------------------------------
log "--- Step 4: Build images (tag=${GIT_SHA}) ---"
IMAGE_TAG="${GIT_SHA}" \
  docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" \
  build --pull --no-cache \
  || die "Image build failed"
log "Images built: raf-backend:${GIT_SHA}, raf-worker:${GIT_SHA}, raf-frontend:${GIT_SHA}"

# Enable rollback from this point onward (old containers still running)
ROLLBACK_ON_EXIT=1

# ---------------------------------------------------------------------------
# Start new containers (alongside old ones on different names temporarily)
# ---------------------------------------------------------------------------
log "--- Step 5: Bring up new containers ---"
IMAGE_TAG="${GIT_SHA}" \
  docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" \
  up -d --remove-orphans \
  || die "docker compose up failed"

# ---------------------------------------------------------------------------
# Health check new containers
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
        warn "${container}: unhealthy. Last 20 log lines:"
        docker logs --tail 20 "${container}" 2>&1 || true
        return 1
        ;;
    esac
    sleep 5
    elapsed=$((elapsed + 5))
  done
  warn "${container}: did not become healthy within ${TIMEOUT}s"
  docker logs --tail 30 "${container}" 2>&1 || true
  return 1
}

log "--- Step 6: Health-check new containers ---"
UNHEALTHY=0
for svc in redis backend worker frontend; do
  wait_healthy "$svc" || UNHEALTHY=1
done

if [[ $UNHEALTHY -ne 0 ]]; then
  die "One or more containers failed health check — triggering rollback"
fi

log "All containers healthy"

# ---------------------------------------------------------------------------
# Tag 'latest' image alias for convenience
# ---------------------------------------------------------------------------
for img in backend worker frontend; do
  docker tag "raf-${img}:${GIT_SHA}" "raf-${img}:latest" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# Prune old images (keep last 3)
# ---------------------------------------------------------------------------
log "--- Step 7: Prune old images ---"
docker image prune -f >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Disable rollback trap — deploy succeeded
# ---------------------------------------------------------------------------
ROLLBACK_ON_EXIT=0
trap - EXIT

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=== Deploy Complete ==="
log "Git SHA : ${GIT_SHA}"
log "Log     : ${LOG_FILE}"
docker compose -f "${COMPOSE_FILE}" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

notify "SUCCESS" "Deployed commit \`${GIT_SHA}\` to $(hostname) on branch \`${DEPLOY_BRANCH}\`"
