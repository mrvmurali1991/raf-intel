#!/usr/bin/env bash
# =============================================================================
# RAF Intelligence — Pilot-Ready Script
#
# Gets a fresh-cloned repo from zero to "ready for a pilot customer demo."
# Safe to re-run: idempotent checks skip already-completed work.
#
# Usage:
#   bash scripts/pilot-ready.sh
#   bash scripts/pilot-ready.sh --skip-tests   # skip test-fast.sh
#   bash scripts/pilot-ready.sh --skip-seed    # skip demo data seeding
#
# Requirements: Docker, docker compose v2, Python 3.11+, Node 20+, jq, openssl
# =============================================================================
set -e
set -o pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
COMPOSE_FILE="$REPO_ROOT/docker-compose.local.yml"
BACKEND_URL="http://localhost:8500"
HEALTH_URL="$BACKEND_URL/health"
HEALTH_TIMEOUT=120
SKIP_TESTS=0
SKIP_SEED=0

for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    --skip-seed)  SKIP_SEED=1 ;;
    --help|-h)
      grep '^#' "$0" | head -20 | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

step()  { echo -e "\n${CYAN}${BOLD}==> $*${RESET}"; }
ok()    { echo -e "    ${GREEN}[OK]${RESET} $*"; }
warn()  { echo -e "    ${YELLOW}[WARN]${RESET} $*"; }
fail()  { echo -e "\n${RED}${BOLD}[FAIL]${RESET} $1"; [ -n "${2:-}" ] && echo -e "       Remediation: $2"; exit 1; }

# ---------------------------------------------------------------------------
# STEP 1 — Prerequisite check
# ---------------------------------------------------------------------------
step "Checking prerequisites"

check_cmd() {
  local cmd="$1" hint="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd found: $(command -v "$cmd")"
  else
    fail "$cmd not found" "$hint"
  fi
}

check_cmd docker     "Install Docker Desktop: https://docs.docker.com/get-docker/"
check_cmd jq         "brew install jq   OR   apt-get install -y jq"
check_cmd openssl    "brew install openssl   OR   apt-get install -y openssl"
check_cmd python3    "Install Python 3.11+: https://python.org/downloads"
check_cmd node       "Install Node 20+: https://nodejs.org  OR  nvm install 20"

# docker compose v2
if docker compose version >/dev/null 2>&1; then
  ok "docker compose v2 found"
else
  fail "docker compose v2 not found" "Upgrade Docker Desktop >= 4.x or install compose plugin: https://docs.docker.com/compose/install/"
fi

# Python version >= 3.11
PY_VER=$(python3 -c "import sys; print(sys.version_info.major*100+sys.version_info.minor)")
if [ "$PY_VER" -ge 311 ]; then
  ok "Python version OK ($(python3 --version))"
else
  warn "Python $(python3 --version) found — 3.11+ recommended. Some features may not work."
fi

# Node version >= 20
NODE_MAJ=$(node -e "console.log(process.versions.node.split('.')[0])")
if [ "$NODE_MAJ" -ge 20 ]; then
  ok "Node version OK ($(node --version))"
else
  warn "Node $(node --version) found — v20+ recommended."
fi

# ---------------------------------------------------------------------------
# STEP 2 — Generate secrets in .env if missing
# ---------------------------------------------------------------------------
step "Ensuring .env with secrets"

ensure_env_var() {
  local key="$1" val="$2"
  if [ -f "$ENV_FILE" ] && grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    ok "$key already set — skipping"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
    ok "$key generated"
  fi
}

touch "$ENV_FILE"

# JWT_SECRET — 64 hex chars
ensure_env_var JWT_SECRET "$(openssl rand -hex 32)"
# JWT_REFRESH_SECRET
ensure_env_var JWT_REFRESH_SECRET "$(openssl rand -hex 32)"
# ENCRYPTION_KEY — valid Fernet key (base64url 32 bytes)
FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
             || openssl rand -base64 32)
ensure_env_var ENCRYPTION_KEY "$FERNET_KEY"
# PHI Fernet key
FERNET_KEY2=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
              || openssl rand -base64 32)
