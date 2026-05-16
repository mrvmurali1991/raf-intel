# Runbook 05 — Wire Sentry DSN into Production

**Severity:** BLOCKER for 10/10 (observability completeness)
**Time estimate:** ~30 minutes
**Performed by:** Kriya (sole operator)
**References:**
- `docs/READINESS_MATRIX.md` § 6 Observability (score 9/10 — Sentry installed but DSN not set in prod)
- `frontend/sentry.{client,server,edge}.config.ts` (already wired in code)
- Commit `c3876bd` (Sentry wired) · commit `94b9eea` (dynamic import to avoid bundle bloat)

---

## Why

Sentry SDK is fully integrated in the code (see commits above). What's missing is the **DSN** in prod `.env` — without it, the SDK is a no-op and uncaught errors fall on the floor. For a paying customer, errors **must** hit a real on-call inbox.

---

## Prerequisites

- [ ] Owner-level access to <https://sentry.io> (or a Sentry self-hosted instance you control).
- [ ] SSH access to prod (`ubuntu@10.1.0.204` via jump host — same as previous runbooks).
- [ ] An email or paging channel (e.g. PagerDuty, Slack webhook) you want production errors routed to.
- [ ] Local repo checked out at `fix/post-review-batch-10` so you can verify the SDK wiring.

---

## Steps

### 1. Create the Sentry organization & project

If you don't already have a Sentry org for RAF Intelligence:

1. Go to <https://sentry.io/signup/> and create an account (use the Kriya / RAF email).
2. Create an organization named `raf-intelligence`.

