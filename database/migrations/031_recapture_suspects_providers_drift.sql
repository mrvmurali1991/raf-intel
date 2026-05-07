-- 031_recapture_suspects_providers_drift.sql
--
-- Promotes three schema patches that were previously applied inline by
-- backend/scripts/seed_demo_panel.py into a proper numbered migration so a
-- fresh `git clone` starts with a fully-consistent schema.
--
-- Patches:
--   1. recapture_gaps         — add current_year SMALLINT and prior_year SMALLINT
--   2. raf_suspect_conditions — add tenant_id VARCHAR(64) NOT NULL DEFAULT '1'
--   3. providers              — add user_id INT NULL; widen tenant_id to VARCHAR(64)
--                               and normalise DEFAULT to '1'
--
-- Background:
--   • recapture_gaps was originally created without current_year / prior_year.
--     The dashboard_stats query in backend/app/routers/health.py filters by
--     `current_year = %s`; without the column the query raises Unknown column
--     and open_recapture_gaps returns 0.
--   • raf_suspect_conditions was created without a tenant_id column.
--     The suspects-count query (`WHERE status='open' AND tenant_id = %s`)
--     fails without it, returning 0 suspects on an otherwise seeded instance.
--   • providers was created in 003_providers.sql with openemr_user_id but
--     without a separate user_id column.  The worklist service resolves a
--     provider's panel via `WHERE user_id = %s AND tenant_id = %s`.
--     providers.tenant_id exists (VARCHAR(50) DEFAULT 'default') but must be
--     widened to VARCHAR(64) and the default normalised to '1'.
--
-- Idempotency:
--   MySQL 8.0 does not support ALTER TABLE … ADD COLUMN IF NOT EXISTS.
--   Every column addition is wrapped in a stored procedure that checks
--   INFORMATION_SCHEMA.COLUMNS before executing the ALTER TABLE, making this
--   migration safe to re-run on an already-migrated database.
--
-- Backfills:
--   • recapture_gaps.current_year / prior_year — seeded from YEAR(NOW()) on
--     rows where current_year IS NULL or = 0 (only applies on instances where
--     the columns were just added; existing data retains its values).
--   • providers.user_id  ← openemr_user_id  (where user_id IS NULL)
--   • providers.tenant_id: rows with old DEFAULT 'default' normalised to '1'.
--   • tenant_id columns added with DEFAULT '1' so future inserts are correct.

-- =============================================================================
-- 1. recapture_gaps — current_year + prior_year
-- =============================================================================

DROP PROCEDURE IF EXISTS _031_patch_recapture_gaps;
DELIMITER //
CREATE PROCEDURE _031_patch_recapture_gaps()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'recapture_gaps'
          AND COLUMN_NAME  = 'current_year'
    ) THEN
        ALTER TABLE recapture_gaps
            ADD COLUMN current_year SMALLINT NOT NULL DEFAULT 0
                COMMENT 'Payment year being actively coded (mirrors payment_year on insert; updated when year rolls over)';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'recapture_gaps'
          AND COLUMN_NAME  = 'prior_year'
    ) THEN
        ALTER TABLE recapture_gaps
            ADD COLUMN prior_year SMALLINT NOT NULL DEFAULT 0
                COMMENT 'Year in which the HCC was originally coded (current_year - 1 for chronic recapture)';
    END IF;
END //
DELIMITER ;
CALL _031_patch_recapture_gaps();
DROP PROCEDURE IF EXISTS _031_patch_recapture_gaps;

-- Backfill: for rows where current_year is 0 (the sentinel written by
-- ADD COLUMN … DEFAULT 0), set current_year to the current calendar year
-- and prior_year to current_year - 1.
-- Rows that already carry a real value (non-zero) are left untouched.
-- If the column pre-existed with proper data this UPDATE matches 0 rows.
UPDATE recapture_gaps
   SET current_year = YEAR(NOW()),
       prior_year   = YEAR(NOW()) - 1
 WHERE current_year = 0;

-- =============================================================================
-- 2. raf_suspect_conditions — tenant_id
-- =============================================================================

DROP PROCEDURE IF EXISTS _031_patch_suspect_conditions;
DELIMITER //
CREATE PROCEDURE _031_patch_suspect_conditions()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'raf_suspect_conditions'
          AND COLUMN_NAME  = 'tenant_id'
    ) THEN
        ALTER TABLE raf_suspect_conditions
            ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1'
                COMMENT 'Owning tenant — propagated from patients.tenant_id at write time';
    ELSE
        -- Column already exists (may be VARCHAR(50) or narrower); widen and
        -- correct the default in one MODIFY so new inserts get '1'.
        ALTER TABLE raf_suspect_conditions
            MODIFY COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1'
                COMMENT 'Owning tenant — propagated from patients.tenant_id at write time';
    END IF;

    -- Covering index for the dashboard suspects-count query:
    --   SELECT COUNT(*) FROM raf_suspect_conditions WHERE status='open' AND tenant_id=%s
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'raf_suspect_conditions'
          AND INDEX_NAME   = 'idx_rsc_tenant_status'
    ) THEN
        CREATE INDEX idx_rsc_tenant_status
            ON raf_suspect_conditions (tenant_id, status);
    END IF;
END //
DELIMITER ;
CALL _031_patch_suspect_conditions();
DROP PROCEDURE IF EXISTS _031_patch_suspect_conditions;

-- =============================================================================
-- 3. providers — user_id + tenant_id (VARCHAR 64, DEFAULT '1')
-- =============================================================================

DROP PROCEDURE IF EXISTS _031_patch_providers;
DELIMITER //
CREATE PROCEDURE _031_patch_providers()
BEGIN
    -- user_id: a RAF-internal user identifier that mirrors openemr_user_id.
    -- The worklist service joins on providers.user_id = auth_token.user_id.
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'providers'
          AND COLUMN_NAME  = 'user_id'
    ) THEN
        ALTER TABLE providers
            ADD COLUMN user_id INT NULL DEFAULT NULL
                COMMENT 'RAF internal user id (mirrors openemr_user_id; set at insert time)';
    END IF;

    -- providers.tenant_id was created as VARCHAR(50) NOT NULL DEFAULT 'default'
    -- in 003_providers.sql.  Widen to VARCHAR(64) and normalise DEFAULT to '1'.
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'providers'
          AND COLUMN_NAME  = 'tenant_id'
    ) THEN
        -- Column absent entirely — add it.
        ALTER TABLE providers
            ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1'
                COMMENT 'Owning tenant';
    ELSE
        -- Column present; widen and correct the default in one MODIFY.
        ALTER TABLE providers
            MODIFY COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1'
                COMMENT 'Owning tenant';
    END IF;

    -- Composite index for worklist query: WHERE user_id = %s AND tenant_id = %s
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'providers'
          AND INDEX_NAME   = 'idx_provider_user_tenant'
    ) THEN
        CREATE INDEX idx_provider_user_tenant
            ON providers (user_id, tenant_id);
    END IF;
END //
DELIMITER ;
CALL _031_patch_providers();
DROP PROCEDURE IF EXISTS _031_patch_providers;

-- Backfill providers.user_id from openemr_user_id for rows that pre-date
-- this migration (openemr_user_id was set at insert time for all existing rows).
UPDATE providers
   SET user_id = CAST(openemr_user_id AS SIGNED)
 WHERE user_id IS NULL
   AND openemr_user_id IS NOT NULL;

-- Backfill providers.tenant_id: rows inserted before this migration carry
-- the old default of 'default'; normalise them to '1' (single-tenant value).
UPDATE providers
   SET tenant_id = '1'
 WHERE tenant_id = 'default';
