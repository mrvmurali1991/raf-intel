# Send a TCPA-compliant outreach campaign

> Audience: Manager / Admin  •  Time: 10 min

Outreach campaigns nudge patients (or providers) to close gaps. TCPA (Telephone
Consumer Protection Act) compliance is non-negotiable for SMS/voice — this tutorial
shows how to verify opt-ins, send the campaign, and replay failed deliveries.

## Prerequisites

- Admin account.
- At least one provider or patient with a documented opt-in. The demo seed includes
  three opted-in patients (IDs 3, 7, 22).

## Step 1 — Open the Outreach console

Navigate to `/recapture/outreach`. The console has four tabs:

- **Campaigns** — create and schedule.
- **Audience** — filter and preview recipients.
- **Templates** — message bodies, with required tokens.
- **Delivery log** — every outbound message and its status.

## Step 2 — Verify opt-ins exist

Open the **Audience** tab. The first filter is **Has TCPA opt-in**, set to "Required"
by default. Don't turn it off — TCPA fines start at $500/violation.

Preview a sample:

```bash
curl -s "http://localhost:8500/api/recapture/outreach/audience?opt_in=required&limit=10" \
  -H "Authorization: Bearer $TOKEN" | jq '.recipients[]'
```

Each recipient row shows `consent_recorded_at`, `consent_source` (e.g., `intake_form`),
and `consent_channels` (e.g., `["sms", "email"]`). A recipient without
`consent_recorded_at` is automatically excluded.

## Step 3 — Pick or create a template

Open **Templates**. The shipped templates include:

- **HCC gap reminder** — generic chronic condition follow-up.
- **A1C 12-month nudge** — patients due for diabetes monitoring.
- **Provider attestation request** — asks an MD to MEAT-sign pending suspects.

Templates require tokens that the engine validates before send:

- `{patient_first_name}`, `{appointment_date}`, `{practice_name}` — required.
- `{stop_message}` — required for SMS (TCPA mandates opt-out instructions in every
  message: "Reply STOP to opt out").

Create a custom template with **+ New template**. The editor lints for missing
required tokens and won't let you save without them.

## Step 4 — Create the campaign

In the **Campaigns** tab press **+ New campaign**:

- **Name** — "A1C nudge Q2 2025".
- **Audience filter** — saved from Step 2.
- **Template** — pick from Step 3.
- **Channel** — `sms`, `email`, or `multi` (prefers patient's preferred channel).
- **Send window** — TCPA quiet hours (8 PM – 8 AM patient local) are auto-enforced;
  you can narrow further (e.g., business hours only).
- **Schedule** — `now` or a future timestamp.

Press **Schedule campaign**. The API call:

```bash
curl -s -X POST "http://localhost:8500/api/recapture/outreach/campaigns" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "A1C nudge Q2 2025",
        "audience_filter_id": "<saved_filter_id>",
        "template_id": "<template_id>",
        "channel": "sms",
        "send_at": "2025-05-20T15:00:00Z"
      }'
```

**Expected outcome:** the campaign appears with status `scheduled`. At send time it
moves to `running` then `complete`. The delivery log fills in real time.

## Step 5 — Watch deliveries

Open **Delivery log**. Each row shows recipient, channel, status (`queued` → `sent` →
`delivered` or `failed`), and the provider response code (Twilio for SMS, SendGrid for
email).

The Twilio/SendGrid clients sit behind a circuit breaker. If the upstream returns 5xx
or times out, the breaker trips and queues messages instead of dropping them. You see
a banner: "Outbound SMS paused (Twilio circuit open). Messages queued."

## Step 6 — Replay failed deliveries

Filter delivery log by `status: failed`. Common causes:

- **`tcpa_quiet_hours`** — quiet hours hit mid-campaign. Auto-rescheduled, no action.
- **`upstream_5xx`** — Twilio/SendGrid had a hiccup. Press **Replay** on the row or
  bulk-select.
- **`opt_in_revoked`** — patient replied STOP since the audience was built. **Do not**
  replay; honor the opt-out.
- **`invalid_phone`** — bad data; fix the patient record.

Bulk replay endpoint:

```bash
curl -s -X POST "http://localhost:8500/api/recapture/outreach/deliveries/replay" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"campaign_id": "<id>", "reasons": ["upstream_5xx"]}'
```

## Step 7 — Respect STOP

When a recipient replies STOP, the Twilio webhook posts an event that immediately
flips `consent_channels` to remove `sms`. Future campaigns auto-exclude. You can see
the opt-out in the patient's Activity feed as `outreach.opt_out`.

## Common pitfalls

- **Bypassing the opt-in filter** — never. TCPA penalties are per message.
- **Templates without STOP language** — the linter blocks save, but only if you use
  the official editor; do not push raw templates via the API without `{stop_message}`.
- **Replaying opt-outs** — never replay `opt_in_revoked` rows.

## Troubleshooting

- **Campaign stays `scheduled` past send time** — the scheduler job is stopped; check
  `/admin/pipeline`.
- **All deliveries `failed: invalid_credential`** — Twilio or SendGrid API key
  rotated; update in `/admin/integrations`.
- **No replay button** — your role lacks `outreach:replay`. Only `admin` and
  `analyst+` can replay.

## Next step

The last admin tutorial covers the ingestion pipeline that feeds everything:

[Tutorial 13 — Configure document ingestion (all 9 sources)](13-admin-document-ingestion.md)