Then create two projects (one per runtime — Sentry's separation of client/server stacks):

| Project name | Platform | Why |
|---|---|---|
| `raf-frontend` | Next.js | Captures browser-side errors (React render, client API calls). |
| `raf-backend` | Python (FastAPI) | Captures server-side exceptions, OTel-traced spans, slow endpoints. |

For each project click **Create Project** → pick the platform → name it → **Create Project**. You can skip the install wizard (SDK already installed in code).

Expected: both projects appear in the org's Projects list.

### 2. Copy the two DSNs

On each project's settings page (`Settings → Projects → <project> → Client Keys (DSN)`):

- Copy the DSN for `raf-frontend` — looks like `https://abc123@o4500000.ingest.sentry.io/4500001`
- Copy the DSN for `raf-backend` — same format, different project id

**Save both** in your password manager — you will paste them into prod `.env` next.

### 3. Configure alert rules in Sentry

For each project: **Alerts → Create Alert Rule**.

Minimum production rules to create:

| Rule | Condition | Action |
|---|---|---|
| Any unhandled error in prod | `event.level >= error AND environment = production` | Email Kriya + post to Slack channel `#raf-alerts` |
| Performance regression | `transaction.duration p95 > 2s for 5 min` | Email Kriya |
| New issue (first occurrence) | `is:new` | Email Kriya |

Expected: three rules appear under the project's Alerts tab.

### 4. Add both DSNs to prod `.env`

SSH to prod:

```bash
ssh -i ~/.ssh/openvpn-key-v2.pem -J ubuntu@15.204.73.232:2222 ubuntu@10.1.0.204
```

Then on the prod host:

```bash
sudo cp /opt/raf-intelligence/.env /opt/raf-intelligence/.env.bak.$(date +%Y%m%d-%H%M%S)
sudoedit /opt/raf-intelligence/.env
```

Find or add these lines (replace the values with the DSNs from step 2):

```ini
# --- Sentry (added by runbook 05) ---
SENTRY_DSN=https://<backend-dsn-from-step-2>@o4500000.ingest.sentry.io/4500001
NEXT_PUBLIC_SENTRY_DSN=https://<frontend-dsn-from-step-2>@o4500000.ingest.sentry.io/4500002
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=
# Sample rates — start conservative; bump up if signal is weak
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.1
```

Save and exit. Verify the lines are present (the secrets are not printed — only the var names):

```bash
sudo grep -E '^(NEXT_PUBLIC_)?SENTRY_' /opt/raf-intelligence/.env | sed 's|=.*|=<redacted>|'
```

Expected:

```
SENTRY_DSN=<redacted>
NEXT_PUBLIC_SENTRY_DSN=<redacted>
SENTRY_ENVIRONMENT=<redacted>
SENTRY_RELEASE=<redacted>
SENTRY_TRACES_SAMPLE_RATE=<redacted>
SENTRY_PROFILES_SAMPLE_RATE=<redacted>
```

### 5. Restart the services so the new env is read

Still on prod:

```bash
cd /opt/raf-intelligence
sudo docker compose restart backend frontend
sudo docker compose ps backend frontend
```

Expected: both rows show `Up <N> seconds (healthy)`.

### 6. Pin the release (optional but recommended)

Sentry groups errors by release. To get release-aware grouping, set `SENTRY_RELEASE` to the current git SHA on every deploy. For this one-time setup:

```bash
SHA="$(cd /opt/raf-intelligence && git rev-parse --short HEAD)"
sudo sed -i.bak "s|^SENTRY_RELEASE=.*|SENTRY_RELEASE=${SHA}|" /opt/raf-intelligence/.env
cd /opt/raf-intelligence && sudo docker compose restart backend frontend
```

Then add `SENTRY_RELEASE="$(git rev-parse --short HEAD)"` to `deploy/zero-downtime-deploy.sh` in a follow-up commit so future deploys auto-tag.

---

## Verification

### A. Sentry is receiving backend events

Trigger a synthetic backend error. From your laptop:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://raf.comercioit.com/api/_debug/sentry-test
```

Expected: `500` (the endpoint deliberately raises). Within ~30s a new event appears under **raf-backend → Issues** in Sentry.

> If `/api/_debug/sentry-test` does not exist in this branch, hit any endpoint that's known to raise on bad input, e.g. `curl -s -X POST https://raf.comercioit.com/api/auth/login -H 'Content-Type: application/json' -d 'not-json'`.

### B. Sentry is receiving frontend events

In your browser DevTools console on <https://raf.comercioit.com>:

```js
throw new Error("sentry-smoke-test-" + Date.now());
```

Expected: within ~30s a new event appears under **raf-frontend → Issues** with the matching message.

### C. Alert rule fires

Within ~1 min of step A, you should receive an email and (if configured) a Slack ping for the new issue.

### D. Source maps upload (frontend only — verify in CI)

Source maps must be uploaded at build time for Sentry stack traces to be readable. Check `frontend/next.config.ts` or `frontend/sentry.client.config.ts` — if `sentry-cli` upload is not wired into the CI build, file a follow-up. For now, raw minified traces are acceptable for the first-customer ship.

---

## Rollback

If Sentry traffic causes problems (rare — but possible if sample rate is too high or DSN points to a wrong project):

1. SSH to prod and restore the backed-up `.env`:

   ```bash
   sudo cp /opt/raf-intelligence/.env.bak.<timestamp> /opt/raf-intelligence/.env
   cd /opt/raf-intelligence && sudo docker compose restart backend frontend
   ```

2. The SDK gracefully no-ops when DSN is unset, so the app continues running.
3. Investigate the issue (wrong DSN? sample rate too high? Sentry quota exhausted?) before re-enabling.

---

## Sign-off

- [ ] Both DSNs saved in password manager.
- [ ] Both DSNs in prod `/opt/raf-intelligence/.env`.
- [ ] Backend test event visible in Sentry **raf-backend** (Verification A).
- [ ] Frontend test event visible in Sentry **raf-frontend** (Verification B).
- [ ] At least one alert rule on each project (Step 3).
- [ ] `SENTRY_ENVIRONMENT=production` confirmed in prod env.
- [ ] Backup of pre-change `.env` retained for 7 days.

When all six are checked, observability dimension moves from 9/10 → 10/10 and the readiness checklist is closed.
