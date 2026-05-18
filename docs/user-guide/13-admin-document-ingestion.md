# Configure document ingestion (all 9 sources)

> Audience: Manager / Admin  •  Time: 12 min

The RAF engine is only as good as the documents that feed it. This tutorial walks
through configuring each of the nine ingestion paths, watching them in the pipeline
dashboard, and confirming that documents land in patient charts.

## Prerequisites

- Admin account.
- Credentials for whichever sources you intend to wire (you can configure them empty
  and fill in later).

## Step 1 — Open the ingestion overview

Navigate to `/documents/sources` (or `Documents → Sources`). You see one card per
source with **status**, **last successful run**, and **documents this week**. The nine
shipped sources are:

| # | Source | Card label | Auth | Cadence |
|---|---|---|---|---|
| 1 | Manual upload | **Manual** | session | on demand |
| 2 | SFTP drop folder | **SFTP** | password / key | every 5 min |
| 3 | S3 bucket | **S3** | IAM role | every 5 min |
| 4 | Direct Trust (HISP) | **Direct** | X.509 | every 1 min |
| 5 | FHIR pull (US Core) | **FHIR / US Core** | OAuth2 | nightly + on demand |
| 6 | CCDA REST | **CCDA** | API key | nightly |
| 7 | HL7v2 MLLP | **HL7v2** | TCP allowlist | streaming |
| 8 | CommonWell / Carequality (HIE) | **HIE** | mutual TLS | nightly |
| 9 | Email-in (S/MIME) | **Email-in** | S/MIME cert | streaming |

## Step 2 — Manual upload (the no-friction one)

Open the **Manual** card → **Configure**. Set max file size, allowed extensions, and
the auto-assign-by-NPI-in-filename toggle. Test it: drop a PDF on `/documents/upload`.
Within seconds the NLP pipeline picks it up.

## Step 3 — SFTP drop folder

The **SFTP** card needs host, port, username, private key (AES-encrypted at rest),
inbox path, and an optional PGP private key. Press **Test connection** for a one-shot
LIST, then **Enable**. The poller runs every 5 min.

## Step 4 — S3 bucket

Provide bucket name and prefix. Use IAM role assumption (recommended) or an access
key under 90 days old. The KMS key for SSE-KMS objects must be readable by the
platform's IAM principal.

## Step 5 — Direct Trust (HISP)

Enter your HISP endpoint and DNS-bound certificate. The Direct messaging adapter is
DSM-based and runs in streaming mode — incoming messages trigger immediate ingestion.
Look at `/admin/integrations/direct` to see the cert chain validation.

## Step 6 — FHIR pull (US Core)

The most common path. Configure:

- **Issuer URL** of the source EHR.
- **Client ID / secret** (or just client ID for PKCE flow).
- **Scopes** — at minimum `system/Patient.read system/Condition.read
  system/Observation.read system/MedicationRequest.read system/DocumentReference.read`.
- **Patient set** — `all`, `attributed`, or a list of FHIR patient IDs.

Press **Authorize**. You're redirected to the EHR for consent, then back. The pull
runs nightly; **Run now** triggers an immediate fetch. The demo seed wires this to
an OpenEMR sandbox (see `docs/OPENEMR_OAUTH2_SETUP.md`).

Note: newly registered FHIR OAuth2 clients on OpenEMR are disabled by default. Enable
the client in the OpenEMR admin UI before pressing Authorize.

## Step 7 — CCDA REST

Some EHRs expose a non-FHIR REST endpoint that returns C-CDA bundles. Provide URL,
API key, and a JSONPath to the bundle field. The CCDA parser handles every C-CDA R2
section the NLP pipeline cares about.

## Step 8 — HL7v2 MLLP

For real-time ADT/ORU feeds. Configure:

- Listen port (we default to 2575).
- Allowed sending application IDs.
- TLS toggle (highly recommended; provide cert).

Press **Enable**; the listener starts. Send a test ADT^A04 with `nc` to confirm the
parser ack returns within 200 ms.

## Step 9 — CommonWell / Carequality (HIE)

Highest impact for patients with care across multiple systems. Upload the mutual-TLS
cert pair issued by the framework, configure the OID, and choose `discovery` or
`query` mode. Each patient is queried nightly.

## Step 10 — Email-in (S/MIME)

A safety net for chart-chase fax-to-email and provider reply attachments. Set an
allowed-sender list, upload your S/MIME private key, and choose a quarantine mailbox.
Incoming messages are decrypted, scanned for malware, and the attachments queued for
the NLP pipeline.

## Step 11 — Monitor the pipeline

Open `/admin/pipeline`. The graph shows each stage: **fetch → parse → de-identify
(local copy only) → NLP → index**. Click any stage to see the last 100 jobs, their
duration, and failures. Failed jobs show the exact error and a **Retry** button.

## Step 12 — Confirm landing

For any source, after a successful run open the **Last 10 documents** drawer on the
card. Each row links to the patient page where it landed. If the NLP entity count is
zero, the parser likely succeeded but the document was empty — check the file.

## Common pitfalls

- **PHI in source URLs** — never put PHI in URL parameters; use POST bodies. The
  ingestion configs are scanned on save.
- **Polling too often** — every-minute polls on the SFTP/S3 sources will rate-limit
  your trading partner.
- **Disabling a source mid-pull** — in-flight jobs finish, but new jobs won't start.
  The pipeline drains cleanly.

## Troubleshooting

- **FHIR auth keeps failing** — confirm the EHR enabled your client (OpenEMR
  disables new clients by default).
- **HL7v2 returns AE acks** — the parser version doesn't match; pick the right
  HL7v2 version in the source config (`2.5.1` is most common).
- **Pipeline backlog growing** — scale the NLP worker pool from `/admin/system/scale`.

## Next step

You've finished the admin track. If you want to integrate from outside the platform:

[Tutorial 14 — Authenticate with JWT (login → refresh → scopes)](14-dev-api-auth.md)
