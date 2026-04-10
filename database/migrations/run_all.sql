-- =============================================================================
-- RAF Intelligence System — Master Migration Runner
-- Run this file against a MySQL 8.0+ instance to build the complete schema
-- from scratch in the correct dependency order.
--
-- Usage:
--   mysql -h <host> -u <user> -p < run_all.sql
--
-- All CREATE TABLE statements use IF NOT EXISTS.
-- All INSERT seed data uses INSERT IGNORE.
-- This file is safe to inspect but should NOT be edited directly —
-- edit the individual numbered migration files instead.
--
-- Execution order (dependency-driven):
--   schema.sql                    (creates DB + 14 core tables + seeds signals)
--   001_fhir_integration.sql      (6 FHIR ingestion tables)
--   002_claims_ingestion.sql      (5 claims processing tables)
--   003_providers.sql             (5 provider + scorecard tables; needs hcc_icd10_crosswalk)
--   004_documents.sql             (4 document tables + ALTER for batch_id FK)
--   005_authentication.sql        (6 auth/RBAC tables + seed RBAC matrix; needs providers)
--   006_raps_edps_submission.sql  (5 CMS submission tables + seed validation rules)
--   007_emr_connections.sql       (3 multi-EMR tables + 12 vendor preset seeds; needs fhir_connections)
--
-- Known issues — read MIGRATION_README.md before running in production:
--   1. provider_hcc_performance FK on hcc_icd10_crosswalk.hcc_code may fail
--      (hcc_code is not unique on the parent); see CONFLICT 1 in README.
--   2. Service-layer auto-DDL in several Python services diverges from this
--      schema; disable _ensure_tables() in services before first run.
--   3. Tables webhooks, webhook_deliveries, raf_jobs, raf_awv_tracking, and
--      raf_coding_corrections are now covered by 023_service_tables.sql.
--      Service-layer auto-DDL is retained as a fallback but the migration
--      file is the source of truth for schema definition.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- STEP 0: Safety checks
-- ---------------------------------------------------------------------------
SET foreign_key_checks = 0;
SET sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- ---------------------------------------------------------------------------
-- STEP 1: Create database (idempotent)
-- ---------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS raf_intelligence
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE raf_intelligence;

-- ---------------------------------------------------------------------------
-- STEP 2: Core RAF engine tables + reference data seed
--         Source: database/schema.sql
-- ---------------------------------------------------------------------------

