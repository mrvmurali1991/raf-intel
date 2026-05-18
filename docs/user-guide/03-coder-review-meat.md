# Review MEAT evidence and force-accept

> Audience: Coder  •  Time: 8 min

In this tutorial you handle the harder case: a suspect that looks real but fails the
automated MEAT check. You will read the evidence drawer, use the **Force accept**
option with a reason, and verify the action is captured in the audit trail.

## Prerequisites

- Tutorial 2 completed.
- A suspect on any patient with `meat_status` of `partial` or `insufficient`. Patient 7
  in the demo seed has at least one.

## Step 1 — Understand MEAT colors

Open `/patients/7` and switch to the **Suspects** tab. Each suspect card shows four
small dots in the top right — Monitor, Evaluate, Assess, Treat. Color meaning:

- **Green** — evidence found.
- **Amber** — partial evidence (e.g., a lab exists but is older than 12 months).
- **Grey** — no evidence found.

The card-level **MEAT score** is the count of green axes, 0–4. The platform treats:

- 3–4 green → clean accept (Tutorial 2).
- 2 green → standard accept (warning shown).
- 0–1 green → **force accept only**, with a written reason.

## Step 2 — Open a partial-MEAT suspect

Find a card with 1–2 green dots. Click **Show evidence**. The drawer lists the rule
output for each MEAT axis:

```
Monitor   - A1C 8.4 on 2024-08-12 (>12 months old)        AMBER
Evaluate  - no recent progress note assessment            GREY
Assess    - "Plan: continue metformin 500mg BID"          GREEN
Treat     - metformin 500mg active                         GREEN
```

This is a real condition (the drug is active and a plan exists), but the lab is stale
and there is no formal assessment. The auto-engine refuses to accept without your
sign-off.

## Step 3 — Force accept with a reason

Press the dropdown next to **Accept** and choose **Force accept**. A modal opens with a
required **Reason** field. Type a real reason — examples:

- "Active medication and care plan present; lab refresh ordered today."
- "Per provider note 2025-04-01, condition remains active despite no recent labs."

Then press **Confirm**.

The UI calls the same endpoint as a regular accept, but with `force=true`:

```bash
curl -s -X PUT "http://localhost:8500/api/suspects/{suspect_id}/accept" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force": true, "reason": "Active medication and care plan present"}'
```

**Expected outcome:** the card turns green with a small **forced** badge. The dollar
impact applies the same as a normal accept.

## Step 4 — Read the audit entry

Every force accept is captured in the immutable audit log. Pull the most recent entries
for this patient:

```bash
curl -s "http://localhost:8500/api/audit/events?patient_id=7&limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq '.events[] | select(.action=="suspect.force_accept")'
```

You should see an event with your `user_id`, the suspect ID, the reason you typed, and
a `signature` field — that signature is RFC-3161 timestamped (see Tutorial 11 for SOC 2
review). Once written, the row cannot be edited; corrections require a *reverse* event
linked to the original.

## Step 5 — Find force accepts in QA

Auditors and supervisors filter the review queue by `forced=true`:

- In the UI: `/review-queue?filter=forced`.
- API: `GET /api/review?forced=true`.

If a QA reviewer disagrees they can re-route the item back to you with a comment.

## Common pitfalls

- **Reason field is required** — the modal will not submit without text. Don't write
  "see chart"; capture the clinical justification in one sentence.
- **Force accepting clean suspects** — the modal still works, but you'll get flagged in
  QA for unnecessary force usage.
- **PHI in the reason** — fine, the field is encrypted at rest, but keep it concise.

## Troubleshooting

- **"403 Forbidden" on force accept** — your role lacks `suspect.force_accept`. Ask
  your admin to assign the `coder_senior` role.
- **Card flips back to blue** — a concurrent QA action declined the accept. Check
  Activity for the reversal.

## Next step

Mistakes happen. The next tutorial shows how to cleanly reverse an accept that should
not have been made:

[Tutorial 4 — Reverse an accepted suspect (writeback)](04-coder-reverse-writeback.md)
