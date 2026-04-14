#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Production Docker Deployment
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"
ENV_FILE="${SCRIPT_DIR}/.env"
TIMEOUT=120  # seconds to wait for health checks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
die()  { log "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "=== RAF Intelligence — Production Deploy ==="

command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin is not installed"

[ -f "$ENV_FILE" ] || die ".env file not found at ${ENV_FILE}"
[ -f "$COMPOSE_FILE" ] || die "Compose file not found at ${COMPOSE_FILE}"

# Validate required env vars are present in .env
for var in GOOGLE_API_KEY JWT_SECRET JWT_REFRESH_SECRET RAF_DB_HOST RAF_DB_USER RAF_DB_PASSWORD NEXT_PUBLIC_API_URL; do
    grep -q "^${var}=" "$ENV_FILE" || die "Required variable ${var} missing from .env"
done

# ---------------------------------------------------------------------------
# Create bind-mount directories
# ---------------------------------------------------------------------------
log "Ensuring data directories exist..."
mkdir -p "${SCRIPT_DIR}/data/redis" "${SCRIPT_DIR}/data/uploads" "${SCRIPT_DIR}/data/logs" "${SCRIPT_DIR}/data/submissions"

# ---------------------------------------------------------------------------
# Build images
# ---------------------------------------------------------------------------
log "Building images..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build --pull

# ---------------------------------------------------------------------------
# Deploy (rolling restart)
# ---------------------------------------------------------------------------
log "Starting services..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

# ---------------------------------------------------------------------------
# Wait for health checks
# ---------------------------------------------------------------------------
wait_healthy() {
    local service="$1"
    local elapsed=0
    log "Waiting for ${service} to become healthy..."
    while [ $elapsed -lt $TIMEOUT ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "raf-${service}" 2>/dev/null || echo "missing")
        case "$status" in
            healthy)
                log "${service} is healthy"
                return 0
                ;;
            unhealthy)
                die "${service} is unhealthy — check logs: docker logs raf-${service}"
                ;;
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

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
log "Pruning dangling images..."
docker image prune -f >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=== Deploy Complete ==="
docker compose -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
