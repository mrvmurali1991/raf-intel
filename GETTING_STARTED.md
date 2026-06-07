# RAF Intelligence -- Developer Onboarding

Healthcare SaaS for RAF score optimization: AI-driven suspect conditions, MEAT evidence extraction, CMS submissions, and provider workflows.

---

## Prerequisites

| Tool       | Version  | Why                                    |
|------------|----------|----------------------------------------|
| Docker     | 24+      | All services run in containers         |
| Node.js    | 22 LTS   | Frontend build (Next.js 16)            |
| Python     | 3.11     | Backend (FastAPI)                      |
| MySQL      | 8.0      | Included in docker-compose; optional locally |

---

## Quick Start (Docker -- under 5 minutes)

```bash
git clone <repo-url> && cd raf-intelligence
cp .env.example .env

# Edit .env -- at minimum set these for local dev:
#   APP_ENV=development
#   RAF_DB_HOST=mysql
#   RAF_DB_PASSWORD=root
#   GOOGLE_API_KEY=<your-gemini-key>   (optional, AI features only)

# Start everything (MySQL, Redis, backend, frontend, OpenEMR):
docker compose -f docker-compose.local.yml up -d --build
```

| Service   | URL                          |
|-----------|------------------------------|
| Frontend  | http://localhost:3444         |
| Backend   | http://localhost:8500         |
| API Docs  | http://localhost:8500/docs    |
| OpenEMR   | http://localhost:8080         |

Login: **admin@raf.health** / **Admin@123**

---

## Quick Start (No Docker -- native)

```bash
# Terminal 1 -- Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload

# Terminal 2 -- Frontend
cd frontend && npm ci
NEXT_PUBLIC_API_URL=http://localhost:8500 npx next dev -p 3000

# Or use Makefile shortcuts:
make dev           # backend + frontend in parallel
make smoke         # 5-endpoint health check
```

---

## Project Structure

```
raf-intelligence/
  backend/
    app/
      main.py              -- FastAPI entrypoint
      config.py            -- Env vars and settings
      db.py                -- MySQL connection pool
      routers/             -- API endpoints (~135 route files)
      services/            -- Business logic (raf/, ai_pipeline/, radv/, emr/, chart_chase/)
      schemas/             -- Pydantic request/response models
      security/            -- RBAC, PHI encryption
      worker.py            -- Celery worker entrypoint
    alembic/               -- Alembic migration versions
    tests/                 -- pytest suite
  frontend/src/
    app/                   -- Next.js App Router pages (~50 routes)
    components/            -- React components (~100 files)
    hooks/                 -- React Query hooks (queries/ + mutations/)
    lib/api.ts             -- Axios instance + typed helpers
    lib/api.generated.ts   -- Auto-generated from OpenAPI spec
    types/                 -- TypeScript type definitions
  database/
    schema.sql             -- Core RAF tables (14 tables)
    migrations/            -- Numbered SQL migrations (001-020+)
    openemr-minimal.sql    -- OpenEMR stub schema for local dev
  docker-compose.local.yml -- Local dev stack (MySQL + all services)
  docker-compose.yml       -- Production stack (external DB)
  Makefile                 -- Dev/deploy shortcuts
  .env.example             -- All env vars with docs
```

---

## Architecture

```
Browser --> Next.js 16 (React 19, Tailwind, shadcn/ui)
         |  axios (JWT auth, auto-refresh)
         v
     FastAPI (Python 3.11, Pydantic v2)
      /       |         \
  MySQL 8   Redis 7    Gemini (Vertex AI)
 (InnoDB)  (cache +     (NLP extraction,
            Celery       suspect generation)
            broker)
              |
         Celery Worker (bulk ingest, AI pipeline, CMS export)
```

Key integrations: OpenEMR (FHIR R4), SMART on FHIR, HL7v2 ADT, Direct Messaging, CCDA.

---

## Running Tests

```bash
cd backend && pytest tests/              # Backend unit tests
cd frontend && npm test                   # Frontend unit tests (vitest)
cd frontend && npx playwright test        # E2E tests (needs running stack)
make smoke                                # Quick 5-endpoint curl check
```

---

## Common Tasks

### Add a new API endpoint

1. Create `backend/app/routers/my_feature.py`:
   ```python
   from fastapi import APIRouter, Depends
   from app.auth import require_auth

   router = APIRouter(prefix="/api/my-feature", tags=["my-feature"])

   @router.get("/")
   async def list_items(user=Depends(require_auth)):
       return {"items": []}
   ```
2. The router is auto-discovered by `backend/app/router_registry.py` -- no manual registration needed.
3. Regenerate frontend types: `cd frontend && npm run gen:api`

### Add a new page

1. Create `frontend/src/app/my-feature/page.tsx` with a `"use client"` directive.
2. The App Router picks it up automatically at `/my-feature`.
3. Add a nav link in the sidebar component if needed.

### Run a database migration

```bash
cd backend
alembic revision --autogenerate -m "add_widget_table"
alembic upgrade head
# Raw SQL migrations in database/migrations/ run on first boot via docker-entrypoint-initdb.d.
```

---

## Key Environment Variables

Set `APP_ENV=development` to relax secret validation. Key vars for local dev:
`RAF_DB_HOST=mysql`, `RAF_DB_PASSWORD=root`, `REDIS_PASSWORD=rafredis123`,
`NEXT_PUBLIC_API_URL=http://localhost:8500`, `GOOGLE_API_KEY=<your-key>` (optional).
JWT_SECRET is auto-generated in dev mode. See `.env.example` for the full list.

---

## Troubleshooting

**Backend won't start -- "FATAL: JWT_SECRET is not set"**
Set `APP_ENV=development` in `.env`. Dev mode auto-generates secrets.

**MySQL connection refused**
If using Docker: wait for the healthcheck (`docker compose logs mysql`). If native: ensure MySQL is on port 3306 and `raf_intelligence` database exists.

**Frontend shows network errors**
Check that `NEXT_PUBLIC_API_URL` matches your backend URL. In Docker local: `http://localhost:8500`. The frontend container builds this at image build time -- rebuild if you change it.

**"Module not found" in backend**
Run `pip install -r requirements.txt` again. WeasyPrint needs native libs (`libpango`, `libcairo`) -- on macOS: `brew install pango cairo`.

**Celery worker not processing jobs**
Ensure Redis is running and `REDIS_URL` is correct. Check: `docker compose logs worker`.

**OpenEMR OAuth2 client disabled**
Dynamically registered OAuth2 clients in OpenEMR are disabled by default. Enable them in the OpenEMR admin panel under Administration > API Clients.

**Port conflicts**
Default ports: 3444 (frontend), 8500 (backend), 8080 (OpenEMR), 3309 (MySQL). Change in `docker-compose.local.yml` or via env vars.

---

## Useful Makefile Targets

`make local-up` / `make local-down` -- start/stop Docker stack |
`make smoke` -- curl health check |
`make pilot-ready` -- full pilot setup |
`make pilot-doctor` -- diagnose issues
