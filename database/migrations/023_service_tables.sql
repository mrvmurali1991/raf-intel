-- =============================================================================
-- RAF Intelligence — Migration 023: Service-Layer Tables
-- =============================================================================
-- This migration creates tables that were previously auto-created by Python
-- service-layer code at startup (CREATE TABLE IF NOT EXISTS). Having them in
-- a proper migration file ensures:
--   1. Schema is version-controlled and reviewable.
--   2. DBA teams can pre-deploy schema before application startup.
--   3. Schema drift between environments is eliminated.
--
-- All statements are idempotent (CREATE TABLE IF NOT EXISTS / INSERT IGNORE).
-- Safe to re-run.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. raf_jobs — Celery / background job persistence
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_jobs (
    id            VARCHAR(36)   PRIMARY KEY,
    task_name     VARCHAR(120)  NOT NULL,
    status        VARCHAR(20)   NOT NULL DEFAULT 'PENDING',
    progress      INT           NOT NULL DEFAULT 0,
    total         INT           NOT NULL DEFAULT 0,
    tenant_id     INT,
    submitted_by  INT,
    args_json     TEXT,
    result_json   TEXT,
    error_message TEXT,
    started_at    DATETIME,
    finished_at   DATETIME,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rj_status  (status),
    INDEX idx_rj_tenant  (tenant_id),
    INDEX idx_rj_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 2. raf_user_notification_preferences — email notification settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_user_notification_preferences (
    user_id             INT             PRIMARY KEY,
    analysis_complete   TINYINT(1)      NOT NULL DEFAULT 1,
    submission_deadline TINYINT(1)      NOT NULL DEFAULT 1,
    care_gap_alerts     TINYINT(1)      NOT NULL DEFAULT 1,
    suspect_alerts      TINYINT(1)      NOT NULL DEFAULT 1,
    sync_failure_alerts TINYINT(1)      NOT NULL DEFAULT 1,
    security_alerts     TINYINT(1)      NOT NULL DEFAULT 1,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 3. webhooks + webhook_deliveries — event subscription & delivery tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS webhooks (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id   VARCHAR(64)  NOT NULL,
    url         TEXT         NOT NULL,
    events      JSON         NOT NULL COMMENT 'Array of subscribed event types',
    secret      VARCHAR(128) NOT NULL COMMENT 'HMAC-SHA256 signing secret',
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    description VARCHAR(255) DEFAULT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_wh_tenant (tenant_id),
    INDEX idx_wh_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    webhook_id      INT UNSIGNED NOT NULL,
    event_type      VARCHAR(64)  NOT NULL,
    payload         JSON         NOT NULL,
    response_status SMALLINT     DEFAULT NULL,
    response_body   TEXT         DEFAULT NULL,
    attempts        TINYINT      NOT NULL DEFAULT 0,
    delivered_at    DATETIME     DEFAULT NULL COMMENT 'Timestamp of first successful delivery',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_wd_webhook (webhook_id),
    INDEX idx_wd_event   (event_type),
    INDEX idx_wd_created (created_at),
    CONSTRAINT fk_wd_webhook FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 4. raf_awv_tracking — Annual Wellness Visit scheduling
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_awv_tracking (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    patient_id       INT          NOT NULL,
    measurement_year SMALLINT     NOT NULL,
    status           VARCHAR(32)  NOT NULL DEFAULT 'scheduled',
    scheduled_by     INT          NULL,
    scheduled_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                     ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_awv_patient_year (patient_id, measurement_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 5. raf_coding_corrections — coder feedback / retraining data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_coding_corrections (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    patient_id      INT          NOT NULL,
    encounter_id    INT,
    hcc_code        VARCHAR(20),
    icd10_code      VARCHAR(20),
    original_value  VARCHAR(100),
    corrected_value VARCHAR(100),
    corrected_by    INT,
    reason          TEXT,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rcc_patient (patient_id),
    INDEX idx_rcc_hcc     (hcc_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
