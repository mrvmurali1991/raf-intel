-- =============================================================================
-- Migration 001: FHIR R4 Integration Support
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Adds tables to support ingestion of FHIR R4 resources from
--              external EHR systems (Epic, Cerner, athenahealth, OpenEMR).
--              Covers connection configuration, sync auditing, patient identity
--              matching, and storage of Condition, Encounter, and
--              DiagnosticReport resources.
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. FHIR_CONNECTIONS
--    Stores EHR connection configurations per tenant.
--    client_secret_encrypted is ciphertext; decryption is handled at the
--    application layer — never stored or logged in plaintext.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fhir_connections (
  id                       INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  tenant_id                VARCHAR(50)    NOT NULL DEFAULT 'default'       COMMENT 'Logical tenant / organisation identifier',
  ehr_type                 ENUM('epic','cerner','athenahealth','openemr','generic_fhir')
                                          NOT NULL                         COMMENT 'EHR vendor or generic FHIR R4 endpoint',
  fhir_base_url            VARCHAR(500)   NOT NULL                         COMMENT 'Root FHIR R4 base URL, e.g. https://ehr.example.com/fhir/R4',
  client_id                VARCHAR(255)   NULL DEFAULT NULL                COMMENT 'OAuth2 / SMART client_id',
  client_secret_encrypted  TEXT           NULL DEFAULT NULL                COMMENT 'AES-256-GCM ciphertext of client_secret; decrypted at app layer',
  auth_type                ENUM('oauth2','smart_on_fhir','basic','api_key')
                                          NOT NULL DEFAULT 'oauth2'        COMMENT 'Authentication scheme used against this endpoint',
  token_url                VARCHAR(500)   NULL DEFAULT NULL                COMMENT 'OAuth2 token endpoint; NULL for basic/api_key auth types',
  scope                    VARCHAR(1000)  NOT NULL DEFAULT 'patient/*.read' COMMENT 'Space-separated SMART/OAuth2 scopes to request',
  status                   ENUM('active','inactive','error')
                                          NOT NULL DEFAULT 'active'        COMMENT 'Operational status of this connection',
  last_sync_at             DATETIME       NULL DEFAULT NULL                COMMENT 'Timestamp of most recent successful sync completion',
  created_at               DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at               DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_connection_tenant_ehr_url (tenant_id, ehr_type, fhir_base_url),
  KEY idx_tenant_id    (tenant_id),
  KEY idx_ehr_type     (ehr_type),
  KEY idx_status       (status),
  KEY idx_last_sync_at (last_sync_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='EHR FHIR R4 connection configurations; one row per distinct endpoint per tenant';


-- =============================================================================
-- 2. FHIR_SYNC_LOG
--    Immutable audit trail of every sync operation against a FHIR connection.
--    Rows are inserted at sync start and updated on completion or failure.
--    Never delete rows from this table; use status='cancelled' to void a run.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fhir_sync_log (
  id                INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  connection_id     INT UNSIGNED  NOT NULL                         COMMENT 'FK -> fhir_connections.id',
  sync_type         ENUM('full','incremental','bulk_export')
                                  NOT NULL                         COMMENT 'full = all history; incremental = since last_sync_at; bulk_export = $export operation',
  resource_type     VARCHAR(50)   NOT NULL DEFAULT ''              COMMENT 'FHIR resource type targeted: Condition, Encounter, DiagnosticReport, Patient, etc.',
  records_fetched   INT UNSIGNED  NOT NULL DEFAULT 0               COMMENT 'Total resources returned by the FHIR server',
  records_processed INT UNSIGNED  NOT NULL DEFAULT 0               COMMENT 'Resources successfully written to local tables',
  records_failed    INT UNSIGNED  NOT NULL DEFAULT 0               COMMENT 'Resources that raised a processing error',
  status            ENUM('running','completed','failed','cancelled')
                                  NOT NULL DEFAULT 'running'       COMMENT 'Lifecycle state of this sync run',
  started_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Wall-clock start of the sync run',
  completed_at      DATETIME      NULL DEFAULT NULL                COMMENT 'Wall-clock end; NULL while status = running',
  error_message     TEXT          NULL DEFAULT NULL                COMMENT 'Last error detail for status = failed',
  created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_connection_id  (connection_id),
  KEY idx_sync_type      (sync_type),
  KEY idx_resource_type  (resource_type),
  KEY idx_status         (status),
  KEY idx_started_at     (started_at),
  KEY idx_conn_type_time (connection_id, resource_type, started_at),
  CONSTRAINT fk_synclog_connection
    FOREIGN KEY (connection_id)
    REFERENCES fhir_connections (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Audit log of FHIR sync operations; one row per sync run per resource type';


-- =============================================================================
-- 3. FHIR_PATIENT_MAPPING
--    Resolves the identity link between an external FHIR Patient resource and
--    the corresponding OpenEMR pid. The full FHIR Patient resource is cached
--    in fhir_resource to avoid repeat fetches and to support offline matching.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fhir_patient_mapping (
  id                INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  connection_id     INT UNSIGNED   NOT NULL                         COMMENT 'FK -> fhir_connections.id',
  fhir_patient_id   VARCHAR(255)   NOT NULL                         COMMENT 'Logical FHIR Patient.id from the source EHR',
  openemr_pid       INT UNSIGNED   NOT NULL                         COMMENT 'Matched OpenEMR patient pid',
  fhir_resource     JSON           NULL DEFAULT NULL                COMMENT 'Full FHIR R4 Patient resource as returned by the EHR',
  matched_on        ENUM('mrn','name_dob','ssn','manual')
                                   NOT NULL                         COMMENT 'Identity matching strategy used to create this link',
  created_at        DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_mapping_conn_fhir_patient (connection_id, fhir_patient_id),
  KEY idx_openemr_pid     (openemr_pid),
  KEY idx_matched_on      (matched_on),
  KEY idx_fhir_patient_id (fhir_patient_id),
  CONSTRAINT fk_mapping_connection
    FOREIGN KEY (connection_id)
    REFERENCES fhir_connections (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Identity bridge between FHIR Patient resources and OpenEMR pids';


-- =============================================================================
-- 4. FHIR_CONDITIONS
--    Stores ingested FHIR R4 Condition resources.  Each row represents one
--    Condition as fetched from the EHR.  Duplicate fetches are handled by the
--    application via (connection_id, fhir_condition_id) lookups before INSERT.
--    hcc_mapped is set to 1 by the RAF pipeline after the ICD-10 code has been
--    evaluated against hcc_icd10_crosswalk and written to raf_patient_hcc.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fhir_conditions (
  id                    INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  connection_id         INT UNSIGNED   NOT NULL                         COMMENT 'FK -> fhir_connections.id',
  fhir_patient_id       VARCHAR(255)   NOT NULL                         COMMENT 'FHIR Patient.id from source EHR',
  openemr_pid           INT UNSIGNED   NULL DEFAULT NULL                COMMENT 'Resolved OpenEMR pid; NULL until identity matching runs',
  fhir_condition_id     VARCHAR(255)   NOT NULL                         COMMENT 'FHIR Condition.id from source EHR',
  icd10_code            VARCHAR(10)    NOT NULL DEFAULT ''              COMMENT 'Primary ICD-10-CM code extracted from Condition.code',
  icd10_display         VARCHAR(500)   NOT NULL DEFAULT ''              COMMENT 'Human-readable display text for the ICD-10 code',
  clinical_status       ENUM('active','recurrence','relapse','inactive','remission','resolved')
                                       NOT NULL DEFAULT 'active'        COMMENT 'Condition.clinicalStatus.coding[0].code',
  verification_status   ENUM('unconfirmed','provisional','differential','confirmed','refuted')
                                       NOT NULL DEFAULT 'confirmed'     COMMENT 'Condition.verificationStatus.coding[0].code',
  onset_date            DATE           NULL DEFAULT NULL                COMMENT 'Condition.onsetDateTime or onsetPeriod.start (date part only)',
  abatement_date        DATE           NULL DEFAULT NULL                COMMENT 'Condition.abatementDateTime (date part only); NULL if still active',
  encounter_fhir_id     VARCHAR(255)   NULL DEFAULT NULL                COMMENT 'FHIR Encounter.id referenced by Condition.encounter',
  recorded_date         DATE           NULL DEFAULT NULL                COMMENT 'Condition.recordedDate',
  fhir_resource         JSON           NULL DEFAULT NULL                COMMENT 'Full FHIR R4 Condition resource JSON',
  hcc_mapped            TINYINT(1)     NOT NULL DEFAULT 0               COMMENT '1 = ICD-10 code has been processed by the HCC mapping pipeline',
  created_at            DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_condition_conn_fhir_id (connection_id, fhir_condition_id),
  KEY idx_fhir_patient_id   (fhir_patient_id),
  KEY idx_openemr_pid        (openemr_pid),
  KEY idx_icd10_code         (icd10_code),
  KEY idx_clinical_status    (clinical_status),
  KEY idx_verification_status (verification_status),
  KEY idx_hcc_mapped         (hcc_mapped),
  KEY idx_onset_date         (onset_date),
  KEY idx_pid_status_code    (openemr_pid, clinical_status, icd10_code),
  CONSTRAINT fk_conditions_connection
    FOREIGN KEY (connection_id)
    REFERENCES fhir_connections (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Ingested FHIR R4 Condition resources with extracted ICD-10 and HCC mapping status';


-- =============================================================================
-- 5. FHIR_ENCOUNTERS
--    Stores ingested FHIR R4 Encounter resources.  Encounter data supports
--    MEAT documentation scoring and links Conditions to service events.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fhir_encounters (
  id                  INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  connection_id       INT UNSIGNED   NOT NULL                         COMMENT 'FK -> fhir_connections.id',
  fhir_patient_id     VARCHAR(255)   NOT NULL                         COMMENT 'FHIR Patient.id from source EHR',
  openemr_pid         INT UNSIGNED   NULL DEFAULT NULL                COMMENT 'Resolved OpenEMR pid; NULL until identity matching runs',
  fhir_encounter_id   VARCHAR(255)   NOT NULL                         COMMENT 'FHIR Encounter.id from source EHR',
  encounter_class     VARCHAR(50)    NOT NULL DEFAULT ''              COMMENT 'Encounter.class.code: AMB, EMER, IMP, SS, etc.',
  encounter_type      VARCHAR(255)   NOT NULL DEFAULT ''              COMMENT 'Encounter.type[0].text or display',
  status              ENUM('planned','arrived','triaged','in-progress','onleave','finished','cancelled')
                                     NOT NULL DEFAULT 'finished'      COMMENT 'Encounter.status',
  period_start        DATETIME       NULL DEFAULT NULL                COMMENT 'Encounter.period.start',
  period_end          DATETIME       NULL DEFAULT NULL                COMMENT 'Encounter.period.end',
  provider_name       VARCHAR(255)   NOT NULL DEFAULT ''              COMMENT 'Display name of the primary participant / practitioner',
  provider_npi        VARCHAR(10)    NOT NULL DEFAULT ''              COMMENT 'NPI of the primary participant; empty string if unknown',
  fhir_resource       JSON           NULL DEFAULT NULL                COMMENT 'Full FHIR R4 Encounter resource JSON',
  created_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_encounter_conn_fhir_id (connection_id, fhir_encounter_id),
  KEY idx_fhir_patient_id  (fhir_patient_id),
  KEY idx_openemr_pid       (openemr_pid),
  KEY idx_encounter_class   (encounter_class),
  KEY idx_status            (status),
  KEY idx_period_start      (period_start),
  KEY idx_provider_npi      (provider_npi),
  KEY idx_pid_period        (openemr_pid, period_start),
  CONSTRAINT fk_encounters_connection
    FOREIGN KEY (connection_id)
    REFERENCES fhir_connections (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Ingested FHIR R4 Encounter resources supporting MEAT documentation and timeline analysis';


-- =============================================================================
-- 6. FHIR_DIAGNOSTIC_REPORTS
--    Stores ingested FHIR R4 DiagnosticReport resources (labs, imaging, etc.).
--    The conclusion field is the plain-text narrative summary extracted from
--    DiagnosticReport.conclusion; used by the suspect-condition pipeline.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fhir_diagnostic_reports (
  id                  INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  connection_id       INT UNSIGNED   NOT NULL                         COMMENT 'FK -> fhir_connections.id',
  fhir_patient_id     VARCHAR(255)   NOT NULL                         COMMENT 'FHIR Patient.id from source EHR',
  openemr_pid         INT UNSIGNED   NULL DEFAULT NULL                COMMENT 'Resolved OpenEMR pid; NULL until identity matching runs',
  fhir_report_id      VARCHAR(255)   NOT NULL                         COMMENT 'FHIR DiagnosticReport.id from source EHR',
  report_type         VARCHAR(255)   NOT NULL DEFAULT ''              COMMENT 'DiagnosticReport.code.text or display',
  category            VARCHAR(100)   NOT NULL DEFAULT ''              COMMENT 'DiagnosticReport.category[0].coding[0].code: LAB, RAD, PAT, etc.',
  status              ENUM('registered','partial','preliminary','final','amended','corrected','appended','cancelled')
                                     NOT NULL DEFAULT 'final'         COMMENT 'DiagnosticReport.status',
  effective_date      DATETIME       NULL DEFAULT NULL                COMMENT 'DiagnosticReport.effectiveDateTime or effectivePeriod.start',
  conclusion          TEXT           NULL DEFAULT NULL                COMMENT 'DiagnosticReport.conclusion plain-text narrative',
  fhir_resource       JSON           NULL DEFAULT NULL                COMMENT 'Full FHIR R4 DiagnosticReport resource JSON',
  created_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_report_conn_fhir_id (connection_id, fhir_report_id),
  KEY idx_fhir_patient_id  (fhir_patient_id),
  KEY idx_openemr_pid       (openemr_pid),
  KEY idx_category          (category),
  KEY idx_status            (status),
  KEY idx_effective_date    (effective_date),
  KEY idx_pid_category_date (openemr_pid, category, effective_date),
  CONSTRAINT fk_reports_connection
    FOREIGN KEY (connection_id)
    REFERENCES fhir_connections (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Ingested FHIR R4 DiagnosticReport resources; conclusions feed suspect-condition AI pipeline';
