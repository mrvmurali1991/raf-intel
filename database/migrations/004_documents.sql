-- =============================================================================
-- RAF Intelligence System - Migration 004: Document Upload & Gemini Vision
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Depends on: schema.sql (raf_patient_demographics)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. DOCUMENTS
--    Uploaded clinical documents (PDFs, images) awaiting or having undergone
--    Gemini Vision extraction. Supports multi-tenant deployments. The
--    file_hash unique constraint enforces deduplication at the storage layer
--    so the same physical document is never processed twice.
-- =============================================================================
CREATE TABLE IF NOT EXISTS documents (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'  COMMENT 'Multi-tenant discriminator',
  patient_id        INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'OpenEMR pid; NULL until document is matched to a patient',
  document_name     VARCHAR(500)      NOT NULL                    COMMENT 'Original filename or user-supplied label',
  document_type     ENUM(
                      'progress_note',
                      'discharge_summary',
                      'lab_report',
                      'radiology_report',
                      'consultation',
                      'operative_note',
                      'pathology',
                      'referral',
                      'insurance_eob',
                      'other'
                    )                 NOT NULL DEFAULT 'other'    COMMENT 'Clinical document classification',
  file_type         ENUM(
                      'pdf','png','jpg','jpeg',
                      'tiff','bmp','gif','webp','heic'
                    )                 NOT NULL                    COMMENT 'File format; drives Gemini Vision input handling',
  file_size_bytes   BIGINT UNSIGNED       NULL DEFAULT NULL       COMMENT 'Raw file size in bytes',
  file_path         VARCHAR(1000)     NOT NULL                    COMMENT 'Absolute server-side storage path or object-store key',
  file_hash         VARCHAR(64)           NULL DEFAULT NULL       COMMENT 'SHA-256 hex digest for deduplication',
  page_count        INT UNSIGNED      NOT NULL DEFAULT 1          COMMENT 'Total pages; 1 for single-page images',
  source            ENUM(
                      'upload',
                      'fax',
                      'ehr_export',
                      'chart_chase',
                      'scan'
                    )                 NOT NULL DEFAULT 'upload'   COMMENT 'How the document entered the system',
  encounter_id      INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'Linked OpenEMR encounter ID (nullable)',
  encounter_date    DATE                  NULL DEFAULT NULL       COMMENT 'Date of service extracted or supplied by uploader',
  provider_name     VARCHAR(255)          NULL DEFAULT NULL       COMMENT 'Treating provider name as read from document',
  provider_npi      VARCHAR(10)           NULL DEFAULT NULL       COMMENT 'Treating provider NPI as read from document',
  status            ENUM(
                      'uploaded',
                      'processing',
                      'analyzed',
                      'reviewed',
                      'archived',
                      'error'
                    )                 NOT NULL DEFAULT 'uploaded' COMMENT 'Lifecycle state of the document',
  uploaded_by       VARCHAR(100)          NULL DEFAULT NULL       COMMENT 'Username or service account that created the record',
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  -- Prevent exact duplicate files from being stored and re-processed
  UNIQUE KEY uq_documents_file_hash        (file_hash),

  KEY idx_documents_patient_id             (patient_id),
  KEY idx_documents_document_type          (document_type),
  KEY idx_documents_status                 (status),
  KEY idx_documents_encounter_date         (encounter_date),
  KEY idx_documents_tenant_id              (tenant_id),
  KEY idx_documents_source                 (source),
  -- Composite used by the worklist query: all unanalyzed docs for a tenant
  KEY idx_documents_tenant_status          (tenant_id, status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Clinical documents uploaded for Gemini Vision extraction and RAF analysis';


-- =============================================================================
-- 2. DOCUMENT_ANALYSIS
--    Stores the full Gemini Vision extraction result for a document. One row
--    per analysis run; re-processing a document creates a new row, allowing
--    comparison across model versions.
-- =============================================================================
CREATE TABLE IF NOT EXISTS document_analysis (
  id                    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  document_id           INT UNSIGNED      NOT NULL                    COMMENT 'FK to documents.id',
  analysis_type         ENUM(
                          'full_extraction',
                          'diagnosis_only',
                          'medication_only',
                          'lab_only'
                        )                 NOT NULL DEFAULT 'full_extraction' COMMENT 'Scope of the Gemini prompt used',
  gemini_model          VARCHAR(100)      NOT NULL DEFAULT 'gemini-2.5-pro'  COMMENT 'Gemini model version used for this run',

  -- Raw OCR / extracted text
  extracted_text        TEXT                  NULL                    COMMENT 'Full text content returned by Gemini Vision',

  -- Structured extraction payloads (JSON arrays)
  extracted_diagnoses   JSON                  NULL
    COMMENT 'Array of {icd10_code, description, confidence, page_number, evidence_text}',
  extracted_medications JSON                  NULL
    COMMENT 'Array of {name, dose, frequency, prescriber}',
  extracted_labs        JSON                  NULL
    COMMENT 'Array of {test_name, value, unit, reference_range, date}',
  extracted_vitals      JSON                  NULL
    COMMENT 'Array of {type, value, unit, date}',
  extracted_procedures  JSON                  NULL
    COMMENT 'Array of {cpt_code, description, date}',
  extracted_providers   JSON                  NULL
    COMMENT 'Array of {name, npi, specialty, role}',

  -- Summarisation and RAF-focused outputs
  clinical_summary      TEXT                  NULL                    COMMENT 'Gemini-generated narrative summary of the document',
  hcc_codes_found       JSON                  NULL
    COMMENT 'Array of {hcc_code, icd10_code, confidence, evidence} confirmed HCC-mapped codes',
  suspect_conditions    JSON                  NULL
    COMMENT 'Array of {icd10_code, hcc_code, evidence, confidence} for conditions not yet documented',
  meat_evidence         JSON                  NULL
    COMMENT 'Object with keys monitor, evaluate, assess, treat — text passages supporting MEAT criteria',

  -- Quality and operational metadata
  quality_score         DECIMAL(5,4)      NOT NULL DEFAULT 0.0000     COMMENT '0.0000–1.0000 Gemini-rated document legibility/completeness',
  processing_time_ms    INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'Wall-clock ms from job start to completion',
  token_count           INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'Total Gemini tokens consumed (input + output)',
  status                ENUM(
                          'pending',
                          'processing',
                          'completed',
                          'failed'
                        )                 NOT NULL DEFAULT 'pending'  COMMENT 'Processing state of this analysis run',
  error_message         TEXT                  NULL                    COMMENT 'Gemini API or parsing error detail on failure',
  created_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_doc_analysis_document_id         (document_id),
  KEY idx_doc_analysis_status              (status),
  KEY idx_doc_analysis_gemini_model        (gemini_model),
  -- Most recent completed analysis per document
  KEY idx_doc_analysis_document_completed  (document_id, status),

  CONSTRAINT fk_doc_analysis_document
    FOREIGN KEY (document_id) REFERENCES documents (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Gemini Vision extraction results per document, one row per analysis run';


-- =============================================================================
-- 3. DOCUMENT_DIAGNOSIS_LINES
--    Normalised, one-row-per-diagnosis expansion of extracted_diagnoses. Allows
--    reviewers to confirm or reject individual codes without patching the JSON
--    payload, and enables indexed lookups by ICD-10 / HCC code across documents.
-- =============================================================================
CREATE TABLE IF NOT EXISTS document_diagnosis_lines (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  document_id       INT UNSIGNED      NOT NULL                    COMMENT 'FK to documents.id',
  analysis_id       INT UNSIGNED      NOT NULL                    COMMENT 'FK to document_analysis.id',
  icd10_code        VARCHAR(10)       NOT NULL                    COMMENT 'ICD-10-CM code extracted from document',
  icd10_description VARCHAR(500)          NULL DEFAULT NULL       COMMENT 'Long description of the ICD-10 code',
  hcc_code          SMALLINT UNSIGNED     NULL DEFAULT NULL       COMMENT 'Mapped HCC V28 category, NULL if non-HCC',
  confidence_score  DECIMAL(5,4)          NULL DEFAULT NULL       COMMENT '0.0000–1.0000 Gemini extraction confidence',
  page_number       INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'Document page where the diagnosis was found',
  evidence_text     TEXT                  NULL                    COMMENT 'Verbatim text passage from the document supporting this diagnosis',

  -- Reviewer workflow flags
  is_confirmed      TINYINT(1)        NOT NULL DEFAULT 0          COMMENT '1 = clinical reviewer accepted this diagnosis',
  is_rejected       TINYINT(1)        NOT NULL DEFAULT 0          COMMENT '1 = clinical reviewer rejected this diagnosis',
  reviewed_by       VARCHAR(100)          NULL DEFAULT NULL       COMMENT 'Username of reviewer who set confirmed/rejected',
  reviewed_at       DATETIME              NULL DEFAULT NULL       COMMENT 'Timestamp of review action',

  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_ddl_document_id                  (document_id),
  KEY idx_ddl_analysis_id                  (analysis_id),
  KEY idx_ddl_icd10_code                   (icd10_code),
  KEY idx_ddl_hcc_code                     (hcc_code),
  KEY idx_ddl_is_confirmed                 (is_confirmed),
  KEY idx_ddl_is_rejected                  (is_rejected),
  -- RAF gap analysis query: pending HCC-mapped lines for a specific document
  KEY idx_ddl_document_hcc_review          (document_id, hcc_code, is_confirmed, is_rejected),

  CONSTRAINT fk_ddl_document
    FOREIGN KEY (document_id) REFERENCES documents (id)
    ON DELETE CASCADE ON UPDATE CASCADE,

  CONSTRAINT fk_ddl_analysis
    FOREIGN KEY (analysis_id) REFERENCES document_analysis (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual diagnosis lines extracted from documents; supports per-code reviewer workflow';


-- =============================================================================
-- 4. DOCUMENT_BATCHES
--    Tracks multi-document upload sessions (chart chase drops, fax bursts, etc.)
--    so the UI can report aggregate progress and allow batch-level retry on
--    partial failures.
-- =============================================================================
CREATE TABLE IF NOT EXISTS document_batches (
  id                    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id             VARCHAR(50)       NOT NULL DEFAULT 'default'  COMMENT 'Multi-tenant discriminator',
  batch_name            VARCHAR(255)      NOT NULL                    COMMENT 'User-supplied label or auto-generated (e.g. "Chart Chase 2026-04-01")',
  total_documents       INT UNSIGNED      NOT NULL DEFAULT 0          COMMENT 'Total documents registered in this batch',
  processed_documents   INT UNSIGNED      NOT NULL DEFAULT 0          COMMENT 'Documents with analysis status = completed',
  failed_documents      INT UNSIGNED      NOT NULL DEFAULT 0          COMMENT 'Documents with analysis status = failed',
  status                ENUM(
                          'uploading',
                          'processing',
                          'completed',
                          'failed'
                        )                 NOT NULL DEFAULT 'uploading' COMMENT 'Aggregate lifecycle state of the batch',
  created_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at          DATETIME              NULL DEFAULT NULL       COMMENT 'Timestamp when all documents reached a terminal state',

  PRIMARY KEY (id),

  KEY idx_doc_batches_tenant_id            (tenant_id),
  KEY idx_doc_batches_status               (status),
  KEY idx_doc_batches_tenant_status        (tenant_id, status),
  KEY idx_doc_batches_created_at           (created_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Batch upload sessions grouping multiple documents for aggregate progress tracking';


-- =============================================================================
-- OPTIONAL: Add batch_id back-reference to documents
--   Allows joining documents to their originating batch. Added as ALTER so
--   this migration is safe to run against a database that already has the
--   documents table created without the column.
-- =============================================================================
ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS batch_id INT UNSIGNED NULL DEFAULT NULL
    COMMENT 'FK to document_batches.id; NULL for individually uploaded documents'
    AFTER source,
  ADD KEY IF NOT EXISTS idx_documents_batch_id (batch_id);

ALTER TABLE documents
  ADD CONSTRAINT IF NOT EXISTS fk_documents_batch
    FOREIGN KEY (batch_id) REFERENCES document_batches (id)
    ON DELETE SET NULL ON UPDATE CASCADE;
