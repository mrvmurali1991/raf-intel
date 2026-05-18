# RAF Intelligence — Pilot Deployment Guide

Get from a fresh clone to a running pilot demo in under 10 minutes.

---

## Prerequisites

| Tool | Min Version | Install hint |
|------|-------------|--------------|
| Docker Desktop | 4.x (compose v2) | https://docs.docker.com/get-docker/ |
| Python | 3.11+ | https://python.org/downloads |
| Node.js | 20+ | https://nodejs.org or `nvm install 20` |
| jq | any | `brew install jq` / `apt-get install -y jq` |
| openssl | any | included on macOS; `apt-get install -y openssl` on Linux |

---

## 10-Minute Quickstart

```bash
# 1. Clone
git clone <repo-url> raf-intelligence
cd raf-intelligence

# 2. One command to rule them all
make pilot-ready
```

That single target will:

1. Verify all prerequisites and print friendly install hints for anything missing
2. Generate `JWT_SECRET`, `ENCRYPTION_KEY`, and placeholder values for external services in `.env` (skips keys already present — idempotent)
3. Start `raf-backend`, `raf-mysql`, and `raf-redis` via `docker compose -f docker-compose.local.yml up -d --build`
4. Poll `/health` every 3 seconds until HTTP 200 (timeout 120 seconds)
5. Apply all Alembic DB migrations
6. Seed the demo patient panel
7. Run the fast unit test suite (`backend/scripts/test-fast.sh`) — exits on failure
8. Execute a 30-second end-to-end smoke: login → list suspects → accept one → verify audit row
9. Print the READY banner with all URLs and credentials

At the end of a successful run you will see:

```
  ╔══════════════════════════════════════════════════════════════╗
  ║              RAF INTELLIGENCE — PILOT READY                 ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Backend URL  : http://localhost:8500                        ║
  ║  Frontend URL : http://localhost:3000                        ║
  ║               (start: cd frontend && npm run dev)            ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Demo login   : admin@raf.health  /  Admin@123               ║
  ...
```

### Start the frontend (in a separate terminal)

```bash
cd frontend && npm install && npm run dev
```

The backend API is containerised; the frontend runs locally via Next.js dev server for faster iteration.

---

## Key URLs

| Page | URL |
|------|-----|
| Dashboard | http://localhost:3000/ |
| Worklist | http://localhost:3000/worklist |
| MD Today | http://localhost:3000/md/today |
| Demo Admin | http://localhost:3000/admin/demo |
| Document Ingestion | http://localhost:3000/admin/document-ingestion |
| API Docs (Swagger) | http://localhost:8500/docs |
| Health check | http://localhost:8500/health |

Demo credentials: `admin@raf.health` / `Admin@123`

---

## Make Targets

| Target | What it does |
|--------|--------------|
| `make pilot-ready` | Full zero-to-demo setup (idempotent) |
| `make pilot-ready-fast` | Same but skips unit tests (`--skip-tests`) |
| `make pilot-doctor` | Diagnostic dashboard: containers, DB counts, errors, cache, FHIR |
| `make pilot-teardown` | Stop containers, remove volumes, clear temp artefacts |
| `make smoke` | Quick 5-endpoint HTTP check (no auth required) |

---

## Diagnostic Dashboard

Run at any time:

```bash
make pilot-doctor
```

Output includes:

- Container health (raf-backend / raf-mysql / raf-redis) with ✅/⚠️/❌
- Backend `/health` endpoint status
- Admin login check
- Row counts: patients, suspects, audit_log, raf_meat_evidence, users, hcc_codes
- Redis keyspace + hit/miss stats
- Outreach service health
- FHIR circuit breaker state
- Last 5 ERROR lines from `docker logs raf-backend`

---

## Teardown

```bash
make pilot-teardown
```

Stops containers, removes Docker volumes (`raf_mysql_data`, `redis_data`), and clears `/tmp/raf-demo-pdfs/`. Safe to re-run.

To preserve data volumes (e.g. for handoff):

