#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Pre-Demo Preflight Script
# =============================================================================
#
# Run this 5 minutes before a sales demo to guarantee a clean, working stack.
#
# Usage:
#   bash scripts/predemo.sh             # full run: seeds + smoke
#   bash scripts/predemo.sh --dry-run   # smoke only, no data mutations
#   bash scripts/predemo.sh --reset     # purge demo data, then re-seed + smoke
#
# Exit codes:
#   0  — all P0 checks green
#   1  — one or more P0 checks failed (login, pages, dashboard data)
#
# Requirements:
#   - Docker (with compose v2 or docker-compose)
#   - curl
#   - bash 3.2+ (macOS default)
# =============================================================================
set -e
set -o pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
DRY_RUN=0
RESET=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --reset)   RESET=1 ;;
    --help|-h)
      grep '^#' "$0" | head -20 | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg  (use --dry-run or --reset)" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Colors / output helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET_COLOR='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0
FAIL_P0=0

_ts()  { date '+%H:%M:%S'; }
info() { printf "${CYAN}[%s] %s${RESET_COLOR}\n" "$(_ts)" "$*"; }
ok()   {
  PASS_COUNT=$(( PASS_COUNT + 1 ))
  printf "  ${GREEN}✓${RESET_COLOR}  %s\n" "$*"
}
fail() {
  local hint="${2:-}"
  FAIL_COUNT=$(( FAIL_COUNT + 1 ))
  printf "  ${RED}✗${RESET_COLOR}  %s\n" "$1"
  [ -n "$hint" ] && printf "     ${YELLOW}hint:${RESET_COLOR} %s\n" "$hint"
}
fail_p0() {
  FAIL_P0=$(( FAIL_P0 + 1 ))
  fail "$@"
}
section() { printf "\n${BOLD}── %s ──${RESET_COLOR}\n" "$*"; }

# ---------------------------------------------------------------------------
# Locate docker compose
# ---------------------------------------------------------------------------
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' found." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.local.yml"
BACKEND_URL="http://localhost:8500"
FRONTEND_URL="http://localhost:3444"

REQUIRED_CONTAINERS="raf-backend raf-frontend raf-mysql"

# ---------------------------------------------------------------------------
# STEP 1 — Stack health
# ---------------------------------------------------------------------------
section "Stack health"

_container_healthy() {
  local name="$1"
  local state
  state="$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)"
  local health
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || true)"

  if [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }; then
    return 0
  fi
  return 1
}

_wait_healthy() {
  local name="$1"
  local max_wait=90
  local elapsed=0
  while [ "$elapsed" -lt "$max_wait" ]; do
    if _container_healthy "$name"; then
      return 0
    fi
    sleep 3
    elapsed=$(( elapsed + 3 ))
  done
  return 1
}

NEED_UP=0
for c in $REQUIRED_CONTAINERS; do
  if ! _container_healthy "$c"; then
    NEED_UP=1
    info "Container $c is not healthy — will (re)start stack"
    break
  fi
done

if [ "$NEED_UP" -eq 1 ]; then
  info "Running: $DC -f $COMPOSE_FILE up -d"
  (cd "$REPO_ROOT" && $DC -f "$COMPOSE_FILE" up -d)
  info "Waiting for containers to become healthy (up to 90s)..."
  for c in $REQUIRED_CONTAINERS; do
    if _wait_healthy "$c"; then
      ok "$c is healthy"
    else
      fail_p0 "$c failed to become healthy" \
        "Run: $DC -f docker-compose.local.yml logs $c"
    fi
  done
else
  for c in $REQUIRED_CONTAINERS; do
    ok "$c is healthy"
  done
fi

# Abort immediately if any container is down — nothing else will work.
if [ "$FAIL_P0" -gt 0 ]; then
  printf "\n${RED}P0 failure: stack is not up. Aborting preflight.${RESET_COLOR}\n"
  exit 1
fi

