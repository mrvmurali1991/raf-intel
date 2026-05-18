# Read a patient chart — every chip explained

> Audience: Physician / MD  •  Time: 8 min

The patient page (`/patients/{id}`) packs a lot of information into a small space.
This tutorial decodes every chip, badge, and color so you can scan a chart in
30 seconds.

## Prerequisites

- A patient page open. Use `/patients/3` for the demo seed.
- Tutorials 6 and 7 done.

## Step 1 — The hero strip

The top band shows:

```
[Avatar]  Jane Doe, F 72        DOB 1952-04-19    MA Plan: Aetna HMO    Last visit: 2025-03-11
          RAF 2.41 signed       Open suspects: 5  Force-accepts: 1      Active claims: 318
```

- **RAF 2.41 signed** — the green color means the value reflects only signed
  attestations. If it's amber it includes pending accepts that have not yet been MEAT
  signed (Tutorial 7).
- **Open suspects** — count returned by `GET /api/suspects/{pid}` with status `open`.
- **Force-accepts** — accepts made without 3+ MEAT axes (Tutorial 3). Anything above
  zero is worth investigating before signing.
- **Active claims** — claim lines in the last 24 months.

## Step 2 — The Suspects tab

Each suspect card carries up to six chips on its top edge:

| Chip | Meaning |
|---|---|
| `HCC 18` | Mapped HCC category and its current RAF weight |
| `+ $1,247` | Dollar impact at your contracted RAF rate |
| `87%` | Engine confidence (calibrated, not raw model output) |
| Four dots | MEAT axes (green / amber / grey) |
| `claims+NLP` | Source signals that fired |
| `accepted` / `forced` / `signed` | Lifecycle stage |

A card with green dots, an `87%`-or-higher confidence, and `claims+NLP` source is the
easiest accept.

## Step 3 — The MEAT tab

Same as Tutorial 7. Each row has:

- The condition.
- Four prefilled fields (Monitor / Evaluate / Assess / Treat).
- A **signed** or **unsigned** badge.
- A timestamp of last edit.

Hover any field to see the source: "from progress note 2025-03-11 §Plan".

## Step 4 — The Documents tab

Lists every chart, note, and attachment. Chips per row:

| Chip | Meaning |
|---|---|
| `pdf` / `ccda` / `fhir` / `hl7` | Original document format |
| `NLP processed 2025-03-11` | NLP pipeline parsed this document |
| `7 entities` | Number of conditions/meds/labs the NLP extracted |
| `signed by Dr X` | Provider signature present in the source |

Click a row to open the in-browser viewer. Highlighted spans show what the NLP
extracted — hover any span to see the canonical ICD-10 / SNOMED / LOINC it mapped to.

## Step 5 — The Claims tab

Each claim line has chips:

| Chip | Meaning |
|---|---|
| `HCC 18` | If the line's primary diagnosis maps to an HCC |
| `Q3 2024` | Date of service quarter |
| `paid` / `denied` / `pending` | Adjudication status |
| `verified` | A linked attestation makes this line RADV-defensible |

A claim with an HCC chip but no `verified` chip is a candidate for chart chase.

## Step 6 — The Activity tab and timeline

The Activity tab is a chronological feed pulled from `GET /api/patients/3/activity`.
Event types you will see most often:

| Action | Meaning |
|---|---|
| `suspect.surfaced` | The engine added a new suspect |
| `suspect.accept` | A coder or MD accepted it |
| `suspect.force_accept` | Force accept with reason |
| `suspect.dismiss` | Dismissed (with or without a reverse link) |
| `meat.attest` | MEAT signed |
| `meat.revoke` | Signature revoked |
| `fhir.writeback.succeeded` | Remote EHR confirmed the Condition write |
| `outreach.sent` | TCPA-checked outreach delivered |

Each row is RFC-3161 timestamped and clickable — open it for the full payload.

## Step 7 — Right rail: risk strip

The right rail is always visible. It shows:

- **Risk summary** — clinical risk factors weighted by your tenant's model.
- **Drug interactions** — flagged by the polypharmacy engine.
- **Care gaps** — HEDIS gaps with due dates.
- **Recent meds** — last 5 prescriptions with start/end dates.

The risk summary card is colored:

- **Green** — no active flags.
- **Amber** — one or two flags worth reviewing in clinic today.
- **Red** — at least one flag requires action before the visit closes.

## Common pitfalls

- **Reading amber RAF as final** — it isn't. Sign the unsigned attestations (Tutorial 7)
  before you treat the number as your true RAF.
- **Trusting `verified` chips without a date** — always confirm the verification is
  current (within 12 months for chronic conditions).
- **Missing the right-rail red flag** — it's easy to focus on the center pane and miss
  a polypharmacy warning. Scan the rail first.

## Troubleshooting

- **Missing tabs** — your role lacks the permission (e.g., Claims is gated for
  `analyst+` roles). Ask your admin.
- **Activity feed empty** — the realtime channel is blocked. The list will still
  populate on refresh.

## Next step

You've completed the MD track. To learn how admins set up your environment:

[Tutorial 9 — Provision a user with MFA and a role](09-admin-user-provisioning.md)
