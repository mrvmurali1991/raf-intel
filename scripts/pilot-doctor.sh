#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Pilot Doctor
#
# Diagnostic dashboard: shows container health, DB row counts, last backend
# errors, cache stats, outreach health, and FHIR circuit status.
#
# Usage:
#   bash scripts/pilot-doctor.sh
#   bash scripts/pilot-doctor.sh --json   # machine-readable JSON output
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_URL="http://localhost:8500"
JSON_MODE=0

for arg in "$@"; do
  case "$arg" in
    --json) JSON_MODE=1 ;;
    --help|-h)
      grep '^#' "$0" | head -12 | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

# ---------------------------------------------------------------------------
# Color / symbol helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

PASS="${GREEN}✅${RESET}"
WARN="${YELLOW}⚠️ ${RESET}"
FAIL="${RED}❌${RESET}"

pad() { printf "%-38s" "$1"; }

row() {
  local label="$1" status="$2" detail="$3"
  echo -e "  $(pad "$label")  $status  $detail"
}

section() {
  echo ""
  echo -e "${CYAN}${BOLD}  ── $* ──${RESET}"
}

header() {
  echo ""
  echo -e "${BOLD}  ╔══════════════════════════════════════════════════════════════╗"
  echo -e "  ║           RAF Intelligence — Pilot Doctor Report            ║"
  echo -e "  ╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo -e "  Run at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
}

# ---------------------------------------------------------------------------
# Helper: get token (returns empty string if login fails)
# ---------------------------------------------------------------------------
get_token() {
  local resp
  resp=$(curl -sf -X POST "$BACKEND_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@raf.health","password":"Admin@123"}' 2>/dev/null) || resp=""
  echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo ""
}

# ---------------------------------------------------------------------------
# Helper: mysql query (returns empty string on failure)
# ---------------------------------------------------------------------------
mysql_q() {
  local query="$1"
  local ctr
  ctr=$(docker ps --filter "name=raf-mysql" --filter "status=running" --format "{{.Names}}" | head -1)
  if [ -z "$ctr" ]; then echo ""; return; fi
  docker exec "$ctr" mysql -uroot -proot raf_intelligence -sN -e "$query" 2>/dev/null || echo ""
}

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
header

# ── 1. Container Health ──────────────────────────────────────────────────
section "Container Health"

for SVC in raf-backend raf-mysql raf-redis; do
  STATE=$(docker inspect --format='{{.State.Status}}' "$SVC" 2>/dev/null || echo "missing")
  HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$SVC" 2>/dev/null || echo "n/a")
  case "$STATE" in
    running)
      if [ "$HEALTH" = "unhealthy" ]; then
        row "$SVC" "$WARN" "running but health=unhealthy"
      else
        row "$SVC" "$PASS" "running  (health: $HEALTH)"
      fi
      ;;
    missing)
      row "$SVC" "$FAIL" "container not found — run: make pilot-ready"
      ;;
    *)
      row "$SVC" "$FAIL" "state=$STATE"
      ;;
  esac
done

# ── 2. Backend /health endpoint ──────────────────────────────────────────
section "Backend API"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  row "/health" "$PASS" "HTTP 200"
else
  row "/health" "$FAIL" "HTTP $HTTP_CODE  (containers up? migrations done?)"
fi

# Login check
TOKEN=$(get_token)
if [ -n "$TOKEN" ]; then
  row "admin login" "$PASS" "access_token obtained"
else
  row "admin login" "$FAIL" "admin@raf.health / Admin@123 not working"
fi

# ── 3. DB Row Counts ─────────────────────────────────────────────────────
section "DB Row Counts (raf_intelligence)"

declare -A TABLES=(
  [patients]="patients"
  [suspects]="raf_suspect_conditions"
  [audit_log]="audit_log"
  [raf_meat_evidence]="raf_meat_evidence"
  [users]="users"
  [hcc_codes]="hcc_codes"
)

for LABEL in patients suspects audit_log raf_meat_evidence users hcc_codes; do
  TABLE="${TABLES[$LABEL]}"
  CNT=$(mysql_q "SELECT COUNT(*) FROM $TABLE;" 2>/dev/null || echo "")
  if [ -z "$CNT" ]; then
    row "$LABEL ($TABLE)" "$WARN" "could not query (DB not reachable?)"
  elif [ "$CNT" -eq 0 ]; then
    row "$LABEL ($TABLE)" "$WARN" "0 rows — run seed: make pilot-ready"
  else
    row "$LABEL ($TABLE)" "$PASS" "$CNT rows"
  fi
done

# ── 4. Cache (Redis) ─────────────────────────────────────────────────────
section "Cache / Redis"

