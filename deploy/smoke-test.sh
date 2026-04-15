#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Post-Deploy Smoke Tests
#
# Hits critical API endpoints and verifies responses.
# Exits non-zero if any check fails (causes CI/CD pipeline to roll back).
#
# Usage:
#   ./deploy/smoke-test.sh [--base-url http://localhost:8500] [--retries 5]
#
# Environment:
#   SMOKE_BASE_URL      — backend base URL (default: http://localhost:8500)
#   SMOKE_ADMIN_EMAIL   — admin login email   (default: admin@raf.health)
#   SMOKE_ADMIN_PASS    — admin password       (default: Admin@123)
#   SMOKE_RETRIES       — retry count per test (default: 5)
#   SMOKE_RETRY_DELAY   — seconds between retries (default: 5)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Parse flags / environment
# ---------------------------------------------------------------------------
BASE_URL="${SMOKE_BASE_URL:-http://localhost:8500}"
ADMIN_EMAIL="${SMOKE_ADMIN_EMAIL:-admin@raf.health}"
ADMIN_PASS="${SMOKE_ADMIN_PASS:-Admin@123}"
MAX_RETRIES="${SMOKE_RETRIES:-5}"
RETRY_DELAY="${SMOKE_RETRY_DELAY:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --retries)  MAX_RETRIES="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
FAILURES=()

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { log "  PASS: $*"; PASS=$((PASS+1)); }
fail() { log "  FAIL: $*" >&2; FAIL=$((FAIL+1)); FAILURES+=("$*"); }

