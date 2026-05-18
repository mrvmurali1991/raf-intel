# Receive webhooks (FHIR / Twilio / SendGrid)

> Audience: Developer / Integrator  •  Time: 9 min

RAF Intelligence both **emits** webhooks (so your downstream systems get notified) and
**receives** webhooks from upstream providers (FHIR subscription pushes, Twilio SMS
status, SendGrid email events). This tutorial covers both directions and the
signature verification you must implement.

## Prerequisites

- Tutorial 14 done; you have a token.
- A public HTTPS endpoint to receive webhooks (use `ngrok http 4000` for local
  testing).

## Step 1 — Emit: register an outbound webhook

Tell the platform where to POST events:

```bash
BASE=http://localhost:8500
H="Authorization: Bearer $ACCESS"

curl -s -X POST "$BASE/api/webhooks" -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{
        "url": "https://your-ngrok-id.ngrok-free.app/raf-events",
        "events": ["suspect.accept", "suspect.dismiss", "meat.attest"],
        "active": true
      }' | jq
```

Expected output:

```json
{
  "id": "wh_01HMV3...",
  "url": "https://...",
  "events": ["suspect.accept", "suspect.dismiss", "meat.attest"],
  "secret": "whsec_abc123...",
  "active": true
}
```

**Save the `secret`.** It is shown once and is the HMAC key for verifying signatures
on every delivery.

## Step 2 — Verify the signature on receipt

Every delivery carries two headers:

- `X-RAF-Signature: t=<timestamp>,v1=<hex hmac>`
- `X-RAF-Delivery: <delivery_uuid>` (idempotency key — dedupe on this)

To verify (Python):

```python
import hmac, hashlib, time

def verify(payload_bytes: bytes, header: str, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    ts = int(parts["t"])
    if abs(time.time() - ts) > 300:
        return False  # >5 min skew — replay
    signed = f"{ts}.".encode() + payload_bytes
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

Reject the request with 4xx if verification fails. The platform retries 5xx but
treats 4xx as a permanent rejection.

## Step 3 — Retry, deliver-at-least-once, idempotency

- Retries: 1 min, 5 min, 30 min, 2 h, 12 h. After the fifth failure the webhook is
  marked `failing` and you get an alert in `/admin/webhooks`.
- Deliveries are **at-least-once**. Use `X-RAF-Delivery` to dedupe — a UUID v7 that
  is identical across retries of the same event.
- Order is **not guaranteed**. Always use the event's `event_id` and `ts` to apply in
  the right order on your side.

## Step 4 — Receive: FHIR subscription pushes

When the platform is a FHIR `Subscription` destination (rest-hook channel), the source
EHR posts to your configured URL. Wire it under
`POST $BASE/api/webhooks/fhir/{tenant_id}`. The platform validates:

- The `X-FHIR-Signature` header (if your source EHR uses one — Epic, Cerner do).
- The `Bundle.entry[*].resource` against US Core profiles.
- The patient-attribution check (the resource's patient must be in your panel).

If you're building your own FHIR producer, send signed requests with the HMAC method
above using the secret shown in `/admin/integrations/fhir`.

## Step 5 — Receive: Twilio status callbacks

Outreach campaigns (Tutorial 12) hand Twilio a status callback URL pointing back to
`POST $BASE/api/webhooks/twilio`. The endpoint verifies Twilio's signature using
`X-Twilio-Signature` and the auth token from `/admin/integrations/twilio`. On
success the platform updates the delivery log row (Tutorial 12, Step 5).

If you proxy Twilio through your own service, forward the original signature header
unchanged.

## Step 6 — Receive: SendGrid event webhooks

Email open/click/bounce events POST to `POST $BASE/api/webhooks/sendgrid`. SendGrid
signs with an Ed25519 public key you upload in `/admin/integrations/sendgrid`. The
platform verifies, drops anything older than 5 minutes, and updates the campaign
delivery row.

## Step 7 — Test an outbound delivery

Force a test event:

```bash
curl -s -X POST "$BASE/api/webhooks/wh_01HMV3.../test" -H "$H" | jq
```

The platform sends a synthetic `webhook.test` event with a deterministic payload to
your URL. Your endpoint should respond `200 OK` within 5 s.

## Step 8 — Inspect deliveries

```bash
curl -s "$BASE/api/webhooks/wh_01HMV3.../deliveries?limit=10" -H "$H" \
  | jq '.deliveries[] | {ts, event, response_status, attempt}'
```

Each row shows your endpoint's response status, latency, and the attempt number.

## Step 9 — Rotate the secret

If the secret leaks (committed to a repo, posted in Slack), rotate immediately:

```bash
curl -s -X POST "$BASE/api/webhooks/wh_01HMV3.../rotate-secret" -H "$H" | jq
```

The response contains the new `secret`. The old one keeps verifying for a 24-hour
overlap so you can deploy without downtime.

## Step 10 — Pause / disable

Set `active: false` to stop deliveries without losing config:

```bash
curl -s -X PUT "$BASE/api/webhooks/wh_01HMV3..." -H "$H" \
  -H 'Content-Type: application/json' -d '{"active": false}'
```

Events that occur while paused are dropped, not queued — re-enable before any window
you care about.

## Common pitfalls

- **Skipping signature verification** — anyone with your URL can forge events.
- **Not deduping on `X-RAF-Delivery`** — retries will double-process.
- **Returning 200 for malformed payloads** — return 4xx so the platform stops
  retrying.

## Troubleshooting

- **Deliveries all 4xx** — your verifier rejects everything. Re-check the secret you
  saved in Step 1.
- **No deliveries arriving** — check the webhook is `active`. Also check the events
  list includes the event types you're testing.
- **5xx storm marks webhook `failing`** — fix your endpoint, then `POST .../resume`
  to clear the failing flag.

## Next step

You finished the developer track. To deepen further, see the API reference in
`/docs/api` and the SDK examples in `/docs/development`.

Return to the [User Guide index](README.md).
