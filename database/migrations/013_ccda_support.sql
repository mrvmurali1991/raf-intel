-- =============================================================================
-- RAF Intelligence System - Migration 013: C-CDA / CCD Document Support
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Depends on: schema.sql (raf_patient_demographics), 001_fhir_integration.sql
--             (hcc_icd10_crosswalk)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. CCDA_DOCUMENTS
--    Master record for every C-CDA / CCD XML document that enters the system.
--    A single document may arrive via file upload, a FHIR $document operation,
--    a Direct Message (HISP), or an HL7 v2.x interface.  The parsed_data JSON
--    column stores a structured summary of all extracted sections so the API
--    can return a full-document view without joining child tables.
-- =============================================================================
CREATE TABLE IF NOT EXISTS ccda_documents (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  patient_id        INT UNSIGNED          NULL DEFAULT NULL
    COMMENT 'OpenEMR pid; NULL when not yet matched to a patient',
  document_type     ENUM(
                      'ccd',
                      'discharge_summary',
                      'referral',
                      'progress_note',
                      'history_physical'
                    )                 NOT NULL DEFAULT 'ccd'
    COMMENT 'HL7 CDA document type code (LOINC-derived)',
  source            ENUM(
                      'upload',
                      'fhir',
                      'direct_message',
                      'hl7'
                    )                 NOT NULL DEFAULT 'upload'
    COMMENT 'Ingestion channel through which the document arrived',
  original_filename VARCHAR(500)          NULL DEFAULT NULL
    COMMENT 'Original client-supplied filename; NULL for programmatic ingestion',
  file_path         VARCHAR(1000)     NOT NULL
    COMMENT 'Absolute server-side path or object-store key for the raw XML',
  file_size         BIGINT UNSIGNED       NULL DEFAULT NULL
    COMMENT 'Raw byte size of the XML file',
  doc_date          DATE                  NULL DEFAULT NULL
    COMMENT 'Clinical effective date parsed from ClinicalDocument/effectiveTime',
  author_name       VARCHAR(255)          NULL DEFAULT NULL
    COMMENT 'Author displayName from CDA header',
  author_npi        VARCHAR(10)           NULL DEFAULT NULL
    COMMENT 'Author NPI extracted from assignedAuthor/id root=2.16.840.1.113883.4.6',
  custodian_org     VARCHAR(255)          NULL DEFAULT NULL
    COMMENT 'Organization name from CDA custodian element',
  status            ENUM(
                      'uploaded',
                      'parsing',
                      'parsed',
                      'error'
                    )                 NOT NULL DEFAULT 'uploaded'
    COMMENT 'Pipeline state of the document',
  error_message     TEXT                  NULL DEFAULT NULL
    COMMENT 'Parser or validation error detail when status = error',
  parsed_data       JSON                  NULL
    COMMENT 'Structured summary of all extracted sections: problems, meds, results, encounters, procedures, vitals',
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'
    COMMENT 'Multi-tenant discriminator',
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_ccda_documents_patient_id         (patient_id),
  KEY idx_ccda_documents_document_type      (document_type),
  KEY idx_ccda_documents_source             (source),
  KEY idx_ccda_documents_status             (status),
  KEY idx_ccda_documents_doc_date           (doc_date),
  KEY idx_ccda_documents_tenant_id          (tenant_id),
  KEY idx_ccda_documents_tenant_status      (tenant_id, status),
  KEY idx_ccda_documents_author_npi         (author_npi)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='C-CDA / CCD XML documents: one row per document, tracks ingestion source and parse lifecycle';


-- =============================================================================
-- 2. CCDA_PROBLEMS
--    Normalised problem list entries extracted from the CDA Problems section
--    (templateId 2.16.840.1.113883.10.20.22.2.5.1).  Both SNOMED CT and
--    ICD-10-CM codes are stored; a best-effort SNOMED→ICD-10 crosswalk is
--    applied at parse time, and ICD-10→HCC mapping is applied via the
--    existing hcc_icd10_crosswalk table.
-- =============================================================================
CREATE TABLE IF NOT EXISTS ccda_problems (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  ccda_id           INT UNSIGNED      NOT NULL
    COMMENT 'FK to ccda_documents.id',
  patient_id        INT UNSIGNED          NULL DEFAULT NULL
    COMMENT 'Denormalised OpenEMR pid for fast per-patient queries',
  icd10_code        VARCHAR(10)           NULL DEFAULT NULL
    COMMENT 'ICD-10-CM code — translated from SNOMED or extracted directly',
  snomed_code       VARCHAR(20)           NULL DEFAULT NULL
    COMMENT 'SNOMED CT concept code from the observation/value element',
  problem_name      VARCHAR(500)      NOT NULL
    COMMENT 'Human-readable problem description from displayName or originalText',
  onset_date        DATE                  NULL DEFAULT NULL
    COMMENT 'Problem onset date from effectiveTime/low',
  resolved_date     DATE                  NULL DEFAULT NULL
    COMMENT 'Problem resolution date from effectiveTime/high; NULL = ongoing',
  status            ENUM(
                      'active',
                      'resolved',
                      'inactive'
                    )                 NOT NULL DEFAULT 'active'
    COMMENT 'Clinical status translated from CDA statusCode',
  hcc_code          VARCHAR(20)           NULL DEFAULT NULL
    COMMENT 'CMS-HCC V28 category mapped from icd10_code via hcc_icd10_crosswalk',
  hcc_description   VARCHAR(500)          NULL DEFAULT NULL
    COMMENT 'Human-readable HCC category label',
  source_section    VARCHAR(100)          NULL DEFAULT NULL
    COMMENT 'CDA section templateId or title from which this entry was extracted',
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'
    COMMENT 'Multi-tenant discriminator',
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_ccda_problems_ccda_id             (ccda_id),
  KEY idx_ccda_problems_patient_id          (patient_id),
  KEY idx_ccda_problems_icd10_code          (icd10_code),
  KEY idx_ccda_problems_snomed_code         (snomed_code),
  KEY idx_ccda_problems_status              (status),
  KEY idx_ccda_problems_hcc_code            (hcc_code),
  KEY idx_ccda_problems_tenant_id           (tenant_id),
  -- RAF gap analysis: all active HCC-mapped problems per patient
  KEY idx_ccda_problems_patient_hcc_status  (patient_id, hcc_code, status),

  CONSTRAINT fk_ccda_problems_ccda
    FOREIGN KEY (ccda_id) REFERENCES ccda_documents (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Problem list entries extracted from C-CDA Problems section; includes ICD-10 and HCC mappings';


-- =============================================================================
-- 3. CCDA_MEDICATIONS
--    Active and historical medications from the CDA Medications section
--    (templateId 2.16.840.1.113883.10.20.22.2.1.1).
-- =============================================================================
CREATE TABLE IF NOT EXISTS ccda_medications (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  ccda_id           INT UNSIGNED      NOT NULL
    COMMENT 'FK to ccda_documents.id',
  patient_id        INT UNSIGNED          NULL DEFAULT NULL
    COMMENT 'Denormalised OpenEMR pid for fast per-patient queries',
  rxnorm_code       VARCHAR(20)           NULL DEFAULT NULL
    COMMENT 'RxNorm concept unique identifier (RxCUI) from consumable/manufacturedMaterial/code',
  medication_name   VARCHAR(500)      NOT NULL
    COMMENT 'Medication display name or originalText',
  dose              VARCHAR(100)          NULL DEFAULT NULL
    COMMENT 'Dose quantity with unit, e.g. "10 mg"',
  route             VARCHAR(100)          NULL DEFAULT NULL
    COMMENT 'Route of administration, e.g. "oral", "IV"',
  frequency         VARCHAR(200)          NULL DEFAULT NULL
    COMMENT 'Dosing frequency from effectiveTime/period or text, e.g. "twice daily"',
  start_date        DATE                  NULL DEFAULT NULL
    COMMENT 'Medication start date from effectiveTime/low',
  end_date          DATE                  NULL DEFAULT NULL
    COMMENT 'Medication end date from effectiveTime/high; NULL = ongoing',
  status            VARCHAR(50)           NULL DEFAULT 'active'
    COMMENT 'Medication status: active, completed, discontinued, etc.',
  prescriber_npi    VARCHAR(10)           NULL DEFAULT NULL
    COMMENT 'Prescriber NPI from performer/assignedEntity/id root=2.16.840.1.113883.4.6',
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'
    COMMENT 'Multi-tenant discriminator',
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_ccda_medications_ccda_id          (ccda_id),
  KEY idx_ccda_medications_patient_id       (patient_id),
  KEY idx_ccda_medications_rxnorm_code      (rxnorm_code),
  KEY idx_ccda_medications_status           (status),
  KEY idx_ccda_medications_tenant_id        (tenant_id),

  CONSTRAINT fk_ccda_medications_ccda
    FOREIGN KEY (ccda_id) REFERENCES ccda_documents (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Medication entries extracted from C-CDA Medications section';


-- =============================================================================
-- 4. CCDA_RESULTS
--    Lab and diagnostic results from the CDA Results section
--    (templateId 2.16.840.1.113883.10.20.22.2.3.1).
-- =============================================================================
CREATE TABLE IF NOT EXISTS ccda_results (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  ccda_id           INT UNSIGNED      NOT NULL
    COMMENT 'FK to ccda_documents.id',
  patient_id        INT UNSIGNED          NULL DEFAULT NULL
    COMMENT 'Denormalised OpenEMR pid for fast per-patient queries',
  loinc_code        VARCHAR(20)           NULL DEFAULT NULL
    COMMENT 'LOINC code identifying the observation type',
  test_name         VARCHAR(500)      NOT NULL
    COMMENT 'Human-readable test name from displayName or originalText',
  value_text        VARCHAR(500)          NULL DEFAULT NULL
    COMMENT 'Raw result value when non-numeric, e.g. "Positive", "Negative"',
  value_numeric     DECIMAL(18, 6)        NULL DEFAULT NULL
    COMMENT 'Numeric result value; NULL for qualitative results',
  unit              VARCHAR(100)          NULL DEFAULT NULL
    COMMENT 'Unit of measure, e.g. "mg/dL", "%"',
  reference_range   VARCHAR(200)          NULL DEFAULT NULL
    COMMENT 'Reference range string as reported, e.g. "70-100"',
  abnormal_flag     VARCHAR(20)           NULL DEFAULT NULL
    COMMENT 'Interpretation code: H (high), L (low), A (abnormal), N (normal)',
  result_date       DATE                  NULL DEFAULT NULL
    COMMENT 'Observation effective date from effectiveTime',
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'
    COMMENT 'Multi-tenant discriminator',
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_ccda_results_ccda_id              (ccda_id),
  KEY idx_ccda_results_patient_id           (patient_id),
  KEY idx_ccda_results_loinc_code           (loinc_code),
  KEY idx_ccda_results_result_date          (result_date),
  KEY idx_ccda_results_abnormal_flag        (abnormal_flag),
  KEY idx_ccda_results_tenant_id            (tenant_id),

  CONSTRAINT fk_ccda_results_ccda
    FOREIGN KEY (ccda_id) REFERENCES ccda_documents (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Lab and diagnostic results extracted from C-CDA Results section';
