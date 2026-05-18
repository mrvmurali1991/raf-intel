# Reverse an accepted suspect (and its writeback)

> Audience: Coder  •  Time: 7 min

Even careful coders accept the wrong suspect occasionally — a chart you didn't see, a
provider correction, an ICD that's actually a rule-out. This tutorial walks through a
**safe reversal**: dismissing the suspect, reversing the FHIR writeback if it already
posted, and proving the chain in the audit log.

## Prerequisites

- Tutorial 2 completed; you have at least one accepted suspect in the last 24 hours.
- You can read your audit events (admin or coder_senior role).

## Step 1 — Find the acceptance

Open `/worklist`, switch the status filter to **Accepted**, sort by **Recent**.
Click the row. You can also pull it from the API:

```bash
curl -s "http://localhost:8500/api/suspects/3" \
  -H "Authorization: Bearer $TOKEN" | jq '.suspects[] | select(.status=="accepted")'
```

Note the `suspect_id` and the `accept_event_id` shown in the row's detail panel — you
need both for a clean reversal.

## Step 2 — Reverse from the UI

In the suspect detail drawer click the overflow menu (**...**) and choose **Reverse
accept**. A modal asks two things:

1. **Reason** (required, free text).
2. **Also reverse FHIR writeback?** (checkbox, default on).

Type the reason ("Provider correction — condition was rule-out, not active") and leave
the checkbox on. Press **Confirm**.

The UI calls the dismiss endpoint with a `reverse_of` link:

```bash
curl -s -X PUT "http://localhost:8500/api/suspects/{suspect_id}/dismiss" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "reason": "Provider correction — condition was rule-out",
        "reverse_of": "{accept_event_id}",
        "reverse_writeback": true
      }'
```

**Expected outcome:** the suspect card flips back to grey (open), the dollar impact is
removed from the patient's accepted RAF total, and a new event of type
`suspect.reverse_accept` is appended.

## Step 3 — Watch the writeback rollback

If the FHIR writeback already succeeded, the platform now issues a `Condition` update
to the source EHR setting `clinicalStatus.coding[0].code = "inactive"` (per the
US Core profile). Watch its status:

```bash
curl -s "http://localhost:8500/api/fhir/writeback/status?patient_id=3" \
  -H "Authorization: Bearer $TOKEN" | jq '.recent[] | select(.kind=="reverse")'
```

You should see `status: "queued"` then `status: "succeeded"` within a minute. If the
remote EHR is offline, the row stays in `pending` and the platform retries with
exponential backoff — that's covered by the FHIR circuit breaker (see Developer
tutorial 16 if you're curious about the mechanism).

## Step 4 — Verify the audit chain

Every reverse links to its original. Pull the chain:

```bash
curl -s "http://localhost:8500/api/audit/events?suspect_id={suspect_id}" \
  -H "Authorization: Bearer $TOKEN" | jq '.events[] | {action, reverse_of, ts}'
```

You should see two rows: the original `suspect.accept` and the new
`suspect.reverse_accept` with `reverse_of` set to the first row's event ID. This pair
is what an external RADV auditor expects to see — both events are RFC-3161 timestamped
and cryptographically linked.

## Step 5 — Tell your team

Reversals create a small ripple: the supervisor receives a notification, the analytics
dashboard adjusts the coder accuracy metric, and the provider gets a (configurable)
inbox message. None of this is silent.

## Common pitfalls

- **Forgetting to reverse the writeback** — you reversed locally but the remote EHR
  still has the condition active. Always leave the checkbox on unless the writeback
  never ran.
- **Trying to reverse twice** — once reversed, the suspect is open again; you can
  re-accept it later, but you cannot reverse the reverse. Re-accept then reverse again
  if needed.
- **No `reverse_of` ID** — the API will accept a plain dismiss, but it won't link the
  audit chain. Always reverse from the UI or include `reverse_of`.

## Troubleshooting

- **"409 Conflict"** — someone else already reversed it. Refresh.
- **FHIR rollback stuck in `pending`** — open `/admin/integrations` and check the FHIR
  circuit. Tutorial 16 describes the breaker states.
- **Reversal denied with 403** — only the original accepter or a `coder_senior` can
  reverse within the first 24 hours; after that an admin must do it.

## Next step

You can now triage, accept, force-accept, and reverse. The last coder tutorial doubles
your speed:

[Tutorial 5 — Keyboard shortcuts: A / D / R + g-prefix nav](05-coder-keyboard-shortcuts.md)
