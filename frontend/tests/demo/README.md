# RAF Intelligence — live demo flow

Playwright-driven 7-scene walk-through of the local stack, designed to drop a deck-ready storyboard and run a polished live demo.

## Files

```
tests/demo/
├── demo-flow.spec.ts     7 scenes with narration, assertions, annotated shots
├── demo-helpers.ts       login, content waits, highlight overlay, data-readiness probe
└── README.md             this file

frontend/playwright.demo.config.ts   separate config (don't touch playwright.config.ts)
docs/DEMO_PRESENTER_GUIDE.md         what to say while the script runs
```

## Quickstart

```bash
# 1. Make sure the local stack is up and seeded — see ../../../docs/DEMO_PRESENTER_GUIDE.md
docker compose -f ../../../docker-compose.local.yml up -d
docker exec -e MIGRATIONS_DIR=/tmp/migrations raf-backend python /app/scripts/apply_migrations.py
docker exec raf-backend sh /app/scripts/run_all_seeds.sh
docker exec raf-backend python /app/scripts/seed_irr_demo.py

# 2. CRITICAL — connect demo EMR so /worklist has patients to show
#    Either click "Connect Demo EMR" on http://localhost:3444/emr-config
#    or POST /api/emr/demo-connect

# 3. Run the demo
cd frontend
DEMO_PASSWORD='Admin@123' npx playwright test --config=playwright.demo.config.ts

# 4. Storyboard is at frontend/playwright-report/demo-shots/
ls playwright-report/demo-shots/
```

## Common modes

| Goal | Command |
|---|---|
| **Headless storyboard refresh** before a call | `DEMO_PASSWORD='Admin@123' npx playwright test --config=playwright.demo.config.ts` |
| **Live screen-share (slow-mo)** with the browser visible | `DEMO_PASSWORD='Admin@123' DEMO_PAUSE_MS=3000 PWDEBUG_SLOWMO=400 npx playwright test --config=playwright.demo.config.ts --headed` |
| **Record a .webm video** to share async | `DEMO_PASSWORD='Admin@123' DEMO_VIDEO=1 npx playwright test --config=playwright.demo.config.ts` |
| **Forensic trace** when a scene fails | `DEMO_PASSWORD='Admin@123' DEMO_TRACE=1 npx playwright test --config=playwright.demo.config.ts; npx playwright show-trace playwright-report/data/*/trace.zip` |
| **Single scene rehearsal** (e.g. just Scene 4) | `npx playwright test --config=playwright.demo.config.ts -g "Scene 4"` |
| **UI mode** for live exploration | `npx playwright test --config=playwright.demo.config.ts --ui` |

## What gets produced

```
playwright-report/
├── demo-shots/
│   ├── 01-worklist.png                  full-page, no annotation
│   ├── 01-worklist-annotated.png        red highlight on key tile
│   ├── 02a-recapture-overview.png
│   ├── 02b-hcc-popover.png              after hovering an HCC chip
│   ├── 02b-hcc-popover-annotated.png
│   ├── 03-suspects-overview.png
│   ├── 03-suspects-calibrated-annotated.png
│   ├── 04-audit-readiness.png
│   ├── 04-audit-readiness-annotated.png
│   ├── 05-velocity-decay.png
│   ├── 05-velocity-decay-annotated.png
│   ├── 06-cfo-summary.png
│   ├── 06-cfo-summary-annotated.png
│   ├── 07a-worklist-phone.png           414×896 viewport
│   └── 07b-worklist-tablet.png          768×1024 viewport
└── index.html                           Playwright HTML report (open with `npx playwright show-report`)
```

## How the demo handles missing data

The `beforeAll` hook calls `probeDataReadiness()` and prints a warning if EMR isn't connected or no patients are loaded.  Each scene then uses `softAssertVisible` for its value-prop element — if the element isn't visible, the run logs `SOFT-FAIL` but **doesn't abort**.  You still get a storyboard for the scenes that did work, and a clear list of which value-props need data to render properly.

Typical "needs data" scenes:
- Scene 2 (HCC popover) — needs at least one open recapture gap
- Scene 4 (kappa tile) — needs `seed_irr_demo.py` to have populated `primary_coder_label` / `secondary_coder_label`
- Scene 5–6 (velocity, CFO) — need recapture-decay/CFO endpoints to return non-empty rows

Run the seeds **and** connect the demo EMR before recording the final storyboard.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| **Storyboard shows the login page on every scene** | Known limitation: the saved storageState cookie isn't being picked up by the auth-context's refresh flow.  Workaround: do a real UI login once in a real browser at http://localhost:3444/login, then copy the cookies into `tests/demo/.demo-auth-state.json` (or just record manually).  Better fix: have the auth-context persist the access token in `localStorage` so it survives page reloads. |
| All scenes show a centered spinner | `/api/auth/refresh` returning 500 — apply migration `030_user_sessions_prev_refresh_hash.sql` |
| `/api/auth/me` returns 401 immediately after successful login | `users.tenant_id IS NULL` — fix with `UPDATE users SET tenant_id=1 WHERE email='admin@raf.health';` |
| Login itself fails with "Invalid email or password" | Account locked from prior demo runs — `UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health';` |
| Run is slow (~3 min) | The 7-scene sequence is intentionally serial (auth rate-limiter would hit at scene 5+ with parallel runs).  Use `-g "Scene N"` to rehearse one scene only |
| `/openapi.json` returns 500 | Pre-existing pydantic forward-ref bug — see `git log` for the snomed_mapping `Body(...)` fix |

## Known limitation: storageState + auth-context

The frontend's auth-context (`frontend/src/contexts/auth-context.tsx`) keeps the access token in **module-level memory** (`let _accessToken: string | null = null`).  On a fresh page load:
1. `getAccessToken()` returns `null`
2. The context falls back to `/api/auth/refresh` which uses the httpOnly `raf_refresh_token` cookie
3. If that succeeds, the user is authenticated; if it fails, redirect to `/login`

The Playwright `globalSetup` does an API-level login that DOES set `raf_refresh_token` correctly in the saved storageState — but for reasons that need further investigation (likely SameSite / cross-port cookie handling between localhost:3444 and localhost:8500), the auth-context's refresh call doesn't always pick it up cleanly during the test run.

**Practical workaround for now**: log in manually in a regular browser, then run the demo headed (`--headed`) and click through scenes yourself.  Or fix the auth-context to persist the access token to `localStorage` (which Playwright's storageState DOES preserve across page reloads).
