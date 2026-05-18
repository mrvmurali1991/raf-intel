#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Pilot Teardown
#
# Stops the 3 local pilot containers, removes their volumes, and clears
# temporary demo artifacts.  Safe to re-run (idempotent).
#
# Usage:
#   bash scripts/pilot-teardown.sh
#   bash scripts/pilot-teardown.sh --keep-data   # skip volume removal
# =============================================================================
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.local.yml"
KEEP_DATA=0

for arg in "$@"; do
  case "$arg" in
    --keep-data) KEEP_DATA=1 ;;
    --help|-h)
      grep '^#' "$0" | head -12 | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

step() { echo -e "\n${CYAN}${BOLD}==> $*${RESET}"; }
ok()   { echo -e "    ${GREEN}[OK]${RESET} $*"; }
warn() { echo -e "    ${YELLOW}[WARN]${RESET} $*"; }

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Stop and remove containers
# ---------------------------------------------------------------------------
step "Stopping containers"

if docker compose -f "$COMPOSE_FILE" ps -q 2>/dev/null | grep -q .; then
  if [ "$KEEP_DATA" -eq 1 ]; then
    docker compose -f "$COMPOSE_FILE" down
    ok "Containers stopped (volumes preserved)"
  else
    docker compose -f "$COMPOSE_FILE" down -v
    ok "Containers stopped and volumes removed"
  fi
else
  ok "No running compose containers found — nothing to stop"
fi

# Force-remove named containers if they survived
for CTR in raf-backend raf-mysql raf-redis raf-frontend; do
  if docker ps -a --filter "name=^${CTR}$" --format "{{.Names}}" | grep -q "^${CTR}$"; then
    docker rm -f "$CTR" >/dev/null 2>&1 && warn "Force-removed stale container: $CTR" || true
  fi
done

# ---------------------------------------------------------------------------
# Remove named Docker volumes
# ---------------------------------------------------------------------------
if [ "$KEEP_DATA" -eq 0 ]; then
  step "Removing Docker volumes"
  for VOL in raf-intelligence_raf_mysql_data raf-intelligence_redis_data \
             raf_mysql_data redis_data; do
    if docker volume ls -q | grep -q "^${VOL}$"; then
      docker volume rm "$VOL" >/dev/null 2>&1 && ok "Removed volume: $VOL" || warn "Could not remove $VOL"
    fi
  done
fi

# ---------------------------------------------------------------------------
# Clear temp demo artefacts
# ---------------------------------------------------------------------------
step "Clearing temp demo artefacts"

if [ -d /tmp/raf-demo-pdfs ]; then
  rm -rf /tmp/raf-demo-pdfs
  ok "Removed /tmp/raf-demo-pdfs"
else
  ok "/tmp/raf-demo-pdfs not present — nothing to clear"
fi

# Remove leftover seed logs
rm -f /tmp/seed.log /tmp/raf-smoke-*.log 2>/dev/null || true
ok "Temp log files cleared"

echo -e "\n${GREEN}${BOLD}Teardown complete.${RESET} Run 'make pilot-ready' to start fresh.\n"
