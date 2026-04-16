-- Migration: track CMS-HCC model version on raf_patient_hcc rows
-- Prevents mixing of V24 (pre-2025) and V28 (2025+) HCC code sets.
-- Idempotent: re-running is safe.

-- 1. Add column if it does not already exist.
SET @col_exists := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'raf_patient_hcc'
      AND COLUMN_NAME  = 'model_version'
);

SET @ddl := IF(
    @col_exists = 0,
    "ALTER TABLE raf_patient_hcc ADD COLUMN model_version VARCHAR(8) NOT NULL DEFAULT 'V28'",
    "SELECT 'model_version column already exists on raf_patient_hcc' AS note"
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2. Backfill legacy rows (pre-2025 -> V24, 2025+ -> V28).
UPDATE raf_patient_hcc
   SET model_version = 'V24'
 WHERE measurement_year < 2025;

UPDATE raf_patient_hcc
   SET model_version = 'V28'
 WHERE measurement_year >= 2025;

-- 3. Index to speed up model_version-filtered reads (e.g. recapture gap detection).
SET @idx_exists := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'raf_patient_hcc'
      AND INDEX_NAME   = 'idx_rph_model_version'
);

SET @idx_ddl := IF(
    @idx_exists = 0,
    "CREATE INDEX idx_rph_model_version ON raf_patient_hcc(measurement_year, model_version)",
    "SELECT 'idx_rph_model_version already exists' AS note"
);

PREPARE stmt2 FROM @idx_ddl;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;
