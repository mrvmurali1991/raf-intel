-- =============================================================================
-- RAF Intelligence System - Migration 010: Chart Chase Management
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Depends on: 004_documents.sql (documents table)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. CHART_CHASE_REQUESTS
--    One row per outreach request for missing or incomplete medical records.
--    Tracks the full lifecycle from creation through receipt of documents,
--    including escalation state and all facility contact details.
-- =============================================================================
CREATE TABLE IF NOT EXISTS chart_chase_requests (
  id                  INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id           VARCHAR(50)       NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  patient_id          INT UNSIGNED      NOT NULL                     COMMENT 'OpenEMR pid',
  provider_npi        VARCHAR(10)           NULL DEFAULT NULL        COMMENT 'NPI of treating provider whose records are being requested',
  requesting_user_id  INT UNSIGNED      NOT NULL                     COMMENT 'FK to raf_users.id — who created this chase',

  -- Classification
  chase_type          ENUM(
                        'initial',
                        'follow_up',
                        'escalation'
                      )                 NOT NULL DEFAULT 'initial'   COMMENT 'Outreach tier',
  reason              ENUM(
                        'suspect_hcc',
                        'audit_response',
                        'missing_encounter',
                        'incomplete_documentation'
                      )                 NOT NULL                     COMMENT 'Clinical reason driving the chase',
  hcc_codes           JSON                  NULL                     COMMENT 'Array of HCC codes motivating this request, e.g. [18, 85]',

  -- Date-of-service window being requested
  dos_from            DATE                  NULL DEFAULT NULL        COMMENT 'Start of date-of-service range',
  dos_to              DATE                  NULL DEFAULT NULL        COMMENT 'End of date-of-service range',

  -- Lifecycle
  status              ENUM(
                        'pending',
                        'sent',
                        'acknowledged',
                        'received',
                        'partial',
                        'completed',
                        'cancelled'
                      )                 NOT NULL DEFAULT 'pending'   COMMENT 'Current state of the chase request',
  priority            ENUM(
                        'critical',
                        'high',
                        'medium',
                        'low'
                      )                 NOT NULL DEFAULT 'medium'    COMMENT 'Operational priority',

  -- Facility contact details (denormalised for portability)
  facility_name       VARCHAR(255)          NULL DEFAULT NULL,
  facility_fax        VARCHAR(30)           NULL DEFAULT NULL,
  facility_email      VARCHAR(255)          NULL DEFAULT NULL,
  facility_phone      VARCHAR(30)           NULL DEFAULT NULL,

  -- Key dates
  request_date        DATE              NOT NULL                     COMMENT 'Date the chase was created / sent',
  due_date            DATE                  NULL DEFAULT NULL        COMMENT 'Target date for receipt',
  received_date       DATE                  NULL DEFAULT NULL        COMMENT 'Date documents were physically received',

  -- Notes and linked document
  notes               TEXT                  NULL,
  document_id         INT UNSIGNED          NULL DEFAULT NULL        COMMENT 'FK to documents.id once records are received',

  -- Attempt tracking
  attempts            INT UNSIGNED      NOT NULL DEFAULT 0           COMMENT 'Total outreach attempts made',
  last_attempt_date   DATE                  NULL DEFAULT NULL        COMMENT 'Date of most recent attempt',

  created_at          DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_ccr_tenant_id           (tenant_id),
  KEY idx_ccr_patient_id          (patient_id),
  KEY idx_ccr_provider_npi        (provider_npi),
  KEY idx_ccr_requesting_user     (requesting_user_id),
  KEY idx_ccr_status              (status),
  KEY idx_ccr_priority            (priority),
  KEY idx_ccr_chase_type          (chase_type),
  KEY idx_ccr_reason              (reason),
  KEY idx_ccr_request_date        (request_date),
  KEY idx_ccr_due_date            (due_date),
  KEY idx_ccr_document_id         (document_id),
  -- Dashboard query: open chases per tenant ordered by priority/due date
  KEY idx_ccr_tenant_status_due   (tenant_id, status, due_date),
  -- Aging report: open chases per patient
  KEY idx_ccr_patient_status      (patient_id, status),

  CONSTRAINT fk_ccr_document
    FOREIGN KEY (document_id) REFERENCES documents (id)
    ON DELETE SET NULL ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Chart chase requests tracking outreach for missing or incomplete medical records';


-- =============================================================================
-- 2. CHART_CHASE_ATTEMPTS
--    One row per individual outreach attempt (fax, email, phone, portal, mail).
--    Provides a full audit trail of all contact activity against a chase request.
-- =============================================================================
CREATE TABLE IF NOT EXISTS chart_chase_attempts (
  id              INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  chase_id        INT UNSIGNED      NOT NULL                     COMMENT 'FK to chart_chase_requests.id',
  attempt_number  INT UNSIGNED      NOT NULL                     COMMENT 'Sequence number within this chase (1, 2, 3 ...)',
  method          ENUM(
                    'fax',
                    'email',
                    'phone',
                    'portal',
                    'mail'
                  )                 NOT NULL                     COMMENT 'Outreach channel used',
  sent_at         DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'When the outreach was dispatched',
  sent_by         VARCHAR(100)      NOT NULL                     COMMENT 'Username or service account that logged this attempt',
  response        TEXT                  NULL                     COMMENT 'Facility response text or notes (NULL if no reply yet)',
  responded_at    DATETIME              NULL DEFAULT NULL        COMMENT 'When the facility responded',
  notes           TEXT                  NULL,

  created_at      DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_cca_chase_id        (chase_id),
  KEY idx_cca_sent_at         (sent_at),
  KEY idx_cca_method          (method),
  -- All attempts for a chase in sequence order
  KEY idx_cca_chase_sequence  (chase_id, attempt_number),

  CONSTRAINT fk_cca_chase
    FOREIGN KEY (chase_id) REFERENCES chart_chase_requests (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual outreach attempt log for each chart chase request';


-- =============================================================================
-- 3. CHART_CHASE_TEMPLATES
--    Reusable message templates for fax cover sheets, emails, and letters.
--    Tenant-scoped so each health plan can maintain its own branded templates.
-- =============================================================================
CREATE TABLE IF NOT EXISTS chart_chase_templates (
  id          INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id   VARCHAR(50)       NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  name        VARCHAR(255)      NOT NULL                     COMMENT 'Human-readable template label',
  type        ENUM(
                'fax_cover',
                'email',
                'letter'
              )                 NOT NULL                     COMMENT 'Output channel this template targets',
  subject     VARCHAR(500)          NULL DEFAULT NULL        COMMENT 'Subject line for email templates; NULL for fax/letter',
  body        TEXT              NOT NULL                     COMMENT 'Template body; supports {{placeholders}} for mail-merge',
  created_at  DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  KEY idx_cct_tenant_id   (tenant_id),
  KEY idx_cct_type        (type),
  KEY idx_cct_tenant_type (tenant_id, type)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Reusable outreach message templates for chart chase communications';
