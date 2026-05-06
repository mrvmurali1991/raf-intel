-- ---------------------------------------------------------------------------
-- add_recapture_close_columns.sql
-- Adds evidence + MEAT element + reopen audit columns to recapture_gaps so
-- the smart-close workflow can persist the clinician's documentation evidence.
--
-- Idempotent — uses INFORMATION_SCHEMA guards so re-running on a server that
-- already has the columns is a no-op.
-- ---------------------------------------------------------------------------

-- evidence_phrase ------------------------------------------------------------
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME   = 'recapture_gaps'
       AND COLUMN_NAME  = 'evidence_phrase'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE recapture_gaps ADD COLUMN evidence_phrase TEXT NULL AFTER resolved_by',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- meat_element ---------------------------------------------------------------
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME   = 'recapture_gaps'
       AND COLUMN_NAME  = 'meat_element'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE recapture_gaps ADD COLUMN meat_element ENUM(''M'',''E'',''A'',''T'') NULL AFTER evidence_phrase',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- reopened_at ----------------------------------------------------------------
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME   = 'recapture_gaps'
       AND COLUMN_NAME  = 'reopened_at'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE recapture_gaps ADD COLUMN reopened_at DATETIME NULL AFTER meat_element',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- reopened_by ----------------------------------------------------------------
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME   = 'recapture_gaps'
       AND COLUMN_NAME  = 'reopened_by'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE recapture_gaps ADD COLUMN reopened_by VARCHAR(128) NULL AFTER reopened_at',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- reopen_reason --------------------------------------------------------------
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME   = 'recapture_gaps'
       AND COLUMN_NAME  = 'reopen_reason'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE recapture_gaps ADD COLUMN reopen_reason TEXT NULL AFTER reopened_by',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
