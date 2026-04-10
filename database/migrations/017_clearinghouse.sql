-- =============================================================================
-- RAF Intelligence System - Migration 017: Clearinghouse Integration
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- Provides real-time eligibility verification via ANSI X12 270/271
-- transactions and modern REST APIs (Availity, Change Healthcare, etc.).
--
-- Tables created:
--   clearinghouse_connections  – vendor credentials and endpoint config
--   eligibility_checks         – individual 270/271 transaction records
--   eligibility_batch          – batch verification job tracking
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. CLEARINGHOUSE_CONNECTIONS
--    One row per configured clearinghouse vendor connection.  API keys and
--    secrets are stored AES-256-GCM encrypted at the application layer
--    before being written here; plaintext credentials never touch the DB.
-- =============================================================================
CREATE TABLE IF NOT EXISTS clearinghouse_connections (
  id                    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id             VARCHAR(50)       NOT NULL DEFAULT 'default'     COMMENT 'Multi-tenant discriminator',
  name                  VARCHAR(255)      NOT NULL                       COMMENT 'Human-readable label for this connection',
  vendor                ENUM(
                          'availity',
                          'change_healthcare',
                          'waystar',
                          'trizetto',
                          'custom'
                        )                 NOT NULL DEFAULT 'custom'      COMMENT 'Clearinghouse vendor',
  api_base_url          VARCHAR(512)      NOT NULL                       COMMENT 'Base URL for the vendor REST API or X12 gateway',
  api_key_encrypted     TEXT                  NULL DEFAULT NULL          COMMENT 'AES-256-GCM encrypted API key / client ID',
  api_secret_encrypted  TEXT                  NULL DEFAULT NULL          COMMENT 'AES-256-GCM encrypted API secret / client secret',
  sender_id             VARCHAR(50)           NULL DEFAULT NULL          COMMENT 'X12 ISA06 sender identifier',
  receiver_id           VARCHAR(50)           NULL DEFAULT NULL          COMMENT 'X12 ISA08 receiver identifier',
  submitter_id          VARCHAR(50)           NULL DEFAULT NULL          COMMENT 'NPI or Tax ID of the submitting organisation',
  status                ENUM(
                          'active',
                          'inactive',
                          'testing'
                        )                 NOT NULL DEFAULT 'testing'     COMMENT 'Operational status',
  test_mode             BOOLEAN           NOT NULL DEFAULT TRUE          COMMENT 'When TRUE all transactions are directed to the sandbox endpoint',
  transaction_count     BIGINT            NOT NULL DEFAULT 0             COMMENT 'Cumulative transaction counter (incremented on every successful check)',
  last_transaction_at   DATETIME              NULL DEFAULT NULL          COMMENT 'Timestamp of the most recent transaction (UTC)',
  created_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_cc_tenant         (tenant_id),
  INDEX idx_cc_vendor         (vendor),
  INDEX idx_cc_status         (status),
  INDEX idx_cc_tenant_status  (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Clearinghouse vendor connections with encrypted API credentials';


-- =============================================================================
-- 2. ELIGIBILITY_CHECKS
--    One row per 270 inquiry / 271 response pair.  Stores the full X12
--    or JSON request and response payload for auditability, plus parsed
--    coverage details relevant to RAF (Medicare Advantage plan info).
-- =============================================================================
CREATE TABLE IF NOT EXISTS eligibility_checks (
  id                    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id             VARCHAR(50)       NOT NULL DEFAULT 'default'     COMMENT 'Multi-tenant discriminator',
  connection_id         INT UNSIGNED      NOT NULL                       COMMENT 'FK → clearinghouse_connections.id',
  patient_id            INT UNSIGNED          NULL DEFAULT NULL          COMMENT 'OpenEMR patient ID (pid) — may be NULL for prospective checks',
  patient_name          VARCHAR(255)          NULL DEFAULT NULL          COMMENT 'Patient full name used in the inquiry',
  patient_dob           DATE                  NULL DEFAULT NULL          COMMENT 'Patient date of birth (YYYY-MM-DD)',
  member_id             VARCHAR(100)          NULL DEFAULT NULL          COMMENT 'Health-plan member ID',
  payer_id              VARCHAR(20)           NULL DEFAULT NULL          COMMENT 'ANSI/ACAS payer ID (e.g. 00001 for Aetna)',
  payer_name            VARCHAR(255)          NULL DEFAULT NULL          COMMENT 'Human-readable payer name',
  service_type          ENUM(
                          'health_benefit_plan',
                          'medicare_part_a',
                          'medicare_part_b',
                          'medicare_advantage'
                        )                 NOT NULL DEFAULT 'health_benefit_plan' COMMENT 'X12 271 service type code category',
  check_date            DATE              NOT NULL                       COMMENT 'Date the eligibility inquiry was submitted',
  status                ENUM(
                          'pending',
                          'submitted',
                          'completed',
                          'error',
                          'timeout'
                        )                 NOT NULL DEFAULT 'pending'     COMMENT 'Transaction lifecycle status',
  request_payload       JSON                  NULL DEFAULT NULL          COMMENT 'Outbound 270 transaction (X12 text or JSON wrapper)',
  response_payload      JSON                  NULL DEFAULT NULL          COMMENT 'Inbound 271 response (X12 text or parsed JSON)',
  is_eligible           BOOLEAN               NULL DEFAULT NULL          COMMENT 'TRUE if patient has active coverage, FALSE if not, NULL if undetermined',
  coverage_start        DATE                  NULL DEFAULT NULL          COMMENT 'Coverage effective date from 271',
  coverage_end          DATE                  NULL DEFAULT NULL          COMMENT 'Coverage termination date from 271 (NULL = active)',
  plan_name             VARCHAR(255)          NULL DEFAULT NULL          COMMENT 'Health plan marketing name',
  plan_number           VARCHAR(100)          NULL DEFAULT NULL          COMMENT 'Plan / contract number',
  copay                 DECIMAL(10, 2)        NULL DEFAULT NULL          COMMENT 'Primary care copay amount in USD',
  coinsurance           DECIMAL(5, 2)         NULL DEFAULT NULL          COMMENT 'Coinsurance percentage (e.g. 20.00 = 20%)',
  deductible            DECIMAL(10, 2)        NULL DEFAULT NULL          COMMENT 'Annual deductible in USD',
  deductible_remaining  DECIMAL(10, 2)        NULL DEFAULT NULL          COMMENT 'Remaining deductible for the benefit year in USD',
  out_of_pocket_max     DECIMAL(10, 2)        NULL DEFAULT NULL          COMMENT 'Annual out-of-pocket maximum in USD',
  medicare_part         VARCHAR(10)           NULL DEFAULT NULL          COMMENT 'Medicare part identifier: A, B, C (MA), or D',
  raf_relevant_info     JSON                  NULL DEFAULT NULL          COMMENT 'Structured MA plan details relevant to RAF scoring (plan type, CMS contract ID, PBP, star rating)',
  error_message         TEXT                  NULL DEFAULT NULL          COMMENT 'Error description when status = error or timeout',
  response_time_ms      INT                   NULL DEFAULT NULL          COMMENT 'Round-trip latency in milliseconds',
  created_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_ec_tenant          (tenant_id),
  INDEX idx_ec_connection      (connection_id),
  INDEX idx_ec_patient         (patient_id),
  INDEX idx_ec_member          (member_id),
  INDEX idx_ec_payer           (payer_id),
  INDEX idx_ec_check_date      (check_date),
  INDEX idx_ec_status          (status),
  INDEX idx_ec_tenant_date     (tenant_id, check_date),
  INDEX idx_ec_patient_date    (patient_id, check_date),

  CONSTRAINT fk_ec_connection
    FOREIGN KEY (connection_id)
    REFERENCES clearinghouse_connections (id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual 270/271 eligibility inquiry and response records';


-- =============================================================================
-- 3. ELIGIBILITY_BATCH
--    Tracks bulk eligibility verification jobs submitted against a panel
--    of patients (e.g. a practice roster or pre-visit check).
-- =============================================================================
CREATE TABLE IF NOT EXISTS eligibility_batch (
  id             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  tenant_id      VARCHAR(50)   NOT NULL DEFAULT 'default'  COMMENT 'Multi-tenant discriminator',
  connection_id  INT UNSIGNED  NOT NULL                    COMMENT 'FK → clearinghouse_connections.id',
  name           VARCHAR(255)      NULL DEFAULT NULL        COMMENT 'User-supplied label for this batch run',
  total_checks   INT           NOT NULL DEFAULT 0          COMMENT 'Total number of eligibility checks in this batch',
  completed      INT           NOT NULL DEFAULT 0          COMMENT 'Count of checks that reached status = completed',
  failed         INT           NOT NULL DEFAULT 0          COMMENT 'Count of checks that reached status = error or timeout',
  status         ENUM(
                   'queued',
                   'processing',
                   'completed',
                   'error'
                 )             NOT NULL DEFAULT 'queued'   COMMENT 'Overall batch lifecycle status',
  started_at     DATETIME          NULL DEFAULT NULL        COMMENT 'Timestamp when processing began (UTC)',
  completed_at   DATETIME          NULL DEFAULT NULL        COMMENT 'Timestamp when the last check finished (UTC)',
  created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_eb_tenant      (tenant_id),
  INDEX idx_eb_connection  (connection_id),
  INDEX idx_eb_status      (status),
  INDEX idx_eb_created     (created_at),

  CONSTRAINT fk_eb_connection
    FOREIGN KEY (connection_id)
    REFERENCES clearinghouse_connections (id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Batch eligibility verification job tracking';
