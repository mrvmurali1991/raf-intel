-- =============================================================================
-- Migration: add_recurring_flag
--
-- Adds tracking columns to recapture_gaps for "recurring gap" detection —
-- (patient_id, hcc_code) pairs that have been an open gap for 2+ consecutive
-- years.  Such gaps are systemic (provider not capturing, patient not visiting)
-- and warrant elevated priority + auto-suggested AWV scheduling.
--
-- Idempotent: safe to re-run.
--   mysql -u root -p raf_intelligence < database/migrations/add_recurring_flag.sql
-- =============================================================================

USE raf_intelligence;

-- ----------------------------------------------------------------------------
-- Column: is_recurring
-- Column: years_recurring
-- Column: awv_suggested
-- ----------------------------------------------------------------------------
-- MySQL 8.0 supports IF NOT EXISTS on ADD COLUMN; we wrap each in a
-- prepared statement guarded by information_schema check so the migration
-- can run on older MySQL too.

SET @col := (SELECT COUNT(*)
             FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name   = 'recapture_gaps'
               AND column_name  = 'is_recurring');
SET @ddl := IF(@col = 0,
  'ALTER TABLE recapture_gaps ADD COLUMN is_recurring TINYINT(1) NOT NULL DEFAULT 0',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col := (SELECT COUNT(*)
             FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name   = 'recapture_gaps'
               AND column_name  = 'years_recurring');
SET @ddl := IF(@col = 0,
  'ALTER TABLE recapture_gaps ADD COLUMN years_recurring SMALLINT NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col := (SELECT COUNT(*)
             FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name   = 'recapture_gaps'
               AND column_name  = 'awv_suggested');
SET @ddl := IF(@col = 0,
  'ALTER TABLE recapture_gaps ADD COLUMN awv_suggested TINYINT(1) NOT NULL DEFAULT 0',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Optional metadata used by /mark-awv-scheduled
SET @col := (SELECT COUNT(*)
             FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name   = 'recapture_gaps'
               AND column_name  = 'awv_visit_date');
SET @ddl := IF(@col = 0,
  'ALTER TABLE recapture_gaps ADD COLUMN awv_visit_date DATE NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col := (SELECT COUNT(*)
             FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name   = 'recapture_gaps'
               AND column_name  = 'awv_encounter_id');
SET @ddl := IF(@col = 0,
  'ALTER TABLE recapture_gaps ADD COLUMN awv_encounter_id VARCHAR(64) NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------------------------------------------------------
-- Index: idx_recurring
-- ----------------------------------------------------------------------------
SET @idx := (SELECT COUNT(*)
             FROM information_schema.statistics
             WHERE table_schema = DATABASE()
               AND table_name   = 'recapture_gaps'
               AND index_name   = 'idx_recurring');
SET @ddl := IF(@idx = 0,
  'CREATE INDEX idx_recurring ON recapture_gaps(is_recurring)',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
