#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Zero-Downtime Production Deployment
#
# Adds three hardening steps on top of the legacy deploy.sh:
#
#   1) Pre-migration mysqldump (gzipped) into /var/backups/raf so we can roll
#      back a failed `alembic upgrade head`.
#   2) Build + tag images with the current commit SHA.
#   3) Optionally push SHA-tagged images to a container registry (GHCR by
#      default) so `rollback.sh` can pull a previous image even after the
#      host has been rebuilt.
#
# Required env (sourced from the project .env or the deploy environment):
#   DB_HOST, DB_USER, DB_PASSWORD, DB_NAME      — pre-migration dump target
#   SHA                                         — short or full commit SHA
#
# Optional env:
#   REGISTRY        — e.g. ghcr.io/raf-intelligence
#   REGISTRY_USER   — registry username
#   REGISTRY_TOKEN  — registry password / PAT (passed via --password-stdin)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.prod.yml"
ENV_FILE="${PROJECT_DIR}/.env"
TIMEOUT=120

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die()  { log "ERROR: $*" >&2; exit 1; }

# Load .env so DB_* and REGISTRY_* are available
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# Resolve SHA — fall back to current git HEAD
SHA="${SHA:-$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)}"

# Pull DB connection params from RAF_DB_* if generic DB_* aren't set
DB_HOST="${DB_HOST:-${RAF_DB_HOST:-}}"
DB_USER="${DB_USER:-${RAF_DB_USER:-}}"
DB_PASSWORD="${DB_PASSWORD:-${RAF_DB_PASSWORD:-}}"
DB_NAME="${DB_NAME:-${RAF_DB_NAME:-}}"

log "=== RAF Intelligence — Zero-Downtime Deploy (SHA=${SHA}) ==="

# ---------------------------------------------------------------------------
# Pre-migration mysqldump
# ---------------------------------------------------------------------------
echo "[$(date)] pre-migration backup..."
dump_path="/var/backups/raf/pre-migration-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p /var/backups/raf
mysqldump --single-transaction --routines --triggers \
    -h "${DB_HOST}" -u "${DB_USER}" -p"${DB_PASSWORD}" "${DB_NAME}" \
    | gzip > "$dump_path" || { echo "Pre-migration dump failed — aborting deploy"; exit 1; }
echo "Pre-migration backup at: $dump_path"

# ---------------------------------------------------------------------------
# Build images (SHA-tagged so we can pin and roll back)
# ---------------------------------------------------------------------------
log "Building backend + frontend images (tag=${SHA})..."
docker build -t "raf-backend:${SHA}" -t "raf-backend:latest" -f "${PROJECT_DIR}/backend/Dockerfile" "${PROJECT_DIR}/backend"
docker build -t "raf-frontend:${SHA}" -t "raf-frontend:latest" -f "${PROJECT_DIR}/frontend/Dockerfile" "${PROJECT_DIR}/frontend"

# ---------------------------------------------------------------------------
# Push to registry (GHCR by default) so rollback works after a host rebuild.
# Only runs when REGISTRY + REGISTRY_TOKEN are set; otherwise we keep the
# legacy local-only behaviour.
# ---------------------------------------------------------------------------
if [ -n "${REGISTRY:-}" ] && [ -n "${REGISTRY_TOKEN:-}" ]; then
    log "Pushing SHA-tagged images to ${REGISTRY}..."
    echo "$REGISTRY_TOKEN" | docker login "$REGISTRY" -u "${REGISTRY_USER:-raf-deploy}" --password-stdin
    docker tag "raf-backend:${SHA}"  "${REGISTRY}/raf-backend:${SHA}"
    docker push "${REGISTRY}/raf-backend:${SHA}"
    docker tag "raf-frontend:${SHA}" "${REGISTRY}/raf-frontend:${SHA}"
    docker push "${REGISTRY}/raf-frontend:${SHA}"
    log "Registry push complete."
else
    log "REGISTRY/REGISTRY_TOKEN not set — skipping registry push (local images only)."
fi

# ---------------------------------------------------------------------------
# Database migrations (after dump, before bringing up new app containers)
# ---------------------------------------------------------------------------
log "Running database migrations..."
(cd "${PROJECT_DIR}/backend" && alembic upgrade head)

# ---------------------------------------------------------------------------
# Rolling restart via docker-compose
# ---------------------------------------------------------------------------
log "Starting services (rolling)..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

# ---------------------------------------------------------------------------
# Wait for health
# ---------------------------------------------------------------------------
wait_healthy() {
    local service="$1"
    local elapsed=0
    log "Waiting for ${service} to become healthy..."
    while [ $elapsed -lt $TIMEOUT ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "raf-${service}" 2>/dev/null || echo "missing")
        case "$status" in
            healthy)   log "${service} healthy"; return 0 ;;
            unhealthy) die "${service} unhealthy — check: docker logs raf-${service}" ;;
        esac
        sleep 5
        elapsed=$((elapsed + 5))
    done
    die "${service} did not become healthy within ${TIMEOUT}s"
}

wait_healthy redis
wait_healthy backend
wait_healthy worker
wait_healthy frontend

log "=== Deploy complete (SHA=${SHA}) ==="
