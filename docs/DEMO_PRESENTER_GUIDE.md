# RAF Intelligence — Demo Presenter Guide

A 5–7 minute live demo that lands the story for three buyer personas at once: the **provider** who has to chart, the **CMO/audit lead** who has to defend RADV, and the **CFO** who has to forecast revenue.

The Playwright script at `frontend/tests/demo/demo-flow.spec.ts` automates the navigation and captures a storyboard you can paste into a deck. The narration below is what to **say** while the script runs.

---

## Pre-flight (5 minutes before joining the call)

For a one-page cheat sheet with exact commands and expected output for every step, see `docs/DEMO_QUICKSTART.md`.

```bash
# 1. Bring the stack up
docker compose -f docker-compose.local.yml up -d

# 2. Apply schema migrations (idempotent — re-runs are safe)
docker cp database/migrations raf-backend:/tmp/migrations
docker exec -e MIGRATIONS_DIR=/tmp/migrations raf-backend python /app/scripts/apply_migrations.py

# 3. Seed the demo panel — 12 synthetic patients, 16 gaps, 15 suspects, RAF scores
#    This also marks the EMR connection as active so /api/emr/status returns connected=true.
#    Do NOT use POST /api/emr/demo-connect or the "Connect Demo EMR" button on /emr-config —
#    that endpoint requires a live OpenEMR instance and will 500 on a local stack without one.
docker exec -e APP_ENV=demo raf-backend python /app/scripts/seed_demo_panel.py

# 4. Seed IRR labels (Cohen's kappa tile in Scene 4)
docker exec -e APP_ENV=demo raf-backend python /app/scripts/seed_irr_demo.py

# 5. Enable demo feature flags (KG panel, velocity strip, CFO forecast, peer percentile)
docker exec -e APP_ENV=demo raf-backend python /app/scripts/enable_demo_flags.py

# 6. Verify auth and data
curl -sS -X POST http://localhost:8500/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@raf.health","password":"Admin@123"}' \
  | grep -q access_token && echo "auth=OK"

# 7. Open http://localhost:3444/login in a fresh browser tab
#    Login: admin@raf.health / Admin@123
#    Expected: /worklist with 12 patient cards and non-zero stats strip
```

**Common pre-flight gotchas**:
- If `/api/auth/me` returns 401 immediately after login: check
  `users.tenant_id IS NOT NULL` for the admin row.  Migration 005 sets
  it but a hand-applied schema may have left it NULL.
- If `/api/auth/refresh` returns 500: re-run Step 2 (migrations).
- If pages spin forever after login: both the refresh-hash migration
  and the sessions migration need to be applied — re-run Step 2.
- If admin login is locked from prior failed attempts: clear it with
  `UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE
   email='admin@raf.health';`
- If the worklist is empty despite a successful seed: re-run Step 3.
  The seed is fully idempotent and re-running it is safe.

---

## The 7-scene flow

Total runtime: **~6 minutes** at conversational pace. Each scene is 30–60 seconds.

### Scene 1 — "Monday morning" (60s) — `/worklist`