# ---------------------------------------------------------------------------
# STEP 2 — Reset demo data (--reset only)
# ---------------------------------------------------------------------------
if [ "$RESET" -eq 1 ]; then
  section "Reset demo data (--reset)"
  info "Purging tagged demo rows..."
  docker exec raf-mysql mysql -uroot -proot raf_intelligence -e "
    DELETE FROM recapture_gaps         WHERE audit_notes IN ('DEMO_PANEL','IRR_DEMO');
    DELETE FROM raf_suspect_conditions WHERE reviewed_by  = 'DEMO_PANEL';
    DELETE FROM raf_patient_hcc        WHERE source_encounter_ids LIKE '%DEMO_PANEL%';
    DELETE FROM patient_data           WHERE is_demo = 1;
    DELETE FROM emr_connections        WHERE name = 'Demo OpenEMR (local seed)';
  " 2>/dev/null && ok "Demo rows purged" \
    || fail "Demo row purge failed (non-fatal — seeds will upsert)" \
            "Check raf-mysql logs"
fi

# ---------------------------------------------------------------------------
# STEP 3 — Apply migrations
# ---------------------------------------------------------------------------
section "Apply migrations"
if [ "$DRY_RUN" -eq 0 ]; then
  info "Copying migrations into container..."
  docker cp "$REPO_ROOT/database/migrations" raf-backend:/tmp/migrations >/dev/null \
    && ok "Migrations copied to /tmp/migrations" \
    || { fail_p0 "docker cp migrations failed" "Check $REPO_ROOT/database/migrations exists"; }

  info "Running apply_migrations.py..."
  docker exec \
    -e MIGRATIONS_DIR=/tmp/migrations \
    raf-backend \
    python /app/scripts/apply_migrations.py \
    && ok "Migrations applied" \
    || fail "apply_migrations.py returned non-zero (may be pre-existing — check logs)" \
            "docker exec raf-backend python /app/scripts/apply_migrations.py"
else
  ok "Migrations skipped (--dry-run)"
fi

# ---------------------------------------------------------------------------
# STEP 4 — Run KG seeds
# ---------------------------------------------------------------------------
section "KG seeds"
if [ "$DRY_RUN" -eq 0 ]; then
  info "Running run_all_seeds.sh (KG)..."
  docker exec raf-backend sh /app/scripts/run_all_seeds.sh \
    && ok "KG seeds applied" \
    || fail "run_all_seeds.sh failed" \
            "docker exec raf-backend sh /app/scripts/run_all_seeds.sh"
else
  ok "KG seeds skipped (--dry-run)"
fi

# ---------------------------------------------------------------------------
# STEP 5 — Seed IRR demo data
# ---------------------------------------------------------------------------
section "IRR demo seed"
if [ "$DRY_RUN" -eq 0 ]; then
  info "Seeding IRR demo..."
  docker exec raf-backend python /app/scripts/seed_irr_demo.py \
    && ok "IRR demo seeded" \
    || fail "seed_irr_demo.py failed" \
            "docker exec raf-backend python /app/scripts/seed_irr_demo.py"
else
  ok "IRR seed skipped (--dry-run)"
fi

# ---------------------------------------------------------------------------
# STEP 6 — Seed demo panel
# ---------------------------------------------------------------------------
section "Demo panel seed"
if [ "$DRY_RUN" -eq 0 ]; then
  info "Copying seed_demo_panel.py into container..."
  docker cp "$REPO_ROOT/backend/scripts/seed_demo_panel.py" \
    raf-backend:/app/scripts/seed_demo_panel.py >/dev/null \
    && ok "seed_demo_panel.py copied" \
    || { fail "docker cp seed_demo_panel.py failed" "Check $REPO_ROOT/backend/scripts/seed_demo_panel.py"; }

  info "Running seed_demo_panel.py..."
  docker exec raf-backend python /app/scripts/seed_demo_panel.py \
    && ok "Demo panel seeded" \
    || fail "seed_demo_panel.py failed" \
            "docker exec raf-backend python /app/scripts/seed_demo_panel.py"
