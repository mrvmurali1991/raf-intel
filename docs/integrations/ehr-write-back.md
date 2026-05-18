# EHR Problem List Write-Back

## Overview

When a provider accepts a suspect HCC condition in RAF Intelligence the system
offers to push that condition to the patient's EHR Problem List. This closes
the clinical loop — the pattern that Apixio (Vim), Notable, and Cotiviti all
use as an enterprise differentiator.

The implementation is split in two phases:

| Phase | What ships | Status |
|-------|-----------|--------|
| 1 (this PR) | Queue table + REST stub — intent logged, 202 returned | Shipped |
| 2 | SMART-on-FHIR Condition POST worker | Planned (needs per-tenant OAuth2 cred flow) |

---

## Architecture

```
Provider clicks "Accept" on /suspects
        |
        v
POST /api/ehr/problem-list-write-back/{patient_id}
        |
        v
  ehr_writeback_queue (status = queued)
        |
        v           [Phase 2 worker]
  SMART-on-FHIR token exchange  (client_credentials or EHR-launch refresh token)
        |
        v
  POST {fhir_base}/Condition        <-- Condition resource (see below)
        |
        v
  UPDATE ehr_writeback_queue SET status = 'sent'
```

---

## FHIR Condition Resource

The Phase 2 worker will POST the following R4 resource to the EHR's FHIR endpoint:

```json
{
  "resourceType": "Condition",
  "clinicalStatus": {
    "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                 "code": "active" }]
  },
  "verificationStatus": {
    "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                 "code": "confirmed" }]
  },
  "category": [
    {
      "coding": [{
        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
        "code": "problem-list-item",
        "display": "Problem List Item"
      }]
    }
  ],
  "code": {
    "coding": [{
      "system": "http://hl7.org/fhir/sid/icd-10-cm",
      "code": "<icd10>",
      "display": "<condition description>"
    }]
  },
  "subject": { "reference": "Patient/<fhir_patient_id>" },
  "recordedDate": "<attested_at ISO-8601>",
  "recorder": { "display": "<attested_by>" },
  "note": [{ "text": "<evidence_text>" }]
}
```

### Required SMART Scopes

```
launch/patient patient/Condition.write
```

For EHR-launch context these scopes are included in the app's registered
`scope` field. For backend-channel writes use `system/Condition.write` with
`client_credentials` grant if the EHR supports it (Epic does via backend
service app).

---

## Queue Table Schema

```sql
CREATE TABLE ehr_writeback_queue (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id       VARCHAR(64)  NOT NULL,
    patient_id      INT          NOT NULL,
    icd10           VARCHAR(16)  NOT NULL,
    hcc_code        VARCHAR(16)  NULL,
    evidence_text   TEXT         NULL,
    attested_by     VARCHAR(255) NULL,
    attested_at     DATETIME     NULL,
    status          ENUM('queued','sent','failed') NOT NULL DEFAULT 'queued',
    last_attempt_at DATETIME     NULL,
    error_detail    TEXT         NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP
);
```

---

## API Reference

### POST `/api/v1/ehr/problem-list-write-back/{patient_id}`

Queues an intent. Returns `202 Accepted`.

**Body:**
```json
{
  "icd10": "E11.9",
  "hcc_code": "19",
  "evidence_text": "A1c 9.2 on 2026-03-14 — diabetes uncontrolled",
  "attested_by": "dr.smith@clinic.org",
  "attested_at": "2026-05-18T14:30:00Z"
}
```

**Response:**
```json
{
  "status": "queued",
  "queue_id": 42,
  "message": "Problem List write-back queued for async EHR delivery."
}
```

### GET `/api/v1/ehr/problem-list-write-back?status=queued`

Admin/manager only. Returns paginated queue rows. Filter by `status`
(`queued` | `sent` | `failed`).

---

## Phase 2 Worker Design (Planned)

1. Cron / Celery beat task runs every 5 minutes.
2. Selects `WHERE status = 'queued' AND (last_attempt_at IS NULL OR last_attempt_at < NOW() - INTERVAL 5 MINUTE)`.
3. For each row, retrieves the per-tenant SMART credentials from the `emr_config` table.
4. Exchanges for an access token (`client_credentials` or stored refresh token).
5. POSTs the Condition resource; on HTTP 2xx sets `status = 'sent'`.
6. On failure increments attempt counter; after 3 retries sets `status = 'failed'` and stores `error_detail`.

Retry back-off: 5 min → 30 min → 2 h.

---

## Testing

```bash
# Queue a write-back (requires auth token)
curl -X POST http://localhost:8500/api/ehr/problem-list-write-back/123 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"icd10":"E11.9","hcc_code":"19","evidence_text":"A1c 9.2"}'

# View queue
curl http://localhost:8500/api/ehr/problem-list-write-back \
  -H "Authorization: Bearer $TOKEN"
```