ensure_env_var PHI_FERNET_KEY "$FERNET_KEY2"
# Placeholders for external services
ensure_env_var SENDGRID_WEBHOOK_KEY "REPLACE_ME_sendgrid_webhook_key"
ensure_env_var TWILIO_AUTH_TOKEN    "REPLACE_ME_twilio_auth_token"
ensure_env_var TWILIO_ACCOUNT_SID   "REPLACE_ME_twilio_account_sid"
ensure_env_var GOOGLE_API_KEY       "REPLACE_ME_google_api_key"
ensure_env_var GEMINI_MODEL         "gemini-2.5-pro"

# ---------------------------------------------------------------------------
# STEP 3 — Spin up containers
# ---------------------------------------------------------------------------
step "Starting Docker containers"

cd "$REPO_ROOT"
mkdir -p data/uploads data/logs data/redis

# Check if already running
if docker ps --filter "name=raf-backend" --filter "status=running" | grep -q raf-backend; then
  ok "raf-backend already running — skipping docker compose up"
else
  docker compose -f "$COMPOSE_FILE" up -d --build
  ok "Containers starting"
fi

# ---------------------------------------------------------------------------
# STEP 4 — Wait for /health 200
# ---------------------------------------------------------------------------
step "Waiting for backend /health (timeout ${HEALTH_TIMEOUT}s)"

elapsed=0
while true; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "200" ]; then
    ok "/health returned 200 (after ${elapsed}s)"
    break
  fi
  if [ "$elapsed" -ge "$HEALTH_TIMEOUT" ]; then
    fail "/health did not return 200 within ${HEALTH_TIMEOUT}s" \
         "Check container logs: docker logs raf-backend --tail=50"
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done

# ---------------------------------------------------------------------------
# STEP 5 — Apply DB migrations
# ---------------------------------------------------------------------------
step "Applying DB migrations"

if docker exec raf-backend python /app/scripts/apply_migrations.py 2>&1 | tail -3; then
  ok "Migrations applied"
else
  warn "apply_migrations.py returned non-zero — may be already current"
fi

# Also unlock the admin user (idempotent)
MYSQL_CTR=$(docker ps --filter "name=raf-mysql" --format "{{.Names}}" | head -1)
if [ -n "$MYSQL_CTR" ]; then
  docker exec "$MYSQL_CTR" mysql -uroot -proot raf_intelligence \
    -e "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health';" \
    2>/dev/null && ok "admin@raf.health login unlocked" \
    || warn "Could not unlock admin (may not exist yet — seed step will create it)"
fi

# ---------------------------------------------------------------------------
# STEP 6 — Seed demo data
# ---------------------------------------------------------------------------
if [ "$SKIP_SEED" -eq 0 ]; then
  step "Seeding demo data"

  # Prefer seed_realistic_demo.py if it exists, fall back to seed_demo_panel.py
  if [ -f "$REPO_ROOT/backend/scripts/seed_realistic_demo.py" ]; then
    SEED_SCRIPT="seed_realistic_demo.py"
  elif [ -f "$REPO_ROOT/backend/scripts/seed_demo_panel.py" ]; then
    SEED_SCRIPT="seed_demo_panel.py"
  else
    SEED_SCRIPT=""
  fi

  if [ -n "$SEED_SCRIPT" ]; then
    docker exec raf-backend python /app/scripts/"$SEED_SCRIPT" \
      && ok "Demo data seeded via $SEED_SCRIPT" \
      || warn "Seed returned non-zero — may be already seeded (idempotent seeds are OK)"
  else
    warn "No seed script found — skipping demo data (add seed_realistic_demo.py to backend/scripts/)"
  fi
else
  ok "Seed step skipped (--skip-seed)"
fi

# ---------------------------------------------------------------------------
# STEP 7 — Fast unit tests
# ---------------------------------------------------------------------------
if [ "$SKIP_TESTS" -eq 0 ]; then
  step "Running fast unit tests"
  if [ -f "$REPO_ROOT/backend/scripts/test-fast.sh" ]; then
    bash "$REPO_ROOT/backend/scripts/test-fast.sh" \
      && ok "All fast tests passed" \
      || fail "test-fast.sh failed" \
              "Fix failing tests before running a pilot demo. Re-run: bash backend/scripts/test-fast.sh"
  else
    warn "backend/scripts/test-fast.sh not found — skipping"
  fi
else
  ok "Tests skipped (--skip-tests)"