REDIS_CTR=$(docker ps --filter "name=raf-redis" --filter "status=running" --format "{{.Names}}" | head -1)
if [ -n "$REDIS_CTR" ]; then
  REDIS_PASS="${REDIS_PASSWORD:-rafredis123}"
  PING=$(docker exec "$REDIS_CTR" redis-cli -a "$REDIS_PASS" ping 2>/dev/null || echo "")
  if [ "$PING" = "PONG" ]; then
    KEYSPACE=$(docker exec "$REDIS_CTR" redis-cli -a "$REDIS_PASS" info keyspace 2>/dev/null | grep "^db" | head -3)
    HITS=$(docker exec "$REDIS_CTR" redis-cli -a "$REDIS_PASS" info stats 2>/dev/null | grep "keyspace_hits:" | cut -d: -f2 | tr -d '\r')
    MISSES=$(docker exec "$REDIS_CTR" redis-cli -a "$REDIS_PASS" info stats 2>/dev/null | grep "keyspace_misses:" | cut -d: -f2 | tr -d '\r')
    row "redis ping" "$PASS" "PONG"
    row "keyspace" "$PASS" "${KEYSPACE:-empty}"
    row "hits/misses" "$PASS" "hits=${HITS:-0}  misses=${MISSES:-0}"
  else
    row "redis ping" "$FAIL" "no PONG — check REDIS_PASSWORD env var"
  fi
else
  row "redis" "$FAIL" "raf-redis container not running"
fi

# ── 5. Outreach health ───────────────────────────────────────────────────
section "Outreach"

if [ -n "$TOKEN" ]; then
  OUTREACH=$(curl -sf "$BACKEND_URL/api/outreach/status" \
    -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
  if echo "$OUTREACH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','ok'))" 2>/dev/null | grep -qi "ok\|active\|healthy"; then
    row "outreach /status" "$PASS" "$(echo "$OUTREACH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d)[:80])" 2>/dev/null)"
  elif [ -z "$OUTREACH" ]; then
    row "outreach /status" "$WARN" "endpoint not reachable (may not be wired)"
  else
    row "outreach /status" "$WARN" "$(echo "$OUTREACH" | head -c 120)"
  fi
else
  row "outreach /status" "$WARN" "skipped — no auth token"
fi

# ── 6. FHIR circuit breaker ──────────────────────────────────────────────
section "FHIR Circuit Breaker"

if [ -n "$TOKEN" ]; then
  FHIR=$(curl -sf "$BACKEND_URL/api/fhir/circuit-status" \
    -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
  if [ -z "$FHIR" ]; then
    FHIR=$(curl -sf "$BACKEND_URL/api/admin/fhir-circuit" \
      -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
  fi
  if echo "$FHIR" | python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('state',d.get('status','unknown')); print(s)" 2>/dev/null | grep -qi "closed\|ok\|healthy"; then
    row "FHIR circuit" "$PASS" "$(echo "$FHIR" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d)[:80])" 2>/dev/null)"
  elif [ -z "$FHIR" ]; then
    row "FHIR circuit" "$WARN" "endpoint not found (may not be deployed)"
  else
    STATE=$(echo "$FHIR" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',d.get('status','?')))" 2>/dev/null || echo "?")
    if echo "$STATE" | grep -qi "open"; then
      row "FHIR circuit" "$FAIL" "circuit OPEN — check FHIR endpoint connectivity"
    else
      row "FHIR circuit" "$WARN" "state=$STATE"
    fi
  fi
else
  row "FHIR circuit" "$WARN" "skipped — no auth token"
fi

# ── 7. Last 5 backend errors ─────────────────────────────────────────────
section "Last 5 Backend Errors (docker logs raf-backend)"

BACKEND_CTR=$(docker ps --filter "name=raf-backend" --filter "status=running" --format "{{.Names}}" | head -1)
if [ -n "$BACKEND_CTR" ]; then
  ERRORS=$(docker logs "$BACKEND_CTR" --tail=200 2>&1 | grep -iE "error|exception|traceback" | tail -5 || echo "")
  if [ -z "$ERRORS" ]; then
    row "recent errors" "$PASS" "none found in last 200 log lines"
  else
    row "recent errors" "$WARN" "see below:"
    echo "$ERRORS" | while IFS= read -r line; do
      echo "    | $line"
    done
  fi
else
  row "backend logs" "$FAIL" "raf-backend not running"
fi

# ── 8. Summary ───────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}Quick actions:${RESET}"
echo "    make pilot-ready      — full setup from scratch"
echo "    make pilot-teardown   — stop and clean up"
echo "    make smoke            — 5-endpoint quick smoke"
echo ""
