# Sign a MEAT attestation (`meat_signed=true`)

> Audience: Physician / MD  •  Time: 9 min

A MEAT-signed attestation is the difference between a coder's best-guess acceptance
and an audit-ready, RADV-defensible diagnosis. This tutorial shows you how to sign,
what the signature changes downstream, and how to revoke if you change your mind.

## Prerequisites

- Tutorial 6 completed; you have at least one **accepted** suspect from the huddle.
- Your account has the `attest_meat` privilege (all MD-role accounts have it).

## Step 1 — Open the attestation page

From a patient chart, click the **MEAT** tab, or navigate to
`/patients/3/meat`. You see a list of accepted-but-unsigned suspects with checkboxes.
Each row also shows the auto-detected MEAT axes (the same dots as Tutorial 3).

## Step 2 — Anatomy of a signed attestation

Click a row. The right rail opens with four required text fields, one per MEAT axis:

- **Monitor** — what objective metric you used.
- **Evaluate** — what assessment you made during the visit.
- **Assess** — your clinical impression.
- **Treat** — the medication, referral, or procedure plan.

Each field auto-fills from the patient's most recent progress note (via the NLP
pipeline). Read the prefill, edit anything that's wrong, and add anything missing.
Empty fields block signing.

## Step 3 — Sign

When all four fields are filled, the **Sign attestation** button activates. The label
reads "Sign as Dr. <your name>, NPI <your npi>". Press it. A confirmation modal warns
that signed attestations are part of the legal medical record. Press **Confirm**.

The UI posts:

```bash
curl -s -X POST "http://localhost:8500/api/meat/attest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "patient_id": 3,
        "suspect_id": "<id>",
        "monitor":  "A1C 9.2 measured 2025-03-11",
        "evaluate": "Reviewed; condition active",
        "assess":   "DM Type 2, poorly controlled, with stage 3 CKD",
        "treat":    "Metformin 500mg BID continued, endocrinology referral placed"
      }'
```

**Expected outcome:** the row collapses, gets a small green checkmark plus the
**signed** badge, and the patient's RAF total turns from "tentative" amber to
"signed" green.

## Step 4 — What changes downstream

Once `meat_signed = true` flips to true, several things happen automatically:

- **CMS submission window opens** — the suspect becomes eligible for the next monthly
  EDPS submission batch. Without a signed MEAT, the platform refuses to submit it.
- **Writeback payload upgraded** — the FHIR `Condition` resource now includes a
  `verificationStatus.coding[0].code = "confirmed"` and an attached
  `Provenance` resource pointing to your signature.
- **Coder QA queue clears** — the suspect leaves the coder QA queue (`/review-queue`).
- **Audit chain extends** — a new event `meat.attest` is appended to the immutable
  log with your NPI, timestamp, and the verbatim text of the four fields.

Verify:

```bash
curl -s "http://localhost:8500/api/audit/events?patient_id=3&action=meat.attest&limit=1" \
  -H "Authorization: Bearer $TOKEN" | jq '.events[0]'
```

## Step 5 — Bulk sign at end-of-day

From `/md/today` press the **End of day** button. Any patient with one or more unsigned
acceptances opens in a focused review. You can review and sign all four MEAT fields,
then click **Sign all**. The endpoint above is called once per suspect.

## Step 6 — Revoke a signature

You can revoke a signature within 24 hours via the same row's overflow menu →
**Revoke attestation**. A reason is required (e.g., "Patient correction at follow-up
visit"). The revoke writes a `meat.revoke` event linked to the original signature.
After 24 hours, only a Chief Medical Officer role can revoke.

## Common pitfalls

- **Auto-fill says "no recent note"** — write the MEAT fields manually from your visit
  notes. Don't copy-paste from a different patient.
- **Signing what you don't believe** — the legal text on the modal is not boilerplate;
  signed attestations carry your NPI into CMS submissions.
- **Forgetting to sign after huddle** — accepted but unsigned RAF is shown in amber
  everywhere. If you see amber, you have unfinished business.

## Troubleshooting

- **"422: at least one field required"** — empty fields. Fill all four.
- **"403: meat attest forbidden"** — your role lacks the privilege; ask your admin to
  add `meat:attest`.
- **Signature shows the wrong NPI** — go to `/settings/profile/clinician` and update
  the NPI; the audit row uses the value at signing time, so old rows are unaffected.

## Next step

You now know how attestation works. The last MD tutorial reads a patient chart from
top to bottom and decodes every chip:

[Tutorial 8 — Read a patient chart — every chip explained](08-md-patient-review.md)
