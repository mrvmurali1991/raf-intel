-- =============================================================================
-- RAF Intelligence System - Migration 002: Claims Data Ingestion Support
-- Adds tables for 837P / 837I / CMS-1500 / UB-04 claim file processing
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Run against: raf_intelligence
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. CLAIMS_BATCHES
--    Tracks every uploaded claim file batch through its full lifecycle.
--    One row per uploaded file; child tables reference this via batch_id.
-- =============================================================================
CREATE TABLE IF NOT EXISTS claims_batches (
  id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id           VARCHAR(50)     NOT NULL DEFAULT 'default'        COMMENT 'Multi-tenant discriminator; "default" for single-tenant deployments',
  batch_name          VARCHAR(255)    NOT NULL                           COMMENT 'Human-readable label for the batch (e.g. filename stem or user-supplied name)',
  file_type           ENUM('837P','837I','CMS1500','UB04','CSV','CUSTOM') NOT NULL COMMENT 'Source format of the uploaded file',
  file_name           VARCHAR(500)        NULL DEFAULT NULL              COMMENT 'Original filename as received from the client',
  file_size_bytes     BIGINT UNSIGNED     NULL DEFAULT NULL              COMMENT 'Raw byte size of the uploaded file',
  total_claims        INT UNSIGNED    NOT NULL DEFAULT 0                 COMMENT 'Total claim segments/records detected during parsing',
  processed_claims    INT UNSIGNED    NOT NULL DEFAULT 0                 COMMENT 'Claims successfully mapped and written to child tables',
  failed_claims       INT UNSIGNED    NOT NULL DEFAULT 0                 COMMENT 'Claims that could not be parsed or persisted',
  status              ENUM('uploaded','parsing','parsed','processing','completed','failed')
                                      NOT NULL DEFAULT 'uploaded'        COMMENT 'Current pipeline stage of this batch',
  error_message       TEXT                NULL DEFAULT NULL              COMMENT 'Populated when status = "failed"; top-level error summary',
  uploaded_by         VARCHAR(100)        NULL DEFAULT NULL              COMMENT 'Username or service account that submitted the file',
  started_at          DATETIME            NULL DEFAULT NULL              COMMENT 'Timestamp when pipeline processing began',
  completed_at        DATETIME            NULL DEFAULT NULL              COMMENT 'Timestamp when pipeline reached "completed" or "failed"',
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_cb_tenant_id    (tenant_id),
  KEY idx_cb_status       (status),
  KEY idx_cb_file_type    (file_type),
  KEY idx_cb_uploaded_by  (uploaded_by),
  KEY idx_cb_created_at   (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Claim file batch registry; one row per uploaded file with lifecycle status tracking';


-- =============================================================================
-- 2. CLAIMS_PROFESSIONAL
--    Parsed claim header records from 837P transactions and CMS-1500 forms.
--    One row per CLM segment (claim submitter ID = claim_id).
--    Diagnosis detail lives in claims_diagnosis_lines; service lines in
--    claims_service_lines.
-- =============================================================================
CREATE TABLE IF NOT EXISTS claims_professional (
  id                        INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  batch_id                  INT UNSIGNED    NOT NULL                       COMMENT 'Parent batch from claims_batches.id',
  claim_id                  VARCHAR(100)    NOT NULL                       COMMENT 'CLM01 - claim submitter ID from the 837P transaction',
  patient_id                INT UNSIGNED        NULL DEFAULT NULL          COMMENT 'OpenEMR pid; NULL until patient match is resolved',
  patient_name              VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'NM1*QC subscriber/patient name as received',
  patient_dob               DATE                NULL DEFAULT NULL          COMMENT 'DMG*D8 patient date of birth',
  patient_gender            ENUM('M','F','U')   NULL DEFAULT NULL          COMMENT 'DMG gender code mapped to M/F/U',
  patient_member_id         VARCHAR(100)        NULL DEFAULT NULL          COMMENT 'Insurance member / subscriber ID (NM1*IL REF)',
  rendering_provider_npi    VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'NPI of the rendering/performing provider (NM1*82)',
  rendering_provider_name   VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'Name of the rendering provider',
  billing_provider_npi      VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'NPI of the billing provider (NM1*85)',
  service_facility_npi      VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'NPI of the service facility (NM1*77)',
  place_of_service          VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'CLM05-1 place of service code (e.g. 11=office, 21=inpatient)',
  claim_frequency_code      VARCHAR(2)          NULL DEFAULT NULL          COMMENT 'CLM05-3 claim frequency / bill type code',
  date_of_service           DATE            NOT NULL                       COMMENT 'Earliest service date on the claim (from DTP*472 or SV1)',
  date_of_service_end       DATE                NULL DEFAULT NULL          COMMENT 'Latest service date when claim spans multiple days',
  total_charge              DECIMAL(10,2)       NULL DEFAULT NULL          COMMENT 'CLM02 total submitted charge amount',
  payer_name                VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'NM1*PR payer name',
  payer_id                  VARCHAR(100)        NULL DEFAULT NULL          COMMENT 'NM1*PR payer identifier (e.g. 00430, 00570)',
  principal_diagnosis       VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'First-listed ICD-10 diagnosis code (HI*ABK); also in claims_diagnosis_lines',
  admit_diagnosis           VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'Admitting diagnosis code (HI*ABJ) when present on professional claim',
  created_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_cp_batch_id                 (batch_id),
  KEY idx_cp_patient_id               (patient_id),
  KEY idx_cp_date_of_service          (date_of_service),
  KEY idx_cp_rendering_provider_npi   (rendering_provider_npi),
  KEY idx_cp_billing_provider_npi     (billing_provider_npi),
  KEY idx_cp_claim_id                 (claim_id),
  KEY idx_cp_patient_member_id        (patient_member_id),
  CONSTRAINT fk_cp_batch_id
    FOREIGN KEY (batch_id)
    REFERENCES claims_batches (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Parsed 837P / CMS-1500 professional claim headers; one row per CLM segment';


-- =============================================================================
-- 3. CLAIMS_DIAGNOSIS_LINES
--    All ICD-10 diagnosis codes attached to a claim, for both professional
--    and institutional claim types.  claim_type + claim_id form a logical FK
--    to claims_professional.id or claims_institutional.id respectively.
--    HCC mapping columns are populated by the post-parse HCC enrichment job.
-- =============================================================================
CREATE TABLE IF NOT EXISTS claims_diagnosis_lines (
  id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  claim_type          ENUM('professional','institutional') NOT NULL      COMMENT 'Discriminator: which parent claims table this row belongs to',
  claim_id            INT UNSIGNED    NOT NULL                           COMMENT 'PK of the parent row in claims_professional or claims_institutional',
  diagnosis_pointer   TINYINT UNSIGNED NOT NULL                          COMMENT 'Diagnosis sequence number within the claim (1-12 per X12 spec)',
  icd10_code          VARCHAR(10)     NOT NULL                           COMMENT 'ICD-10-CM diagnosis code, stripped of decimal (e.g. E1140)',
  icd10_description   VARCHAR(500)        NULL DEFAULT NULL              COMMENT 'Short description; denormalized from hcc_icd10_crosswalk for query convenience',
  is_principal        TINYINT(1)      NOT NULL DEFAULT 0                 COMMENT '1 = first-listed / principal diagnosis',
  is_admitting        TINYINT(1)      NOT NULL DEFAULT 0                 COMMENT '1 = admitting diagnosis (HI*ABJ loop)',
  hcc_code            SMALLINT UNSIGNED   NULL DEFAULT NULL              COMMENT 'Mapped HCC V28 code; NULL until enrichment job runs',
  hcc_mapped          TINYINT(1)      NOT NULL DEFAULT 0                 COMMENT '1 = enrichment job has attempted HCC lookup (regardless of match)',
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_cdl_claim_type_claim_id (claim_type, claim_id),
  KEY idx_cdl_icd10_code          (icd10_code),
  KEY idx_cdl_hcc_code            (hcc_code),
  KEY idx_cdl_hcc_mapped          (hcc_mapped),
  KEY idx_cdl_is_principal        (is_principal)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='ICD-10 diagnosis codes per claim for both professional and institutional claim types';


-- =============================================================================
-- 4. CLAIMS_SERVICE_LINES
--    CPT / HCPCS procedure lines from SV1 (professional) or SV2
--    (institutional) loops.  claim_type + claim_id mirror the pattern used
--    in claims_diagnosis_lines.  diagnosis_pointers is a JSON array of
--    integers referencing diagnosis_pointer values in claims_diagnosis_lines.
-- =============================================================================
CREATE TABLE IF NOT EXISTS claims_service_lines (
  id                      INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  claim_type              ENUM('professional','institutional') NOT NULL  COMMENT 'Discriminator: which parent claims table this row belongs to',
  claim_id                INT UNSIGNED    NOT NULL                       COMMENT 'PK of the parent row in claims_professional or claims_institutional',
  line_number             TINYINT UNSIGNED NOT NULL                      COMMENT 'Sequential line number within the claim (1-based)',
  cpt_hcpcs_code          VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'SV101-2 procedure code (CPT or HCPCS Level II)',
  modifier_1              VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'SV101-3 first procedure modifier',
  modifier_2              VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'SV101-4 second procedure modifier',
  units                   DECIMAL(5,2)        NULL DEFAULT NULL          COMMENT 'SV104 service unit count',
  charge_amount           DECIMAL(10,2)       NULL DEFAULT NULL          COMMENT 'SV102 submitted charge for this line',
  date_of_service         DATE                NULL DEFAULT NULL          COMMENT 'DTP*472 line-level date of service; overrides claim-level when present',
  place_of_service        VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'SV105 line-level place of service; overrides claim-level when present',
  diagnosis_pointers      JSON                NULL DEFAULT NULL          COMMENT 'Array of integers referencing diagnosis_pointer in claims_diagnosis_lines (SV107)',
  rendering_provider_npi  VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'Line-level rendering provider NPI when different from claim-level',
  created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_csl_claim_type_claim_id (claim_type, claim_id),
  KEY idx_csl_cpt_hcpcs_code      (cpt_hcpcs_code),
  KEY idx_csl_date_of_service     (date_of_service),
  KEY idx_csl_rendering_npi       (rendering_provider_npi)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='CPT/HCPCS procedure service lines per claim for both professional and institutional claim types';


-- =============================================================================
-- 5. CLAIMS_INSTITUTIONAL
--    Parsed claim header records from 837I transactions and UB-04 forms.
--    Admission/discharge dates and facility-level fields distinguish these
--    from professional claims.  Diagnosis and service lines share
--    claims_diagnosis_lines and claims_service_lines via claim_type='institutional'.
-- =============================================================================
CREATE TABLE IF NOT EXISTS claims_institutional (
  id                        INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  batch_id                  INT UNSIGNED    NOT NULL                       COMMENT 'Parent batch from claims_batches.id',
  claim_id                  VARCHAR(100)        NULL DEFAULT NULL          COMMENT 'CLM01 - claim submitter ID from the 837I transaction',
  patient_id                INT UNSIGNED        NULL DEFAULT NULL          COMMENT 'OpenEMR pid; NULL until patient match is resolved',
  patient_name              VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'NM1*QC patient name as received',
  patient_dob               DATE                NULL DEFAULT NULL          COMMENT 'DMG*D8 patient date of birth',
  patient_gender            ENUM('M','F','U')   NULL DEFAULT NULL          COMMENT 'DMG gender code mapped to M/F/U',
  patient_member_id         VARCHAR(100)        NULL DEFAULT NULL          COMMENT 'Insurance member / subscriber ID',
  attending_provider_npi    VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'NPI of the attending physician (NM1*71)',
  attending_provider_name   VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'Name of the attending physician',
  facility_npi              VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'NPI of the billing / rendering facility (NM1*85)',
  facility_name             VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'Name of the billing / rendering facility',
  admission_date            DATE                NULL DEFAULT NULL          COMMENT 'DTP*435 admission date',
  discharge_date            DATE                NULL DEFAULT NULL          COMMENT 'DTP*096 discharge date',
  admission_type            VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'CL101 type of admission code (e.g. 1=emergency, 2=urgent)',
  admission_source          VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'CL102 source of admission code (e.g. 1=physician referral)',
  discharge_status          VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'CL103 patient discharge status code (e.g. 01=home, 20=expired)',
  type_of_bill              VARCHAR(5)          NULL DEFAULT NULL          COMMENT 'CLM05-1 type of bill code for institutional (e.g. 0111, 0131)',
  drg_code                  VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'HI*DR DRG assigned by payer or facility grouper',
  total_charges             DECIMAL(12,2)       NULL DEFAULT NULL          COMMENT 'CLM02 total submitted charges (wider precision for institutional)',
  payer_name                VARCHAR(255)        NULL DEFAULT NULL          COMMENT 'NM1*PR payer name',
  payer_id                  VARCHAR(100)        NULL DEFAULT NULL          COMMENT 'NM1*PR payer identifier',
  principal_diagnosis       VARCHAR(10)         NULL DEFAULT NULL          COMMENT 'First-listed ICD-10 diagnosis code (HI*ABK); also in claims_diagnosis_lines',
  created_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ci_batch_id               (batch_id),
  KEY idx_ci_patient_id             (patient_id),
  KEY idx_ci_admission_date         (admission_date),
  KEY idx_ci_discharge_date         (discharge_date),
  KEY idx_ci_attending_provider_npi (attending_provider_npi),
  KEY idx_ci_facility_npi           (facility_npi),
  KEY idx_ci_claim_id               (claim_id),
  KEY idx_ci_drg_code               (drg_code),
  KEY idx_ci_patient_member_id      (patient_member_id),
  CONSTRAINT fk_ci_batch_id
    FOREIGN KEY (batch_id)
    REFERENCES claims_batches (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Parsed 837I / UB-04 institutional claim headers; one row per CLM segment';
