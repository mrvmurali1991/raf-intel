-- =============================================================================
-- Migration 008: Care Gap Closure Workflow
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Task assignment and tracking system for care gap closure.
--              Supports suspect/recapture/new gap types, status transitions,
--              comment threads, and a full audit history per task.
--
-- Tables added:
--   1. care_gap_tasks     — primary task record per patient/provider/HCC
--   2. care_gap_comments  — threaded comments on a task
--   3. care_gap_history   — immutable status-change audit trail
--
-- Dependencies:
--   005_authentication.sql must be applied first (users table for FKs)
--   003_providers.sql must be applied first (providers table)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. CARE_GAP_TASKS
--    One row per actionable care gap assigned to a provider or coder.
--    gap_type distinguishes:
--      suspect    — condition identified by suspect engine, not yet coded
--      recapture  — chronic HCC coded in a prior year not yet seen this year
--      new        — net-new gap identified via chart review or algorithm
-- =============================================================================
CREATE TABLE IF NOT EXISTS care_gap_tasks (
    id                  INT UNSIGNED        NOT NULL AUTO_INCREMENT,
    tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default'         COMMENT 'Logical tenant / organisation identifier',

    -- Clinical references
    patient_id          INT                 NOT NULL                            COMMENT 'OpenEMR patient pid',
    provider_id         INT                 NOT NULL                            COMMENT 'FK → providers.id — responsible provider',
    hcc_code            VARCHAR(20)         NOT NULL                            COMMENT 'CMS-HCC code this gap relates to (e.g. HCC18)',
    hcc_description     VARCHAR(500)        NOT NULL DEFAULT ''                 COMMENT 'Human-readable HCC description',
    suspect_condition_id INT UNSIGNED       NULL DEFAULT NULL                   COMMENT 'FK → raf_suspect_conditions.id if auto-generated',

    -- Task classification
    gap_type            ENUM('suspect','recapture','new')
                                            NOT NULL DEFAULT 'suspect'          COMMENT 'How the gap was identified',
    priority            ENUM('critical','high','medium','low')
                                            NOT NULL DEFAULT 'medium'           COMMENT 'Clinical or revenue priority',
    status              ENUM('open','in_progress','scheduled','completed','rejected')
                                            NOT NULL DEFAULT 'open'             COMMENT 'Lifecycle state of this closure task',

    -- Assignment
    assigned_to         INT                 NULL DEFAULT NULL                   COMMENT 'FK → users.id — coder or provider assigned to close the gap',

    -- Content
    notes               TEXT                NULL DEFAULT NULL                   COMMENT 'Free-text clinical notes',
    evidence_summary    TEXT                NULL DEFAULT NULL                   COMMENT 'Structured summary of supporting evidence (labs, meds, etc.)',
    due_date            DATE                NULL DEFAULT NULL                   COMMENT 'Target closure date',

    -- Lifecycle timestamps
    created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at        DATETIME            NULL DEFAULT NULL                   COMMENT 'Set when status transitions to completed or rejected',

    -- Ownership / audit
    created_by          INT                 NULL DEFAULT NULL                   COMMENT 'FK → users.id — user who created the task',

    PRIMARY KEY (id),

    -- Lookup indexes
    INDEX idx_patient        (patient_id),
    INDEX idx_provider       (provider_id),
    INDEX idx_assigned_to    (assigned_to),
    INDEX idx_status         (status),
    INDEX idx_priority       (priority),
    INDEX idx_gap_type       (gap_type),
    INDEX idx_due_date       (due_date),
    INDEX idx_tenant_status  (tenant_id, status),
    INDEX idx_tenant_provider(tenant_id, provider_id, status),
    INDEX idx_hcc_code       (hcc_code)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Care gap closure tasks assigned to providers and coders';


-- =============================================================================
-- 2. CARE_GAP_COMMENTS
--    Free-text comments attached to a care gap task for clinical collaboration.
-- =============================================================================
CREATE TABLE IF NOT EXISTS care_gap_comments (
    id          INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    task_id     INT UNSIGNED    NOT NULL                    COMMENT 'FK → care_gap_tasks.id',
    user_id     INT             NOT NULL                    COMMENT 'FK → users.id — comment author',
    comment     TEXT            NOT NULL                    COMMENT 'Comment body',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    INDEX idx_task (task_id),
    CONSTRAINT fk_cgc_task
        FOREIGN KEY (task_id) REFERENCES care_gap_tasks (id)
        ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Threaded comments on care gap tasks';


-- =============================================================================
-- 3. CARE_GAP_HISTORY
--    Immutable audit trail: one row per status change or significant action.
--    Rows are never updated or deleted (insert-only table).
-- =============================================================================
CREATE TABLE IF NOT EXISTS care_gap_history (
    id          INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    task_id     INT UNSIGNED    NOT NULL                    COMMENT 'FK → care_gap_tasks.id',
    action      VARCHAR(100)    NOT NULL                    COMMENT 'Action label, e.g. created / status_changed / assigned / commented',
    old_status  VARCHAR(50)     NULL DEFAULT NULL           COMMENT 'Status before the action (NULL for creation events)',
    new_status  VARCHAR(50)     NULL DEFAULT NULL           COMMENT 'Status after the action',
    user_id     INT             NOT NULL                    COMMENT 'FK → users.id — user who performed the action',
    note        TEXT            NULL DEFAULT NULL           COMMENT 'Optional free-text context for the action',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    INDEX idx_task       (task_id),
    INDEX idx_user       (user_id),
    INDEX idx_created_at (created_at),
    CONSTRAINT fk_cgh_task
        FOREIGN KEY (task_id) REFERENCES care_gap_tasks (id)
        ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable audit trail for care gap task lifecycle events';
