# Review SOC 2 daily evidence

> Audience: Manager / Admin  •  Time: 8 min

SOC 2 Type II evidence is collected automatically every day. Your job as admin is to
**spot check** the daily collection, fix gaps before they break a control, and grant
read-only access to your external auditor when the time comes.

## Prerequisites

- Admin account.
- Tutorial 9 done so you know how to create users (you'll create an `auditor` here).

## Step 1 — Open the SOC 2 dashboard

Navigate to `/audit/soc2`. The top panel shows the **Control health** strip: one tile
per control family (Security, Availability, Confidentiality, Processing Integrity,
Privacy). Each tile is green / amber / red based on the last 24 h of evidence runs.

The data comes from:

```bash
curl -s "http://localhost:8500/api/audit/soc2/controls" \
  -H "Authorization: Bearer $TOKEN" | jq '.controls[] | {family, control_id, last_run, status}'
```

## Step 2 — Tour a control

Click any tile — for example **Security**. You see the list of controls within that
family, with:

- **Control ID** (e.g., `CC6.1-mfa-enforced`).
- **Description** (one line, plain English).
- **Evidence type** (`log`, `config_snapshot`, `query_result`, `screenshot`).
- **Last collected** timestamp.
- **Last status** (`pass`, `fail`, `degraded`).

Click a control to open its evidence stream. You see every snapshot for the last
90 days, each with a download link to the artifact. Artifacts are stored in
object storage, signed and RFC-3161 timestamped.

## Step 3 — Investigate a failure

If a control is red, the page shows the latest reason — e.g., "MFA not enabled on
2 user accounts" with a link to the offending user IDs.

Two paths to fix:

1. **Remediate the gap** — e.g., enable MFA on those users (Tutorial 9, Step 4).
2. **Document an exception** — for genuine business reasons, press **Add exception**.
   You'll be asked for a reason, an expiry date, and a CSO/CTO approver. The exception
   is itself an audit artifact.

After remediation, click **Re-run collection** to refresh the control immediately
instead of waiting for the nightly job.

## Step 4 — Cross-check the evidence index

The evidence index keeps an append-only log of every artifact. Pull the last week:

```bash
curl -s "http://localhost:8500/api/audit/soc2/index?since=7d" \
  -H "Authorization: Bearer $TOKEN" | jq '.entries[0]'
```

Each entry has `control_id`, `artifact_hash`, `signed_url_template`, and a
`rfc3161_token`. Verify the chain integrity by clicking **Verify chain** in the UI;
the platform recomputes every hash and confirms each artifact's RFC-3161 token is
still valid against the configured TSA.

## Step 5 — Create an auditor user

When your external SOC 2 auditor arrives, create a dedicated read-only user:

1. `/users` → **Add user**.
2. Role: `auditor` (Tutorial 9, Step 3).
3. Force MFA on.

An `auditor` can:

- Read every control, evidence entry, and download artifacts.
- Pull the audit event log.
- Run the chain-verifier.

An `auditor` **cannot**:

- Change settings, users, or controls.
- See PHI in clinical pages.
- Trigger writeback, send outreach, or run pipelines.

## Step 6 — Daily ritual

Adopt this 5-minute morning habit:

1. Open `/audit/soc2`.
2. Scan the five control-family tiles — any red?
3. If red, click in, identify cause, remediate or document.
4. Spot-check one random green control to ensure the collector isn't silently
   broken.
5. Confirm yesterday's chain verification ran (banner at the top).

## Common pitfalls

- **Ignoring amber** — amber means "degraded", usually a slow collector. Left alone,
  amber turns red within 48 h.
- **Letting exceptions expire silently** — the page shows a banner 7 days before any
  exception expires. Renew or remediate.
- **Sharing the auditor account** — give each individual auditor their own login.

## Troubleshooting

- **All tiles grey** — the collector job is not running. Check `/admin/pipeline` →
  **soc2_collector** job; restart if stopped.
- **Chain verify fails** — almost always a clock-skew issue with the TSA. The error
  message shows which artifact failed; re-issue its RFC-3161 token.
- **Auditor can't see a control** — confirm the user has the `auditor` role (not just
  `viewer`).

## Next step

Controls are tracked. Next, send a TCPA-compliant outreach campaign:

[Tutorial 12 — Send a TCPA-compliant outreach campaign](12-admin-outreach.md)
