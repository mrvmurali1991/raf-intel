-- =============================================================================
-- Migration 009: Coder Worklist / Queue System
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Provides a structured review queue so medical coders can see,
--              claim, and action their assigned coding tasks.  Items are fed
--              from NLP analysis results, claims processing, and manual
--              manager assignments.
--
-- Tables added:
--   1. coder_worklist          — per-item review tasks assigned to coders
--   2. coder_worklist_actions  — immutable audit trail for every state change
--   3. coder_productivity      — daily coder productivity roll-up
--
-- Dependencies:
--   005_authentication.sql must be applied first (users table for FKs)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. CODER_WORKLIST
--    One row per review task.  A task is the unit of work a coder acts on:
--    it binds a patient + encounter to a specific review type and tracks the
--    full lifecycle from queued through completed (or returned/escalated).
--
--    Priority 1 = highest urgency.
--    source: how the item entered the queue.
--    hcc_codes: JSON array of HCC integers the coder should evaluate, e.g.
--               [18, 85, 111] — populated at queue time from NLP suspects or
--               claims analysis results.
-- =============================================================================
CREATE TABLE IF NOT EXISTS coder_worklist (
  -- -------------------------------------------------------------------
  -- Identity
  -- -------------------------------------------------------------------
  id                   INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id            VARCHAR(50)     NOT NULL DEFAULT 'default'
                         COMMENT 'Logical tenant / organisation identifier',

  -- -------------------------------------------------------------------
  -- Assignment
  -- -------------------------------------------------------------------
  coder_user_id        INT UNSIGNED    NOT NULL
                         COMMENT 'FK → users.id — the coder this item is assigned to',
  reviewer_user_id     INT UNSIGNED    NULL DEFAULT NULL
                         COMMENT 'FK → users.id — QA reviewer who audited the completed item',

  -- -------------------------------------------------------------------
  -- Clinical context
  -- -------------------------------------------------------------------
  patient_id           INT UNSIGNED    NOT NULL
                         COMMENT 'OpenEMR patient PID',
  encounter_id         INT UNSIGNED    NULL DEFAULT NULL
                         COMMENT 'OpenEMR encounter ID (NULL when encounter is not yet linked)',

  -- -------------------------------------------------------------------
  -- Work classification
  -- -------------------------------------------------------------------
  review_type          ENUM(
                         'initial_coding',
                         'suspect_review',
                         'audit_response',
                         'recapture'
                       )               NOT NULL DEFAULT 'suspect_review'
                         COMMENT 'Type of coding work required',
  source               ENUM(
                         'auto',
                         'manual',
                         'claims',
                         'nlp'
                       )               NOT NULL DEFAULT 'manual'
                         COMMENT 'How this item entered the queue',
  priority             TINYINT UNSIGNED NOT NULL DEFAULT 3
                         COMMENT '1 = highest urgency, 5 = lowest; drives queue sort order',

  -- -------------------------------------------------------------------
  -- Lifecycle
  -- -------------------------------------------------------------------
  status               ENUM(
                         'queued',
                         'in_progress',
                         'completed',
                         'returned',
                         'escalated'
                       )               NOT NULL DEFAULT 'queued'
                         COMMENT 'Current workflow state of this item',
  assigned_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                         COMMENT 'When the item was placed in the queue',
  started_at           DATETIME        NULL DEFAULT NULL
                         COMMENT 'When the coder claimed and began working the item',
  completed_at         DATETIME        NULL DEFAULT NULL
                         COMMENT 'When the coder marked the review finished',
  reviewed_at          DATETIME        NULL DEFAULT NULL
                         COMMENT 'When the QA reviewer audited the completed item',
  due_date             DATE            NULL DEFAULT NULL
                         COMMENT 'Deadline by which the review must be completed',

  -- -------------------------------------------------------------------
  -- Coding data
  -- -------------------------------------------------------------------
  hcc_codes            JSON            NULL DEFAULT NULL
                         COMMENT 'Array of HCC integer codes to evaluate, e.g. [18, 85]',
  notes                TEXT            NULL DEFAULT NULL
                         COMMENT 'Free-text notes added by coder or assigning manager',

  -- -------------------------------------------------------------------
  -- QA outcome
  -- -------------------------------------------------------------------
  quality_score        DECIMAL(5,2)    NULL DEFAULT NULL
                         COMMENT 'QA accuracy score 0–100 assigned by reviewer',

  -- -------------------------------------------------------------------
  -- Audit timestamps
  -- -------------------------------------------------------------------
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                         ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  -- Covering index for a coder's open queue (most common query)
  KEY idx_coder_status_priority  (coder_user_id, status, priority, due_date),
  -- Filter by tenant and status for manager views
  KEY idx_tenant_status          (tenant_id, status),
  -- Patient-centric lookup
  KEY idx_patient_id             (patient_id),
  -- Encounter-centric lookup
  KEY idx_encounter_id           (encounter_id),
  -- Due-date alerting
  KEY idx_due_date               (due_date),
  -- Reviewer assignment
  KEY idx_reviewer_user_id       (reviewer_user_id),
  -- Source-based filtering for auto-queue dashboards
  KEY idx_source                 (source),
  -- Round-robin / load-balance: count open items per coder fast
  KEY idx_coder_queued           (coder_user_id, status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Coder review queue: one row per coding task assigned to a coder';


-- =============================================================================
-- 2. CODER_WORKLIST_ACTIONS
--    Append-only audit trail — every state change, claim, note, or escalation
--    produces one row.  Never updated; only inserted and read.
--
--    action examples:  'assigned', 'claimed', 'started', 'completed',
--                      'returned', 'escalated', 'note_added', 'reassigned'
--    details: free JSON — for 'completed' this holds coding_decisions[];
--             for 'returned' it holds reason; etc.
-- =============================================================================
CREATE TABLE IF NOT EXISTS coder_worklist_actions (
  id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  worklist_id  INT UNSIGNED  NOT NULL
                 COMMENT 'FK → coder_worklist.id',
  user_id      INT UNSIGNED  NOT NULL
                 COMMENT 'FK → users.id — user who performed this action',
  action       VARCHAR(50)   NOT NULL
                 COMMENT 'Action verb: assigned | claimed | started | completed | returned | escalated | note_added | reassigned',
  details      JSON          NULL DEFAULT NULL
                 COMMENT 'Structured payload specific to the action type',
  created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  -- Most common query: chronological action log for a single item
  KEY idx_worklist_id   (worklist_id, created_at),
  -- User activity feed
  KEY idx_user_id       (user_id, created_at),
  -- Action-type aggregation for reporting
  KEY idx_action        (action),

  CONSTRAINT fk_wl_action_worklist
    FOREIGN KEY (worklist_id)
    REFERENCES coder_worklist (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable audit trail: one row per lifecycle action on a worklist item';


-- =============================================================================
-- 3. CODER_PRODUCTIVITY
--    Daily roll-up of each coder's throughput metrics.
--    One row per (coder_user_id, date, tenant_id).
--    Written by the service layer after each item completion and by a nightly
--    reconciliation job.
-- =============================================================================
CREATE TABLE IF NOT EXISTS coder_productivity (
  id                   INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id            VARCHAR(50)     NOT NULL DEFAULT 'default',
  coder_user_id        INT UNSIGNED    NOT NULL
                         COMMENT 'FK → users.id',
  date                 DATE            NOT NULL
                         COMMENT 'Calendar date this row covers',

  -- -------------------------------------------------------------------
  -- Daily metrics
  -- -------------------------------------------------------------------
  reviews_completed    SMALLINT UNSIGNED NOT NULL DEFAULT 0
                         COMMENT 'Number of items moved to completed status on this date',
  avg_time_minutes     DECIMAL(8,2)    NULL DEFAULT NULL
                         COMMENT 'Average minutes from started_at → completed_at across completed items',
  accuracy_rate        DECIMAL(5,4)    NULL DEFAULT NULL
                         COMMENT 'QA accuracy rate 0–1 (NULL when no items have been reviewed yet)',

  -- -------------------------------------------------------------------
  -- Audit timestamps
  -- -------------------------------------------------------------------
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                         ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),

  UNIQUE KEY uq_coder_date_tenant    (coder_user_id, date, tenant_id),
  KEY idx_tenant_date                (tenant_id, date),
  KEY idx_coder_user_id              (coder_user_id),
  KEY idx_date                       (date)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Daily coder productivity metrics: throughput, cycle time, accuracy';


-- =============================================================================
-- Record this migration
-- =============================================================================
INSERT IGNORE INTO schema_migrations (version) VALUES ('009_coder_worklist.sql');
