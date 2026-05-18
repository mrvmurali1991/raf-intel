# Run your morning huddle on `/md/today`

> Audience: Physician / MD  •  Time: 8 min

This tutorial walks a physician through the daily pre-visit huddle. By the end you
will have triaged today's schedule, reviewed AI-surfaced suspects per patient, and
swipe-accepted the ones you're ready to address in clinic.

## Prerequisites

- An MD-role account. (Demo: use `admin@raf.health` which has all roles.)
- A populated `/md/today` schedule. The demo seed pre-loads today's visits for the
  four sample patients (IDs 3, 7, 8, 22).

## Step 1 — Open `/md/today`

Sign in and navigate to `/md/today`. You land on a kanban-style view with three
columns:

- **Pre-huddle** — patients arriving today, with one card each.
- **In huddle** — the card you're currently reviewing.
- **Ready** — patients you've signed off on.

Each card surfaces: visit time, chief complaint (if available), accepted RAF, and the
count of **open suspects** worth reviewing.

## Step 2 — Pre-visit briefing

Click the first card. The right rail opens a pre-visit briefing pulled from
`GET /api/previsit/{patient_id}`. It summarizes:

- Open and closed care gaps.
- Top three AI-surfaced suspects with one-line rationale.
- Medications added since last visit.
- Lab and vital trends with a small spark.

Take 30–60 seconds to scan. This is your "what changed since last visit" digest.

## Step 3 — Swipe accept

For each suspect in the briefing you have three big buttons:

- **Accept** (green) — confirms the condition and creates a coding line.
- **Address in visit** (amber) — sends it to your visit-note pre-fill but does **not**
  finalize until you sign the note.
- **Decline** (red) — dismisses with a single-tap reason chip (e.g., "rule-out only",
  "resolved").

Tap **Accept** on one suspect. The card animates out and the next slides in. The
swipe is bound to the same backend call coders use:

```bash
curl -s -X PUT "http://localhost:8500/api/suspects/{suspect_id}/accept" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"md_huddle"}'
```

The `source: "md_huddle"` tag is what later distinguishes physician-driven accepts
from coder-driven ones in analytics.

**Expected outcome:** the suspect count on the card decreases by one; if you cleared
the last suspect, the card moves to the **Ready** column.

## Step 4 — Move the patient to Ready

When you've reviewed every suspect for a patient, the **Mark ready** button activates
at the bottom of the rail. Click it. The card moves to **Ready**, locking your
acceptances. The next patient in **Pre-huddle** auto-promotes.

## Step 5 — Cohort speedrun

To work through the whole morning at once, press the **Speedrun** chip at the top.
This shows one suspect at a time across all your scheduled patients, sorted by
confidence × dollar impact. You can clear 20 patients in roughly 10 minutes once you
get rhythm.

## Step 6 — Finish the huddle

When the **Pre-huddle** column is empty, the page banner switches to "Huddle complete".
A summary modal shows how many suspects you accepted, addressed, or declined. Hit
**Send to team** to email the summary to your MA and coder for the day.

## Common pitfalls

- **Accepting in haste** — the huddle is a triage, not a final coding decision. Use
  **Address in visit** when you're not 100% sure; you'll confirm during the encounter.
- **Forgetting to sign** — accepts here are *unsigned* until you sign the visit note
  with MEAT attestation (Tutorial 7). The acceptance is recorded, but `meat_signed`
  remains `false` until you sign.
- **Swiping the wrong direction** — the colors are deliberate (green right, red left).
  Tap, don't swipe, if you're unsure.

## Troubleshooting

- **Empty schedule** — check that today's date matches the demo seed. The seed seeds
  today's visits; you may need to re-run `make seed-today` if your demo is older.
- **No briefing for a patient** — the previsit endpoint failed; refresh, or open the
  patient page directly and review suspects from there.
- **Stuck on "loading"** — the activity stream WebSocket is blocked. Disable browser
  extensions or whitelist `/api/realtime`.

## Next step

Acceptance during huddle is provisional. To make it final and audit-clean, attach a
MEAT-signed attestation:

[Tutorial 7 — Sign a MEAT attestation (`meat_signed=true`)](07-md-signed-attestation.md)
