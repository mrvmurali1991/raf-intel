-- =============================================================================
-- Recapture Campaign Workflow + Coder Assignments
-- =============================================================================
-- Adds two tables that turn manual gap triage into a campaign-level batch
-- workflow:
--   1) recapture_campaigns          — a saved filter + status + target date.
--   2) recapture_coder_assignments  — per-gap assignment to a coder, with a
--                                     kanban-friendly status column.
--
-- The (campaign_id, gap_id) UNIQUE constraint guarantees a gap can only be
-- assigned once per campaign — re-running an assign call is therefore safe
-- (idempotent on the unique key).
-- =============================================================================

CREATE TABLE IF NOT EXISTS recapture_campaigns (
  id                 INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id          VARCHAR(64) NOT NULL,
  name               VARCHAR(200) NOT NULL,
  description        TEXT NULL,
  status             ENUM('draft','active','paused','completed','archived')
                       NOT NULL DEFAULT 'draft',
  filter_criteria    JSON NULL
                       COMMENT 'e.g. {"hcc_codes":["18","19"],"min_revenue":5000,"max_age_days":90}',
  target_close_date  DATE NULL,
  created_by         VARCHAR(128) NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                       ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_tenant_status (tenant_id, status)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Bulk recapture-gap campaigns (Edifecs/Episource-style batch workflow)';

CREATE TABLE IF NOT EXISTS recapture_coder_assignments (
  id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  campaign_id  INT UNSIGNED NOT NULL,
  coder_id     INT NOT NULL
                 COMMENT 'users.id of the assigned coder/admin',
  gap_id       INT UNSIGNED NOT NULL,
  status       ENUM('assigned','in_progress','closed','dismissed','reassigned')
                 NOT NULL DEFAULT 'assigned',
  closed_at    DATETIME NULL,
  notes        TEXT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                 ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_assign (campaign_id, gap_id),
  INDEX idx_coder_status (coder_id, status),
  CONSTRAINT fk_rca_campaign
    FOREIGN KEY (campaign_id) REFERENCES recapture_campaigns(id) ON DELETE CASCADE,
  CONSTRAINT fk_rca_gap
    FOREIGN KEY (gap_id) REFERENCES recapture_gaps(id) ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Per-gap coder assignments inside a recapture campaign';