**What you click**: Login → land on `/worklist` (or click *Today's worklist* in sidebar).

**What you say**:

> "A primary-care provider walks in Monday morning. They don't open a generic dashboard — they need to know which patients to see this week and why. RAF Intelligence opens directly to *Today's worklist*: every patient on the panel ranked by priority score, with their open gaps, suspect conditions, and revenue at risk in one card."

**Why this matters**: Every competitor lands a provider on a generic stat dashboard. We land them on *the action they came to take*.

**Visual proof point**: Top-right *Patients to see / Open gaps / Revenue at risk* tile strip.

---

### Scene 2 — "Why this HCC?" (60s) — `/recapture`, hover an HCC chip

**What you click**: Sidebar → *Recapture Gaps* → hover any HCC chip in the gap table.

**What you say**:

> "This is the moment that separates us from Navina and Apixio. They give you a black-box 'this patient has HCC 19' suggestion. We give you the **evidence chain**: hover the HCC chip and you see ICD-10 → SNOMED CT → HCC mapping with the actual peer-reviewed citations the rule was derived from. When a RADV auditor asks 'why did you code this?' you answer with citations, not with 'the model said so.'"

**Why this matters**: Buyer's #1 fear is "I'll get audited and not be able to justify the codes." KG explainability is the single largest differentiator.

**Visual proof point**: Hover popover with traceback + citation list.

---

### Scene 3 — "Calibrated confidence" (45s) — `/suspects`

**What you click**: Sidebar → *Suspects* → point at a suspect card with a `confidence` chip.

**What you say**:

> "Every confidence number on this page is Platt-calibrated. The raw model outputs had an Expected Calibration Error of 0.22 — meaning when the model said 78%, the real-world rate was closer to 56%. We fit Platt scaling on a held-out set and the calibrated ECE drops to 0.03. When you see 78% here, it means 78%. Most coding tools don't bother with calibration — they just expose raw logits."

**Why this matters**: Calibrated probabilities are what makes the workflow **safe** — coders can confidently filter by confidence threshold.

**Visual proof point**: Small purple "calibrated" chip below confidence bar when raw differs from calibrated.

---

### Scene 4 — "Audit defense: dual-coder MEAT + Cohen's kappa" (60s) — `/recapture`, scroll to RADV section

**What you click**: Stay on `/recapture` → scroll to *RADV Audit Defense* section.

**What you say**:

> "Audit-readiness gauge tells you what % of gaps are dual-signed and RADV-defensible. The new tile below shows **inter-rater reliability** — Cohen's kappa = 0.52, in the *moderate* band per Landis & Koch. Most competitors report 'agreement %' which is naïve when one rater dominates; we report kappa with chance-correction. One-click PDF export gives you the audit-ready bundle with timestamps, actor IDs, and MEAT phrases per gap."

**Why this matters**: RADV failures cost MA plans tens of millions. Defensibility is the procurement check.

**Visual proof point**: Audit-readiness gauge + IRR pill ("0.52 · moderate").

---

### Scene 5 — "Velocity & decay" (45s) — `/recapture`, velocity strip

**What you click**: Scroll up to *Recapture velocity & decay*.

**What you say**:

> "Operations question: are we closing gaps fast enough to hit year-end? The velocity strip shows YTD recaptured, projected-vs-budget, and average days-to-close. The decay curve below shows the cumulative-closure-rate by month — most teams discover in November that they're behind schedule. We surface that gap in February so they can intervene before the cliff."

**Why this matters**: This is the operational lever — gives the COO the pacing dashboard they currently build in Excel.

**Visual proof point**: Sparkline + Projected $ tile with delta vs budget.

---

### Scene 6 — "CFO executive summary" (45s) — `/recapture`, scroll to CFO section

**What you click**: Scroll down to *CFO executive summary*.

**What you say**:

> "Same data, CFO lens. Quarterly $ projection, top conditions by revenue contribution, top providers. The amber **PROJECTED** badge tells you at a glance what's actual vs forecast — the single most-asked CFO question. Year-over-year tab compares against last cycle's recapture velocity."

**Why this matters**: Sells to the financial buyer — they're the one signing the contract.

**Visual proof point**: Amber "PROJECTED" caps badge on hero band.

---

### Scene 7 — "Mobile / iPad" (30s) — `/worklist` at narrow viewport

**What you do**: Hit Cmd+Opt+I → Toggle Device Toolbar → iPad / iPhone preset, then navigate back to `/worklist`.

**What you say**:

> "Every page is mobile-first. Same worklist, same patient cards, but the layout collapses to a single column on phone, two on tablet. Providers chart at the bedside, not in front of a laptop. The KG popovers and audit defense work identically."

**Why this matters**: Doctors work on iPads. If your tool only works on a 27-inch monitor, you've lost.

**Visual proof point**: Single-column worklist on the iPhone preset.

---

## Closing line (15s)

> "What you've seen: KG explainability, Platt-calibrated confidence, Cohen's-kappa IRR, and a mobile-first worklist — built on top of the standard MEAT-audit / RADV-PDF workflow your team already does. The differentiator isn't any one feature; it's that everything is **traceable**. Every code, every confidence, every audit decision."

---

## Q&A grenades you should expect

| Question | Honest answer |
|---|---|
| "What's your real-world accuracy?" | "Synthetic benchmark: 84.8% precision / 100% recall on N=52 charts; ECE 0.03 calibrated. Real-chart benchmark on N≥1000 is the next milestone before procurement." |
| "Are you HIPAA compliant?" | "PHI sanitisation covers all 18 Safe Harbor identifiers before any LLM call; Vertex AI BAA in place; audit log retention configured at 6 years (HIPAA minimum). SOC2 Type 1 in scope for next quarter." |
| "How does this scale?" | "Backend is FastAPI + MySQL + Celery. Local benchmark on 6 providers / 16 gaps shows scorecard at 16ms median. Production load test on 50K-member panel pending." |
| "Why not just use OpenAI / Gemini directly?" | "Ungrounded LLMs hallucinate at 5–10%. Our KG layer constrains the model to walk the actual ICD-SNOMED-HCC ontology — every suggestion is traceable to a real concept node. That's why we can show citations." |
| "What about Navina?" | "Navina has the polished UX. We have parity on UX now (since the production-readiness pass) plus the KG explainability + calibration + Cohen's kappa they don't ship." |

---

## Running the automated demo

```bash
cd frontend

# Headed (browser visible — what you'll show on the call)
BASE_URL=http://localhost:3444 \
  DEMO_EMAIL=admin@raf.health \
  DEMO_PASSWORD='Admin@123' \
  npx playwright test tests/demo/demo-flow.spec.ts \
    --project=chromium --headed --workers=1

# Headless + record video for an asynchronous-share version
BASE_URL=http://localhost:3444 \
  DEMO_EMAIL=admin@raf.health \
  DEMO_PASSWORD='Admin@123' \
  npx playwright test tests/demo/demo-flow.spec.ts \
    --project=chromium --workers=1 --video=on

# Output:
#   frontend/playwright-report/demo-shots/01-worklist.png
#   frontend/playwright-report/demo-shots/02a-recapture-overview.png
#   frontend/playwright-report/demo-shots/02b-hcc-popover.png
#   frontend/playwright-report/demo-shots/03-suspects-calibrated.png
#   frontend/playwright-report/demo-shots/04-audit-readiness.png
#   frontend/playwright-report/demo-shots/05-velocity-decay.png
#   frontend/playwright-report/demo-shots/06-cfo-summary.png
#   frontend/playwright-report/demo-shots/07a-worklist-mobile.png
#   frontend/playwright-report/demo-shots/07b-worklist-tablet.png
```

Drop the screenshots into a Keynote / Google Slides storyboard before the call so you have a fallback if the live demo glitches mid-pitch.

---

## What NOT to demo (yet)

- `/system`, `/developer`, `/users` — admin pages; not the buyer's job to care
- `/raf-calculate`, `/crosswalk` — analyst tools; show only if asked specifically
- `/uploads`, `/emr-config` — onboarding flow; show in the *follow-up* call once they're sold on the value
- `/audit`, `/quality`, `/submissions` — compliance ops; show in the *technical deep-dive* call

The **first** call is about **value**, not breadth. 7 scenes is enough.

---

## What's still imperfect (be honest)

Volunteer these caveats before the buyer finds them. Honesty builds more trust than a polished dodge.

| Area | What to say |
|---|---|
| **Worklist empty state** | If the seed steps were skipped, `/worklist` shows an "AI-Powered Risk Adjustment" onboarding banner with no patient cards. This is intentional empty-state behavior, not a bug — but it kills the demo story. Always run the pre-flight seed before the call. If the worklist is empty during the demo: "I need to run one setup step — give me 60 seconds." Re-run `docker exec -e APP_ENV=demo raf-backend python /app/scripts/seed_demo_panel.py` and hard-refresh. |
| **Cohen's kappa N=20** | The IRR tile on `/recapture` shows kappa = 0.52 ("moderate") on a 20-gap labeled set. If a buyer asks "what's this based on?" say: "This is our demo synthetic set of 20 dual-coded gaps — a realistic distribution but not production volume. In a live tenant the kappa computes over all dual-coded gaps in the measurement year, so accuracy improves with volume." Do not claim the 0.52 is a real-world benchmark. |
| **Synthetic data benchmark** | The 84.8% precision / 100% recall benchmark in Q&A is from N=52 synthetic charts, not live clinical records. Lead with this, not hide it: "Our benchmark on 52 synthetic charts is 84.8%. We are building the real-chart benchmark on N≥1000 clinical records — that is the number we'll stand behind for procurement." The calibration story (ECE 0.03) is robust and worth leading with. |
| **Scenes 4–6 onboarding capture** | The velocity strip (Scene 5) and CFO summary (Scene 6) depend on recapture-decay and CFO forecast endpoints. If these return empty rows (the feature flags were not enabled in Step 5 of pre-flight), Scenes 5 and 6 show empty charts. Recovery: run `docker exec -e APP_ENV=demo raf-backend python /app/scripts/enable_demo_flags.py` and hard-refresh. |
| **No SOC2 yet** | SOC2 Type 1 is in scope for next quarter. Do not say "we are SOC2 compliant." Say "we have the controls in place and the audit is scheduled — we are not yet certified." |
