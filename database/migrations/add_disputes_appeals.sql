-- =============================================================================
-- Migration: add_disputes_appeals
--
-- Adds the dispute / appeal management workflow tables to the RAF Intelligence
-- database.  These tables track CMS / payer denials of submitted HCC codes,
-- evidence gathered to support an appeal, and the appeal outcome chain so we
-- can measure win-rate, dollars recovered, and average cycle time.
--
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- IMPORTANT: tenant_id is included on every workflow table so the existing
-- tenant + RBAC layer (provider_service / router_registry) can scope queries.
-- It is declared NULLable to remain compatible with single-tenant dev DBs.
--
-- Idempotent: safe to re-run.  Uses CREATE TABLE IF NOT EXISTS.
-- =============================================================================

USE raf_intelligence;

-- -----------------------------------------------------------------------------
-- 1. HCC_DISPUTES
--    A single denial event for one (patient, HCC) pair from CMS / payer / audit
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hcc_disputes (
  id                       INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id                INT UNSIGNED      NULL DEFAULT NULL COMMENT 'FK to tenants table; NULL for single-tenant deployments',
  patient_id               INT UNSIGNED      NOT NULL COMMENT 'OpenEMR pid',
  measurement_year         YEAR              NOT NULL DEFAULT 2026,
  hcc_code                 SMALLINT UNSIGNED NOT NULL,
  icd10                    VARCHAR(10)       NOT NULL,
  original_submission_id   VARCHAR(100)      NULL DEFAULT NULL COMMENT 'External claim / submission identifier',
  disputed_by              ENUM('cms','payer','internal_audit') NOT NULL,
  payer_name               VARCHAR(150)      NULL DEFAULT NULL,
  denial_reason_code       VARCHAR(50)       NULL DEFAULT NULL COMMENT 'Standard denial reason code (CARC/RARC for payers)',
  denial_reason_text       TEXT              NULL,
  denial_received_at       DATETIME          NOT NULL,
  financial_impact         DECIMAL(12,2)     NOT NULL DEFAULT 0.00 COMMENT 'Estimated $ at risk if dispute is lost',
  status                   ENUM('open','in_review','appealing','won','lost','abandoned') NOT NULL DEFAULT 'open',
  assigned_to              VARCHAR(100)      NULL DEFAULT NULL COMMENT 'Username or user-id of coder/auditor handling the case',
  notes                    TEXT              NULL,
  created_by               VARCHAR(100)      NULL DEFAULT NULL,
  created_at               DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at               DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  closed_at                DATETIME          NULL DEFAULT NULL COMMENT 'When status moved to won / lost / abandoned',
  PRIMARY KEY (id),
  KEY idx_disp_tenant       (tenant_id),
  KEY idx_disp_patient      (patient_id),
  KEY idx_disp_status       (status),
  KEY idx_disp_assigned_to  (assigned_to),
  KEY idx_disp_received_at  (denial_received_at),
  KEY idx_disp_hcc_code     (hcc_code),
  KEY idx_disp_tenant_status (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='HCC denial / dispute events tracked through the full appeal workflow';


-- -----------------------------------------------------------------------------
-- 2. HCC_APPEALS
--    Each round of appeal submitted against a dispute (1 = first level, etc.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hcc_appeals (
  id                       INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  dispute_id               INT UNSIGNED      NOT NULL,
  appeal_round             TINYINT UNSIGNED  NOT NULL DEFAULT 1 COMMENT '1=first level, 2=reconsideration, 3=ALJ/external',
  appeal_letter_text       MEDIUMTEXT        NULL,
  appeal_letter_model      VARCHAR(100)      NULL DEFAULT NULL COMMENT 'AI model that drafted the letter (if any)',
  evidence_attached_json   JSON              NULL COMMENT 'Array of {evidence_id, type, snippet} cited in this appeal',
  submitted_by             VARCHAR(100)      NULL DEFAULT NULL,
  submitted_at             DATETIME          NULL DEFAULT NULL,
  response_received_at     DATETIME          NULL DEFAULT NULL,
  outcome                  ENUM('pending','overturned','upheld','partial','withdrawn') NOT NULL DEFAULT 'pending',
  outcome_notes            TEXT              NULL,
  monetary_recovered       DECIMAL(12,2)     NOT NULL DEFAULT 0.00,
  created_at               DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at               DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_appeal_dispute_round (dispute_id, appeal_round),
  KEY idx_appeal_dispute    (dispute_id),
  KEY idx_appeal_outcome    (outcome),
  KEY idx_appeal_submitted  (submitted_at),
  CONSTRAINT fk_appeal_dispute
    FOREIGN KEY (dispute_id)
    REFERENCES hcc_disputes (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-round appeal submissions and outcomes for an HCC dispute';


-- -----------------------------------------------------------------------------
-- 3. DISPUTE_EVIDENCE
--    Evidence rows attached to a dispute (chart excerpts, labs, imaging, etc.)
--    Most rows are auto-populated from raf_meat_evidence, but coders can add
--    additional evidence (e.g. a consult note that wasn't in MEAT extraction).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dispute_evidence (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  dispute_id        INT UNSIGNED      NOT NULL,
  evidence_type     ENUM('chart_excerpt','lab','imaging','note','consult','medication','other') NOT NULL,
  source_doc_id     VARCHAR(100)      NULL DEFAULT NULL COMMENT 'External doc id (encounter id / FHIR resource id / file path)',
  source_table      VARCHAR(64)       NULL DEFAULT NULL COMMENT 'Internal source table (e.g. raf_meat_evidence)',
  source_row_id     INT UNSIGNED      NULL DEFAULT NULL COMMENT 'PK in source_table',
  encounter_date    DATE              NULL DEFAULT NULL,
  snippet_text      TEXT              NULL,
  meat_components   VARCHAR(8)        NULL DEFAULT NULL COMMENT 'String like "MEAT" listing components present',
  uploaded_by       VARCHAR(100)      NULL DEFAULT NULL,
  uploaded_at       DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_evd_dispute    (dispute_id),
  KEY idx_evd_type       (evidence_type),
  KEY idx_evd_source     (source_table, source_row_id),
  CONSTRAINT fk_evd_dispute
    FOREIGN KEY (dispute_id)
    REFERENCES hcc_disputes (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Evidence rows attached to a dispute, primarily from raf_meat_evidence';


-- =============================================================================
-- End of add_disputes_appeals migration
-- =============================================================================
