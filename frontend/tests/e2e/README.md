# E2E Test Suite — RAF Intelligence

## Running tests

### Smoke suite (default, required on every PR)

```bash
cd frontend
npx playwright test --grep @smoke --reporter=line
# or equivalently (PW_GREP defaults to @smoke):
PW_GREP=@smoke npx playwright test
```

Smoke covers **Tests A and B** — coder accept-and-write-back + MD huddle flow.
Typical runtime: under 90 seconds on staging.

### Full suite (nightly)

```bash
PW_GREP=@full npx playwright test
```

Runs all 7 tests (A–G).  Typical runtime: 8–12 minutes on staging.

### Single spec

```bash
npx playwright test full-platform-workflow.spec.ts --grep @smoke --reporter=line
```

### Against a local dev server

```bash
E2E_BASE_URL=http://localhost:3000 PW_GREP=@smoke npx playwright test
```

---

## Debugging failures

### 1. Replay the video

After a failure the video is saved to `frontend/test-results/`.

```bash
open frontend/test-results/<run-id>/video.webm
```

### 2. Trace viewer (step-through DevTools)

Traces are recorded on the first retry.

```bash
npx playwright show-trace frontend/test-results/<run-id>/trace.zip
```

### 3. Headed mode

```bash
npx playwright test full-platform-workflow.spec.ts --headed --slowmo=400
```

### 4. Debug with Playwright Inspector

```bash
PWDEBUG=1 npx playwright test full-platform-workflow.spec.ts
```

---

## Helper modules

| File | Purpose |
|------|---------|
| `helpers/auth.ts` | `loginAs(page, role)`, `logout(page)`, `getAuthToken(page)` |
| `helpers/wait.ts` | `waitForApiCall`, `waitForToast`, `waitForDrawer` |
| `helpers/fixtures.ts` | Known patient IDs, HCC codes, RADV params, source card counts |

Seeded roles: `admin`, `coder`, `physician` — all use password `Admin@123`.

---

## Known flakies and mitigations

| Test | Flaky scenario | Mitigation |
|------|---------------|------------|
| Test A — write-back status | `writeback-status` returns 404 when suspect ID is not in DOM attribute | Falls back to asserting the accept API response; assertion is skipped gracefully |
| Test B — RAF pill tooltip | Tooltip dismissed by pointer jitter on slow CI runners | `hover()` uses default 200ms dwell; increase `actionTimeout` if needed |
| Test D — RADV records | Record count endpoint may return 202 (async job) instead of 200 | Both statuses accepted; count assertion only runs on 200 |
| Test F — outreach health | `failed_provider_unconfigured_24h` is 0 in clean environments | Field presence is asserted, not its value |
| Test G — coder role 403 | Coder credentials may not be seeded in all environments | Falls back to UI redirect assertion when token is absent |

---

## Idempotency

- Tests call `POST /api/suspects/{id}/accept` — repeated runs will get a 409 on
  subsequent calls (already accepted). Test A uses `waitForResponse` and only
  asserts toast on the first call; a 409 still confirms the business rule fired.
- RADV runs created by Test D accumulate but do not affect other tests.
- Outreach messages enqueued by Test F use a clearly labelled `E2E DLQ test` body
  and can be bulk-deleted from the admin panel after a nightly run.

---

## CI integration

```yaml
# .github/workflows/e2e.yml (excerpt)
- name: Smoke tests (every PR)
  run: cd frontend && npx playwright test --grep @smoke --reporter=line
  env:
    E2E_BASE_URL: https://raf.comercioit.com

- name: Full suite (nightly)
  run: cd frontend && PW_GREP=@full npx playwright test
  env:
    E2E_BASE_URL: https://raf.comercioit.com
```