```bash
bash scripts/pilot-teardown.sh --keep-data
```

---

## Customer-Supplied Environment Variables

Add these to `.env` before running `make pilot-ready` (or after — re-running is idempotent for the container restart):

### AI / LLM

```env
GOOGLE_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-2.5-pro
```

Obtain at: https://ai.google.dev/

### Messaging (Twilio)

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=<your-auth-token>
TWILIO_FROM_NUMBER=+1XXXXXXXXXX
```

### Email (SendGrid)

```env
SENDGRID_API_KEY=SG.xxxxxxxxxxxxx
SENDGRID_FROM_EMAIL=noreply@yourorg.com
SENDGRID_WEBHOOK_KEY=<sendgrid-webhook-signing-secret>
```

### OpenEMR FHIR (optional — required for live EMR sync)

```env
OPENEMR_URL=https://your-openemr-instance.com
OPENEMR_CLIENT_ID=<oauth2-client-id>
OPENEMR_CLIENT_SECRET=<oauth2-client-secret>
OPENEMR_DB_HOST=<host>
OPENEMR_DB_USER=<user>
OPENEMR_DB_PASSWORD=<password>
OPENEMR_DB_NAME=openemr
```

See `docs/OPENEMR_OAUTH2_SETUP.md` for step-by-step OAuth2 client setup including the "enable disabled client" requirement.

### Production overrides

```env
APP_ENV=production
FRONTEND_URL=https://your-pilot-domain.com
BACKEND_PORT=8500
DB_SSL_ENABLED=false     # set true if using RDS / Cloud SQL with TLS
```

---

## Troubleshooting

### `/health` never returns 200 (timeout at step 4)

```
docker logs raf-backend --tail=100
```

Common causes:
- Database connection refused: check `RAF_DB_HOST` and that `raf-mysql` is healthy (`docker ps`)
- Missing `ENCRYPTION_KEY` / `PHI_FERNET_KEY`: re-run `make pilot-ready` to auto-generate
- Port 8500 already in use: `lsof -i :8500` and kill the conflicting process

### Migrations fail

```
docker exec raf-backend python /app/scripts/apply_migrations.py
```

If you see `Target database is not up to date`, confirm the `raf_intelligence` DB exists:

```
docker exec raf-mysql mysql -uroot -proot -e "SHOW DATABASES;"
```

If it is absent, the schema init script did not run. Recreate the container with volumes removed:

```bash
make pilot-teardown && make pilot-ready
```

### Admin login fails (401)

The admin account may be locked from failed attempts:

```bash
docker exec raf-mysql mysql -uroot -proot raf_intelligence \
  -e "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health';"
```

`pilot-ready.sh` runs this automatically, but you can run it manually at any time.

### Seed returns 0 patients

```bash
docker exec raf-backend python /app/scripts/seed_demo_panel.py
```

Then run `make pilot-doctor` to confirm row counts.

### Redis "no PONG"

The default password is `rafredis123`. If you customised `REDIS_PASSWORD` in `.env`, ensure the container was restarted after the change:

```bash
docker compose -f docker-compose.local.yml restart redis
```

### Docker image build fails

```bash
docker compose -f docker-compose.local.yml build --no-cache backend
```

Common cause: stale layer cache after a Python dependency change.

---

## Re-running After a Code Change

`pilot-ready.sh` is idempotent. Just run:

```bash
make pilot-ready
```

It will skip secret generation (already in `.env`), skip `docker compose up` if containers are already running, and re-run migrations + smoke.

To force a full rebuild:

```bash
make pilot-teardown && make pilot-ready
```

---

## Enterprise / Procurement Documentation

See `docs/enterprise/` for:

- `OBSERVABILITY.md` — metrics, tracing, alerting stack
- Security architecture and SOC 2 alignment
- HA deployment topology (`docs/HA_DEPLOYMENT.md`)
- Database replica setup (`docs/DB_REPLICA.md`)
- Incident runbooks (`docs/incident_runbooks.md`)
