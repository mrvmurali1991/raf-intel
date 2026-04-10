-- =============================================================================
-- Migration 011: Provider Attestation Workflow
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Enables providers to review and sign off on suspect HCC
--              conditions identified by the RAF Intelligence platform.
--              Captures digital attestation, rejection, and deferral
--              decisions with a tamper-evident signature hash.
--
-- Tables added:
--   1. provider_attestations   — individual HCC attestation decisions
--   2. attestation_batches     — batch signing sessions per provider
--   3. attestation_reminders   — reminder delivery log
--
-- Dependencies:
--   003_providers.sql must be applied first (providers table)
--   005_authentication.sql must be applied first (users table)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. PROVIDER_ATTESTATIONS
--    One row per HCC condition presented to a provider for review.
--    A single suspect condition may produce one attestation per provider
--    encounter (patient_id + encounter_id + hcc_code must be unique per
--    provider within a measurement period).
-- =============================================================================
CREATE TABLE IF NOT EXISTS provider_attestations (
    -- -----------------------------------------------------------------------
    -- Identity
    -- -----------------------------------------------------------------------
    id                  INT UNSIGNED        NOT NULL AUTO_INCREMENT,
    tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default'
                                            COMMENT 'Logical tenant / organisation identifier',

    -- -----------------------------------------------------------------------
    -- Clinical context
    -- -----------------------------------------------------------------------
    patient_id          INT                 NOT NULL
                                            COMMENT 'OpenEMR pid — foreign key to openemr.patient_data',
    encounter_id        INT                 NULL DEFAULT NULL
                                            COMMENT 'OpenEMR encounter id if available',
    hcc_code            VARCHAR(20)         NOT NULL
                                            COMMENT 'CMS-HCC code (e.g. "HCC18")',
    hcc_description     VARCHAR(500)        NOT NULL DEFAULT ''
                                            COMMENT 'Human-readable HCC description',
    icd10_code          VARCHAR(10)         NOT NULL
                                            COMMENT 'ICD-10-CM code supporting this HCC',
    icd10_description   VARCHAR(500)        NOT NULL DEFAULT ''
                                            COMMENT 'ICD-10-CM short description',
    source              ENUM(
                            'suspect',
                            'nlp',
                            'claims',
                            'manual'
                        )                   NOT NULL DEFAULT 'suspect'
                                            COMMENT 'Origin of this condition: suspect engine, NLP, claims data, or manual entry',

    -- -----------------------------------------------------------------------
    -- Provider identity
    -- -----------------------------------------------------------------------
    provider_npi        VARCHAR(10)         NOT NULL
                                            COMMENT 'National Provider Identifier (10 digits)',
    provider_user_id    INT                 NOT NULL
                                            COMMENT 'FK to raf_intelligence.users.id',

    -- -----------------------------------------------------------------------
    -- Attestation decision
    -- -----------------------------------------------------------------------
    status              ENUM(
                            'pending',
                            'attested',
                            'rejected',
                            'deferred'
                        )                   NOT NULL DEFAULT 'pending'
                                            COMMENT 'Current review status',
    attestation_type    ENUM(
                            'confirm_active',
                            'confirm_resolved',
                            'reject_inaccurate',
                            'defer_need_info'
                        )                   NULL DEFAULT NULL
                                            COMMENT 'Specific attestation decision type; NULL while pending',
    clinical_justification
                        TEXT                NULL DEFAULT NULL
                                            COMMENT 'Provider narrative supporting the decision',
    reject_reason       VARCHAR(500)        NULL DEFAULT NULL
                                            COMMENT 'Structured reason when status = rejected',
    deferred_until      DATE                NULL DEFAULT NULL
                                            COMMENT 'Date the provider requests follow-up when deferred',
    evidence_references JSON                NULL DEFAULT NULL
                                            COMMENT 'Array of document/note references supporting the decision',

    -- -----------------------------------------------------------------------
    -- Digital signature
    -- -----------------------------------------------------------------------
    signature_hash      VARCHAR(256)        NULL DEFAULT NULL
                                            COMMENT 'SHA-256 HMAC of provider_user_id + timestamp + decision; tamper-evident',
    attested_at         DATETIME            NULL DEFAULT NULL
                                            COMMENT 'UTC timestamp of the provider decision',

    -- -----------------------------------------------------------------------
    -- Audit trail
    -- -----------------------------------------------------------------------
    ip_address          VARCHAR(45)         NULL DEFAULT NULL
                                            COMMENT 'IPv4 or IPv6 of the provider client at decision time',
    user_agent          VARCHAR(500)        NULL DEFAULT NULL
                                            COMMENT 'HTTP User-Agent of the provider client',
    batch_id            INT UNSIGNED        NULL DEFAULT NULL
                                            COMMENT 'FK to attestation_batches.id when submitted as part of a batch',

    created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    -- Fast lookup for pending work per provider
    INDEX idx_provider_status       (provider_user_id, status),
    -- Patient-level view of all attestations
    INDEX idx_patient_attestations  (patient_id, status),
    -- Tenant scoping
    INDEX idx_tenant_created        (tenant_id, created_at),
    -- Batch membership
    INDEX idx_batch                 (batch_id),
    -- HCC lookup
    INDEX idx_hcc_code              (hcc_code),
    -- Deferred follow-up scheduler
    INDEX idx_deferred_until        (deferred_until)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Provider review and sign-off decisions on suspect HCC conditions';


-- =============================================================================
-- 2. ATTESTATION_BATCHES
--    Groups multiple attestations into a single provider session.
--    Allows a provider to review N conditions, then submit all decisions
--    at once, triggering a single batch signature event.
-- =============================================================================
CREATE TABLE IF NOT EXISTS attestation_batches (
    id                  INT UNSIGNED        NOT NULL AUTO_INCREMENT,
    tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default',

    -- Provider who owns this batch
    provider_npi        VARCHAR(10)         NOT NULL,
    provider_user_id    INT                 NOT NULL,

    -- Aggregate counters (denormalised for dashboard performance)
    total_conditions    INT UNSIGNED        NOT NULL DEFAULT 0
                                            COMMENT 'Number of attestations added to this batch',
    attested_count      INT UNSIGNED        NOT NULL DEFAULT 0,
    rejected_count      INT UNSIGNED        NOT NULL DEFAULT 0,
    deferred_count      INT UNSIGNED        NOT NULL DEFAULT 0,

    status              ENUM(
                            'in_progress',
                            'completed'
                        )                   NOT NULL DEFAULT 'in_progress',

    started_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        DATETIME            NULL DEFAULT NULL
                                            COMMENT 'UTC timestamp when all decisions were submitted',

    created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    INDEX idx_batch_provider    (provider_user_id, status),
    INDEX idx_batch_tenant      (tenant_id, status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Batch signing sessions grouping multiple attestation decisions per provider';


-- =============================================================================
-- 3. ATTESTATION_REMINDERS
--    Tracks reminder notifications sent for pending attestations.
--    Supports both in-app and email channels.
-- =============================================================================
CREATE TABLE IF NOT EXISTS attestation_reminders (
    id                  INT UNSIGNED        NOT NULL AUTO_INCREMENT,
    attestation_id      INT UNSIGNED        NOT NULL
                                            COMMENT 'FK to provider_attestations.id',
    reminder_type       ENUM(
                            'email',
                            'in_app'
                        )                   NOT NULL DEFAULT 'in_app',
    sent_at             DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at     DATETIME            NULL DEFAULT NULL
                                            COMMENT 'When the provider dismissed the in-app reminder or opened the email',

    PRIMARY KEY (id),
    INDEX idx_reminder_attestation  (attestation_id),
    INDEX idx_reminder_sent         (sent_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Reminder delivery log for pending provider attestations';
