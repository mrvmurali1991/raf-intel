# Demo Quickstart — "I have 5 minutes before the call"

Read time: ~90 seconds. Commands are copy-paste ready.

---

## 5 minutes before the call

Run these in order. Expected output is shown after each command.

**Step 1 — Bring the stack up**

```bash
docker compose -f docker-compose.local.yml up -d
```

Expected: all containers reach `healthy` or `running`. Check with:

```bash
docker compose -f docker-compose.local.yml ps
```

You need `raf-backend` and `raf-frontend` to show `running`. MySQL may still be `starting` for another 10–15 s — that is fine; the backend retries.

---

**Step 2 — Apply migrations**

```bash
docker cp database/migrations raf-backend:/tmp/migrations
docker exec -e MIGRATIONS_DIR=/tmp/migrations raf-backend python /app/scripts/apply_migrations.py
```

Expected: a list of migration filenames ending with `All migrations applied.`

If you see `No pending migrations` — that is also fine; it means the DB is already current.

---

**Step 3 — Seed the demo panel** (patients, gaps, suspects, RAF scores)

```bash
docker exec -e APP_ENV=demo raf-backend python /app/scripts/seed_demo_panel.py
```

Expected last lines:

```
Demo panel seeded: 12 patients, <YEAR> measurement year, tenant_id=1
  → /api/emr/status         should now return connected=true
  → /api/dashboard/stats    should return total_patients=12
  → /worklist               should show prioritized cards
  → /recapture              should show ~16 open gaps
  → /suspects               should show ~15 calibrated suspects
```

---

