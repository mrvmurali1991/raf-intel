-- =============================================================================
-- Migration: add_feature_flags
-- Adds the user_feature_flags table used by the feature-toggle infrastructure.
--
-- Idempotent: safe to re-run.  Run against the raf_intelligence database.
--
--   mysql -u root -p raf_intelligence < database/migrations/add_feature_flags.sql
-- =============================================================================

USE raf_intelligence;

CREATE TABLE IF NOT EXISTS user_feature_flags (
  id           INT UNSIGNED       NOT NULL AUTO_INCREMENT,
  user_id      INT UNSIGNED       NOT NULL,
  flag_key     VARCHAR(80)        NOT NULL,
  enabled      TINYINT(1)         NOT NULL DEFAULT 1,
  updated_at   DATETIME           NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_user_flag (user_id, flag_key),
  KEY idx_user_id  (user_id),
  KEY idx_flag_key (flag_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-user overrides for feature toggles surfaced in the UI';
