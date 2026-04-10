# RAF Intelligence — Database Migration Reference

**Database:** `raf_intelligence`  
**Engine:** InnoDB | Charset: utf8mb4_unicode_ci | MySQL 8.0+  
**Total tables (migrations + schema):** 42  
**Last audited:** 2026-04-01

---

## Table of Contents

1. [Table Inventory](#table-inventory)
2. [Execution Order](#execution-order)
3. [Foreign Key Dependency Map](#foreign-key-dependency-map)
4. [FK Conflicts Found](#fk-conflicts-found)
5. [Auto-DDL Conflicts (Service Layer)](#auto-ddl-conflicts-service-layer)
6. [Tables Not Covered by Any Migration](#tables-not-covered-by-any-migration)
7. [Fresh Install Instructions](#fresh-install-instructions)
8. [Upgrade Instructions](#upgrade-instructions)
9. [Migration File Summaries](#migration-file-summaries)

---

## Table Inventory

### schema.sql — Core RAF Engine (14 tables)

| # | Table | Purpose |
|---|-------|---------|
| 1 | `hcc_icd10_crosswalk` | ICD-10 to HCC V28 mapping; reference data loaded from CMS files |
| 2 | `hcc_raf_coefficients` | RAF weight coefficients per HCC per model segment (CNA, CFA, etc.) |
| 3 | `hcc_demographic_coefficients` | Age/sex base score weights per model segment |
| 4 | `hcc_hierarchy_rules` | HCC trumping rules — higher-severity HCC suppresses lower |
| 5 | `hcc_interaction_terms` | Combination bonus scores when multiple HCCs co-exist |
| 6 | `raf_patient_demographics` | Patient demographic factors for RAF calculation; root FK anchor |
| 7 | `raf_patient_hcc` | Per-patient coded HCC conditions with MEAT status |
| 8 | `raf_scores` | Calculated RAF scores with full demographic/disease/interaction breakdown |
| 9 | `raf_suspect_conditions` | AI-flagged missing diagnoses awaiting provider review |
| 10 | `raf_meat_evidence` | MEAT documentation evidence per patient HCC per encounter |
| 11 | `raf_medication_signals` | Drug-to-HCC inference rules (seeded with 60+ rules) |
| 12 | `raf_lab_signals` | Abnormal lab threshold rules mapped to suspect HCCs (seeded with 25+ rules) |
| 13 | `raf_nlp_jobs` | AI/NLP pipeline job queue and result tracking |
| 14 | `raf_audit_packages` | Generated PDF audit report packages per patient per year |

### 001_fhir_integration.sql — FHIR R4 Data Ingestion (6 tables)

| # | Table | Purpose |
|---|-------|---------|
| 15 | `fhir_connections` | EHR connection configurations (Epic, Cerner, athenahealth, OpenEMR) |
| 16 | `fhir_sync_log` | Immutable audit trail of every FHIR sync operation |
| 17 | `fhir_patient_mapping` | Identity bridge between FHIR Patient IDs and OpenEMR pids |
| 18 | `fhir_conditions` | Ingested FHIR R4 Condition resources with extracted ICD-10 codes |
| 19 | `fhir_encounters` | Ingested FHIR R4 Encounter resources |
| 20 | `fhir_diagnostic_reports` | Ingested FHIR R4 DiagnosticReport resources (labs, imaging) |

### 002_claims_ingestion.sql — Claims Data Processing (5 tables)

| # | Table | Purpose |
|---|-------|---------|
| 21 | `claims_batches` | Uploaded claim file registry; lifecycle tracking per file |
| 22 | `claims_professional` | Parsed 837P/CMS-1500 professional claim headers |
| 23 | `claims_institutional` | Parsed 837I/UB-04 institutional claim headers |
| 24 | `claims_diagnosis_lines` | All ICD-10 codes attached to a claim (shared by professional + institutional) |
| 25 | `claims_service_lines` | CPT/HCPCS procedure lines (shared by professional + institutional) |

### 003_providers.sql — Provider Registry & Scorecards (5 tables)

| # | Table | Purpose |
|---|-------|---------|
| 26 | `providers` | Provider registry keyed by NPI; supports multi-tenant |
| 27 | `provider_patient_panel` | Patient attribution/assignment to providers |
| 28 | `provider_scorecard_snapshots` | Point-in-time performance snapshots per provider per year |
| 29 | `provider_hcc_performance` | Per-HCC capture rates and revenue at stake per provider per year |
| 30 | `provider_alerts` | Actionable patient-level alerts routed to providers |

### 004_documents.sql — Document Upload & Gemini Vision (4 tables + 1 ALTER)

| # | Table | Purpose |
|---|-------|---------|
| 31 | `document_batches` | Multi-document upload session grouping |
| 32 | `documents` | Clinical documents uploaded for Gemini Vision extraction |
| 33 | `document_analysis` | Gemini Vision extraction results per document per run |
| 34 | `document_diagnosis_lines` | Normalised per-code reviewer workflow rows extracted from documents |
| — | `ALTER documents ADD batch_id` | Back-reference FK from documents to document_batches |

### 005_authentication.sql — Users & Access Control (6 tables + seed data)

| # | Table | Purpose |
|---|-------|---------|
| 35 | `users` | Application users with RBAC, MFA, and account lockout |
| 36 | `user_sessions` | Active JWT and refresh token session tracking |
| 37 | `user_permissions` | Granular per-user permission overrides |
| 38 | `audit_log` | Immutable PHI access and mutation audit trail (BIGINT PK for volume) |
| 39 | `password_reset_tokens` | Single-use password recovery tokens |
| 40 | `role_default_permissions` | Default permission matrix per role (seeded with full RBAC matrix) |

### 006_raps_edps_submission.sql — CMS Submission Management (5 tables + seed data)

| # | Table | Purpose |
|---|-------|---------|
| 41 | `submission_batches` | CMS submission batch header; one row per submitted file |
| 42 | `submission_records` | Individual RAPS/EDPS/EDGE detail records with CMS response disposition |
| 43 | `submission_response_files` | CMS response files received per batch (MAO-002, MAO-004) |
| 44 | `submission_schedule` | CMS deadline calendar per payment year, sweep, and program type |
| 45 | `submission_validation_rules` | Configurable registry of pre-submission validation rules (seeded) |

---

## Execution Order

The scripts must be applied in this exact sequence. Each migration depends on objects created by earlier steps.

```
1. schema.sql                    (creates database + 14 core RAF tables + seeds medication/lab signals)
2. 001_fhir_integration.sql      (depends on: none from schema directly; adds fhir_connections root)
3. 002_claims_ingestion.sql      (depends on: none from earlier migrations)
4. 003_providers.sql             (depends on: hcc_icd10_crosswalk from schema.sql)
5. 004_documents.sql             (depends on: none from earlier migrations)
6. 005_authentication.sql        (depends on: providers from 003)
7. 006_raps_edps_submission.sql  (depends on: none from earlier migrations)
```

**Intra-file dependency order within schema.sql:**

```
hcc_icd10_crosswalk
  └── hcc_raf_coefficients (no FK, but logically dependent)
  └── hcc_hierarchy_rules  (no FK, but logically dependent)
  └── provider_hcc_performance (FK in 003) -> hcc_icd10_crosswalk.hcc_code

raf_patient_demographics
  └── raf_patient_hcc        (FK: patient_id + measurement_year)
  └── raf_scores             (FK: patient_id + measurement_year)
  └── raf_suspect_conditions (FK: patient_id + measurement_year)

raf_patient_hcc
  └── raf_meat_evidence      (FK: patient_hcc_id)
```

---

## Foreign Key Dependency Map

```
hcc_icd10_crosswalk <──────────────────── provider_hcc_performance.hcc_code (003)

raf_patient_demographics <─────────────── raf_patient_hcc.(patient_id, measurement_year)
                         <─────────────── raf_scores.(patient_id, measurement_year)
                         <─────────────── raf_suspect_conditions.(patient_id, measurement_year)

raf_patient_hcc <──────────────────────── raf_meat_evidence.patient_hcc_id

fhir_connections <─────────────────────── fhir_sync_log.connection_id
                 <─────────────────────── fhir_patient_mapping.connection_id
                 <─────────────────────── fhir_conditions.connection_id
                 <─────────────────────── fhir_encounters.connection_id
                 <─────────────────────── fhir_diagnostic_reports.connection_id

claims_batches <────────────────────────── claims_professional.batch_id
               <────────────────────────── claims_institutional.batch_id

providers <─────────────────────────────── provider_patient_panel.provider_id
          <─────────────────────────────── provider_scorecard_snapshots.provider_id
          <─────────────────────────────── provider_hcc_performance.provider_id
          <─────────────────────────────── provider_alerts.provider_id
          <─────────────────────────────── users.provider_id (005)

document_batches <──────────────────────── documents.batch_id (via ALTER in 004)

documents <─────────────────────────────── document_analysis.document_id
          <─────────────────────────────── document_diagnosis_lines.document_id

document_analysis <─────────────────────── document_diagnosis_lines.analysis_id

users <─────────────────────────────────── user_sessions.user_id
      <─────────────────────────────────── user_permissions.user_id
      <─────────────────────────────────── audit_log.user_id
      <─────────────────────────────────── password_reset_tokens.user_id
      <─────────────────────────────────── user_permissions.granted_by (self-ref)

user_sessions <─────────────────────────── audit_log.session_id

submission_batches <────────────────────── submission_records.batch_id
                   <────────────────────── submission_response_files.batch_id
```

---

## FK Conflicts Found

### CONFLICT 1 — `provider_hcc_performance` references `hcc_icd10_crosswalk` before its dependency is stated

**File:** `003_providers.sql`  
**Constraint:** `fk_hcc_perf_crosswalk FOREIGN KEY (hcc_code) REFERENCES hcc_icd10_crosswalk (hcc_code)`

**Assessment:** This is safe as long as `schema.sql` runs before `003_providers.sql`, which is the documented order. However the constraint references `hcc_icd10_crosswalk.hcc_code` (a non-PK column). MySQL will accept this only if `hcc_code` has a unique or primary key index on the parent. Inspection of `schema.sql` confirms `hcc_code` has only a non-unique `KEY idx_hcc_code (hcc_code)` — it is NOT UNIQUE and NOT the PRIMARY KEY.

**Impact:** MySQL will raise `errno: 150 "Foreign key constraint is incorrectly formed"` when running `003_providers.sql` in strict mode.

**Fix required:** Either:
- Add `UNIQUE KEY uq_hcc_code_year (hcc_code, effective_year)` on `hcc_icd10_crosswalk` covering just `hcc_code` alone, OR
- Drop the FK constraint from `provider_hcc_performance` and enforce referential integrity at the application layer (recommended, since multiple ICD-10 codes map to each `hcc_code` and uniqueness cannot hold on that column alone).

---

### CONFLICT 2 — `004_documents.sql` ALTER adds `batch_id` FK after `document_batches` is created in the same file

**Assessment:** The file creates `document_batches` first, then `documents`, then alters `documents` to add `batch_id` referencing `document_batches`. This ordering is correct within the file. No issue on fresh install. On upgrades where `documents` was already deployed without `document_batches`, the `ADD COLUMN IF NOT EXISTS` syntax (MySQL 8.0+) is required — and the file already uses it. Safe.

---

### CONFLICT 3 — `005_authentication.sql` creates `users` before `providers`, but `users.provider_id` references `providers`

**Assessment:** Migration 005 declares `CONSTRAINT fk_users_provider_id FOREIGN KEY (provider_id) REFERENCES providers (id)`. The `providers` table is created by migration 003. As long as the documented execution order is followed (003 before 005), this is safe.

**Risk:** If anyone runs 005 before 003, the FK will fail. The `run_all.sql` file enforces correct order.

---

## Auto-DDL Conflicts (Service Layer)

Multiple Python services contain `_ensure_tables()` functions that issue `CREATE TABLE IF NOT EXISTS` DDL at application startup. These run independently of the migration files and can diverge from the canonical schema over time.

### Summary of Conflicts

#### `auth_service.py` vs `005_authentication.sql`

| Issue | Detail |
|-------|--------|
| **`users` table — PK type mismatch** | Migration: `INT UNSIGNED AUTO_INCREMENT`. Service auto-DDL: `INT AUTO_INCREMENT` (unsigned omitted). |
| **`users` table — missing columns** | Migration has: `first_name`, `last_name`, `title`, `npi`, `provider_id`, `email_verified`, `tenant_id` (VARCHAR). Service auto-DDL lacks all of these. |
| **`users` table — extra columns** | Service auto-DDL has `password_reset_token`, `password_reset_expires`, `mfa_recovery_codes`. Migration handles reset via the separate `password_reset_tokens` table. This is a functional divergence. |
| **`users.tenant_id` type mismatch** | Migration: `VARCHAR(50)`. Service auto-DDL: `INT` (integer, not string). Breaks multi-tenant string-key lookups. |
| **`user_sessions` — column divergence** | Migration has `session_token`, `refresh_token`, `expires_at`, `refresh_expires_at`, `revoked_at`. Service auto-DDL has `session_id`, `session_token_hash`, `refresh_token_hash`, `last_used_at`, `last_activity_at`. These are materially different schemas. |
| **`permissions` table — not in migration** | Service auto-DDL creates a `permissions` table (generic resource/action registry). Migration 005 has no equivalent. This table is service-only. |
| **`role_default_permissions` — column mismatch** | Migration has `granted TINYINT(1)`. Service auto-DDL lacks the `granted` column. Migration also seeds the full RBAC matrix; service auto-DDL does not seed. |
| **`audit_log` — missing columns** | Migration has `request_body_hash`, `session_id` (FK), `response_status` as `INT UNSIGNED`. Service auto-DDL missing `request_body_hash`; `resource_id` is `VARCHAR(255)` vs migration's `VARCHAR(100)`. |

**Verdict:** `auth_service.py` auto-DDL will create an **incompatible** `users` and `user_sessions` schema if it runs against a fresh database before migration 005 is applied. If migration 005 runs first, the `CREATE TABLE IF NOT EXISTS` in the service will silently no-op and the service may fail at runtime when it attempts to INSERT or SELECT columns that exist in the service schema but not the migration schema, or vice versa.

**Required action:** Disable or remove `_ensure_tables()` from `auth_service.py` entirely. The migration is the authoritative schema owner.

---

#### `document_service.py` vs `004_documents.sql`

| Issue | Detail |
|-------|--------|
| **`documents.id` type mismatch** | Migration: `INT UNSIGNED AUTO_INCREMENT`. Service auto-DDL: `VARCHAR(36)` (UUID string). All FKs pointing to `documents.id` from `document_analysis` and `document_diagnosis_lines` use the service's `VARCHAR(36)` type and will be incompatible with the migration's `INT UNSIGNED`. |
| **`documents` — column name divergence** | Migration: `document_name`. Service: `filename` + `original_name`. Migration: `file_size_bytes`. Service: `file_size`. Migration: `file_hash`. Service: `sha256`. |
| **`document_analysis` — column divergence** | Migration has extensive structured JSON columns: `extracted_diagnoses`, `extracted_medications`, `extracted_labs`, `extracted_vitals`, `extracted_procedures`, `extracted_providers`, `hcc_codes_found`, `suspect_conditions`, `meat_evidence`. Service auto-DDL uses flat LONGTEXT columns: `medications_json`, `lab_results_json`, `suspect_conditions_json`, etc. and adds `raw_gemini_json`, `patient_name_detected`, `patient_dob_detected`, `patient_mrn_detected`. |
| **`document_diagnosis_lines.id` type** | Migration: `INT UNSIGNED AUTO_INCREMENT`. Service: `VARCHAR(36)`. |
| **`document_batch_items` — not in migration** | Service auto-DDL creates `document_batch_items` as a junction table linking batches to individual documents. Migration 004 has no equivalent. |

**Verdict:** The `documents` service has the **most severe conflict** in the codebase. The primary key type difference (`INT UNSIGNED` vs `VARCHAR(36)`) means the migration schema and the service schema are mutually incompatible at the storage level. Running both will not cause an error (both use `IF NOT EXISTS`) but whichever runs first will own the table, and the other will silently use the wrong schema.

**Required action:** Align the PK type. Decide authoritatively on `INT UNSIGNED AUTO_INCREMENT` (migration) or `VARCHAR(36)` UUID (service) and update the other to match. Update all FK references accordingly. Remove `_ensure_tables()` from `document_service.py` once reconciled.

---

#### `provider_service.py` vs `003_providers.sql`

| Issue | Detail |
|-------|--------|
| **Column subset** | Service auto-DDL for `providers` has a reduced column set (no `credential`, `specialty_category`, `practice_name`, `email`, `phone`, `openemr_user_id`). |
| **`provider_scorecard_snapshots`** | Service auto-DDL defines significantly fewer columns than migration 003's comprehensive scorecard schema. |
| **No FKs in service auto-DDL** | Service omits all FK constraints defined in migration 003. |

**Verdict:** Service auto-DDL will silently create underspecified tables on first startup against a fresh DB. Migration 003 is the authoritative version.

**Required action:** Remove `_ensure_tables()` from `provider_service.py`.

---

#### `submission_service.py` vs `006_raps_edps_submission.sql`

| Issue | Detail |
|-------|--------|
| **`submission_batches.id` type mismatch** | Migration: `INT UNSIGNED AUTO_INCREMENT`. Service auto-DDL: `VARCHAR(36)` (UUID). All child FKs (`submission_records.batch_id`) use `VARCHAR(36)` in service vs `INT UNSIGNED` in migration. |
| **`submission_records` — column divergence** | Service has `dos_from`/`dos_through` (migration uses `from_date`/`through_date`), `hicn_mbi` (migration uses `hicn_or_mbi`), adds `payment_amount`, `risk_score_adj`. Migration has `delete_indicator` ENUM, `record_type` ENUM, `diagnosis_cluster`, `risk_assessment_code`, `rendering_provider_npi`, `facility_npi`, `place_of_service`. |
| **`submission_responses` vs `submission_response_files`** | Service creates `submission_responses`; migration creates `submission_response_files`. These are different table names covering the same domain. Both will co-exist, causing split data. |
| **`submission_schedule` — column divergence** | Service has `is_custom`, `description`. Migration has `submission_type` ENUM, `status`, `notes`, FK to tenant. |
| **`submission_validation_rules`** | Exists only in migration 006; not in service auto-DDL. |

**Verdict:** The service and migration define **different table names** for CMS responses (`submission_responses` vs `submission_response_files`), meaning the application will write response data to a table that the migration did not create.

**Required action:** Standardize on `submission_response_files` (migration name). Update service code. Remove `_ensure_tables()` from `submission_service.py`.

---

#### `webhook_service.py` — No migration coverage

| Issue | Detail |
|-------|--------|
| **`webhooks` table** | Defined only in `webhook_service.py` inline DDL. No migration file exists for this table. |
| **`webhook_deliveries` table** | Same — service-only, no migration. |

**Required action:** Create `007_webhooks.sql` migration to canonicalize these tables.

---

#### `job_service.py` — No migration coverage

| Issue | Detail |
|-------|--------|
| **`raf_jobs` table** | Defined only in `job_service.py` auto-DDL. No migration file exists. |

Note: `schema.sql` has `raf_nlp_jobs`. The `raf_jobs` table in `job_service.py` appears to be a parallel or replacement job queue. These may be functionally duplicative.

**Required action:** Determine if `raf_jobs` duplicates `raf_nlp_jobs`. If distinct, create a migration. If duplicative, remove from service and point code at `raf_nlp_jobs`.

---

#### `prospective_service.py` — No migration coverage

| Issue | Detail |
|-------|--------|
| **`raf_awv_tracking` table** | Defined inline in `prospective_service.py`. No migration file exists. |

**Required action:** Create a migration (can be added to an expanded `007_` file) to canonicalize this table.

---

## Tables Not Covered by Any Migration

These tables are created only via service-layer auto-DDL and have no canonical migration:

| Table | Service | Severity |
|-------|---------|----------|
| `webhooks` | `webhook_service.py` | High — data loss risk on fresh install without the service running first |
| `webhook_deliveries` | `webhook_service.py` | High |
| `raf_jobs` | `job_service.py` | High |
| `raf_awv_tracking` | `prospective_service.py` | High |
| `permissions` | `auth_service.py` | Medium — service-internal; not referenced by migration |
| `document_batch_items` | `document_service.py` | Medium — migration 004 tracks batches but has no items junction table |

---

## Fresh Install Instructions

Use this procedure to build the database from zero on a new server.

```bash
# 1. Connect as a MySQL user with CREATE DATABASE privileges
mysql -h <host> -u <admin_user> -p

# 2. Run the master migration script (sources all files in order)
mysql -h <host> -u <admin_user> -p < /path/to/database/migrations/run_all.sql

# 3. Verify table count (expect 45 tables including service-only ones after first app start)
mysql -h <host> -u <admin_user> -p raf_intelligence -e "SHOW TABLES;"

# 4. Load reference data (ICD-10/HCC crosswalk + RAF coefficients)
python scripts/import_icd10_hcc_crosswalk.py
python scripts/import_raf_coefficients.py

# 5. (Optional) Load demo environment
python scripts/seed_demo_environment.py
```

**Default admin credentials created by migration 005:**

| Field | Value |
|-------|-------|
| Email | `admin@raf.health` |
| Password | `admin123` |
| Role | `admin` |

**Change this password immediately after first login.**

---

## Upgrade Instructions

For an existing deployment that already has some tables:

```bash
# 1. Back up the database before any migration
mysqldump -h <host> -u <admin_user> -p raf_intelligence > raf_intelligence_backup_$(date +%Y%m%d).sql

# 2. Check which migrations have already run
#    (Tracking table does not exist yet — check manually)
mysql -h <host> -u <admin_user> -p raf_intelligence -e "SHOW TABLES;"

# 3. Run only the migrations not yet applied
#    All CREATE TABLE statements use IF NOT EXISTS and are therefore idempotent.
#    ALTER TABLE statements in 004 use ADD COLUMN IF NOT EXISTS (MySQL 8.0+ syntax).
#    It is safe to re-run individual migration files.

mysql -h <host> -u <admin_user> -p < /path/to/database/migrations/001_fhir_integration.sql
# ... and so on for any missing migrations

# 4. Recommended: implement a migration tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     VARCHAR(50) NOT NULL,
  applied_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_migrations (version) VALUES
  ('schema'), ('001'), ('002'), ('003'), ('004'), ('005'), ('006');
```

**Note on auto-DDL:** If services have been running and auto-DDL has already created tables, those tables will not be dropped or modified by migrations (all use `IF NOT EXISTS`). Divergent columns added by services but absent from migrations will persist silently. After resolving conflicts described above, run `ALTER TABLE` statements manually to bring existing tables into alignment with the canonical migration schemas.

---

## Migration File Summaries

| File | Tables Created | Seed Data | External Dependencies |
|------|---------------|-----------|----------------------|
| `schema.sql` | 14 | 60+ medication signals, 25+ lab signals | None — creates database |
| `001_fhir_integration.sql` | 6 | None | None |
| `002_claims_ingestion.sql` | 5 | None | None |
| `003_providers.sql` | 5 | None | `hcc_icd10_crosswalk` (schema.sql) |
| `004_documents.sql` | 4 + 1 ALTER | None | None |
| `005_authentication.sql` | 6 | Full RBAC matrix + 1 default admin user | `providers` (003) |
| `006_raps_edps_submission.sql` | 5 | 10 CMS validation rules | None |

**Total tables created by migrations: 45**  
(14 schema + 6 FHIR + 5 claims + 5 providers + 4 documents + 6 auth + 5 submissions)
