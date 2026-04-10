-- =============================================================================
-- RAF Intelligence System - Migration 006
-- RAPS / EDPS / EDGE Submission Management
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. SUBMISSION_BATCHES
--    Top-level tracking record for each CMS submission batch (RAPS, EDPS, EDGE).
--    One row per file submitted to CMS; status advances through the workflow from
--    draft -> validated -> submitted -> acknowledged -> processed (or error).
-- =============================================================================
CREATE TABLE IF NOT EXISTS submission_batches (
  id                        INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id                 VARCHAR(50)     NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  submission_type           ENUM('RAPS','EDPS','EDGE') NOT NULL          COMMENT 'CMS submission program type',
  batch_id_cms              VARCHAR(50)     NOT NULL                      COMMENT 'CMS-assigned batch control number (BCN)',
  payment_year              YEAR            NOT NULL                      COMMENT 'CMS payment year the data supports',
  file_name                 VARCHAR(500)    NULL      DEFAULT NULL        COMMENT 'Original submitted file name',
  file_path                 VARCHAR(1000)   NULL      DEFAULT NULL        COMMENT 'Absolute path or S3 key of the submission file',
  total_records             INT UNSIGNED    NOT NULL DEFAULT 0            COMMENT 'Total detail records included in batch',
  accepted_records          INT UNSIGNED    NOT NULL DEFAULT 0            COMMENT 'Records accepted by CMS per response file',
  rejected_records          INT UNSIGNED    NOT NULL DEFAULT 0            COMMENT 'Records rejected by CMS per response file',
  duplicate_records         INT UNSIGNED    NOT NULL DEFAULT 0            COMMENT 'Records flagged as duplicates by CMS',
  status                    ENUM('draft','validated','submitted','acknowledged','processed','error')
                                            NOT NULL DEFAULT 'draft'      COMMENT 'Lifecycle state of the batch',
  submitted_at              DATETIME        NULL      DEFAULT NULL        COMMENT 'Timestamp when file was transmitted to CMS',
  cms_response_received_at  DATETIME        NULL      DEFAULT NULL        COMMENT 'Timestamp when CMS response file was received',
  submission_deadline       DATE            NULL      DEFAULT NULL        COMMENT 'CMS-mandated deadline for this sweep',
  sweep_type                ENUM('initial','mid_year','final','supplemental')
                                            NOT NULL DEFAULT 'initial'    COMMENT 'CMS submission sweep window',
  created_by                VARCHAR(100)    NULL      DEFAULT NULL        COMMENT 'Username or service account that created the batch',
  created_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_batch_tenant_cms_type (tenant_id, batch_id_cms, submission_type),
  KEY idx_sb_payment_year   (payment_year),
  KEY idx_sb_status         (status),
  KEY idx_sb_sweep_type     (sweep_type),
  KEY idx_sb_submitted_at   (submitted_at),
  KEY idx_sb_tenant_status  (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='CMS submission batch header: one row per submitted file for RAPS, EDPS, or EDGE programs';


-- =============================================================================
-- 2. SUBMISSION_RECORDS
--    Individual detail records within a submission batch.
--    Captures both the outbound diagnosis data and the CMS acceptance/rejection
--    decision returned via MAO-002 / MAO-004 / EDPS response files.
-- =============================================================================
CREATE TABLE IF NOT EXISTS submission_records (
  id                      BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  batch_id                INT UNSIGNED     NOT NULL                      COMMENT 'FK -> submission_batches.id',
  record_type             ENUM(
                            'RAPS_detail',
                            'EDPS_encounter',
                            'EDGE_enrollment',
                            'EDGE_medical',
                            'EDGE_pharmacy',
                            'EDGE_supplemental'
                          )                NOT NULL                      COMMENT 'CMS record format type',
  patient_id              INT UNSIGNED     NULL      DEFAULT NULL        COMMENT 'OpenEMR pid; NULL for non-OpenEMR sourced records',
  hicn_or_mbi             VARCHAR(20)      NOT NULL                      COMMENT 'Health Insurance Claim Number or Medicare Beneficiary Identifier',
  member_id               VARCHAR(50)      NULL      DEFAULT NULL        COMMENT 'Plan-assigned member ID',
  icd10_code              VARCHAR(10)      NOT NULL                      COMMENT 'Submitted ICD-10-CM diagnosis code (no dots)',
  hcc_code                SMALLINT UNSIGNED NULL     DEFAULT NULL        COMMENT 'Mapped HCC category at time of submission',
  diagnosis_cluster       VARCHAR(5)       NULL      DEFAULT NULL        COMMENT 'RAPS diagnosis cluster number (01-10); max 10 per encounter',
  provider_type           ENUM('01','02','03','04','05')
                                           NULL      DEFAULT NULL        COMMENT 'RAPS provider type code (01=physician, 02=outpatient, etc.)',
  from_date               DATE             NOT NULL                      COMMENT 'Service from date',
  through_date            DATE             NOT NULL                      COMMENT 'Service through date',
  delete_indicator        ENUM('0','1')    NOT NULL DEFAULT '0'          COMMENT '0=new/replacement record; 1=delete a previously submitted record',
  risk_assessment_code    VARCHAR(10)      NULL      DEFAULT NULL        COMMENT 'RAPS risk assessment type code where applicable',
  rendering_provider_npi  VARCHAR(10)      NULL      DEFAULT NULL        COMMENT 'NPI of rendering/treating provider',
  facility_npi            VARCHAR(10)      NULL      DEFAULT NULL        COMMENT 'NPI of facility (required for institutional EDPS claims)',
  place_of_service        VARCHAR(5)       NULL      DEFAULT NULL        COMMENT 'CMS place of service code',
  validation_status       ENUM('pending','valid','invalid','warning')
                                           NOT NULL DEFAULT 'pending'    COMMENT 'Pre-submission validation result',
  validation_errors       JSON             NULL      DEFAULT NULL        COMMENT 'Array of validation rule objects: [{rule_code, severity, message}]',
  cms_status              ENUM('pending','accepted','rejected','duplicate')
                                           NOT NULL DEFAULT 'pending'    COMMENT 'CMS acceptance decision from response file',
  cms_error_code          VARCHAR(10)      NULL      DEFAULT NULL        COMMENT 'CMS-returned error/reject code',
  cms_error_description   VARCHAR(500)     NULL      DEFAULT NULL        COMMENT 'Human-readable description of CMS error code',
  source_encounter_id     INT UNSIGNED     NULL      DEFAULT NULL        COMMENT 'OpenEMR encounter ID that originated this record',
  source_claim_id         INT UNSIGNED     NULL      DEFAULT NULL        COMMENT 'Internal claim ID if sourced from a claims feed',
  created_at              DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at              DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_sr_batch_id          (batch_id),
  KEY idx_sr_patient_id        (patient_id),
  KEY idx_sr_icd10_code        (icd10_code),
  KEY idx_sr_hcc_code          (hcc_code),
  KEY idx_sr_validation_status (validation_status),
  KEY idx_sr_cms_status        (cms_status),
  KEY idx_sr_hicn_mbi          (hicn_or_mbi),
  KEY idx_sr_from_through      (from_date, through_date),
  KEY idx_sr_source_encounter  (source_encounter_id),

  CONSTRAINT fk_sr_batch
    FOREIGN KEY (batch_id)
    REFERENCES submission_batches (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual RAPS/EDPS/EDGE detail records within a submission batch, including CMS response disposition';


-- =============================================================================
-- 3. SUBMISSION_RESPONSE_FILES
--    Tracks each CMS response file received for a batch (MAO-002, MAO-004,
--    EDPS response, EDGE response).  A batch may receive multiple response
--    files across the submission cycle.
-- =============================================================================
CREATE TABLE IF NOT EXISTS submission_response_files (
  id                              INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  batch_id                        INT UNSIGNED   NOT NULL                      COMMENT 'FK -> submission_batches.id',
  response_type                   ENUM('MAO-002','MAO-004','EDPS_response','EDGE_response')
                                                 NOT NULL                      COMMENT 'CMS response file format type',
  file_name                       VARCHAR(500)   NULL      DEFAULT NULL        COMMENT 'CMS-provided response file name',
  file_path                       VARCHAR(1000)  NULL      DEFAULT NULL        COMMENT 'Absolute path or S3 key of the response file',
  total_records                   INT UNSIGNED   NOT NULL DEFAULT 0            COMMENT 'Total records in the response file',
  accepted                        INT UNSIGNED   NOT NULL DEFAULT 0            COMMENT 'Records accepted per this response',
  rejected                        INT UNSIGNED   NOT NULL DEFAULT 0            COMMENT 'Records rejected per this response',
  duplicate                       INT UNSIGNED   NOT NULL DEFAULT 0            COMMENT 'Records flagged as duplicate per this response',
  payment_reconciliation_amount   DECIMAL(14,2)  NULL      DEFAULT NULL        COMMENT 'Net payment reconciliation amount from MAO-004 (USD); NULL when not applicable',
  processed_at                    DATETIME       NULL      DEFAULT NULL        COMMENT 'Timestamp when this response file was fully parsed and applied',
  created_at                      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_srf_batch_id      (batch_id),
  KEY idx_srf_response_type (response_type),
  KEY idx_srf_processed_at  (processed_at),

  CONSTRAINT fk_srf_batch
    FOREIGN KEY (batch_id)
    REFERENCES submission_batches (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='CMS response files received per batch (MAO-002, MAO-004, EDPS/EDGE responses)';


-- =============================================================================
-- 4. SUBMISSION_SCHEDULE
--    Tracks CMS-mandated submission deadlines per payment year and sweep.
--    Provides an operational calendar for workflow triggers and alerting.
-- =============================================================================
CREATE TABLE IF NOT EXISTS submission_schedule (
  id                INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  tenant_id         VARCHAR(50)   NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  payment_year      YEAR          NOT NULL                      COMMENT 'CMS payment year',
  sweep_type        ENUM('initial','mid_year','final','supplemental')
                                  NOT NULL                      COMMENT 'CMS submission sweep window',
  submission_type   ENUM('RAPS','EDPS','EDGE')
                                  NOT NULL                      COMMENT 'CMS submission program type',
  deadline_date     DATE          NOT NULL                      COMMENT 'Hard CMS deadline for this sweep/type combination',
  status            ENUM('upcoming','in_progress','submitted','missed')
                                  NOT NULL DEFAULT 'upcoming'   COMMENT 'Operational status of this deadline',
  notes             TEXT          NULL      DEFAULT NULL        COMMENT 'Free-text notes (e.g. CMS deadline change, extension granted)',
  created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_schedule_tenant_year_sweep_type (tenant_id, payment_year, sweep_type, submission_type),
  KEY idx_ss_payment_year   (payment_year),
  KEY idx_ss_deadline_date  (deadline_date),
  KEY idx_ss_status         (status),
  KEY idx_ss_tenant_status  (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='CMS submission deadline calendar per payment year, sweep, and program type';


-- =============================================================================
-- 5. SUBMISSION_VALIDATION_RULES
--    Configurable registry of pre-submission validation rules.
--    Rules are referenced by rule_code in submission_records.validation_errors
--    JSON payloads and can be toggled active/inactive without a code deploy.
-- =============================================================================
CREATE TABLE IF NOT EXISTS submission_validation_rules (
  id                INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  rule_code         VARCHAR(20)    NOT NULL                      COMMENT 'Short unique identifier used in validation_errors JSON (e.g. RAPS_001)',
  rule_description  VARCHAR(500)   NULL      DEFAULT NULL        COMMENT 'Human-readable description of what the rule checks',
  severity          ENUM('error','warning','info')
                                   NOT NULL DEFAULT 'error'      COMMENT 'error=blocks submission; warning=flags but allows; info=informational only',
  rule_type         ENUM('format','clinical','crosswalk','date','provider','duplicate')
                                   NOT NULL                      COMMENT 'Functional category of the rule',
  is_active         TINYINT(1)     NOT NULL DEFAULT 1            COMMENT '1=rule is enforced; 0=rule is disabled',
  created_at        DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_svr_rule_code (rule_code),
  KEY idx_svr_severity   (severity),
  KEY idx_svr_rule_type  (rule_type),
  KEY idx_svr_is_active  (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Registry of configurable CMS submission validation rules; referenced by rule_code in validation_errors JSON';


-- =============================================================================
-- SEED DATA: submission_validation_rules
--    Common CMS RAPS and EDPS validation rules.
--    INSERT IGNORE ensures idempotency on repeated migration runs.
-- =============================================================================
INSERT IGNORE INTO submission_validation_rules
  (rule_code, rule_description, severity, rule_type, is_active)
VALUES
  -- RAPS rules
  ('RAPS_001', 'Invalid HICN/MBI format: value does not match CMS beneficiary identifier pattern',
    'error',   'format',    1),
  ('RAPS_002', 'ICD-10 code not valid for service date: code was not effective during the reported service period',
    'error',   'crosswalk', 1),
  ('RAPS_003', 'Diagnosis cluster exceeds maximum: more than 10 diagnosis clusters submitted for a single encounter',
    'error',   'clinical',  1),
  ('RAPS_004', 'Date range invalid: from_date is after through_date',
    'error',   'date',      1),
  ('RAPS_005', 'Service date outside payment year: at least one service date falls outside the applicable payment year data collection window',
    'error',   'date',      1),
  -- EDPS rules
  ('EDPS_001', 'Missing rendering provider NPI: a valid 10-digit NPI is required for all EDPS encounter records',
    'error',   'provider',  1),
  ('EDPS_002', 'Invalid place of service code: submitted code is not a recognized CMS place of service value',
    'error',   'format',    1),
  ('EDPS_003', 'Encounter date in future: service date cannot be a future date relative to submission date',
    'error',   'date',      1),
  ('EDPS_004', 'Duplicate encounter record: an identical beneficiary/provider/date/diagnosis combination already exists in a prior accepted batch',
    'warning', 'duplicate', 1),
  ('EDPS_005', 'Missing facility information for institutional claims: facility NPI is required when place of service indicates an inpatient or institutional setting',
    'error',   'provider',  1);