-- 2.1 HCC reference tables (no external dependencies)
CREATE TABLE IF NOT EXISTS hcc_icd10_crosswalk (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  icd10_code        VARCHAR(10)       NOT NULL,
  icd10_description VARCHAR(500)      NOT NULL DEFAULT '',
  hcc_code          SMALLINT UNSIGNED NOT NULL,
  hcc_label         VARCHAR(255)      NOT NULL DEFAULT '',
  effective_year    YEAR              NOT NULL DEFAULT 2024,
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_crosswalk_code_year (icd10_code, hcc_code, effective_year),
  KEY idx_icd10_code     (icd10_code),
  KEY idx_hcc_code       (hcc_code),
  KEY idx_effective_year (effective_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='ICD-10 to HCC V28 mapping table';

CREATE TABLE IF NOT EXISTS hcc_raf_coefficients (
  id            INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  hcc_code      SMALLINT UNSIGNED NOT NULL,
  model_segment ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
  coefficient   DECIMAL(8,4)      NOT NULL,
  model_year    YEAR              NOT NULL DEFAULT 2024,
  created_at    DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_coeff_hcc_seg_year (hcc_code, model_segment, model_year),
  KEY idx_hcc_code      (hcc_code),
  KEY idx_model_segment (model_segment),
  KEY idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='RAF coefficient weights per HCC per model segment';

CREATE TABLE IF NOT EXISTS hcc_demographic_coefficients (
  id            INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  model_segment ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
  age_band      VARCHAR(20)       NOT NULL,
  sex           ENUM('M','F')     NOT NULL,
  coefficient   DECIMAL(8,4)      NOT NULL,
  model_year    YEAR              NOT NULL DEFAULT 2024,
  created_at    DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_demo_seg_age_sex_year (model_segment, age_band, sex, model_year),
  KEY idx_model_segment (model_segment),
  KEY idx_age_band      (age_band),
  KEY idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Demographic base score coefficients per model segment';

CREATE TABLE IF NOT EXISTS hcc_hierarchy_rules (
  id             INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  hcc_code       SMALLINT UNSIGNED NOT NULL,
  trumped_by_hcc SMALLINT UNSIGNED NOT NULL,
  model_year     YEAR              NOT NULL DEFAULT 2024,
  created_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_hierarchy_pair_year (hcc_code, trumped_by_hcc, model_year),
  KEY idx_hcc_code       (hcc_code),
  KEY idx_trumped_by_hcc (trumped_by_hcc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='HCC hierarchy rules: lower HCC is suppressed when higher HCC is present';

CREATE TABLE IF NOT EXISTS hcc_interaction_terms (
  id                 INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  term_name          VARCHAR(100)  NOT NULL,
  hcc_codes_required JSON          NOT NULL,
  model_segment      ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
  coefficient        DECIMAL(8,4)  NOT NULL,
  model_year         YEAR          NOT NULL DEFAULT 2024,
  created_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_interaction_name_seg_year (term_name, model_segment, model_year),
  KEY idx_model_segment (model_segment),
  KEY idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Interaction term bonuses for combinations of HCC conditions';

-- 2.2 Patient RAF tables (raf_patient_demographics is the FK root anchor)
CREATE TABLE IF NOT EXISTS raf_patient_demographics (
  id               INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  patient_id       INT UNSIGNED   NOT NULL,
  measurement_year YEAR           NOT NULL,
  age_band         VARCHAR(20)    NOT NULL,
  sex              ENUM('M','F')  NOT NULL,
  dual_status      TINYINT(1)     NOT NULL DEFAULT 0,
  dual_type        VARCHAR(20)    NOT NULL DEFAULT 'non_dual',
  disabled         TINYINT(1)     NOT NULL DEFAULT 0,
  orec             VARCHAR(1)     NOT NULL DEFAULT '0',
  institutional    TINYINT(1)     NOT NULL DEFAULT 0,
  enrollment_source VARCHAR(30)   NOT NULL DEFAULT 'derived',
  model_segment    ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL DEFAULT 'CNA',
  created_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_patient_year (patient_id, measurement_year),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_dual_status      (dual_status),
  KEY idx_orec             (orec),
  KEY idx_disabled         (disabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Patient demographic factors for RAF calculation, linked to OpenEMR pid';

CREATE TABLE IF NOT EXISTS raf_patient_hcc (
  id                   INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  patient_id           INT UNSIGNED      NOT NULL,
  measurement_year     YEAR              NOT NULL,
  hcc_code             SMALLINT UNSIGNED NOT NULL,
  icd10_codes          JSON              NOT NULL,
  source_encounter_ids JSON              NOT NULL,
  raf_coefficient      DECIMAL(8,4)      NOT NULL DEFAULT 0.0000,
  meat_status          ENUM('complete','partial','missing') NOT NULL DEFAULT 'missing',
  is_trumped           TINYINT(1)        NOT NULL DEFAULT 0,
  trumped_by_hcc       SMALLINT UNSIGNED NULL DEFAULT NULL,
  created_at           DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_patient_hcc_year (patient_id, hcc_code, measurement_year),
  KEY idx_patient_id       (patient_id),
  KEY idx_hcc_code         (hcc_code),
  KEY idx_measurement_year (measurement_year),
  KEY idx_meat_status      (meat_status),
  KEY idx_is_trumped       (is_trumped),
  CONSTRAINT fk_phcc_demographics
    FOREIGN KEY (patient_id, measurement_year)
    REFERENCES raf_patient_demographics (patient_id, measurement_year)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-patient HCC conditions with supporting encounter references and MEAT status';

CREATE TABLE IF NOT EXISTS raf_scores (
  id                   INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  patient_id           INT UNSIGNED  NOT NULL,
  measurement_year     YEAR          NOT NULL,
  score_type           VARCHAR(50)   NOT NULL DEFAULT 'prospective',
  model_segment        ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL DEFAULT 'CNA',
  demographic_score    DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  disease_score        DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  interaction_score    DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  total_raw            DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  normalization_factor DECIMAL(8,4)  NOT NULL DEFAULT 1.0000,
  final_raf            DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  hcc_count            SMALLINT      NOT NULL DEFAULT 0,
  calculated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_score_patient_year_type_seg (patient_id, measurement_year, score_type, model_segment),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_final_raf        (final_raf),
  KEY idx_score_type       (score_type),
  CONSTRAINT fk_scores_demographics
    FOREIGN KEY (patient_id, measurement_year)
    REFERENCES raf_patient_demographics (patient_id, measurement_year)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Final calculated RAF scores with full demographic/disease/interaction breakdown';

CREATE TABLE IF NOT EXISTS raf_suspect_conditions (
  id               INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  patient_id       INT UNSIGNED      NOT NULL,
  measurement_year YEAR              NOT NULL,
  suspect_hcc      SMALLINT UNSIGNED NOT NULL,
  suspect_icd10    VARCHAR(10)       NOT NULL,
  evidence_type    ENUM('medication','lab','imaging','referral','historical') NOT NULL,
  evidence_detail  JSON              NOT NULL,
  confidence_score DECIMAL(5,4)      NOT NULL DEFAULT 0.0000,
  status           ENUM('open','accepted','dismissed','coded') NOT NULL DEFAULT 'open',
  reviewed_by      VARCHAR(100)      NULL DEFAULT NULL,
  reviewed_at      DATETIME          NULL DEFAULT NULL,
  created_at       DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_suspect_hcc      (suspect_hcc),
  KEY idx_suspect_icd10    (suspect_icd10),
  KEY idx_evidence_type    (evidence_type),
  KEY idx_confidence_score (confidence_score),
  KEY idx_status           (status),
  KEY idx_patient_year_hcc (patient_id, measurement_year, suspect_hcc),
  CONSTRAINT fk_suspect_demographics
    FOREIGN KEY (patient_id, measurement_year)
    REFERENCES raf_patient_demographics (patient_id, measurement_year)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AI-identified suspect conditions flagged for provider coding review';

CREATE TABLE IF NOT EXISTS raf_meat_evidence (
  id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
  patient_hcc_id     INT UNSIGNED NOT NULL,
  encounter_id       INT UNSIGNED NOT NULL,
  encounter_date     DATE         NOT NULL,
  meat_m             TEXT         NULL,
  meat_e             TEXT         NULL,
  meat_a             TEXT         NULL,
  meat_t             TEXT         NULL,
  meat_m_present     TINYINT(1)   NOT NULL DEFAULT 0,
  meat_e_present     TINYINT(1)   NOT NULL DEFAULT 0,
  meat_a_present     TINYINT(1)   NOT NULL DEFAULT 0,
  meat_t_present     TINYINT(1)   NOT NULL DEFAULT 0,
  completeness_score DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
  raw_note_excerpt   TEXT         NULL,
  created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_patient_hcc_id (patient_hcc_id),
  KEY idx_encounter_id   (encounter_id),
  KEY idx_encounter_date (encounter_date),
  KEY idx_completeness   (completeness_score),
  CONSTRAINT fk_meat_patient_hcc
    FOREIGN KEY (patient_hcc_id)
    REFERENCES raf_patient_hcc (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='MEAT documentation evidence per patient HCC per encounter';

-- 2.3 Signal + job tables (no FK dependencies on patient tables)
CREATE TABLE IF NOT EXISTS raf_medication_signals (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  drug_name_pattern VARCHAR(255)      NOT NULL,
  drug_class        VARCHAR(100)      NOT NULL DEFAULT '',
  suspect_icd10     VARCHAR(10)       NOT NULL,
  suspect_hcc       SMALLINT UNSIGNED NOT NULL,
  confidence_base   DECIMAL(5,4)      NOT NULL DEFAULT 0.7000,
  notes             VARCHAR(500)      NOT NULL DEFAULT '',
  is_active         TINYINT(1)        NOT NULL DEFAULT 1,
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_drug_class    (drug_class),
  KEY idx_suspect_icd10 (suspect_icd10),
  KEY idx_suspect_hcc   (suspect_hcc),
  KEY idx_is_active     (is_active),
  FULLTEXT KEY ftx_drug_name (drug_name_pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Medication signal rules: drug patterns mapped to suspect HCC diagnoses';

CREATE TABLE IF NOT EXISTS raf_lab_signals (
  id                 INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  lab_name_pattern   VARCHAR(255)      NOT NULL,
  lab_loinc_code     VARCHAR(20)       NOT NULL DEFAULT '',
  threshold_operator ENUM('<','<=','>','>=','=','!=','BETWEEN') NOT NULL,
  threshold_value    DECIMAL(12,4)     NULL,
  threshold_low      DECIMAL(12,4)     NULL,
  threshold_high     DECIMAL(12,4)     NULL,
  threshold_unit     VARCHAR(30)       NOT NULL DEFAULT '',
  suspect_icd10      VARCHAR(10)       NOT NULL,
  suspect_hcc        SMALLINT UNSIGNED NOT NULL,
  confidence_base    DECIMAL(5,4)      NOT NULL DEFAULT 0.7500,
  notes              VARCHAR(500)      NOT NULL DEFAULT '',
  is_active          TINYINT(1)        NOT NULL DEFAULT 1,
  created_at         DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_lab_loinc     (lab_loinc_code),
  KEY idx_suspect_icd10 (suspect_icd10),
  KEY idx_suspect_hcc   (suspect_hcc),
  KEY idx_is_active     (is_active),
  FULLTEXT KEY ftx_lab_name (lab_name_pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Lab signal rules: abnormal lab thresholds mapped to suspect HCC diagnoses';

CREATE TABLE IF NOT EXISTS raf_nlp_jobs (
  id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_type           VARCHAR(100) NOT NULL,
  target_id          INT UNSIGNED NOT NULL,
  target_type        VARCHAR(50)  NOT NULL DEFAULT 'encounter',
  status             ENUM('queued','running','completed','failed','cancelled') NOT NULL DEFAULT 'queued',
  model_used         VARCHAR(100) NOT NULL DEFAULT '',
  processing_time_ms INT UNSIGNED NULL,
  result_summary     JSON         NULL,
  error_message      TEXT         NULL,
  queued_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at         DATETIME     NULL,
  completed_at       DATETIME     NULL,
  created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_job_type  (job_type),
  KEY idx_target    (target_type, target_id),
  KEY idx_status    (status),
  KEY idx_queued_at (queued_at),
  KEY idx_model_used (model_used)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='NLP and AI processing job queue and result tracking';

CREATE TABLE IF NOT EXISTS raf_audit_packages (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  patient_id       INT UNSIGNED NOT NULL,
  measurement_year YEAR         NOT NULL,
  generated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  file_path        VARCHAR(500) NOT NULL DEFAULT '',
  status           ENUM('generating','ready','failed','archived') NOT NULL DEFAULT 'generating',
  package_version  VARCHAR(20)  NOT NULL DEFAULT '1.0',
  generated_by     VARCHAR(100) NULL DEFAULT NULL,
  file_size_bytes  INT UNSIGNED NULL,
  checksum_sha256  CHAR(64)     NULL,
  created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_status           (status),
  KEY idx_generated_at     (generated_at),
  KEY idx_patient_year     (patient_id, measurement_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Generated RAF audit report packages with file references';

-- 2.4 Seed data from schema.sql is loaded separately via import scripts.
--     Run after this file completes:
--       python scripts/import_icd10_hcc_crosswalk.py
--       python scripts/import_raf_coefficients.py
--     Medication and lab signals are seeded inline in schema.sql;
--     to re-apply them, run schema.sql directly after this file.

-- ---------------------------------------------------------------------------
-- STEP 3: FHIR R4 integration tables
--         Source: 001_fhir_integration.sql
-- ---------------------------------------------------------------------------
SOURCE 001_fhir_integration.sql;

-- ---------------------------------------------------------------------------
-- STEP 4: Claims ingestion tables
--         Source: 002_claims_ingestion.sql
-- ---------------------------------------------------------------------------
SOURCE 002_claims_ingestion.sql;

-- ---------------------------------------------------------------------------
-- STEP 5: Provider registry and scorecard tables
--         Source: 003_providers.sql
--         Requires: hcc_icd10_crosswalk (Step 2)
--
-- WARNING: provider_hcc_performance contains a FK on hcc_icd10_crosswalk.hcc_code
--          which is a non-unique column. MySQL may raise errno 150 on strict
--          deployments. If this step fails, comment out the CONSTRAINT
--          fk_hcc_perf_crosswalk block in 003_providers.sql and re-run.
--          See CONFLICT 1 in database/MIGRATION_README.md.
-- ---------------------------------------------------------------------------
SOURCE 003_providers.sql;

-- ---------------------------------------------------------------------------
-- STEP 6: Document upload and Gemini Vision tables
--         Source: 004_documents.sql
--         Includes ALTER TABLE to add batch_id FK to documents table.
-- ---------------------------------------------------------------------------
SOURCE 004_documents.sql;

-- ---------------------------------------------------------------------------
-- STEP 7: Authentication and RBAC tables
--         Source: 005_authentication.sql
--         Requires: providers (Step 5)
--         Seeds:    Full RBAC permission matrix, default admin user
-- ---------------------------------------------------------------------------
SOURCE 005_authentication.sql;

-- ---------------------------------------------------------------------------
-- STEP 8: CMS RAPS/EDPS/EDGE submission tables
--         Source: 006_raps_edps_submission.sql
--         Seeds:  10 CMS validation rules
-- ---------------------------------------------------------------------------
SOURCE 006_raps_edps_submission.sql;

-- ---------------------------------------------------------------------------
-- STEP 9: Multi-EMR connection registry
--         Source: 007_emr_connections.sql
--         Requires: fhir_connections (Step 3 / 001_fhir_integration.sql)
--         Creates:  emr_connections, emr_sync_log, emr_vendor_presets
--         Seeds:    12 vendor presets (openemr, epic, cerner, athenahealth,
--                   allscripts, eclinicalworks, drchrono, nextgen, greenway,
--                   practice_fusion, generic_fhir, generic_rest)
-- ---------------------------------------------------------------------------
SOURCE 007_emr_connections.sql;

-- ---------------------------------------------------------------------------
-- STEP 10: Enterprise RAF features — ESRD, New Enrollee, Frailty, Sweep Period
--          Source: v2026_04_raf_features.sql
--          Adds:   enrollment_months, plan_type to raf_patient_demographics
--                  new_enrollee, esrd_segment, frailty_addend, sweep_period,
--                  dos_start, dos_end columns to raf_scores
--                  Creates: frailty_assessments, raf_sweep_windows tables
--                  Extends: model_segment ENUMs to include ESRD_DLY/FG/NE and NE_* segments
-- ---------------------------------------------------------------------------
SOURCE v2026_04_raf_features.sql;

-- ---------------------------------------------------------------------------
-- STEP 11: Pipeline Migrations (008 - 023)
--          Sourcing remaining features in dependency order.
-- ---------------------------------------------------------------------------
SOURCE 008_care_gaps.sql;
SOURCE 009_coder_worklist.sql;
SOURCE 010_chart_chase.sql;
SOURCE 011_provider_attestation.sql;
SOURCE 012_awv_scheduling.sql;
SOURCE 013_ccda_support.sql;
SOURCE 014_adt_listener.sql;
SOURCE 015_smart_on_fhir.sql;
SOURCE 016_direct_messaging.sql;
SOURCE 017_clearinghouse.sql;
SOURCE 018_predictive_models.sql;
SOURCE 019_cohort_analysis.sql;
SOURCE 020_realtime_dashboard.sql;
SOURCE 021_bi_export.sql;
SOURCE 022_financial_reconciliation.sql;
SOURCE 023_service_tables.sql;

-- ---------------------------------------------------------------------------
-- STEP 12: Record migration history
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    VARCHAR(50) NOT NULL,
  applied_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Tracks which migration files have been applied to this database instance';

INSERT IGNORE INTO schema_migrations (version) VALUES
  ('schema.sql'),
  ('001_fhir_integration.sql'),
  ('002_claims_ingestion.sql'),
  ('003_providers.sql'),
  ('004_documents.sql'),
  ('005_authentication.sql'),
  ('006_raps_edps_submission.sql'),
  ('007_emr_connections.sql'),
  ('008_care_gaps.sql'),
  ('009_coder_worklist.sql'),
  ('010_chart_chase.sql'),
  ('011_provider_attestation.sql'),
  ('012_awv_scheduling.sql'),
  ('013_ccda_support.sql'),
  ('014_adt_listener.sql'),
  ('015_smart_on_fhir.sql'),
  ('016_direct_messaging.sql'),
  ('017_clearinghouse.sql'),
  ('018_predictive_models.sql'),
  ('019_cohort_analysis.sql'),
  ('020_realtime_dashboard.sql'),
  ('021_bi_export.sql'),
  ('022_financial_reconciliation.sql'),
  ('023_service_tables.sql'),
  ('v2026_04_raf_features.sql');

-- ---------------------------------------------------------------------------
-- STEP 12: Restore safe defaults
-- ---------------------------------------------------------------------------
SET foreign_key_checks = 1;

-- ---------------------------------------------------------------------------
-- Completion notice
-- ---------------------------------------------------------------------------
SELECT
  COUNT(*)            AS total_tables,
  NOW()               AS applied_at,
  'run_all.sql done'  AS status
FROM information_schema.tables
WHERE table_schema = 'raf_intelligence'
  AND table_type   = 'BASE TABLE';