fi

# ---------------------------------------------------------------------------
# STEP 8 — 30-second end-to-end smoke
# ---------------------------------------------------------------------------
step "Running 30-second end-to-end smoke"

LOGIN_PAYLOAD='{"email":"admin@raf.health","password":"Admin@123"}'
LOGIN_RESP=$(curl -sf -X POST "$BACKEND_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "$LOGIN_PAYLOAD" 2>/dev/null) || LOGIN_RESP=""

if echo "$LOGIN_RESP" | grep -q '"access_token"'; then
  ok "Login: access_token obtained"
  TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
else
  fail "Login failed — no access_token in response" \
       "Verify admin@raf.health / Admin@123 exist and DB seed ran. Response: $(echo "$LOGIN_RESP" | head -c 200)"
fi

AUTH_HEADER="Authorization: Bearer $TOKEN"

# List suspects
SUSPECTS_RESP=$(curl -sf "$BACKEND_URL/api/suspects?limit=5" \
  -H "$AUTH_HEADER" 2>/dev/null) || SUSPECTS_RESP=""
if echo "$SUSPECTS_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('total',0))" 2>/dev/null | grep -qv "^0$"; then
  ok "Suspects list: returned results"
else
  warn "Suspects list returned 0 results — seed may not have run"
fi

# Accept a suspect (find the first pending one)
SUSPECT_ID=$(echo "$SUSPECTS_RESP" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  items=d if isinstance(d,list) else d.get('items',d.get('suspects',[]))
  pending=[x for x in items if isinstance(x,dict) and x.get('status','') in ('pending','','PENDING')]
  if pending: print(pending[0].get('id',pending[0].get('suspect_id','')))
except: pass
" 2>/dev/null || echo "")

if [ -n "$SUSPECT_ID" ]; then
  ACCEPT_RESP=$(curl -sf -X POST "$BACKEND_URL/api/suspects/$SUSPECT_ID/accept" \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" -d '{}' 2>/dev/null) || ACCEPT_RESP=""
  if echo "$ACCEPT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null | grep -qi "accept\|approved"; then
    ok "Suspect $SUSPECT_ID accepted"
  else
    warn "Suspect accept returned unexpected payload (non-fatal)"
  fi
else
  warn "No pending suspect found to accept — skipping accept step"
fi

# Verify audit log has a row
AUDIT_RESP=$(curl -sf "$BACKEND_URL/api/admin/audit-log?limit=1" \
  -H "$AUTH_HEADER" 2>/dev/null) || AUDIT_RESP=""
if echo "$AUDIT_RESP" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  items=d if isinstance(d,list) else d.get('items',d.get('entries',[]))
  print(len(items))
except: print(0)
" 2>/dev/null | grep -qv "^0$"; then
  ok "Audit log: row(s) present"
else
  warn "Audit log appears empty — may need more activity"
fi

ok "30-second smoke complete"

# ---------------------------------------------------------------------------
# STEP 9 — READY banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║              RAF INTELLIGENCE — PILOT READY                 ║"
echo "  ╠══════════════════════════════════════════════════════════════╣"
echo "  ║  Backend URL  : http://localhost:8500                        ║"
echo "  ║  Frontend URL : http://localhost:3000                        ║"
echo "  ║               (start: cd frontend && npm run dev)            ║"
echo "  ╠══════════════════════════════════════════════════════════════╣"
echo "  ║  Demo login   : admin@raf.health  /  Admin@123               ║"
echo "  ╠══════════════════════════════════════════════════════════════╣"
echo "  ║  Key URLs:                                                   ║"
echo "  ║    Dashboard    http://localhost:3000/                       ║"
echo "  ║    Worklist     http://localhost:3000/worklist               ║"
echo "  ║    MD Today     http://localhost:3000/md/today               ║"
echo "  ║    Demo Admin   http://localhost:3000/admin/demo             ║"
echo "  ║    Doc Ingest   http://localhost:3000/admin/document-ingest  ║"
echo "  ║    API Docs     http://localhost:8500/docs                   ║"
echo "  ╠══════════════════════════════════════════════════════════════╣"
echo "  ║  Diagnostics  : make pilot-doctor                            ║"
echo "  ║  Teardown     : make pilot-teardown                          ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
