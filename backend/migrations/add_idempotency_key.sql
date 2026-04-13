-- Migration: add idempotency_key to submission_batches
-- Prevents duplicate CMS file generation on network retries / double-click.
-- Run once against the RAF database.

ALTER TABLE submission_batches ADD COLUMN idempotency_key VARCHAR(64) NULL;

CREATE UNIQUE INDEX uk_sb_idempotency ON submission_batches(idempotency_key);
