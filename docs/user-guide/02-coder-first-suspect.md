# Accept your first HCC suspect

> Audience: Coder  •  Time: 8 min

You will find an open AI-surfaced HCC suspect on patient 3, review the supporting
evidence, and accept it. Acceptance creates a prospective coding line item and (if
writeback is enabled for your tenant) queues an FHIR `Condition` for the source EHR.

## Prerequisites

- Tutorial 1 completed (you can navigate the sidebar).
- Demo seed loaded — patient 3 must have at least one open suspect. Verify:

```bash
curl -s "http://localhost:8500/api/suspects/3" \
  -H "Authorization: Bearer $TOKEN" | jq '.suspects | length'
# Expected output: an integer >= 1
```

## Step 1 — Open patient 3

Navigate to `/patients/3` from the Patients page or paste the URL. Click the
**Suspects** tab. You see a card per suspect with:

- A condition title (e.g. "Diabetes with chronic kidney disease, stage 3").
- The mapped HCC code and RAF weight.
- A confidence score and the rule(s) that fired (claims, labs, meds, NLP).
- The dollar impact at your contract's RAF-per-point rate.

## Step 2 — Read the evidence

Click **Show evidence** on the first card. The drawer that opens lists every supporting
fact the engine used: ICD codes from claims, LOINC results, prescriptions, and NLP
snippets from progress notes. Each row links to the source document.

Stop and ask yourself the four MEAT questions:

- **Monitor** — is the condition being tracked (labs, repeat visits)?
- **Evaluate** — is there a current assessment in a recent note?
- **Assess** — is there an active care plan?
- **Treat** — is there a medication, referral, or procedure?

You need at least two of MEAT for a safe accept. The drawer color-codes which of the
four are satisfied. If three or more are green, this is a clean acceptance.

## Step 3 — Accept

Click the green **Accept** button on the card. A modal asks for an optional comment
("Verified A1C 9.2 on 2025-03-11"). Press **Confirm**.

Under the hood the UI calls:

```bash
curl -s -X PUT "http://localhost:8500/api/suspects/{suspect_id}/accept" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment":"Verified A1C 9.2 on 2025-03-11"}'
```

**Expected outcome:** the card flips from blue (open) to green (accepted), the dollar
impact moves into the patient's accepted RAF total at the top of the page, and an entry
appears in the **Activity** tab: `accepted_by_user`.

## Step 4 — Verify writeback (optional)

If your tenant has FHIR writeback enabled, a background job posts a `Condition`
resource to the source EHR within a minute. Check status:

```bash
curl -s "http://localhost:8500/api/fhir/writeback/status?patient_id=3" \
  -H "Authorization: Bearer $TOKEN" | jq '.recent[0]'
```

You should see `status: "queued"` then later `status: "succeeded"` with the remote
`resource_id`.

## Step 5 — Find it in your accepted list

Click the **Activity** tab in the patient header, or return to `/worklist` and switch
the status filter from **Open** to **Accepted**. Your new acceptance shows your name
and the timestamp.

## Common pitfalls

- **"Insufficient MEAT" warning** — the engine detected only 0 or 1 MEAT axes. Force
  accepts are allowed but logged; do them only with a documented reason. Tutorial 3
  covers force-accept.
- **Accept button greyed out** — the suspect is already accepted, dismissed, or locked
  for QA review.
- **422 on the API** — you sent an empty body. Pass at least `{}`.

## Troubleshooting

- **No suspects on patient 3** — run the scanner once:
  `curl -X POST "$BASE/api/suspects/scan/3" -H "Authorization: Bearer $TOKEN"`.
- **Accept succeeded but no Activity entry** — refresh the page. The event stream is
  WebSocket-backed; if your browser blocked it, the UI falls back to polling every 15 s.

## Next step

You accepted a clean suspect. Now learn what to do when the MEAT evidence is thin:

[Tutorial 3 — Review MEAT evidence and force-accept](03-coder-review-meat.md)
