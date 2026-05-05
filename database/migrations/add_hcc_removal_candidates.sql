-- =============================================================================
-- Migration: add_hcc_removal_candidates
--   Adds the table backing the "two-way coding" HCC removal-candidate workflow.
--   For each currently-coded HCC the engine asks: does the chart actually
--   document MEAT evidence supporting it?  If not, a removal candidate row is
--   inserted here for clinician review.
--
--   This is the COUNTERPART to raf_suspect_conditions:
--     - raf_suspect_conditions:   chart says yes, billing says no -> ADD code
--     - hcc_removal_candidates:   billing says yes, chart says no  -> REMOVE code
--
--   Status flow mirrors the suspect engine:
--       pending   - awaiting clinician review (default on insert)
--       dismissed - clinician keeps the HCC (false alarm)
--       removed   - clinician confirms the HCC should be removed
--
--   No FK to raf_patient_hcc.id because:
--     - raf_patient_hcc rows are wiped/recomputed on every RAF rerun, which
--       would cascade-delete review history and lose audit trail.
--     - We instead store the natural keys (patient_id, measurement_year,
--       hcc_code) so the candidate survives RAF recomputation.
--
-- Idempotent: safe to re-run.
-- Apply with:
--   mysql -u <user> -p raf_intelligence < database/migrations/add_hcc_removal_candidates.sql
-- =============================================================================

USE raf_intelligence;

CREATE TABLE IF NOT EXISTS hcc_removal_candidates (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  patient_id        INT UNSIGNED      NOT NULL COMMENT 'OpenEMR pid',
  tenant_id         VARCHAR(64)       NOT NULL DEFAULT 'default'
                     COMMENT 'Multi-tenant scoping; mirrors patient/provider tenant_id',
  measurement_year  YEAR              NOT NULL,
  hcc_code          SMALLINT UNSIGNED NOT NULL,
  icd10             VARCHAR(20)       NOT NULL DEFAULT '' COMMENT 'Representative ICD-10 from raf_patient_hcc.icd10_codes',
  patient_hcc_id    INT UNSIGNED      NULL DEFAULT NULL COMMENT 'Best-effort FK snapshot to raf_patient_hcc.id at scan time (no DB FK; see header)',
  confidence        DECIMAL(5,4)      NOT NULL DEFAULT 0.0000
                     COMMENT '0.0000-1.0000 confidence the HCC is unsupported (1.0 = no MEAT at all)',
  reason            TEXT              NOT NULL
                     COMMENT 'Human-readable explanation of why removal was suggested',
  evidence          JSON              NULL
                     COMMENT 'Structured snapshot: searched_terms, snippets[], scanned_encounters[], meat_score, etc.',
  last_supported_date DATE            NULL DEFAULT NULL
                     COMMENT 'Most recent encounter date that DID provide some MEAT support, if any',
  status            ENUM('pending','dismissed','removed') NOT NULL DEFAULT 'pending',
  reviewed_by       VARCHAR(100)      NULL DEFAULT NULL,
  reviewed_at       DATETIME          NULL DEFAULT NULL,
  review_notes      TEXT              NULL DEFAULT NULL,
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  -- One pending candidate per (tenant, patient, year, HCC).  Keeping the
  -- composite UNIQUE key lets us ON DUPLICATE KEY UPDATE during rescans
  -- instead of duplicating rows for the same finding.
  UNIQUE KEY uq_removal_tenant_patient_year_hcc
    (tenant_id, patient_id, measurement_year, hcc_code),
  KEY idx_patient_id        (patient_id),
  KEY idx_tenant_id         (tenant_id),
  KEY idx_measurement_year  (measurement_year),
  KEY idx_hcc_code          (hcc_code),
  KEY idx_status            (status),
  KEY idx_confidence        (confidence),
  KEY idx_patient_year_status (patient_id, measurement_year, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Two-way coding: HCCs currently billed but lacking MEAT support in chart';