else
  ok "Demo panel seed skipped (--dry-run)"
fi

# ---------------------------------------------------------------------------
# STEP 7 — Unlock admin login
# ---------------------------------------------------------------------------
section "Unlock admin account"
docker exec raf-mysql mysql -uroot -proot raf_intelligence \
  -e "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health';" \
  2>/dev/null \
  && ok "admin@raf.health login unlocked" \
  || fail "Could not reset failed_login_attempts" \
          "docker exec raf-mysql mysql -uroot -proot raf_intelligence -e \"...UPDATE users...\""

# ---------------------------------------------------------------------------
# STEP 8 — Smoke probes
# ---------------------------------------------------------------------------
section "Smoke probes"

# Helper: HTTP status for a URL (no auth)
_http_code() {
  curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$1" 2>/dev/null || echo "000"
}

# Helper: POST JSON, capture body
_post_json() {
  local url="$1"
  local body="$2"
  curl -s -X POST \
    -H "Content-Type: application/json" \
    -d "$body" \
    --max-time 10 \
    "$url" 2>/dev/null || true
}

# Helper: GET with auth header, capture body
_get_auth() {
  local url="$1"
  local token="$2"
  curl -s -H "Authorization: Bearer $token" \
    --max-time 10 \
    "$url" 2>/dev/null || true
}

# ----- 8a. Login -----
info "Probe: POST /api/auth/login"
LOGIN_RESPONSE="$(_post_json "${BACKEND_URL}/api/auth/login" \
  '{"email":"admin@raf.health","password":"Admin@123"}')"

ACCESS_TOKEN=""
if echo "$LOGIN_RESPONSE" | grep -q '"access_token"'; then
  ACCESS_TOKEN="$(echo "$LOGIN_RESPONSE" | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || true)"
fi

if [ -n "$ACCESS_TOKEN" ]; then
  ok "Login: access_token obtained"
else
  fail_p0 "Login: no access_token returned" \
    "Check admin@raf.health exists + password Admin@123; run unlock step above"
fi

# ----- 8b. Dashboard stats -----
info "Probe: GET /api/dashboard/stats"
if [ -n "$ACCESS_TOKEN" ]; then
  STATS_BODY="$(_get_auth "${BACKEND_URL}/api/dashboard/stats" "$ACCESS_TOKEN")"
  TOTAL_PATIENTS=""
  if echo "$STATS_BODY" | grep -q '"total_patients"'; then
    TOTAL_PATIENTS="$(echo "$STATS_BODY" | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_patients',0))" 2>/dev/null || echo "0")"
  fi
  if [ -n "$TOTAL_PATIENTS" ] && [ "$TOTAL_PATIENTS" -gt 0 ] 2>/dev/null; then
    ok "Dashboard stats: total_patients=${TOTAL_PATIENTS}"
  else
    fail_p0 "Dashboard stats: total_patients is 0 or missing" \
      "Run without --dry-run to seed the demo panel, or check seed_demo_panel.py"
  fi
else
  fail_p0 "Dashboard stats: skipped (no auth token)" \
    "Fix login probe first"
fi

# ----- 8c. EMR status -----
info "Probe: GET /api/emr/status"
if [ -n "$ACCESS_TOKEN" ]; then
  EMR_BODY="$(_get_auth "${BACKEND_URL}/api/emr/status" "$ACCESS_TOKEN")"
  if echo "$EMR_BODY" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('connected') else 1)" 2>/dev/null; then
    ok "EMR status: connected=true"
  else
    fail "EMR status: connected=false" \
      "seed_demo_panel.py should insert an emr_connections row; re-run without --dry-run"
  fi
else
  fail "EMR status: skipped (no auth token)" \
    "Fix login probe first"
fi

