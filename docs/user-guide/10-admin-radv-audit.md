# Run a RADV audit from sample to export

> Audience: Manager / Admin  •  Time: 12 min

A RADV (Risk Adjustment Data Validation) audit selects a representative sample of
patients, pulls every supporting document for each HCC, and prepares a packet you can
hand a CMS contractor or simulate internally. This tutorial walks an end-to-end run.

## Prerequisites

- Admin account.
- At least one MEAT-signed attestation in the dataset (Tutorial 7).

## Step 1 — Open the RADV page

Navigate to `/audit/radv` (or `Audit → RADV` in the sidebar). Existing audit runs are
listed with status (`draft`, `running`, `complete`, `exported`).

## Step 2 — Create an audit run

Press **New audit run**. Fill the dialog:

- **Name** — e.g., "2024 prospective sample".
- **Sample year** — coverage year you're attesting to.
- **Population filter** — MA plan, geography, attribution provider.
- **Sample size** — default 200. CMS RADV uses 201; 30 is fine for a smoke test.
- **Stratification** — `none`, `by_hcc`, `by_plan`, or `by_provider`.

Press **Create draft**. Under the hood:

```bash
curl -s -X POST "http://localhost:8500/api/radv/audits" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "2024 prospective sample",
        "year": 2024,
        "sample_size": 200,
        "stratification": "by_hcc"
      }'
```

The response includes an `audit_id`.

## Step 3 — Sample

In the draft view press **Generate sample**. The platform runs the stratified random
sample (deterministic; same seed yields same sample). You see a table of selected
patients, their HCCs in scope, and the count of supporting documents per HCC.

Verify the count looks right:

```bash
curl -s "http://localhost:8500/api/radv/audits/{audit_id}/sample" \
  -H "Authorization: Bearer $TOKEN" | jq '.summary'
```

You should see e.g. `{"patients": 200, "hccs": 612, "documents": 1840}`.

## Step 4 — Simulate

Press **Simulate**. The simulator evaluates each HCC in the sample against the
audit-grade rule set and assigns a verdict:

| Verdict | Meaning |
|---|---|
| `supported` | MEAT-signed attestation + documents present |
| `partial` | Some MEAT axes documented, others missing |
| `unsupported` | No defensible documentation |
| `excluded` | Out of scope (e.g., coding error pre-correction) |

The page renders the verdict mix as both a count and a projected dollar at risk.
Use this to triage chart chase before the real auditor arrives.

## Step 5 — Drill into a partial / unsupported HCC

Click any row to see why it failed:

- Which MEAT axes are missing.
- Which documents were considered and rejected (e.g., "note older than 24 months").
- Suggested actions: queue chart chase, request a corrected progress note, or remove
  the coded line from the next submission.

For `unsupported` rows you can press **Send to chart chase**, which creates a
provider outreach task (Tutorial 12 sends the campaign).

## Step 6 — Export the packet

Press **Export packet**. The system bundles:

- A summary PDF with the methodology, sample list, and verdict table.
- One folder per patient containing each supporting document (PDF/CCDA).
- A `manifest.json` cryptographically linking documents to events in the audit trail.

The export is signed with the tenant's KMS key and RFC-3161 timestamped. The bundle
appears in `/audit/radv/exports` once ready.

Download or share via signed URL:

```bash
curl -s "http://localhost:8500/api/radv/audits/{audit_id}/export" \
  -H "Authorization: Bearer $TOKEN" | jq '.download_url'
```

## Step 7 — Lock the run

Once exported, press **Lock**. A locked run is immutable. Any post-lock changes to
underlying suspects do not affect this run's verdicts. Locking writes a `radv.lock`
event with your user ID and the bundle's content hash.

## Common pitfalls

- **Re-sampling after starting work** — re-sampling discards prior verdicts. Lock
  drafts you've worked.
- **Sample size too small** — CMS expects 201 patients per contract for prospective
  audits. The simulator works on 30 but the projection error grows.
- **Forgetting stratification** — a flat random sample under-represents rare HCCs.
  Stratify by HCC when your auditor cares about coverage.

## Troubleshooting

- **"500: insufficient documentation index"** — the document NLP pipeline has not
  finished processing recent uploads. Wait for `/admin/pipeline` to clear, then
  re-sample.
- **Sample is empty** — your population filter excluded everyone. Loosen the filter.
- **Export stuck in `building`** — large packets take 5–10 min. The status endpoint
  returns `progress: 0.42`. Just wait.

## Next step

You ran an audit. Now make sure the controls you're attesting to are also collected
daily:

[Tutorial 11 — Review SOC 2 daily evidence](11-admin-soc2-evidence.md)
