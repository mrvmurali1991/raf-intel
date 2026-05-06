-- 028_raf_patient_hcc_model_version.sql
--
-- Adds model_version and tenant_id columns to raf_patient_hcc.
--
-- Background: The CMS transitioned from HCC model V24 to V28 starting with
-- payment year 2024.  The same HCC code number can map to different clinical
-- definitions under V24 versus V28, so gap detection that compares prior-year
-- to current-year HCCs MUST gate on model version.  Without this column the
-- recapture_gap_service cannot reliably restrict the comparison to rows within
-- the same model version, which can produce spurious gaps or silent misses.
--
-- tenant_id is needed so the gap-detection query can be scoped per tenant
-- without joining through the patients table.
--
-- Both columns default to values that preserve backward compatibility with
-- existing rows: tenant_id = '1' (the default single-tenant value) and
-- model_version = 'V28' (all rows written after 2024 should use V28).
-- Operators running a multi-tenant migration MUST backfill tenant_id from
-- the patients.tenant_id join before enabling the model_version filter in
-- recapture_gap_service.

-- MySQL 8.0 does not support ADD COLUMN IF NOT EXISTS on ALTER TABLE, so
-- each column add is wrapped in a procedural existence check against
-- INFORMATION_SCHEMA so this migration is safe to re-run.

DROP PROCEDURE IF EXISTS _add_rph_columns;
DELIMITER //
CREATE PROCEDURE _add_rph_columns()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'raf_patient_hcc'
          AND COLUMN_NAME  = 'model_version'
    ) THEN
        ALTER TABLE raf_patient_hcc
            ADD COLUMN model_version VARCHAR(10) NOT NULL DEFAULT 'V28'
                COMMENT 'CMS HCC model version: V24 or V28';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'raf_patient_hcc'
          AND COLUMN_NAME  = 'tenant_id'
    ) THEN
        ALTER TABLE raf_patient_hcc
            ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1'
                COMMENT 'Owning tenant — propagated from patients.tenant_id at write time';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'raf_patient_hcc'
          AND INDEX_NAME   = 'idx_rph_tenant_year_mv'
    ) THEN
        CREATE INDEX idx_rph_tenant_year_mv
            ON raf_patient_hcc (tenant_id, measurement_year, model_version);
    END IF;
END //
DELIMITER ;
CALL _add_rph_columns();
DROP PROCEDURE IF EXISTS _add_rph_columns;
