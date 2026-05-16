#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Rollback to previous SHA-tagged images
#
# Usage:
#   PREVIOUS_SHA=<short_sha> ./scripts/rollback.sh
#
# Strategy:
#   1) If `raf-backend:$PREVIOUS_SHA` exists locally, retag it as :latest.
#   2) Otherwise, pull it from $REGISTRY/raf-backend:$PREVIOUS_SHA and retag.
#   3) Same for the frontend image.
#   4) docker compose up -d to bring services back up on the pinned tag.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.prod.yml"
ENV_FILE="${PROJECT_DIR}/.env"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[ -n "${PREVIOUS_SHA:-}" ] || die "PREVIOUS_SHA env var is required (e.g. PREVIOUS_SHA=abc1234 $0)"

# Load .env so REGISTRY_* are available
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# ---------------------------------------------------------------------------
# Resolve an image: prefer local, else pull from registry, else fail.
# ---------------------------------------------------------------------------
resolve_image() {
    local repo="$1"   # e.g. raf-backend
    local sha="$2"

    if docker image inspect "${repo}:${sha}" >/dev/null 2>&1; then
        log "Local image ${repo}:${sha} found — using local copy."
    elif [ -n "${REGISTRY:-}" ]; then
        log "Local image ${repo}:${sha} missing — pulling ${REGISTRY}/${repo}:${sha}..."
        if [ -n "${REGISTRY_TOKEN:-}" ]; then
            echo "$REGISTRY_TOKEN" | docker login "$REGISTRY" -u "${REGISTRY_USER:-raf-deploy}" --password-stdin
        fi
        docker pull "${REGISTRY}/${repo}:${sha}" \
            || die "Could not pull ${REGISTRY}/${repo}:${sha} — rollback impossible."
        docker tag "${REGISTRY}/${repo}:${sha}" "${repo}:${sha}"
    else
        die "Local image ${repo}:${sha} missing and no \$REGISTRY configured — rollback impossible."
    fi

    # Retag as :latest so docker-compose picks it up
    docker tag "${repo}:${sha}" "${repo}:latest"
}

log "=== Rolling back to SHA=${PREVIOUS_SHA} ==="

resolve_image "raf-backend"  "${PREVIOUS_SHA}"
resolve_image "raf-frontend" "${PREVIOUS_SHA}"

log "Restarting services on rolled-back images..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

log "=== Rollback complete (now running SHA=${PREVIOUS_SHA}) ==="
log "NOTE: database migrations are NOT auto-reverted. If schema changed since"
log "      ${PREVIOUS_SHA}, restore from the pre-migration dump in /var/backups/raf."
