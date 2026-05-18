# Use the `/api/suspects` API end-to-end

> Audience: Developer / Integrator  •  Time: 8 min

This tutorial drives the full suspect lifecycle from a terminal: list, scan, accept,
dismiss, force-accept, reverse — the same operations a coder does in the UI, scripted.

## Prerequisites

- Tutorial 14 done. You have an access token in `$ACCESS`.
- The four seeded demo patients (IDs 3, 7, 8, 22).

```bash
BASE=http://localhost:8500
H="Authorization: Bearer $ACCESS"
```

## Step 1 — List a patient's suspects

```bash
curl -s "$BASE/api/suspects/3" -H "$H" | jq '.suspects[] | {id, hcc_code, status, confidence}'
```

Expected output: an array of suspect objects, one per open / accepted / dismissed
condition. Each has:

```json
{
  "id": "sp_01HMV3...",
  "hcc_code": "HCC18",
  "icd10": "E11.22",
  "status": "open",
  "confidence": 0.87,
  "meat": {"monitor": "green", "evaluate": "amber", "assess": "green", "treat": "green"},
  "dollar_impact_usd": 1247.55,
  "evidence_count": 7
}
```

## Step 2 — Trigger a fresh scan

If the engine hasn't run lately, force it:

```bash
curl -s -X POST "$BASE/api/suspects/scan/3" -H "$H" | jq
```

Expected output: `{"patient_id": 3, "scanned_at": "...", "new_count": 0, "updated_count": 4}`.
The scan is idempotent; re-running it never duplicates suspects.

## Step 3 — Filter by status / confidence

The patient-scoped endpoint supports query parameters:

```bash
curl -s "$BASE/api/suspects/3?status=open&min_confidence=0.80" -H "$H" \
  | jq '.suspects | length'
```

For cross-patient queries pull from `/api/worklist`:

```bash
curl -s "$BASE/api/worklist?status=queued&limit=50" -H "$H" \
  | jq '.items[] | {patient_id, suspect_hcc_code, confidence}'
```

## Step 4 — Accept a suspect

Pick any `open` suspect ID from Step 1, then:

```bash
SID=sp_01HMV3XXXXXXXX

curl -s -X PUT "$BASE/api/suspects/$SID/accept" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"comment": "Verified via API smoke test"}' | jq
```

Expected output:

```json
{
  "ok": true,
  "suspect_id": "sp_01HMV3...",
  "status": "accepted",
  "event_id": "evt_01HMV3..."
}
```

The `event_id` is the audit event you'll reference if you reverse later.

## Step 5 — Force accept

For low-MEAT suspects, pass `force: true` with a reason:

```bash
curl -s -X PUT "$BASE/api/suspects/$SID/accept" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"force": true, "reason": "Active medication and care plan documented"}' | jq
```

`reason` is **required** when `force=true`. Empty reasons return 422.

## Step 6 — Dismiss a suspect

```bash
curl -s -X PUT "$BASE/api/suspects/$SID/dismiss" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"reason": "Rule-out only, not active"}' | jq
```

Returns `{"ok": true, "status": "dismissed", "event_id": "..."}`.

## Step 7 — Reverse an accept

Pass `reverse_of` set to the original `event_id`. To roll back any FHIR writeback,
also pass `reverse_writeback: true`:

```bash
ACCEPT_EVT=evt_01HMV3...

curl -s -X PUT "$BASE/api/suspects/$SID/dismiss" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"reason\": \"Provider correction\",
       \"reverse_of\": \"$ACCEPT_EVT\",
       \"reverse_writeback\": true}" | jq
```

The audit log now has a `suspect.reverse_accept` event linked to the original.

## Step 8 — Bulk operations

For batches, use `POST /api/suspects/bulk-update`:

```bash
curl -s -X POST "$BASE/api/suspects/bulk-update" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{
        "operations": [
          {"suspect_id": "sp_a", "action": "accept", "comment": "via API"},
          {"suspect_id": "sp_b", "action": "dismiss", "reason": "duplicate"}
        ]
      }' | jq
```

The response includes per-row results so you can retry partial failures.

## Step 9 — Pagination & rate limits

The patient endpoint returns all suspects (one patient = bounded set). The worklist
endpoint paginates with `limit` (max 200) and `cursor`. Look for the `next_cursor`
field in responses.

Rate limits per token:

- Read endpoints — 600 req/min.
- Write endpoints — 60 req/min.
- Bulk update — 6 req/min (each request can contain up to 500 operations).

429 responses include `Retry-After`; respect it.

## Step 10 — Audit your API calls

Every write is captured. Pull the recent audit events for your service account:

```bash
curl -s "$BASE/api/audit/events?user_id=me&limit=10" -H "$H" | jq '.events[] | .action'
```

## Common pitfalls

- **Missing Content-Type** — POST/PUT without `Content-Type: application/json` is
  rejected with 415.
- **Stale token** — refresh proactively (Tutorial 14) instead of waiting for 401.
- **Reversal without `reverse_of`** — works as a plain dismiss, but the audit chain
  isn't linked. Always include it.

## Troubleshooting

- **403 `scope_missing`** — your token lacks `suspects:write`; mint a new one.
- **409 `already_accepted`** — race; refetch and check `status`.
- **422 with `validation_error`** — read the `errors` array; usually a missing
  required field.

## Next step

The last developer tutorial covers the other direction — receiving events from
external systems:

[Tutorial 16 — Receive webhooks (FHIR / Twilio / SendGrid)](16-dev-webhooks.md)
