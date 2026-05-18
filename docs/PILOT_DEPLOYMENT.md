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
8. Execute a 30-second end-to-end smoke: login, list suspects, accept one, verify audit row
9. Print the READY banner with all URLs and credentials

### Start the frontend (separate terminal)

```bash
cd frontend && npm install && npm run dev
```

The backend API is containerised; the frontend runs locally via Next.js dev server for faster iteration.

---

## Demo Credentials

- URL: http://localhost:3000
- Login: `admin@raf.health` / `Admin@123`

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

```bash
make pilot-doctor
```

Output includes:

- Container health (raf-backend / raf-mysql / raf-redis) with OK/!!/XX
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

Stops containers, removes Docker volumes, and clears `/tmp/raf-demo-pdfs/`. Safe to re-run.

To preserve data volumes:

```bash
bash scripts/pilot-teardown.sh --keep-data
```

---

## Customer-Supplied Environment Variables

Add these to `.env` before running `make pilot-ready` (re-running is idempotent):

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

See `docs/OPENEMR_OAUTH2_SETUP.md` for step-by-step OAuth2 client setup, including the "enable disabled client" requirement.

### Production overrides

```env
APP_ENV=production
FRONTEND_URL=https://your-pilot-domain.com
BACKEND_PORT=8500
DB_SSL_ENABLED=false
```

---

## Troubleshooting

### `/health` never returns 200

```
docker logs raf-backend --tail=100
```

Common causes:
- Database connection refused: check `RAF_DB_HOST` and that `raf-mysql` is healthy (`docker ps`)
- Missing `ENCRYPTION_KEY` / `PHI_FERNET_KEY`: re-run `make pilot-ready` to auto-generate
- Port 8500 already in use: `lsof -i :8500` and kill the conflicting process

### Migrations fail

```bash
docker exec raf-backend python /app/scripts/apply_migrations.py
```

If the `raf_intelligence` DB is absent:

```bash
make pilot-teardown && make pilot-ready
```

### Admin login fails (401)

```bash
docker exec raf-mysql mysql -uroot -proot raf_intelligence \
  -e "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health';"
```

`pilot-ready.sh` runs this automatically, but you can run it manually.

### Seed returns 0 patients

```bash
docker exec raf-backend python /app/scripts/seed_demo_panel.py
```

Then run `make pilot-doctor` to confirm row counts.

### Redis "no PONG"

```bash
docker compose -f docker-compose.local.yml restart redis
```

### Docker image build fails

```bash
docker compose -f docker-compose.local.yml build --no-cache backend
```

---

## Re-running After a Code Change

`pilot-ready.sh` is idempotent. Just run:

```bash
make pilot-ready
```

To force a full rebuild from scratch:

```bash
make pilot-teardown && make pilot-ready
```

---

## Enterprise / Procurement Documentation

See `docs/enterprise/` for security architecture, SOC 2 alignment, and HA deployment details.
See `docs/HA_DEPLOYMENT.md` for multi-server topology.
See `docs/incident_runbooks.md` for on-call procedures.
