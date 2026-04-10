# RAF Intelligence API Reference

Version: **2.0.0** — API version header: `X-API-Version: v1`

---

## Table of Contents

1. [Overview](#overview)
2. [Base URL and Transport](#base-url-and-transport)
3. [Authentication](#authentication)
4. [Common Conventions](#common-conventions)
5. [Patients](#patients)
6. [RAF Calculation](#raf-calculation)
7. [Clinical Note Analysis](#clinical-note-analysis)
8. [Documents](#documents)
9. [C-CDA / CCD Documents](#c-cda--ccd-documents)
10. [Suspect Conditions](#suspect-conditions)
11. [Attestations](#attestations)
12. [Chart Chase](#chart-chase)
13. [Reports](#reports)
14. [Providers](#providers)
15. [Claims](#claims)
16. [CMS Submissions (RAPS/EDPS)](#cms-submissions-rapsedps)
17. [EMR Integration](#emr-integration)
18. [FHIR R4 Integration](#fhir-r4-integration)
19. [SMART on FHIR](#smart-on-fhir)
20. [ADT Feed](#adt-feed)
21. [Clearinghouse (Eligibility)](#clearinghouse-eligibility)
22. [Direct Messaging](#direct-messaging)
23. [Prospective RAF](#prospective-raf)
24. [Annual Wellness Visits (AWV)](#annual-wellness-visits-awv)
25. [Quality Measures (HEDIS / STARS)](#quality-measures-hedis--stars)
26. [Care Gaps](#care-gaps)
27. [Cohorts](#cohorts)
28. [Coder Worklist](#coder-worklist)
29. [Webhooks](#webhooks)
30. [Notifications](#notifications)
31. [Jobs](#jobs)
32. [BI Export](#bi-export)
33. [Audit Packages (RADV)](#audit-packages-radv)
34. [Benchmarks](#benchmarks)
35. [Real-Time Dashboard](#real-time-dashboard)
36. [Admin](#admin)
37. [ICD-10 Lookup](#icd-10-lookup)
38. [Compliance Status](#compliance-status)
39. [Health Checks](#health-checks)
40. [Dashboard Utilities](#dashboard-utilities)
41. [Error Reference](#error-reference)

---

## Overview

RAF Intelligence is an enterprise-grade CMS HCC risk adjustment platform for Medicare Advantage plans. The API covers:

- Patient demographics and encounter data pulled from OpenEMR via an active EMR connection
- CMS-HCC V24/V28 blended RAF score calculation using `hccinfhir`
- AI-powered clinical note NLP analysis (Gemini Vision + MedCAT pipeline)
- Suspect condition detection from medications, labs, procedures, and historical diagnoses
- Provider attestation workflows and chart chase management
- CMS RAPS/EDPS submission generation and tracking
- FHIR R4 and SMART on FHIR integrations
- HL7v2 ADT feed listeners (MLLP)
- Population health cohorts, HEDIS quality measures, and AWV scheduling
- Real-time dashboard (SSE + WebSocket), BI export, and RADV audit packages

---

## Base URL and Transport

| Environment | Base URL |
|-------------|----------|
| Development | `http://localhost:8500` |
| Production  | `https://<your-domain>` (TLS required) |

All endpoints are prefixed with `/api/`. The root `/` and health endpoints at `/health` do not carry a prefix.

**Required headers on every authenticated request:**

```
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json
```

**Response headers always present:**

| Header | Description |
|--------|-------------|
| `X-API-Version` | Always `v1` |
| `X-Request-ID` | UUID trace ID for the request |
| `X-Process-Time-Ms` | Server processing time in milliseconds |

---

## Authentication

Prefix: `/api/auth` — tag: `auth`

JWT access tokens expire per `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 min). Refresh tokens are long-lived (default 7 days). MFA is TOTP-based.

### POST /api/auth/login

Authenticate with email and password. Returns an access token and refresh token. If MFA is enabled for the account, returns `mfa_required: true` and a `session_token` to be completed with `/api/auth/mfa/verify`.

**Auth required:** None (public)

**Rate limit:** 10/minute per IP

**Request body:**
```json
{
  "email": "clinician@health.org",
  "password": "S3cur3P@ss!"
}
```

**Response 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 42,
    "email": "clinician@health.org",
    "role": "clinician",
    "full_name": "Dr. Jane Smith"
  }
}
```

**Response 200 (MFA required):**
```json
{
  "mfa_required": true,
  "session_token": "tmp_abc123..."
}
```

**Response 401:** Invalid credentials.

---

### POST /api/auth/refresh

Exchange a refresh token for a new access token.

**Auth required:** None (public)

**Request body:**
```json
{ "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4..." }
```

**Response 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

---

### POST /api/auth/logout

Revoke the current session.

**Auth required:** Bearer JWT

**Response 200:** `{ "message": "Logged out" }`

---

### GET /api/auth/me

Return profile of the currently authenticated user.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "id": 42,
  "email": "clinician@health.org",
  "full_name": "Dr. Jane Smith",
  "role": "clinician",
  "is_active": true,
  "mfa_enabled": false,
  "created_at": "2025-01-15T10:00:00Z"
}
```

---

### PUT /api/auth/me

Update the current user's own profile (name, email).

**Auth required:** Bearer JWT

**Request body:** Any subset of `{ "full_name": "...", "email": "..." }`

---

### PUT /api/auth/change-password

Change password for the current user.

**Auth required:** Bearer JWT

**Request body:**
```json
{
  "current_password": "OldP@ss1",
  "new_password": "NewP@ss2!"
}
```

---

### POST /api/auth/forgot-password

Send a password reset email.

**Auth required:** None (public)

**Request body:** `{ "email": "clinician@health.org" }`

**Response 200:** `{ "message": "Reset email sent if account exists" }`

---

### POST /api/auth/reset-password

Complete a password reset using the emailed token.

**Auth required:** None (public)

**Request body:**
```json
{
  "token": "<reset_token_from_email>",
  "new_password": "NewP@ss1!"
}
```

---

### GET /api/auth/sessions

List all active sessions for the current user.

**Auth required:** Bearer JWT

---

### DELETE /api/auth/sessions/{session_id}

Revoke a specific session by ID.

**Auth required:** Bearer JWT

---

### MFA Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/mfa/enable` | Begin TOTP setup — returns QR code URI |
| `POST` | `/api/auth/mfa/verify-setup` | Confirm TOTP code to activate MFA |
| `POST` | `/api/auth/mfa/verify` | Complete login after MFA challenge |
| `POST` | `/api/auth/mfa/disable` | Disable MFA (requires password confirmation) |

---

### User Management (Admin / Manager)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/auth/users` | admin/manager | Paginated user list |
| `POST` | `/api/auth/users` | admin | Create a new user |
| `GET` | `/api/auth/users/{id}` | admin/manager | User detail |
| `PUT` | `/api/auth/users/{id}` | admin | Update user |
| `DELETE` | `/api/auth/users/{id}` | admin | Deactivate user |
| `GET` | `/api/auth/users/{id}/permissions` | admin | Get resource permissions |
| `PUT` | `/api/auth/users/{id}/permissions` | admin | Set resource permissions |
| `GET` | `/api/auth/audit-log` | admin/manager | Paginated auth audit log |

**Create user request body:**
```json
{
  "email": "new.coder@health.org",
  "password": "TempP@ss1!",
  "full_name": "Alex Coder",
  "role": "coder"
}
```

**Roles:** `admin`, `manager`, `clinician`, `coder`, `viewer`

---

## Common Conventions

### Pagination

All list endpoints accept `limit` (default 100, max 1000) and `offset` (default 0) query parameters.

```
GET /api/patients?limit=25&offset=50
```

Response envelope:
```json
{
  "total": 1240,
  "limit": 25,
  "offset": 50,
  "patients": [ ... ]
}
```

### Permission System

Endpoints enforce resource-level permissions in addition to role checks. Permissions are structured as `resource:action` pairs (e.g., `patients:read`, `reports:write`). The `admin` role bypasses all permission checks. Permissions are set per-user via `PUT /api/auth/users/{id}/permissions`.

### Rate Limiting

Most endpoints are limited to **60 requests/minute** per user. Upload endpoints are limited to **10 requests/minute**. Exceeded limits return HTTP 429 with a `Retry-After` header.

### HIPAA Security Headers

Every response carries:
- `Cache-Control: no-store, no-cache, must-revalidate`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`

---

## Patients

Prefix: `/api/patients` — tag: `patients`

Patient data is read from the connected OpenEMR database. A valid active EMR connection must exist (configured via `/api/emr/connections`). All patient endpoints require `patients:read` permission.

---

### GET /api/patients

Return a paginated list of patients.

**Auth required:** `patients:read`

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 100 | Max results (1–1000) |
| `offset` | int | 0 | Pagination offset |
| `search` | string | — | Search by name or PID |

**Response 200:**
```json
{
  "total": 3840,
  "limit": 100,
  "offset": 0,
  "patients": [
    {
      "pid": 1001,
      "fname": "Margaret",
      "lname": "Chen",
      "dob": "1942-03-15",
      "sex": "Female",
      "latest_raf": 1.842,
      "hcc_count": 5
    }
  ]
}
```

---

### GET /api/patients/{pid}

Single patient with demographics and latest RAF score.

**Auth required:** `patients:read`

**Path params:** `pid` — OpenEMR patient ID (integer)

**Response 200:**
```json
{
  "pid": 1001,
  "fname": "Margaret",
  "lname": "Chen",
  "dob": "1942-03-15",
  "sex": "Female",
  "address": "...",
  "latest_raf": 1.842,
  "raf_calculated_at": "2026-03-20T14:32:00Z",
  "hcc_count": 5,
  "active_suspects": 2
}
```

---

### GET /api/patients/{pid}/encounters

Encounter history from OpenEMR.

**Auth required:** `patients:read`

**Response 200:** `{ "pid": 1001, "encounters": [ { "id": 500, "date": "2026-01-10", "provider": "Dr. Kim", "reason": "...", "soap_note_available": true } ] }`

---

### GET /api/patients/{pid}/medications

Active prescriptions. Includes `diagnosis` field for medication-linked HCC detection.

**Auth required:** `patients:read`

---

### GET /api/patients/{pid}/medication-gaps

Medication-linked diagnoses that have not been billed in the current measurement year. Used for suspect detection.

**Auth required:** `patients:read`

---

### GET /api/patients/{pid}/diagnoses

All ICD-10 billing codes for the patient from OpenEMR encounter forms.

**Auth required:** `patients:read`

---

### GET /api/patients/{pid}/procedures

CPT procedure codes with AI-generated condition hints.

**Auth required:** `patients:read`

---

### GET /api/patients/{pid}/lab-suspects

Rule-based suspect conditions derived from lab results and vitals (e.g., HbA1c indicating diabetes, eGFR indicating CKD).

**Auth required:** `patients:read`

---

### GET /api/patients/{pid}/comprehensive-profile

Full aggregated patient profile: demographics, diagnoses, medications, procedures, lab suspects, RAF scores, open suspects, and encounter history. Designed as a single-call payload for the patient detail page.

**Auth required:** `patients:read`

---

### POST /api/patients/import

Bulk import patients from a CSV file upload.

**Auth required:** `patients:write`

**Content-Type:** `multipart/form-data`

**Form fields:**
- `file` — CSV file (required)

**Response 202:**
```json
{ "job_id": "uuid-...", "message": "Import queued", "rows_detected": 450 }
```

---

### GET /api/patients/import/template

Download a blank CSV template for patient bulk import.

**Auth required:** Bearer JWT

**Response:** CSV file download

---

## RAF Calculation

Prefix: `/api/raf` — tag: `raf`

Implements CMS-HCC V24/V28 blended scoring using the `hccinfhir` library. Blend weights follow the CMS schedule:

| Payment Year | V24 Weight | V28 Weight |
|-------------|------------|------------|
| PY2024 | 67% | 33% |
| PY2025 | 33% | 67% |
| PY2026+ | 0% | 100% |

---

### POST /api/raf/calculate/{pid}

Calculate and store the RAF score for a single patient using ICD-10 codes from the current measurement year.

**Auth required:** `raf:write`

**Path params:** `pid` — patient ID

**Optional request body:**
```json
{
  "year": 2026,
  "model_segment": "CNA"
}
```

**`model_segment` values:** `CNA` (Community Non-Dual Aged), `CND` (Community Non-Dual Disabled), `CFA` (Community Full-Benefit Dual Aged), `CFD` (Community Full-Benefit Dual Disabled), `CPA` (Community Partial-Dual Aged), `CPD` (Community Partial-Dual Disabled), `INS` (Institutional), `NE` (New Enrollee)

**Response 200:**
```json
{
  "pid": 1001,
  "year": 2026,
  "final_raf": 1.842,
  "v24_raf": 1.790,
  "v28_raf": 1.865,
  "v24_weight": 0.0,
  "v28_weight": 1.0,
  "hcc_count": 5,
  "model_segment": "CNA",
  "calculated_at": "2026-04-06T09:14:22Z"
}
```

---

### POST /api/raf/calculate-all

Batch-calculate RAF scores for all patients linked to active EMR connections. Runs asynchronously.

**Auth required:** `raf:write`

**Query params:** `year` (int, optional, defaults to current year)

**Response 202:**
```json
{ "job_id": "uuid-...", "queued": 3840, "message": "Batch calculation started" }
```

---

### GET /api/raf/scores/{pid}

Retrieve the stored RAF score for a patient.

**Auth required:** `raf:read`

**Response 200:** Same shape as POST calculate response.

---

### GET /api/raf/scores/{pid}/breakdown

Detailed HCC breakdown with MEAT documentation status (Monitoring, Evaluation, Assessment, Treatment) for each HCC code.

**Auth required:** `raf:read`

**Query params:** `year` (int, optional)

**Response 200:**
```json
{
  "pid": 1001,
  "year": 2026,
  "final_raf": 1.842,
  "hccs": [
    {
      "hcc_code": "HCC18",
      "label": "Diabetes with Chronic Complications",
      "icd10_codes": ["E11.65", "E11.40"],
      "v24_coefficient": 0.302,
      "v28_coefficient": 0.288,
      "meat_status": "documented",
      "evidence_count": 3
    }
  ],
  "demographics_factor": 0.379,
  "interactions": [ ... ]
}
```

---

### GET /api/raf/scores/{pid}/model-comparison

Side-by-side V24 vs V28 comparison for a patient.

**Auth required:** `raf:read`

**Response 200:**
```json
{
  "pid": 1001,
  "v24": { "raf": 1.790, "hcc_count": 5, "hccs": [ ... ] },
  "v28": { "raf": 1.865, "hcc_count": 5, "hccs": [ ... ] },
  "delta": 0.075,
  "blend": { "py2024": 1.815, "py2025": 1.840, "py2026": 1.865 }
}
```

---

### GET /api/raf/scores/{pid}/history

Historical RAF scores across all calculated years.

**Auth required:** `raf:read`

---

### GET /api/raf/population-summary

Population-level RAF statistics.

**Auth required:** `raf:read`

**Response 200:**
```json
{
  "total_patients": 3840,
  "patients_with_scores": 3210,
  "average_raf": 1.427,
  "median_raf": 1.203,
  "high_raf_patients": 412,
  "hcc_distribution": { "HCC18": 820, "HCC85": 615, ... }
}
```

---

### GET /api/raf/models

List all available RAF models with descriptions (CMS-HCC V24, CMS-HCC V28, RxHCC, HHS-HCC).

**Auth required:** `raf:read`

---

### POST /api/raf/calculate-multi/{pid}

Calculate RAF simultaneously across CMS-HCC, RxHCC, and HHS-HCC models.

**Auth required:** `raf:write`

**Response 200:**
```json
{
  "pid": 1001,
  "cms_hcc": { "raf": 1.842, "model": "V28" },
  "rx_hcc": { "raf": 0.423, "rxc_count": 3 },
  "hhs_hcc": { "raf": 2.104, "hcc_count": 7 }
}
```

---

### GET /api/raf/scores/{pid}/multi-model

Retrieve stored CMS-HCC scores and run live RxHCC/HHS-HCC calculations for comparison.

**Auth required:** `raf:read`

---

## Clinical Note Analysis

Prefix: `/api/analysis` — tag: `analysis`

Seven-stage NLP pipeline: MedCAT NER → Assertion filtering → Retrieve-Rank → Gemini analysis → ICD-10 validation → Confidence routing → MEAT evidence persistence.

---

### POST /api/analysis/encounter/{encounter_id}

Fetch a SOAP note from OpenEMR by encounter ID and run the full NLP pipeline.

**Auth required:** `analysis:write`

**Path params:** `encounter_id` — OpenEMR encounter ID

**Response 200:**
```json
{
  "encounter_id": 500,
  "pid": 1001,
  "pipeline": {
    "medcat": "ok",
    "assertion": "ok",
    "retrieve_rank": "ok",
    "gemini": "ok"
  },
  "diagnoses": [
    {
      "icd10": "E11.65",
      "description": "Type 2 diabetes mellitus with hyperglycemia",
      "hcc": "HCC18",
      "confidence": 0.94,
      "meat_documented": true
    }
  ],
  "raw_entities": [ ... ],
  "processed_at": "2026-04-06T09:20:00Z"
}
```

---

### POST /api/analysis/note

Run the NLP pipeline on user-supplied note text. No OpenEMR encounter required.

**Auth required:** `analysis:write`

**Request body:**
```json
{
  "note_text": "Patient presents with worsening HbA1c of 8.9. Diagnosed with T2DM...",
  "pid": 1001,
  "encounter_date": "2026-04-06"
}
```

**Response 200:** Same shape as `POST /api/analysis/encounter/{encounter_id}`

---

### POST /api/analysis/batch/{pid}

Queue a background job to analyze every encounter for a patient.

**Auth required:** `analysis:write`

**Response 202:** `{ "job_id": "uuid-...", "encounter_count": 12 }`

---

### GET /api/analysis/jobs/{job_id}

Poll the status of an async batch analysis job.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "job_id": "uuid-...",
  "status": "progress",
  "progress": 8,
  "total": 12,
  "started_at": "2026-04-06T09:15:00Z"
}
```

---

### GET /api/analysis/jobs/{job_id}/results

Retrieve full results of a completed batch job.

**Auth required:** Bearer JWT

---

## Documents

Prefix: `/api/documents` — tag: `documents`

Upload clinical documents (PDF, image, TIFF) for Gemini Vision analysis. Extracted diagnoses can be reviewed and linked to patient records.

---

### POST /api/documents/upload

Upload a clinical document and trigger Gemini Vision analysis.

**Auth required:** `documents:write`

**Content-Type:** `multipart/form-data`

**Form fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | PDF, JPG, PNG, or TIFF |
| `patient_id` | int | No | Link to patient at upload time |
| `batch_id` | string | No | Associate with an existing batch |
| `document_type` | string | No | e.g. `progress_note`, `lab_report`, `discharge_summary` |

**Response 202:**
```json
{
  "document_id": "doc_abc123",
  "filename": "progress_note_2026.pdf",
  "status": "processing",
  "batch_id": "batch_xyz",
  "message": "Document uploaded and queued for analysis"
}
```

---

### GET /api/documents

List uploaded documents with optional filters.

**Auth required:** `documents:read`

**Query params:** `patient_id`, `batch_id`, `status` (`pending`/`analyzed`/`approved`/`rejected`), `limit`, `offset`

---

### GET /api/documents/{document_id}

Get document metadata and analysis results.

**Auth required:** `documents:read`

**Response 200:**
```json
{
  "document_id": "doc_abc123",
  "filename": "progress_note_2026.pdf",
  "status": "analyzed",
  "patient_id": 1001,
  "analyzed_at": "2026-04-06T09:25:00Z",
  "diagnoses": [
    {
      "line_id": 1,
      "icd10": "I50.9",
      "description": "Heart failure, unspecified",
      "hcc": "HCC85",
      "confidence": 0.91,
      "review_status": "pending"
    }
  ]
}
```

---

### POST /api/documents/{document_id}/analyze

Re-trigger Gemini Vision analysis on an already-uploaded document.

**Auth required:** `documents:write`

---

### PUT /api/documents/{document_id}/diagnoses/{line_id}

Approve or reject an individual extracted diagnosis line.

**Auth required:** `documents:write`

**Request body:**
```json
{ "review_status": "approved", "reviewer_notes": "Confirmed from chart" }
```

---

### DELETE /api/documents/{document_id}

Delete a document and its analysis results.

**Auth required:** `documents:write`

---

### GET /api/documents/stats

Aggregate document processing statistics (counts by status, average processing time).

**Auth required:** `documents:read`

---

### Batch Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/documents/batches` | Create a new document batch |
| `GET` | `/api/documents/batches` | List batches |
| `GET` | `/api/documents/batches/{batch_id}` | Batch detail with per-document status |
| `POST` | `/api/documents/batches/{batch_id}/process` | Trigger batch processing |

---

## C-CDA / CCD Documents

Prefix: `/api/ccda` — tag: `ccda`

Upload, parse, and export Consolidated Clinical Document Architecture (C-CDA R2.1 / CCD) XML files.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ccda/upload` | Upload a C-CDA XML file |
| `POST` | `/api/ccda/{id}/parse` | (Re)parse a document |
| `GET` | `/api/ccda` | List documents for the tenant |
| `GET` | `/api/ccda/{id}` | Document detail with parsed_data |
| `GET` | `/api/ccda/{id}/problems` | Extracted problem list |
| `GET` | `/api/ccda/{id}/medications` | Extracted medications |
| `GET` | `/api/ccda/{id}/results` | Extracted lab results |
| `GET` | `/api/ccda/{id}/hcc-impact` | HCC categories found in the document |
| `POST` | `/api/ccda/export/{patient_id}` | Generate a C-CDA export for a patient |
| `DELETE` | `/api/ccda/{id}` | Delete document and file |

**Auth required:** Bearer JWT + `documents:read` or `documents:write` as applicable.

**Upload example:**
```
POST /api/ccda/upload
Content-Type: multipart/form-data

file=<ccd_xml_file>
patient_id=1001   (optional)
```

---

## Suspect Conditions

Prefix: `/api/suspects` — tag: `suspects`

Suspect conditions are potential HCC codes not yet captured on a claim, derived from medications, lab results, procedures, historical diagnoses, and AI note analysis. Stored in `raf_suspect_conditions`.

---

### GET /api/suspects

All open suspect conditions across the population, sorted by confidence score (descending).

**Auth required:** `suspects:read`

**Query params:** `year` (int), `evidence_type` (`medication`/`lab`/`imaging`/`referral`/`historical`), `min_confidence` (float 0–1), `limit`, `offset`

**Response 200:**
```json
{
  "total": 286,
  "suspects": [
    {
      "id": 1044,
      "patient_id": 1001,
      "suspect_hcc": 18,
      "suspect_icd10": "E11.65",
      "evidence_type": "medication",
      "evidence_detail": { "drug": "Metformin", "ndc": "00093-1048-01" },
      "confidence_score": 0.94,
      "status": "open",
      "measurement_year": 2026
    }
  ]
}
```

---

### GET /api/suspects/{pid}

All suspects for a single patient.

**Auth required:** `suspects:read`

---

### POST /api/suspects/scan/{pid}

Run a full suspect scan (all detection engines) for one patient.

**Auth required:** `suspects:write`

**Response 200:** `{ "pid": 1001, "suspects_found": 3, "suspects": [ ... ] }`

---

### POST /api/suspects/scan-all

Run suspect scan for every patient. Async background job.

**Auth required:** `suspects:write`

**Response 202:** `{ "job_id": "uuid-...", "patients_queued": 3840 }`

---

### PUT /api/suspects/{suspect_id}/accept

Mark a suspect as accepted/coded. The corresponding ICD-10 code should be added to the patient's encounter.

**Auth required:** `suspects:write`

**Request body:** `{}` (empty)

**Response 200:** `{ "suspect_id": 1044, "status": "accepted" }`

---

### PUT /api/suspects/{suspect_id}/dismiss

Dismiss a suspect condition.

**Auth required:** `suspects:write`

**Request body:**
```json
{ "reason": "Already coded in prior year, not active this year" }
```

---

### POST /api/suspects/bulk-update

Accept or dismiss multiple suspects in one call.

**Auth required:** `suspects:write`

**Request body:**
```json
{
  "ids": [1044, 1045, 1046],
  "action": "dismiss",
  "reason": "Reviewed at provider meeting, not clinically supported"
}
```

**Response 200:** `{ "updated": 3, "failed": 0 }`

---

## Attestations

Prefix: `/api/attestations` — tag: `attestations`

Provider sign-off workflow for suspect HCC conditions. Providers confirm, reject, or defer each condition via structured attestation.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/attestations` | List attestation requests (filter by provider NPI, status) |
| `POST` | `/api/attestations` | Create a single attestation request |
| `GET` | `/api/attestations/dashboard` | KPI stats (pending count, avg resolution time) |
| `POST` | `/api/attestations/remind` | Trigger email reminders for pending attestations |
| `POST` | `/api/attestations/batch` | Create a batch signing session |
| `PUT` | `/api/attestations/batch/{id}/submit` | Submit all decisions in a batch |
| `GET` | `/api/attestations/{id}` | Single attestation detail |
| `PUT` | `/api/attestations/{id}/attest` | Provider confirms condition as active/resolved |
| `PUT` | `/api/attestations/{id}/reject` | Provider rejects as inaccurate |
| `PUT` | `/api/attestations/{id}/defer` | Provider defers (needs more information) |

**Auth required:** `attestations:read` or `attestations:write`

**Create request body:**
```json
{
  "patient_id": 1001,
  "provider_npi": "1234567890",
  "hcc_code": "HCC18",
  "hcc_description": "Diabetes with Chronic Complications",
  "icd10_code": "E11.65",
  "icd10_description": "Type 2 diabetes mellitus with hyperglycemia",
  "source": "suspect",
  "encounter_id": 500
}
```

---

## Chart Chase

Prefix: `/api/chart-chase` — tag: `chart-chase`

Track and manage requests for missing medical records. Supports multi-attempt outreach with aging reports.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/chart-chase` | List requests with filters (status, priority, provider) |
| `POST` | `/api/chart-chase` | Create a new chart chase request |
| `GET` | `/api/chart-chase/dashboard` | Aggregated stats and aging report |
| `GET` | `/api/chart-chase/templates` | List outreach templates |
| `POST` | `/api/chart-chase/templates` | Create an outreach template |
| `POST` | `/api/chart-chase/bulk` | Bulk create from a suspect list |
| `GET` | `/api/chart-chase/{id}` | Request detail with attempt history |
| `PUT` | `/api/chart-chase/{id}` | Update mutable fields |
| `POST` | `/api/chart-chase/{id}/attempt` | Log an outreach attempt (call, fax, portal) |
| `PUT` | `/api/chart-chase/{id}/receive` | Mark records received, optionally link a document |
| `PUT` | `/api/chart-chase/{id}/cancel` | Cancel the request |

**Auth required:** `chart_chase:read` or `chart_chase:write`

**Create request body:**
```json
{
  "patient_id": 1001,
  "provider_npi": "1234567890",
  "chase_type": "initial",
  "reason": "suspect_hcc",
  "hcc_codes": [18, 85],
  "dos_from": "2025-01-01",
  "dos_to": "2025-12-31",
  "priority": "high",
  "facility_name": "City Medical Center"
}
```

---

## Reports

Prefix: `/api/reports` — tag: `reports`

All report endpoints require `reports:read` permission.

---

### GET /api/reports/revenue-opportunity

Population-level RAF gap analysis and estimated annual revenue opportunity. Uses the CMS MA benchmark rate of $11,015.04 per RAF point.

**Query params:** `year` (int, defaults to current year)

**Response 200:**
```json
{
  "year": 2026,
  "patients_analyzed": 3210,
  "billed_raf_avg": 1.203,
  "ai_raf_avg": 1.427,
  "raf_gap": 0.224,
  "revenue_opportunity": 7_842_876.48,
  "currency": "USD"
}
```

---

### GET /api/reports/patient-scorecard

Per-patient comparison of billed RAF vs AI-detected RAF.

**Query params:** `year`, `min_gap` (float), `limit`, `offset`

**Response 200:**
```json
{
  "patients": [
    {
      "pid": 1001,
      "name": "Margaret Chen",
      "billed_raf": 1.203,
      "ai_raf": 1.842,
      "gap": 0.639,
      "revenue_opportunity": 7035.61,
      "open_suspects": 2
    }
  ]
}
```

---

### GET /api/reports/hcc-distribution

HCC code frequency and average coefficient across the population.

**Query params:** `year`, `top_n` (int, default 20)

**Response 200:**
```json
{
  "year": 2026,
  "hccs": [
    { "hcc_code": "HCC18", "label": "Diabetes with Chronic Complications", "patient_count": 820, "prevalence_pct": 21.4 }
  ]
}
```

---

### GET /api/reports/suspects-summary

All open suspect conditions across all patients grouped by HCC.

---

### GET /api/reports/recapture-gaps

Active problem list entries not billed in the current measurement year.

---

### GET /api/reports/data-completeness

Data quality metrics: percentage of patients with RAF scores, note analysis coverage, documentation completeness.

---

### GET /api/reports/workflow-summary

Dashboard queue counts for suspects, attestations, chart chases, and care gaps.

---

## Providers

Prefix: `/api/providers` — tag: `providers`

---

### POST /api/providers

Create a new provider record.

**Auth required:** `providers:write`

**Request body:**
```json
{
  "first_name": "James",
  "last_name": "Park",
  "npi": "1234567890",
  "specialty": "Internal Medicine",
  "email": "j.park@health.org",
  "status": "active"
}
```

---

### GET /api/providers

List providers with search and filter.

**Auth required:** `providers:read`

**Query params:** `search`, `specialty`, `status`, `limit`, `offset`

---

### GET /api/providers/leaderboard

All providers ranked by scorecard metrics (RAF capture rate, documentation score, suspect closure rate).

**Auth required:** `providers:read`

---

### GET /api/providers/summary

Aggregate provider statistics across the panel.

**Auth required:** `providers:read`

---

### POST /api/providers/auto-discover

Auto-discover providers from OpenEMR users table. Creates provider records for any OpenEMR users not yet in the RAF system.

**Auth required:** `providers:write`

---

### GET /api/providers/{id}

Provider detail.

**Auth required:** `providers:read`

---

### PUT /api/providers/{id}

Update provider (name, NPI, specialty, email, status).

**Auth required:** `providers:write`

---

### DELETE /api/providers/{id}

Deactivate a provider (soft delete).

**Auth required:** `providers:write`

---

### GET /api/providers/{id}/patients

List patients in the provider's panel.

**Auth required:** `providers:read`

**Query params:** `limit`, `offset`

---

### POST /api/providers/{id}/patients/auto-attribute

Auto-attribute patients to the provider based on encounter history.

**Auth required:** `providers:write`

---

### GET /api/providers/{id}/scorecard

Latest provider scorecard. Recalculates automatically if the cached score is stale (>24 hours).

**Auth required:** `providers:read`

**Response 200:**
```json
{
  "provider_id": 7,
  "npi": "1234567890",
  "name": "Dr. James Park",
  "scorecard": {
    "raf_capture_rate": 0.84,
    "documentation_score": 0.77,
    "suspect_closure_rate": 0.61,
    "awv_completion_rate": 0.52,
    "overall_score": 0.735
  },
  "calculated_at": "2026-04-06T08:00:00Z"
}
```

---

### POST /api/providers/{id}/scorecard/refresh

Force-recalculate the provider scorecard.

**Auth required:** `providers:write`

---

### GET /api/providers/{id}/hcc-performance

Per-HCC capture rates for the provider's panel.

**Auth required:** `providers:read`

---

### GET /api/providers/{id}/alerts

Active performance alerts for the provider.

**Auth required:** `providers:read`

---

### PUT /api/providers/{id}/alerts/{alert_id}/acknowledge

Acknowledge a provider alert.

**Auth required:** `providers:write`

---

## Claims

Prefix: `/api/claims` — tag: `claims`

Ingest 837P, 837I, and CSV claims files. Supports patient matching, HCC mapping, and RAF calculation from claims data.

---

### POST /api/claims/upload

Upload a claims file (CSV, 837P, 837I, .x12, .edi). Max 100 MB. Creates a new batch.

**Auth required:** `claims:write`

**Rate limit:** 10/minute

**Content-Type:** `multipart/form-data`

**Form fields:** `file` — the claims file

**Response 202:**
```json
{
  "batch_id": "batch_c001",
  "filename": "2026_q1_claims.csv",
  "status": "processing",
  "rows_detected": 4200
}
```

---

### GET /api/claims/batches

List all uploaded claim batches.

**Auth required:** `claims:read`

---

### GET /api/claims/batches/{id}

Batch detail with processing statistics (matched patients, HCC codes found, errors).

**Auth required:** `claims:read`

---

### DELETE /api/claims/batches/{id}

Delete a batch and all associated claim records.

**Auth required:** `claims:write`

---

### POST /api/claims/batches/{id}/process

Run patient matching and HCC mapping for a batch.

**Auth required:** `claims:write`

---

### GET /api/claims/batches/{id}/claims

Paginated claim records in a batch.

**Auth required:** `claims:read`

**Query params:** `limit`, `offset`, `patient_id`

---

### GET /api/claims/batches/{id}/diagnoses

ICD-10 codes in the batch with HCC mapping results.

**Auth required:** `claims:read`

---

### GET /api/claims/batches/{id}/hcc-summary

HCC distribution for the batch.

**Auth required:** `claims:read`

---

### GET /api/claims/batches/{id}/unmapped-patients

Claim members not matched to an OpenEMR patient record.

**Auth required:** `claims:read`

---

### POST /api/claims/batches/{id}/calculate-raf

Calculate RAF scores for all patients matched in this batch.

**Auth required:** `claims:write`

**Response 202:** `{ "job_id": "uuid-...", "matched_patients": 312 }`

---

### GET /api/claims/stats

Overall claims statistics across all batches.

**Auth required:** `claims:read`

---

## CMS Submissions (RAPS/EDPS)

Prefix: `/api/submissions` — tag: `submissions`

Manage the full CMS risk-adjustment submission lifecycle for MA plans.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/submissions/generate` | Generate a RAPS or EDPS submission file |
| `GET` | `/api/submissions/batches` | List submission batches |
| `GET` | `/api/submissions/batches/{id}` | Batch detail |
| `GET` | `/api/submissions/batches/{id}/records` | Records in a batch |
| `POST` | `/api/submissions/batches/{id}/validate` | Run CMS validation rules |
| `GET` | `/api/submissions/batches/{id}/validation-report` | Validation summary |
| `POST` | `/api/submissions/batches/{id}/submit` | Mark as submitted and download |
| `GET` | `/api/submissions/batches/{id}/download` | Download the submission file |
| `POST` | `/api/submissions/batches/{id}/upload-response` | Upload MAO-002/MAO-004 reply from CMS |
| `GET` | `/api/submissions/batches/{id}/responses` | List response files |
| `GET` | `/api/submissions/batches/{id}/reconciliation` | Payment reconciliation data |
| `GET` | `/api/submissions/batches/{id}/errors` | Error records for correction |
| `GET` | `/api/submissions/schedule` | CMS submission deadlines |
| `POST` | `/api/submissions/schedule` | Add or update a custom deadline |
| `GET` | `/api/submissions/stats` | Overall submission statistics |

**Auth required:** `submissions:read` or `submissions:write`

**Generate request body:**
```json
{
  "submission_type": "RAPS",
  "plan_id": "H1234",
  "contract_number": "H1234001",
  "payment_year": 2026,
  "data_year": 2025,
  "patient_ids": [1001, 1002, 1003]
}
```

---

## EMR Integration

Prefix: `/api/emr` — tag: `emr`

Manage EMR connections. Supports direct database connections (MySQL, PostgreSQL, MSSQL, Oracle), FHIR R4, and REST API connection types.

---

### GET /api/emr/vendors

List all supported EMR vendor presets with default connection settings.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "vendors": [
    { "vendor": "openemr", "display_name": "OpenEMR", "default_port": 3306, "connection_type": "direct_db" },
    { "vendor": "epic", "display_name": "Epic", "connection_type": "fhir_r4" },
    { "vendor": "cerner", "display_name": "Cerner", "connection_type": "fhir_r4" }
  ]
}
```

---

### GET /api/emr/vendors/{vendor}

Get a single vendor preset with defaults populated.

**Auth required:** Bearer JWT

---

### POST /api/emr/connections

Create a new EMR connection.

**Auth required:** admin role

**Request body (direct_db example):**
```json
{
  "name": "OpenEMR Production",
  "vendor": "openemr",
  "connection_type": "direct_db",
  "db_host": "10.1.2.216",
  "db_port": 3306,
  "db_name": "openemr",
  "db_username": "rafuser",
  "db_password": "secret",
  "db_type": "mysql",
  "is_active": true
}
```

**Request body (fhir_r4 example):**
```json
{
  "name": "Epic FHIR",
  "vendor": "epic",
  "connection_type": "fhir_r4",
  "fhir_base_url": "https://ehr.example.com/fhir/r4",
  "auth_type": "oauth2",
  "token_url": "https://ehr.example.com/oauth/token",
  "client_id": "raf-app",
  "client_secret": "..."
}
```

**Response 201:** Connection record with credentials masked.

---

### GET /api/emr/connections

List all connections. Credentials are always masked in responses.

**Auth required:** Bearer JWT

---

### GET /api/emr/connections/{id}

Get one connection (credentials masked).

**Auth required:** Bearer JWT

---

### PUT /api/emr/connections/{id}

Update an existing connection.

**Auth required:** admin role

---

### DELETE /api/emr/connections/{id}

Delete a connection.

**Auth required:** admin role

---

### POST /api/emr/connections/{id}/test

Test connectivity for a connection. Returns latency and error details.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "success": true,
  "latency_ms": 24,
  "patient_count": 3840,
  "message": "Connection OK"
}
```

---

### POST /api/emr/connections/{id}/sync

Trigger a full data sync for a connection.

**Auth required:** admin role

**Response 202:** `{ "job_id": "uuid-...", "message": "Sync started" }`

---

### GET /api/emr/connections/{id}/sync/history

Sync history for a connection (last N syncs with status and duration).

**Auth required:** Bearer JWT

---

### GET /api/emr/connections/{id}/mappings

Get field mappings for a connection (maps EMR fields to RAF system fields).

**Auth required:** Bearer JWT

---

### PUT /api/emr/connections/{id}/mappings

Update field mappings.

**Auth required:** admin role

---

## FHIR R4 Integration

Prefix: `/api/fhir` — tag: `fhir`

Dedicated FHIR R4 connection management with sync, patient mapping, and condition processing into the HCC pipeline.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/fhir/connections` | Register a FHIR server (Epic, Cerner, athenahealth, generic) |
| `GET` | `/api/fhir/connections` | List connections |
| `GET` | `/api/fhir/connections/{id}` | Single connection |
| `PUT` | `/api/fhir/connections/{id}` | Update connection |
| `DELETE` | `/api/fhir/connections/{id}` | Remove connection |
| `POST` | `/api/fhir/connections/{id}/test` | Test connectivity |
| `POST` | `/api/fhir/sync/{connection_id}` | Trigger full FHIR sync |
| `GET` | `/api/fhir/sync/{connection_id}/status` | Sync history and current status |
| `GET` | `/api/fhir/patients/{connection_id}` | List patients synced from FHIR |
| `POST` | `/api/fhir/patients/{connection_id}/map` | Map a FHIR patient to an OpenEMR pid |
| `GET` | `/api/fhir/conditions/{connection_id}` | List synced conditions |
| `GET` | `/api/fhir/conditions/{connection_id}/unmapped` | Conditions not yet HCC-mapped |
| `POST` | `/api/fhir/conditions/{connection_id}/process` | Process conditions into HCC and RAF pipeline |

**Auth required:** `fhir:read` or `fhir:write`

**Create connection request body:**
```json
{
  "name": "Epic Sandbox",
  "vendor": "epic",
  "base_url": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4",
  "auth_type": "oauth2",
  "token_url": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token",
  "client_id": "my-client-id",
  "client_secret": "my-secret"
}
```

---

## SMART on FHIR

Prefix: `/api/smart` — tag: `smart_fhir`

Supports EHR-launch and standalone-launch flows for in-EHR app launch.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/smart/launch` | None | Initiate EHR-launch or standalone-launch |
| `GET` | `/api/smart/callback` | None | OAuth2 authorization callback |
| `GET` | `/api/smart/context` | Bearer JWT | Current SMART context for this session |
| `GET` | `/api/smart/patient` | Bearer JWT | FHIR Patient resource for the session patient |
| `GET` | `/api/smart/sessions` | Bearer JWT | Active/recent SMART sessions |
| `GET` | `/api/smart/.well-known/smart-configuration` | None | App SMART metadata |
| `POST` | `/api/smart/registrations` | admin | Register an EHR app |
| `GET` | `/api/smart/registrations` | admin | List registrations |
| `PUT` | `/api/smart/registrations/{id}` | admin | Update a registration |
| `DELETE` | `/api/smart/registrations/{id}` | admin | Delete a registration |

---

## ADT Feed

Prefix: `/api/adt` — tag: `adt`

Real-time HL7v2 ADT message listener via MLLP. Processes Admit, Discharge, Transfer events and triggers suspect scans and care gap updates.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/adt/connections` | List ADT MLLP connection configs |
| `POST` | `/api/adt/connections` | Create a new MLLP listener config |
| `PUT` | `/api/adt/connections/{id}` | Update config |
| `POST` | `/api/adt/connections/{id}/start` | Start the MLLP listener |
| `POST` | `/api/adt/connections/{id}/stop` | Stop the MLLP listener |
| `GET` | `/api/adt/connections/{id}/status` | Listener runtime health |
| `GET` | `/api/adt/messages` | List received ADT messages |
| `GET` | `/api/adt/messages/{id}` | Message detail with raw HL7 |
| `POST` | `/api/adt/messages/replay/{id}` | Reprocess a stored message |
| `GET` | `/api/adt/subscriptions` | List webhook subscriptions for ADT events |
| `POST` | `/api/adt/subscriptions` | Subscribe to ADT event types |
| `GET` | `/api/adt/dashboard` | Volume and error-rate aggregates |

**Auth required:** Bearer JWT + `adt:read` or `adt:write`

---

## Clearinghouse (Eligibility)

Prefix: `/api/clearinghouse` — tag: (clearinghouse)

Real-time insurance eligibility verification via ANSI X12 270/271 transactions and modern REST APIs.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/clearinghouse/connections` | Create a clearinghouse connection |
| `GET` | `/api/clearinghouse/connections` | List connections |
| `PUT` | `/api/clearinghouse/connections/{id}` | Update a connection |
| `POST` | `/api/clearinghouse/connections/{id}/test` | Test reachability |
| `POST` | `/api/clearinghouse/check` | Single real-time eligibility check |
| `POST` | `/api/clearinghouse/batch` | Batch eligibility verification |
| `GET` | `/api/clearinghouse/checks` | List checks with filters |
| `GET` | `/api/clearinghouse/checks/{id}` | Check detail (includes 270/271 payloads) |
| `GET` | `/api/clearinghouse/batch/{id}` | Batch status and progress |
| `GET` | `/api/clearinghouse/dashboard` | Aggregate statistics |

**Auth required:** Bearer JWT

**Single eligibility check request body:**
```json
{
  "patient_id": 1001,
  "payer_id": "00590",
  "dos": "2026-04-06",
  "service_type_code": "30"
}
```

---

## Direct Messaging

Prefix: `/api/direct` — tag: `direct_messaging`

Secure provider-to-provider messaging via the Direct Project protocol (S/MIME over SMTP).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/direct/dashboard` | Aggregate messaging stats |
| `GET` | `/api/direct/messages` | Inbox/sent with filters |
| `POST` | `/api/direct/messages` | Compose and send a message |
| `GET` | `/api/direct/messages/{id}` | Message detail with attachments |
| `PUT` | `/api/direct/messages/{id}/read` | Mark as read |
| `DELETE` | `/api/direct/messages/{id}` | Delete a message |
| `GET` | `/api/direct/addresses` | Managed Direct addresses |
| `POST` | `/api/direct/addresses` | Register a new Direct address |
| `PUT` | `/api/direct/addresses/{id}` | Update an address record |
| `GET` | `/api/direct/addresses/search` | Address book / directory search |
| `GET` | `/api/direct/trust-anchors` | List trust bundles |
| `POST` | `/api/direct/trust-anchors` | Add a trust anchor |

**Auth required:** Bearer JWT

---

## Prospective RAF

Prefix: `/api/prospective` — tag: `prospective`

Pre-visit and population prospective RAF management tools.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/prospective/worklist` | Priority-ranked patient worklist for outreach |
| `GET` | `/api/prospective/worklist/{pid}/pre-visit-summary` | Pre-visit RAF summary for a patient |
| `GET` | `/api/prospective/awv-eligible` | AWV-eligible patients not yet scheduled |
| `POST` | `/api/prospective/awv/{pid}/mark-scheduled` | Mark a patient's AWV as scheduled |
| `GET` | `/api/prospective/chase-list` | Export outreach chase list as CSV |
| `GET` | `/api/prospective/summary` | Population prospective summary statistics |

**Auth required:** `patients:read` (read endpoints), `patients:write` (write endpoints)

---

## Annual Wellness Visits (AWV)

Prefix: `/api/awv` — tag: `awv`

Scheduling, outreach tracking, visit checklists, and results for Annual Wellness Visits.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/awv` | List AWV schedules with filters |
| `POST` | `/api/awv` | Create a new AWV schedule record |
| `GET` | `/api/awv/eligible` | Patients eligible for AWV |
| `GET` | `/api/awv/dashboard` | Completion rates and revenue impact |
| `POST` | `/api/awv/bulk-outreach` | Generate a bulk outreach campaign |
| `GET` | `/api/awv/{id}` | Single AWV schedule detail |
| `PUT` | `/api/awv/{id}` | Partial update of an AWV schedule |
| `PUT` | `/api/awv/{id}/schedule` | Set appointment date/time |
| `PUT` | `/api/awv/{id}/complete` | Mark completed with clinical results |
| `POST` | `/api/awv/{id}/outreach` | Log an outreach contact attempt |
| `GET` | `/api/awv/{id}/checklist` | Get the full visit checklist |
| `PUT` | `/api/awv/{id}/checklist/{item_id}` | Mark a checklist item complete or incomplete |

**Auth required:** `patients:read` or `patients:write`

---

## Quality Measures (HEDIS / STARS)

Prefix: `/api/quality` — tag: `quality`

HEDIS quality measure evaluation and CMS STARS rating estimation.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/quality/measures` | List all tracked HEDIS measures |
| `GET` | `/api/quality/measures/{code}` | Measure detail with population stats |
| `GET` | `/api/quality/patients/{pid}` | All quality measures for a single patient |
| `GET` | `/api/quality/gaps` | Patients with open care gaps |
| `GET` | `/api/quality/summary` | Population quality dashboard |
| `GET` | `/api/quality/stars-estimate` | Estimated CMS STARS rating |
| `GET` | `/api/quality/overlap` | RAF/HEDIS HCC overlap analysis |

**Auth required:** `quality:read`

---

## Care Gaps

Prefix: `/api/care-gaps` — tag: `care_gaps`

Care gap closure workflow. Tasks are assigned to clinical staff and tracked through resolution.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/care-gaps` | List with filters and pagination |
| `POST` | `/api/care-gaps` | Create a gap task |
| `GET` | `/api/care-gaps/dashboard` | Summary statistics |
| `POST` | `/api/care-gaps/bulk-assign` | Bulk-assign tasks to a user |
| `POST` | `/api/care-gaps/generate` | Auto-generate tasks from open suspects |
| `GET` | `/api/care-gaps/{id}` | Task detail with comments and history |
| `PUT` | `/api/care-gaps/{id}` | Partial update |
| `PUT` | `/api/care-gaps/{id}/assign` | Assign to a user |
| `PUT` | `/api/care-gaps/{id}/status` | Transition status |
| `POST` | `/api/care-gaps/{id}/comments` | Add a comment |

**Auth required:** `care_gaps:read` or `care_gaps:write`

---

## Cohorts

Prefix: `/api/cohorts` — tag: `cohorts`

Dynamic patient population management with point-in-time snapshots and cohort comparisons.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/cohorts` | Create a cohort from filter criteria |
| `GET` | `/api/cohorts` | List cohorts |
| `GET` | `/api/cohorts/population-health` | Global population metrics |
| `GET` | `/api/cohorts/{id}` | Cohort detail with summary stats |
| `PUT` | `/api/cohorts/{id}` | Update criteria or metadata |
| `DELETE` | `/api/cohorts/{id}` | Archive cohort |
| `GET` | `/api/cohorts/{id}/members` | Paginated member list |
| `POST` | `/api/cohorts/{id}/refresh` | Refresh dynamic membership |
| `POST` | `/api/cohorts/{id}/snapshot` | Take a point-in-time snapshot |
| `GET` | `/api/cohorts/{id}/trends` | Historical snapshots |
| `POST` | `/api/cohorts/compare` | Compare two cohorts |
| `GET` | `/api/cohorts/comparisons/{id}` | Comparison result detail |
| `GET` | `/api/cohorts/{id}/export` | Export cohort as CSV |

**Auth required:** `cohorts:read` or `cohorts:write`

**Create cohort request body:**
```json
{
  "name": "High-RAF Diabetic Panel",
  "description": "Patients with RAF > 1.5 and HCC18",
  "criteria": {
    "min_raf": 1.5,
    "hcc_codes": [18],
    "provider_id": 7
  },
  "is_dynamic": true
}
```

---

## Coder Worklist

Prefix: `/api/worklist` — tag: `worklist`

Review queue for coders to evaluate NLP-extracted and claims-derived diagnoses before attestation.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/worklist` | Bearer JWT | Coder's queue (paginated, filterable) |
| `GET` | `/api/worklist/next` | Bearer JWT | Claim the next available item |
| `GET` | `/api/worklist/stats` | Bearer JWT | Coder productivity metrics |
| `GET` | `/api/worklist/{id}` | Bearer JWT | Single item detail |
| `PUT` | `/api/worklist/{id}/start` | Bearer JWT | Move item to in_progress |
| `PUT` | `/api/worklist/{id}/complete` | Bearer JWT | Complete with coding decisions |
| `PUT` | `/api/worklist/{id}/escalate` | Bearer JWT | Escalate to supervisor |
| `PUT` | `/api/worklist/{id}/return` | Bearer JWT | Return for additional clinical info |
| `POST` | `/api/worklist/assign` | worklist:manage | Manual assignment (manager/admin) |
| `POST` | `/api/worklist/auto-queue` | worklist:manage | Trigger auto-assignment from source data |

---

## Webhooks

Prefix: `/api/webhooks` — tag: `webhooks`

Register HTTPS endpoints to receive real-time event notifications. Events are delivered via signed `POST` requests. The signature is computed as `HMAC-SHA256(payload, secret)` in the `X-RAF-Signature` header.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/webhooks` | Register a new webhook |
| `GET` | `/api/webhooks` | List webhooks for the tenant |
| `GET` | `/api/webhooks/events` | Available event types with descriptions |
| `GET` | `/api/webhooks/{id}` | Webhook detail |
| `PUT` | `/api/webhooks/{id}` | Update a webhook |
| `DELETE` | `/api/webhooks/{id}` | Delete a webhook |
| `POST` | `/api/webhooks/{id}/test` | Send a test event |
| `GET` | `/api/webhooks/{id}/deliveries` | Delivery history (status, response code) |

**Auth required:** Bearer JWT

**Create webhook request body:**
```json
{
  "url": "https://your-system.com/raf-events",
  "events": ["suspect.created", "raf.calculated", "document.analyzed"],
  "secret": "your-hmac-secret-min-16-chars",
  "description": "Production event sink"
}
```

**Available events (from `GET /api/webhooks/events`):** `suspect.created`, `suspect.accepted`, `suspect.dismissed`, `raf.calculated`, `document.analyzed`, `document.approved`, `attestation.created`, `attestation.completed`, `sync.completed`, `sync.failed`, `care_gap.created`, `care_gap.closed`

---

## Notifications

Prefix: `/api/notifications` — tag: `notifications`

Email notification configuration and per-user preferences.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/notifications/config` | SMTP config status (no credentials exposed) |
| `POST` | `/api/notifications/test` | Send a test email to the current user |
| `GET` | `/api/notifications/preferences` | Current user's notification preferences |
| `PUT` | `/api/notifications/preferences` | Update notification preferences |

**Auth required:** Bearer JWT

**Preferences request body:**
```json
{
  "analysis_complete": true,
  "submission_deadline": true,
  "care_gap_alerts": true,
  "suspect_alerts": false,
  "sync_failure_alerts": true
}
```

---

## Jobs

Prefix: `/api/jobs` — tag: `jobs`

Monitor and manage Celery background tasks. All queries are tenant-scoped — users cannot see jobs from other tenants.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | List jobs for the tenant (filter by status, task_name) |
| `GET` | `/api/jobs/stats` | Aggregate counts by status |
| `GET` | `/api/jobs/{job_id}` | Job detail with Celery progress meta |
| `DELETE` | `/api/jobs/{job_id}` | Cancel a pending or running job |

**Auth required:** `jobs:read` (list/get), `jobs:write` (cancel)

**Job status values:** `pending`, `started`, `progress`, `success`, `failure`, `revoked`

**Job detail response:**
```json
{
  "id": "uuid-...",
  "task_name": "calculate_raf_batch",
  "status": "progress",
  "progress": 1840,
  "total": 3840,
  "started_at": "2026-04-06T09:00:00Z",
  "celery_meta": { "current": 1840, "total": 3840, "status": "Processing patients..." }
}
```

---

## BI Export

Prefix: `/api/bi` — tag: `bi_export`

Export datasets to Tableau, PowerBI, Looker, Metabase, and generic OData / CSV / JSON / Excel consumers.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/bi/datasets` | List available datasets |
| `POST` | `/api/bi/datasets` | Create a custom dataset |
| `GET` | `/api/bi/datasets/{id}` | Dataset detail with query template |
| `PUT` | `/api/bi/datasets/{id}` | Update dataset metadata or query |
| `POST` | `/api/bi/datasets/{id}/refresh` | Trigger synchronous data refresh |
| `GET` | `/api/bi/datasets/{id}/download` | Download as CSV / JSON / Excel |
| `GET` | `/api/bi/datasets/{id}/preview` | First 100 rows as JSON |
| `GET` | `/api/bi/datasets/{id}/schema` | Column schema for BI tool import |
| `POST` | `/api/bi/connections` | Register a BI tool connection |
| `GET` | `/api/bi/connections` | List BI connections |
| `POST` | `/api/bi/connections/{id}/push` | Push dataset to the configured BI tool |
| `GET` | `/api/bi/export-log` | Paginated export audit history |
| `GET` | `/api/bi/tableau/wdc` | Tableau Web Data Connector HTML page |
| `GET` | `/api/bi/odata/{dataset_name}` | OData v4 feed for PowerBI "Get Data → OData" |

**Auth required:** Bearer JWT

**Download query params:** `format` — `csv`, `json`, `xlsx` (default `csv`)

---

## Audit Packages (RADV)

Prefix: `/api/audit` — tag: `audit`

Generate RADV-ready PDF audit packages for individual patients. Packages include RAF breakdown, MEAT evidence, suspect conditions, and documentation links.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/audit/generate/{pid}` | Generate a RADV audit PDF for a patient |
| `GET` | `/api/audit/packages` | List previously generated packages |
| `GET` | `/api/audit/download/{fname}` | Download a PDF by filename |

**Auth required:** `audit:write` (generate), `audit:read` (list/download)

**Generate request body:**
```json
{
  "year": 2026,
  "model_segment": "CNA",
  "include_suspects": true,
  "recalculate": false
}
```

**Response 200:**
```json
{
  "pid": 1001,
  "filename": "radv_1001_2026.pdf",
  "download_url": "/api/audit/download/radv_1001_2026.pdf",
  "generated_at": "2026-04-06T09:30:00Z"
}
```

---

## Benchmarks

Prefix: `/api/benchmarks` — tag: `benchmarks`

Accuracy benchmarking for the RAF Intelligence NLP pipeline against gold-standard clinical test cases.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/benchmarks/run` | admin role | Run the full accuracy benchmark |
| `GET` | `/api/benchmarks/results` | Bearer JWT | Latest benchmark run results |
| `GET` | `/api/benchmarks/results/history` | Bearer JWT | Historical benchmark run summaries |
| `GET` | `/api/benchmarks/test-cases` | Bearer JWT | List built-in gold-standard test cases |
| `POST` | `/api/benchmarks/test-cases/custom` | Bearer JWT | Run pipeline against a custom test case |

**Benchmark result response:**
```json
{
  "run_id": "uuid-...",
  "precision": 0.923,
  "recall": 0.887,
  "f1_score": 0.905,
  "total_cases": 50,
  "passed": 46,
  "failed": 4,
  "run_at": "2026-04-06T08:00:00Z"
}
```

---

## Real-Time Dashboard

Prefix: `/api/realtime` — tag: `realtime`

SSE and WebSocket feeds for live dashboard updates, plus persistent alert management.

---

### GET /api/realtime/events (SSE)

Server-Sent Events stream. Delivers live RAF score updates, sync events, suspect alerts, and KPI changes.

**Auth:** Pass `?token=<access_token>` as a query parameter (browsers cannot set Authorization headers on EventSource).

```
GET /api/realtime/events?token=eyJhbGciOiJIUzI1NiIs...
Accept: text/event-stream
```

**Events pushed:**
```
event: kpi_update
data: {"average_raf": 1.427, "patients_analyzed": 3210, "timestamp": "..."}

event: suspect_alert
data: {"patient_id": 1001, "hcc": "HCC18", "confidence": 0.94}
```

---

### WS /api/realtime/ws (WebSocket)

Bidirectional WebSocket. Pass `?token=<access_token>` for authentication. Supports client-sent subscription messages to filter event types.

---

### Alert Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/realtime/alerts` | List persisted alerts for current user |
| `PUT` | `/api/realtime/alerts/{id}/read` | Mark a single alert as read |
| `PUT` | `/api/realtime/alerts/read-all` | Mark all alerts as read |
| `GET` | `/api/realtime/alerts/unread-count` | Badge count for the UI |

**Auth required:** Bearer JWT

---

### Dashboard Configs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/realtime/dashboards` | Save a dashboard layout config |
| `GET` | `/api/realtime/dashboards` | List user's saved dashboard configs |
| `PUT` | `/api/realtime/dashboards/{id}` | Update a dashboard config |
| `DELETE` | `/api/realtime/dashboards/{id}` | Delete a dashboard config |

---

### GET /api/realtime/kpi

Live KPI snapshot (patients analyzed, average RAF, open suspects, revenue opportunity).

**Auth required:** Bearer JWT

---

## Admin

Prefix: `/api/admin` and `/api/admin/retention` — tag: `admin`

All admin endpoints require the `admin` role.

---

### Backup Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/backups` | List backup files with sizes and timestamps |
| `POST` | `/api/admin/backups/trigger` | Trigger a manual backup |
| `GET` | `/api/admin/backups/schedule` | Get backup schedule config |
| `GET` | `/api/admin/backups/jobs` | Backup job history |
| `GET` | `/api/admin/backups/{filename}/download` | Download a backup file |

**Trigger backup request body:**
```json
{ "backup_type": "full" }
```

`backup_type` values: `full`, `raf`, `openemr`

---

### System Information

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/system` | OS, Python version, disk usage, uptime |

---

### Data Retention (HIPAA)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/retention` | Retention policies and current data age |
| `PUT` | `/api/admin/retention/{resource}` | Update retention period for a resource |
| `POST` | `/api/admin/retention/sweep` | Run a manual retention sweep |

**Update retention request body:**
```json
{ "retention_days": 2555 }
```

---

### Error Monitoring

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/errors` | Recent captured errors (`limit` query param, max 100) |
| `GET` | `/api/admin/errors/stats` | Aggregate error counts by exception type |
| `POST` | `/api/admin/errors/report` | Report a client-side error (no auth required) |

---

## ICD-10 Lookup

**Auth required:** Bearer JWT

### GET /api/icd10/validate/{code}

Validate an ICD-10-CM code and return description and HCC mapping.

**Response 200:**
```json
{
  "code": "E1165",
  "input": "E11.65",
  "valid": true,
  "info": {
    "description": "Type 2 diabetes mellitus with hyperglycemia",
    "billable": true,
    "hcc_v24": "HCC18",
    "hcc_v28": "HCC37"
  }
}
```

### GET /api/icd10/search

Full-text search across ICD-10-CM descriptions.

**Query params:** `query` (string, required), `max_results` (int, 1–200, default 20)

**Response 200:**
```json
{
  "query": "diabetes chronic",
  "count": 12,
  "results": [
    { "code": "E1165", "description": "Type 2 diabetes mellitus with hyperglycemia", "hcc": "HCC18" }
  ]
}
```

---

## Compliance Status

### GET /api/compliance/status

Returns the current HIPAA compliance posture of this deployment.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "hipaa_compliant": true,
  "status": "compliant",
  "checks": {
    "jwt_secret_configured": true,
    "tls_enforced": true,
    "mfa_available": true,
    "audit_logging": true,
    "rbac_enforced": true,
    "rate_limiting": true,
    "access_token_expiry_minutes": 30,
    "encryption_in_transit": true,
    "security_headers": true,
    "phi_access_logging": true,
    "baa_provider": "Google Cloud (Gemini)"
  },
  "assessed_at": "2026-04-06T09:00:00Z"
}
```

---

## Health Checks

No authentication required on health endpoints. Safe for load-balancer probes.

### GET /health

Full health check. Returns 200 if all dependencies are healthy, 503 if degraded. Includes database connectivity, Gemini model, scheduler status, and error statistics.

**Response 200:**
```json
{
  "status": "healthy",
  "databases": { "raf": true, "openemr": true },
  "gemini_model": "gemini-1.5-pro",
  "sync_scheduler": { "running": true, "next_run": "2026-04-06T10:00:00Z" },
  "monitoring": { "total_errors": 0, "errors_last_hour": 0 }
}
```

**Response 503:** Same shape with `"status": "degraded"` and one or more `databases` entries set to `false`.

---

### GET /health/ready

Kubernetes-style readiness probe. Returns 503 if ANY critical dependency fails.

**Response 200:**
```json
{
  "ready": true,
  "checks": {
    "databases": true,
    "redis": true,
    "gemini_api_key": true
  }
}
```

---

### GET /

Root ping.

**Response 200:**
```json
{
  "service": "RAF Intelligence API",
  "version": "2.0.0",
  "status": "running",
  "docs": "/docs"
}
```

---

## Dashboard Utilities

### GET /api/dashboard/stats

Quick population stats for the main dashboard.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "total_patients": 3840,
  "patients_analyzed": 3210,
  "average_raf": 1.427,
  "coverage_pct": 83.6
}
```

Returns all zeros if no active EMR connection is configured.

---

### GET /api/dashboard/trends

Period-over-period trend data (current 30 days vs prior 30 days).

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "period": "30d",
  "patients_analyzed": {
    "current": 3210,
    "prior": 2980,
    "change_pct": 7.7
  },
  "average_raf": {
    "current": 1.427,
    "prior": 1.388,
    "change_pct": 2.8
  }
}
```

---

### GET /api/insights

Data-driven clinical intelligence insights derived from live database state. Each insight is independently generated; a single failing query does not block others.

**Auth required:** Bearer JWT

**Response 200:**
```json
{
  "insights": [
    {
      "id": "uuid-...",
      "type": "suspect_opportunity",
      "title": "286 open suspect conditions detected",
      "detail": "Potential RAF uplift of 0.42 per patient on average",
      "severity": "high",
      "generated_at": "2026-04-06T09:00:00Z"
    }
  ]
}
```

---

## Error Reference

All error responses follow a consistent shape:

```json
{
  "detail": "Human-readable error description",
  "request_id": "uuid-..."
}
```

For validation errors (422), `detail` is an array of Pydantic error objects:
```json
{
  "detail": [
    { "loc": ["body", "email"], "msg": "value is not a valid email address", "type": "value_error.email" }
  ]
}
```

| HTTP Code | Meaning |
|-----------|---------|
| 400 | Bad request — invalid input not caught by validation |
| 401 | Unauthenticated — missing or expired JWT |
| 403 | Forbidden — valid token but insufficient role or permission |
| 404 | Resource not found |
| 409 | Conflict — duplicate resource |
| 413 | Payload too large — file upload exceeds 100 MB |
| 422 | Validation error — request body failed Pydantic validation |
| 429 | Rate limit exceeded — check `Retry-After` header |
| 503 | Service unavailable — no active EMR connection or dependency failure. Check `Retry-After` header. |
| 500 | Internal server error — see `request_id` for log correlation |

**No active EMR connection (503):**
```json
{
  "detail": "No active EMR connection configured. Add a connection via the EMR Config page.",
  "emr_connected": false
}
```

---

## Interactive Documentation

Available in non-production environments only:

| URL | Description |
|-----|-------------|
| `/docs` | Swagger UI with try-it-now functionality |
| `/redoc` | ReDoc read-only reference |
| `/openapi.json` | Raw OpenAPI 3.1 schema |
