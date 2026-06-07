# RAF Intelligence — AI Assistant Context

## What this project does
Medicare Risk Adjustment Factor (RAF) optimization SaaS. Connects to EHRs via FHIR, uses AI to find undocumented HCC conditions, helps coders capture missing revenue.

## Tech Stack
- Backend: FastAPI (Python 3.11), MySQL (mysql-connector-python, raw SQL), Redis, Celery
- Frontend: Next.js 16 (App Router), React 19, Tailwind v4, shadcn/ui
- AI: Google Gemini (`google-genai`) for clinical note analysis
- Auth: JWT (PyJWT) with refresh token rotation
- PDF: WeasyPrint + Jinja2 for RADV audit packets, ReportLab for reports
- Testing: pytest (backend), Vitest (frontend unit), Playwright (e2e)

## Project Structure
- `backend/app/routers/` — API endpoints (138 FastAPI router files)
- `backend/app/services/` — Business logic layer
- `backend/app/services/raf/` — RAF score calculator (V24/V28 blend, coefficients, calibration)
- `backend/app/services/ai_pipeline/` — Gemini-powered suspect HCC detection (prompts in `prompts/`)
- `backend/app/services/auth/` — Auth service internals
- `backend/app/middleware/` — Request middleware (audit, rate limiting)
- `backend/app/schemas/` — Pydantic request/response models
- `backend/app/security/` — Security utilities
- `backend/tests/` — pytest test suite (`test_*.py`)
- `backend/alembic/` — Alembic DB migrations
- `frontend/src/app/` — Next.js App Router pages (~55 route groups)
- `frontend/src/components/` — React components (Sidebar, DataTable, dashboards, etc.)
- `frontend/src/components/ui/` — Shared UI primitives (shadcn-based: button, card, dialog, etc.)
- `frontend/src/lib/` — Utilities (api.ts, api.generated.ts, utils.ts, constants.ts, format.ts)
- `frontend/src/hooks/` — Custom React hooks
- `frontend/src/contexts/` — React contexts
- `frontend/src/providers/` — React providers
- `database/` — Schema DDL (`schema.sql`), demo seed (`demo-seed.sql`), migrations
- `deploy/` — Zero-downtime deploy, rollback, smoke test scripts
- `scripts/` — Operational scripts (backup, restore, seed, import crosswalks)
- `e2e/` — Playwright end-to-end tests
- `docker-compose.yml` — Simple production compose (backend, Redis, Celery)
- `docker-compose.prod.yml` — Hardened production stack with nginx/TLS

## Key Conventions

### Backend
- **Raw SQL with mysql-connector** (no ORM). All queries use parameterized `%s` placeholders.
- `raf_cursor()` context manager from `app.db` for all database access.
- `run_in_db_executor()` wraps sync DB calls for async FastAPI endpoints.
- `require_permission("resource", "action")` as a FastAPI `Depends()` for authorization.
- `require_role("admin")` for admin-only endpoints.
- Router registration is centralized in `app/router_registry.py`.
- Config loaded from `.env` via `app/config.py` (`settings` singleton).
- Connection pool size defaults to 30 (`DB_POOL_SIZE` env var).
- Slow query logging threshold: 500ms (`SLOW_QUERY_THRESHOLD_MS`).

### Frontend
- Tailwind classes only (no inline styles).
- `globals.css` contains design tokens as CSS custom properties.
- `api.generated.ts` is auto-generated from OpenAPI spec (`npm run gen:api`).
- `@tanstack/react-query` for server state management.
- `axios` for HTTP requests (configured in `api.ts`).
- `lucide-react` for icons.

### Testing
- Backend: `pytest` — files in `backend/tests/test_*.py`
- Frontend: `vitest run` / `vitest` (watch mode)
- E2E: `playwright test` — specs in `e2e/`
- Bundle size checks: `npm run bundle:check`

## Important Files
- `backend/app/main.py` — FastAPI app entry, lifespan, OpenAPI tags
- `backend/app/auth.py` — JWT auth dependencies (`get_current_user`, `require_permission`, `optional_auth`)
- `backend/app/db.py` — MySQL connection pools, `raf_cursor()`, read replicas, dynamic pools
- `backend/app/config.py` — Settings loaded from `.env`
- `backend/app/router_registry.py` — Centralized router registration
- `backend/app/services/raf/calculator.py` — RAF score engine
- `backend/app/services/raf/blend_weights.py` — V24/V28 payment blend
- `backend/app/services/ai_pipeline/orchestrator.py` — AI pipeline orchestration
- `backend/app/services/ai_pipeline/suspect_engine.py` — Suspect HCC detection
- `backend/app/services/ai_pipeline/prompts/` — Gemini prompt templates (.md files)
- `frontend/src/components/Sidebar.tsx` — Main navigation
- `frontend/src/app/globals.css` — Design tokens, Tailwind config
- `frontend/src/lib/api.ts` — Axios instance and API helpers
- `frontend/src/lib/api.generated.ts` — Generated OpenAPI types
- `database/schema.sql` — Canonical database schema

## Credentials
- Demo login: `admin@raf.health` / `Admin@123` (never rehash this password while debugging)
- Production server: `ubuntu@10.1.0.204` via jump host `15.204.73.232:2222`

## Development Commands

```bash
# Backend
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload

# Frontend
cd frontend && npm run dev    # runs on port 3001

# Tests
cd backend && pytest
cd frontend && npm test
cd frontend && npm run test:e2e

# Generate API types from running backend
cd frontend && npm run gen:api
```

## Rules
- **Never deploy without explicit user approval** — user has live demos.
- **Never modify dormant modules** (Twilio SMS/voice outreach, letter print, chart_chase, knowledge_graph).
- **Always check backend response fields** before writing frontend code — never guess field names.
- **Never duplicate SQL/config constants** across files — always import from a single source.
- **Code review scope = only in-use modules** — skip dormant modules when reviewing.
- **Always `git status` before pull/rebase** — prod server often has uncommitted edits.
- **One branch per workstream** — cut a fresh branch off server before starting new work.
- **Demo credentials are fixed** — `admin@raf.health` / `Admin@123` is canonical.
- **Prod MySQL has no TLS** — `DB_SSL_ENABLED=false` in prod `.env` (internal network).
- **Iterate until 10/10** — when asked to fix and verify, loop until every check passes.
