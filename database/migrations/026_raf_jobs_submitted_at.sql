-- 026_raf_jobs_submitted_at.sql
-- Adds submitted_at column to raf_jobs for startup stale-job recovery hook.
-- Safe to run against already-migrated databases (MySQL 8+).

ALTER TABLE raf_jobs ADD COLUMN IF NOT EXISTS submitted_at DATETIME NULL;