**Step 4 — Seed IRR labels** (Cohen's kappa tile on the audit screen)

```bash
docker exec -e APP_ENV=demo raf-backend python /app/scripts/seed_irr_demo.py
```

Expected last line: `Hit GET /api/recapture/audit-readiness to see the live kappa.`

---

**Step 5 — Enable demo feature flags**

```bash
docker exec -e APP_ENV=demo raf-backend python /app/scripts/enable_demo_flags.py
```

Expected: a list of flag keys each showing `[OK]` and a final `All N demo flags are enabled for user_id=1.`

---

**Step 6 — Verify auth and data counts**

```bash
curl -sS -X POST http://localhost:8500/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@raf.health","password":"Admin@123"}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
tok = d.get('access_token','')
print('auth=OK' if tok else 'auth=FAIL — check output below', d)
"
```

Expected: `auth=OK`

---

**Step 7 — Open the browser**

```
http://localhost:3444/login
```

Login: `admin@raf.health` / `Admin@123`

You should land on `/worklist` with 12 patient cards and the stats strip showing non-zero patients, gaps, and revenue-at-risk numbers.

---

**If anything is wrong, see the "If a scene breaks live" section below.**

---

## What works in the demo today

| Page | What you see | Notes |
|---|---|---|
| `/worklist` | 12 synthetic patients, priority-ranked, with open gaps and suspects per card | Real UI, synthetic patients |
| `/recapture` | ~16 open HCC gaps, HCC chip hover popover with ICD-10 → SNOMED → HCC traceback | KG evidence panel requires `kg_evidence_panel` flag — Step 5 enables it |
| `/suspects` | ~15 NLP-flagged suspects with Platt-calibrated confidence chips | Raw vs calibrated confidence both visible |
| `/recapture` → RADV section | Audit-readiness gauge + Cohen's kappa pill ("0.52 · moderate") | Requires Step 4 IRR seed |
| `/recapture` → velocity strip | YTD recaptured, projected vs budget, days-to-close sparkline | Requires CFO forecast flag (Step 5) |
| `/recapture` → CFO summary | Quarterly $ projection, top conditions, amber PROJECTED badge | Same flag as velocity |
| `/worklist` at mobile viewport | Single-column layout on iPhone/iPad Device Toolbar preset | Cmd+Opt+I → Toggle Device Toolbar |

---

## What to skip

Do not navigate to these pages during the first call. They either show empty state or are not relevant to the value story.

| Page | Why to skip |
|---|---|
| `/emr-config` | Onboarding flow — shows setup wizard, not product value |
| `/uploads` | Onboarding flow — same reason |
| `/system`, `/developer`, `/users` | Admin-only — not the buyer's concern |
| `/raf-calculate`, `/crosswalk` | Analyst tools — show only if buyer asks explicitly |
| `/audit`, `/quality`, `/submissions` | Compliance ops — save for the technical deep-dive call |
| `/worklist` with zero data | If the seed steps above were skipped the worklist shows an "AI-Powered Risk Adjustment" onboarding banner — this is correct empty-state behavior, but it kills the demo story. Run Steps 3–5 first. |

---

## What to do if a scene breaks live

1. **Storyboard fallback** — Static annotated screenshots are at `frontend/playwright-report/demo-shots/`. Share your screen showing those images in Preview or a Keynote slide if the live UI hangs.

   | Scene | Fallback screenshot |
   |---|---|
   | 1 — Worklist | `01-worklist-annotated.png` |
   | 2 — HCC popover | `02b-hcc-popover.png` |
   | 3 — Suspects calibrated | `03-suspects-calibrated-annotated.png` |
   | 4 — Audit readiness | `04-audit-readiness-annotated.png` |
   | 5 — Velocity strip | `05-velocity-decay-annotated.png` |
   | 6 — CFO summary | `06-cfo-summary-annotated.png` |
   | 7 — Mobile | `07a-worklist-phone.png` |

2. **Auth loop (spinner after login)** — Apply the refresh-hash migration:
   ```bash
   docker exec -e MIGRATIONS_DIR=/tmp/migrations raf-backend python /app/scripts/apply_migrations.py
   ```

3. **Worklist empty after seed** — The admin user's provider record may be missing:
   ```bash
   docker exec -e APP_ENV=demo raf-backend python /app/scripts/seed_demo_panel.py
   ```
   Re-running is safe (idempotent). Then hard-refresh the browser.

4. **Login locked** — Prior failed attempts lock the account:
   ```bash
   docker exec raf-backend python -c "
   import sys; sys.path.insert(0,'/app')
   from app.db import raf_cursor
   with raf_cursor() as c:
       c.execute(\"UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health'\")
   print('unlocked')
   "
   ```

5. **Port conflict** — If `localhost:3444` or `localhost:8500` is already bound:
   ```bash
   docker compose -f docker-compose.local.yml down && docker compose -f docker-compose.local.yml up -d
   ```

---

## Q&A — the 5 questions buyers always ask

| Question | Honest answer |
|---|---|
| "What's your real-world accuracy?" | Synthetic benchmark on N=52 charts: 84.8% precision, 100% recall, ECE 0.03 (calibrated). Real-chart benchmark on N≥1000 clinical records is the next milestone before enterprise procurement. We volunteer this caveat — ungrounded benchmark claims are what got Olive and other AI-health vendors in trouble. |
| "Are you HIPAA compliant?" | PHI sanitisation covers all 18 Safe Harbor identifiers before any LLM call. Vertex AI BAA is in place. Audit log retention is configured at 6 years (HIPAA minimum). SOC2 Type 1 is in scope for next quarter. We are not yet SOC2 certified — we will tell you when we are. |
| "How does this compare to Navina?" | Navina has a polished UX and strong EMR integrations. We match the UX (mobile-first, same clinical workflow) and add three things Navina does not ship: KG explainability with citations, Platt-calibrated confidence (not raw logits), and Cohen's kappa IRR for RADV defensibility. |
| "How does this scale to our panel size?" | Local benchmark on 6 providers / 16 gaps: scorecard at 16ms median. We have not yet run a 50K-member production load test — that is scheduled before the first enterprise contract goes live. |
| "What about security?" | Backend is containerized (Docker), no PHI persisted in any LLM provider, Vertex AI BAA signed. TLS terminates at the load balancer in production. Security audit checklist is at `docs/SECURITY_AUDIT_CHECKLIST.md`. Pen test is not yet scheduled — we will tell you when it is. |