# ----- 8d. Frontend pages (200 checks) -----
PAGES="/ /worklist /patients /recapture /suspects"
info "Probe: frontend pages"
for page in $PAGES; do
  CODE="$(_http_code "${FRONTEND_URL}${page}")"
  if [ "$CODE" = "200" ] || [ "$CODE" = "307" ] || [ "$CODE" = "308" ]; then
    ok "Frontend ${page}: HTTP ${CODE}"
  else
    fail_p0 "Frontend ${page}: HTTP ${CODE}" \
      "Check raf-frontend container logs: docker logs raf-frontend --tail 30"
  fi
done

# Mobile UA probe (same base URL, different UA to exercise SSR path)
info "Probe: mobile UA"
MOBILE_CODE="$(curl -s -o /dev/null -w "%{http_code}" \
  -A "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1" \
  --max-time 8 "${FRONTEND_URL}/" 2>/dev/null || echo "000")"
if [ "$MOBILE_CODE" = "200" ] || [ "$MOBILE_CODE" = "307" ] || [ "$MOBILE_CODE" = "308" ]; then
  ok "Frontend / (mobile UA): HTTP ${MOBILE_CODE}"
else
  fail_p0 "Frontend / (mobile UA): HTTP ${MOBILE_CODE}" \
    "Check raf-frontend container: docker logs raf-frontend --tail 30"
fi

# ----- 8e. Audit-readiness / IRR kappa -----
info "Probe: GET /api/recapture/audit-readiness"
if [ -n "$ACCESS_TOKEN" ]; then
  IRR_BODY="$(_get_auth "${BACKEND_URL}/api/recapture/audit-readiness" "$ACCESS_TOKEN")"
  KAPPA=""
  if echo "$IRR_BODY" | grep -q '"inter_rater_reliability"'; then
    KAPPA="$(echo "$IRR_BODY" | \
      python3 -c "
import sys, json
d = json.load(sys.stdin)
irr = d.get('inter_rater_reliability') or {}
print(irr.get('kappa', '') if isinstance(irr, dict) else '')
" 2>/dev/null || true)"
  fi

  KAPPA_OK=0
  if [ -n "$KAPPA" ]; then
    KAPPA_OK="$(python3 -c "print(1 if float('$KAPPA') > 0 else 0)" 2>/dev/null || echo 0)"
  fi

  if [ "$KAPPA_OK" = "1" ]; then
    ok "Audit-readiness: inter_rater_reliability.kappa=${KAPPA}"
  else
    fail "Audit-readiness: kappa not > 0 (kappa=${KAPPA})" \
      "Re-run without --dry-run to seed IRR demo data"
  fi
else
  fail "Audit-readiness: skipped (no auth token)" \
    "Fix login probe first"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section "Summary"
printf "\n"
printf "  Passed : ${GREEN}${PASS_COUNT}${RESET_COLOR}\n"
printf "  Failed : ${RED}${FAIL_COUNT}${RESET_COLOR}"
[ "$FAIL_COUNT" -gt 0 ] && printf "  (P0: ${RED}${FAIL_P0}${RESET_COLOR})" || true
printf "\n\n"

END_TS="$(date '+%H:%M:%S')"
if [ "$FAIL_P0" -gt 0 ]; then
  printf "${RED}${BOLD}PREFLIGHT FAILED — do not start the demo.${RESET_COLOR}\n"
  printf "Fix the ${RED}✗${RESET_COLOR} items above, then re-run: bash scripts/predemo.sh\n\n"
  exit 1
elif [ "$FAIL_COUNT" -gt 0 ]; then
  printf "${YELLOW}${BOLD}PREFLIGHT PASSED (with warnings).${RESET_COLOR}\n"
  printf "Non-P0 items flagged above — demo can proceed, but check warnings.\n\n"
  exit 0
else
  printf "${GREEN}${BOLD}ALL CHECKS PASSED — demo environment is ready.${RESET_COLOR}\n"
  printf "Stack: ${FRONTEND_URL}  |  API: ${BACKEND_URL}  |  Completed: ${END_TS}\n\n"
  exit 0
fi