# retry_curl <description> <expected_http_code> <extra_curl_args...>
# Returns: sets RESPONSE_BODY and RESPONSE_CODE
RESPONSE_BODY=""
RESPONSE_CODE=""
retry_curl() {
  local description="$1"
  local expected_code="$2"
  shift 2
  local attempt=0

  while [[ $attempt -lt $MAX_RETRIES ]]; do
    attempt=$((attempt+1))
    log "  [${attempt}/${MAX_RETRIES}] ${description}..."

    local tmpfile
    tmpfile=$(mktemp)
    RESPONSE_CODE=$(curl -sS -o "${tmpfile}" -w "%{http_code}" \
      --max-time 15 \
      --connect-timeout 5 \
      "$@" 2>/dev/null || echo "000")
    RESPONSE_BODY=$(cat "${tmpfile}")
    rm -f "${tmpfile}"

    if [[ "${RESPONSE_CODE}" == "${expected_code}" ]]; then
      return 0
    fi

    if [[ $attempt -lt $MAX_RETRIES ]]; then
      log "    Got HTTP ${RESPONSE_CODE}, expected ${expected_code}. Retrying in ${RETRY_DELAY}s..."
      sleep "${RETRY_DELAY}"
    fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
log "======================================================="
log " RAF Intelligence — Smoke Tests"
log " Base URL : ${BASE_URL}"
log " Admin    : ${ADMIN_EMAIL}"
log " Retries  : ${MAX_RETRIES} x ${RETRY_DELAY}s"
log "======================================================="

AUTH_TOKEN=""

# ---------------------------------------------------------------------------
# Test 1: GET /health — backend alive
# ---------------------------------------------------------------------------
log ""
log "Test 1: GET /health"
if retry_curl "Health endpoint" "200" \
    "${BASE_URL}/health"; then
  # Check response contains status:ok or healthy
  if echo "${RESPONSE_BODY}" | grep -qiE '"(status|health)"\s*:\s*"(ok|healthy)"'; then
    ok "GET /health returned 200 with healthy status"
  else
    fail "GET /health returned 200 but body doesn't indicate healthy: ${RESPONSE_BODY}"
  fi
else
  fail "GET /health did not return 200 (got ${RESPONSE_CODE}): ${RESPONSE_BODY}"
fi

# ---------------------------------------------------------------------------
# Test 2: POST /api/auth/login — valid credentials
# ---------------------------------------------------------------------------
log ""
log "Test 2: POST /api/auth/login"
LOGIN_PAYLOAD="{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASS}\"}"
if retry_curl "Auth login" "200" \
    -X POST \
    -H 'Content-Type: application/json' \
    -d "${LOGIN_PAYLOAD}" \
    "${BASE_URL}/api/auth/login"; then
  # Extract access token
  AUTH_TOKEN=$(echo "${RESPONSE_BODY}" | grep -oP '"access_token"\s*:\s*"\K[^"]+' || echo "")
  if [[ -n "${AUTH_TOKEN}" ]]; then
    ok "POST /api/auth/login returned 200 with access_token"
  else
    fail "POST /api/auth/login returned 200 but no access_token in body: ${RESPONSE_BODY}"
  fi
else
  fail "POST /api/auth/login did not return 200 (got ${RESPONSE_CODE})"
fi

# Remaining tests require auth token
if [[ -z "${AUTH_TOKEN}" ]]; then
  log ""
  warn "No auth token — skipping authenticated endpoint tests"
else

# ---------------------------------------------------------------------------
# Test 3: GET /api/patients — returns array
# ---------------------------------------------------------------------------
log ""
log "Test 3: GET /api/patients"
if retry_curl "Patients list" "200" \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    "${BASE_URL}/api/patients?limit=5"; then
  # Expect a JSON array or object with a patients/items/data key
  if echo "${RESPONSE_BODY}" | grep -qE '^\[|\{"(patients|items|data)"'; then
    ok "GET /api/patients returned 200 with array/collection"
  elif echo "${RESPONSE_BODY}" | grep -qE '"(id|patient_id|mrn)"'; then
    ok "GET /api/patients returned 200 with patient data"
  else
    fail "GET /api/patients returned 200 but unexpected body: ${RESPONSE_BODY:0:200}"
  fi
else
  fail "GET /api/patients did not return 200 (got ${RESPONSE_CODE})"
fi

# ---------------------------------------------------------------------------
# Test 4: GET /api/pipeline/phases — returns 8 phases
# ---------------------------------------------------------------------------
log ""
log "Test 4: GET /api/pipeline/phases"
if retry_curl "Pipeline phases" "200" \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    "${BASE_URL}/api/pipeline/phases"; then
  PHASE_COUNT=$(echo "${RESPONSE_BODY}" | grep -oP '"(name|phase|id)"' | wc -l || echo "0")
  if [[ $PHASE_COUNT -ge 8 ]]; then
    ok "GET /api/pipeline/phases returned 200 with ${PHASE_COUNT} phase entries (>= 8)"
  else
    # Also check for array length >= 8
    ARR_LEN=$(echo "${RESPONSE_BODY}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('phases',d.get('data',[]))))" 2>/dev/null || echo "0")
    if [[ $ARR_LEN -ge 8 ]]; then
      ok "GET /api/pipeline/phases returned 200 with ${ARR_LEN} phases"
    else
      fail "GET /api/pipeline/phases returned 200 but found ${PHASE_COUNT} phase fields / ${ARR_LEN} items (expected >= 8)"
    fi
  fi
else
  fail "GET /api/pipeline/phases did not return 200 (got ${RESPONSE_CODE})"
fi

# ---------------------------------------------------------------------------
# Test 5: GET /api/raf/population — returns data
# ---------------------------------------------------------------------------
log ""
log "Test 5: GET /api/raf/population"
if retry_curl "RAF population" "200" \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    "${BASE_URL}/api/raf/population"; then
  if [[ -n "${RESPONSE_BODY}" && "${RESPONSE_BODY}" != "null" && "${RESPONSE_BODY}" != "[]" ]]; then
    ok "GET /api/raf/population returned 200 with non-empty data"
  else
    fail "GET /api/raf/population returned 200 but empty/null body"
  fi
else
  fail "GET /api/raf/population did not return 200 (got ${RESPONSE_CODE})"
fi

fi  # end authenticated tests

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "======================================================="
log " Results: ${PASS} passed, ${FAIL} failed"
log "======================================================="

if [[ $FAIL -gt 0 ]]; then
  log ""
  log "Failed tests:"
  for f in "${FAILURES[@]}"; do
    log "  - ${f}"
  done
  log ""
  exit 1
fi

log "All smoke tests passed."
exit 0
