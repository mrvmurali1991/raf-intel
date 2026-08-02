-- =============================================================================
-- Migration 034: Close the local-dev schema gap
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- =============================================================================
--
-- WHY THIS FILE EXISTS
-- ---------------------------------------------------------------------------
-- The backend fails on a freshly-migrated local database because of two
-- distinct problems, both confirmed by reading the code (not guessed):
--
-- PROBLEM 1 — run_all.sql is stale.
--   database/migrations/run_all.sql SOURCEs schema.sql, 001-007,
--   v2026_04_raf_features.sql, and 008-023. It stops at 023_service_tables.sql.
--   Every file numbered 024-033 AND every add_*.sql file (30 files total) was
--   added later and NEVER wired into run_all.sql. If a dev builds their local
--   DB the documented way (`mysql < run_all.sql`), all 30 of those files are
--   silently skipped, even though each one is itself correct and idempotent.
--   This is the majority of "missing column/table" reports.
--
-- PROBLEM 2 — three tables have code that was written against a schema no
--   migration file ever defines, even counting all 56 files on disk:
--     - password_history            (table doesn't exist anywhere, ever)
--     - raf_comorbidity_patterns    (table doesn't exist; a similarly-named
--                                    but differently-shaped kg_comorbidity_patterns
--                                    exists instead — not a usable substitute)
--     - raf_specificity_upgrades    (table doesn't exist anywhere, ever)
--     - emr_connections             (007_emr_connections.sql defines a table
--                                    with different column NAMES than
--                                    backend/app/services/emr_manager.py uses:
--                                    status vs is_active, db_username vs
--                                    db_user, fhir_base_url vs base_url,
--                                    client_secret_encrypted vs client_secret,
--                                    api_key_encrypted vs api_key, auth_type vs
--                                    api_auth_type, config_overrides vs
--                                    extra_config — plus display_name,
--                                    access_token, refresh_token_emr,
--                                    token_expires_at are missing entirely)
--
-- This file fixes both: Part A re-sources every orphaned-but-correct file in
-- dependency order (no SQL is duplicated — each ALTER/CREATE still lives in
-- its one canonical file); Part B adds the genuinely new DDL for the three
-- gaps in problem 2, guarded with INFORMATION_SCHEMA checks so it's safe to
-- re-run.
--
-- USAGE
--   Run from the database/migrations/ directory itself (SOURCE paths below
--   are bare filenames, exactly like run_all.sql already does):
--     cd database/migrations
--     mysql -h <host> -u <user> -p raf_intelligence < 034_local_dev_schema_gap_fix.sql
--
--   This assumes run_all.sql (or an equivalent already-applied baseline
--   through 023_service_tables.sql) has already been run once. If you are
--   building a brand-new database, run run_all.sql first, then this file.
--
-- NOT INCLUDED — read before you assume "done":
--   add_patients_compat_view.sql is intentionally NOT sourced here. It
--   creates `patients` as a VIEW over `openemr.patient_data` (a *separate*
--   MySQL schema/database, not a table in raf_intelligence) LEFT JOINed to
--   raf_patient_demographics. If your local MySQL instance does not also
--   have an `openemr` database with a populated `patient_data` table (e.g.
--   via `docker-compose up` bringing up the `mysql` + `openemr` services
--   defined in docker-compose.yml), sourcing it here would either error
--   ("Table 'openemr.patient_data' doesn't exist") and abort the rest of
--   this batch, or silently create a view that returns zero rows. Run it
--   yourself, separately, once your local OpenEMR schema exists:
--     mysql -h <host> -u <user> -p raf_intelligence < add_patients_compat_view.sql
-- =============================================================================

USE raf_intelligence;
SET foreign_key_checks = 0;

-- =============================================================================
-- PART A — source every migration file that exists on disk but was never
-- wired into run_all.sql. Every one of these is independently idempotent
-- (CREATE TABLE IF NOT EXISTS / guarded ADD COLUMN), so re-running this
-- whole file is safe.
-- =============================================================================

-- --- plain numbered migrations, no recapture_gaps dependency -----------------
SOURCE 024_ai_audit_log.sql;
SOURCE 025_normalize_emr_db_host.sql;
SOURCE 026_raf_jobs_submitted_at.sql;
SOURCE 027_add_hcc_codes_found.sql;
SOURCE 028_raf_patient_hcc_model_version.sql;
SOURCE 030_user_sessions_prev_refresh_hash.sql;
SOURCE 032_patients_view_mbi.sql;
SOURCE 033_fix_auth_schema_drift.sql;

-- --- recapture_gaps chain — order matters: base table first, then every ----
-- --- file that ALTERs it. add_recapture_ai_suggestions.sql (despite its
-- --- unnumbered name) is what actually creates recapture_gaps; 029 and 031
-- --- are numbered but ALTER a table that only this file creates.
SOURCE add_recapture_ai_suggestions.sql;
SOURCE 029_recapture_gaps_irr_labels.sql;
SOURCE 031_recapture_suspects_providers_drift.sql;
SOURCE add_recapture_close_columns.sql;
SOURCE add_recapture_meat_audit.sql;
SOURCE add_recurring_flag.sql;
SOURCE add_recapture_bonus_config.sql;
SOURCE add_recapture_campaigns.sql;
SOURCE add_recapture_outreach.sql;

-- --- knowledge graph chain — base concepts/edges tables first --------------
SOURCE add_knowledge_graph.sql;
SOURCE add_kg_evidence_rules.sql;
SOURCE add_atc_hierarchy.sql;
SOURCE add_kg_brand_to_generic.sql;
SOURCE add_kg_query_log.sql;
SOURCE add_demographic_risk_factors.sql;
SOURCE add_hcc_comorbidity_patterns.sql;
SOURCE add_specialty_hcc_priors.sql;

-- --- standalone, no cross-file dependency -----------------------------------
SOURCE add_hcc_removal_candidates.sql;
SOURCE add_loinc_lab_signals.sql;
SOURCE add_feature_flags.sql;
SOURCE add_disputes_appeals.sql;
SOURCE add_phi_access_log.sql;

-- =============================================================================
-- PART B — genuinely new DDL. None of the above files define these; they do
-- not exist anywhere in database/migrations/*.sql or backend/alembic/versions/.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- B1. password_history
--     Used by auth_service.py: _check_password_history() (change_password,
--     reset_password) and _record_password_history(). Every password change
--     or reset currently raises 1146 "Table 'password_history' doesn't exist".
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_history (
  id            INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  user_id       INT UNSIGNED    NOT NULL,
  password_hash VARCHAR(255)    NOT NULL                        COMMENT 'Previous argon2id/bcrypt hash, retained to block reuse',
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_password_history_user_id (user_id, created_at),
  CONSTRAINT fk_password_history_user_id
    FOREIGN KEY (user_id)
    REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Password reuse history; auth_service.py keeps the last 5 hashes per user';

-- -----------------------------------------------------------------------------
-- B2. raf_comorbidity_patterns
--     Used by suspect_engine.py:93,1101-1218 (scan_comorbidities). Columns
--     below are the exact fields that function reads off each row via
--     pat.get(...). kg_comorbidity_patterns (add_hcc_comorbidity_patterns.sql)
--     is NOT a substitute — different shape (JSON required_evidence /
--     output_hcc / upgrades_from_hcc vs this table's condition_a/condition_b
--     pair-matching shape).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_comorbidity_patterns (
  id                INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  pattern_name      VARCHAR(200)    NOT NULL,
  condition_a_icd   VARCHAR(10)     NOT NULL                    COMMENT 'ICD-10 prefix that must be present (required)',
  condition_a_hcc   VARCHAR(10)     NULL,
  condition_b_icd   VARCHAR(10)     NULL                        COMMENT 'ICD-10 prefix that must also be present; NULL = single-condition pattern',
  condition_b_hcc   VARCHAR(10)     NULL,
  suspect_icd10     VARCHAR(10)     NOT NULL                    COMMENT 'ICD-10 code suspected to be present but not yet coded',
  suspect_hcc       VARCHAR(10)     NULL,
  confidence_base   DECIMAL(4,3)    NOT NULL DEFAULT 0.600,
  notes             TEXT            NULL                        COMMENT 'Clinical rationale shown in suspect evidence',
  is_active         TINYINT(1)      NOT NULL DEFAULT 1,
  created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_rcp_is_active     (is_active),
  KEY idx_rcp_condition_a   (condition_a_icd),
  KEY idx_rcp_suspect_icd10 (suspect_icd10)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Comorbidity co-occurrence rules read by suspect_engine.scan_comorbidities()';

-- -----------------------------------------------------------------------------
-- B3. raf_specificity_upgrades
--     Used by suspect_engine.py:104,1241-1389 (scan_specificity_upgrades).
--     Columns are the exact fields read via rule.get(...).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_specificity_upgrades (
  id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  generic_icd10       VARCHAR(10)     NOT NULL                  COMMENT 'Unspecified/generic ICD-10 code the patient is already coded with',
  generic_hcc         VARCHAR(10)     NULL,
  specific_icd10      VARCHAR(10)     NOT NULL                  COMMENT 'More specific ICD-10 code supported by required_evidence',
  specific_hcc        VARCHAR(10)     NULL,
  required_evidence   VARCHAR(255)    NOT NULL                  COMMENT 'ICD-10 prefix, lab pattern (e.g. eGFR<15), or medication name fragment, depending on evidence_type',
  evidence_type       ENUM('comorbidity','lab','medication','procedure')
                                      NOT NULL DEFAULT 'comorbidity',
  confidence_base     DECIMAL(4,3)    NOT NULL DEFAULT 0.750,
  revenue_delta_est   DECIMAL(10,2)   NOT NULL DEFAULT 0.00     COMMENT 'Estimated annual RAF revenue uplift from the upgrade',
  description         TEXT            NULL,
  is_active           TINYINT(1)      NOT NULL DEFAULT 1,
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_rsu_is_active     (is_active),
  KEY idx_rsu_generic_icd10 (generic_icd10)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='ICD-10 specificity-upgrade rules read by suspect_engine.scan_specificity_upgrades()';

-- -----------------------------------------------------------------------------
-- B4. emr_connections — add the columns emr_manager.py actually queries.
--     Additive only: nothing else in the codebase references the old
--     status/db_username/fhir_base_url/client_secret_encrypted/
--     api_key_encrypted/auth_type/config_overrides names for THIS table
--     (verified by grep across backend/app/), so old columns are left in
--     place rather than renamed/dropped, and new columns are backfilled
--     from them once.
-- -----------------------------------------------------------------------------
DROP PROCEDURE IF EXISTS _fix_emr_connections_drift;
DELIMITER //
CREATE PROCEDURE _fix_emr_connections_drift()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'display_name'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN display_name VARCHAR(200) NULL
                COMMENT 'Human-readable label; emr_manager.py SELECTs/INSERTs this directly (separate from `name`)' AFTER name;
        UPDATE emr_connections SET display_name = name WHERE display_name IS NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'db_user'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN db_user VARCHAR(100) NULL COMMENT 'emr_manager.py name for db_username';
        UPDATE emr_connections SET db_user = db_username WHERE db_user IS NULL AND db_username IS NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'db_password'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN db_password TEXT NULL COMMENT 'emr_manager.py name for db_password_encrypted; app encrypts before write regardless of column name';
        UPDATE emr_connections SET db_password = db_password_encrypted WHERE db_password IS NULL AND db_password_encrypted IS NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'base_url'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN base_url VARCHAR(500) NULL COMMENT 'emr_manager.py name for fhir_base_url; also holds the REST api_base_url mapping for fhir_r4/rest_api types';
        UPDATE emr_connections SET base_url = fhir_base_url WHERE base_url IS NULL AND fhir_base_url IS NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'client_secret'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN client_secret TEXT NULL COMMENT 'emr_manager.py name for client_secret_encrypted';
        UPDATE emr_connections SET client_secret = client_secret_encrypted WHERE client_secret IS NULL AND client_secret_encrypted IS NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'api_key'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN api_key TEXT NULL COMMENT 'emr_manager.py name for api_key_encrypted';
        UPDATE emr_connections SET api_key = api_key_encrypted WHERE api_key IS NULL AND api_key_encrypted IS NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'api_auth_type'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN api_auth_type VARCHAR(20) NULL COMMENT 'emr_manager.py name for auth_type';
        UPDATE emr_connections SET api_auth_type = auth_type WHERE api_auth_type IS NULL AND auth_type IS NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'is_active'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'emr_manager.py name for status; every WHERE is_active = 1 call site depends on this';
        UPDATE emr_connections SET is_active = IF(status = 'active', 1, 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'extra_config'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN extra_config JSON NULL COMMENT 'emr_manager.py name for config_overrides';
        UPDATE emr_connections SET extra_config = config_overrides WHERE extra_config IS NULL AND config_overrides IS NOT NULL;
    END IF;

    -- OAuth2 token storage for SMART-on-FHIR connections — not in 007 at all.
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'access_token'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN access_token TEXT NULL COMMENT 'AES-256-GCM ciphertext of the current OAuth2 access token';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'refresh_token_emr'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN refresh_token_emr TEXT NULL COMMENT 'AES-256-GCM ciphertext of the OAuth2 refresh token (named _emr to avoid confusion with users.refresh_token)';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emr_connections' AND COLUMN_NAME = 'token_expires_at'
    ) THEN
        ALTER TABLE emr_connections
            ADD COLUMN token_expires_at DATETIME NULL COMMENT 'Expiry of access_token; set via NOW() + INTERVAL expires_in SECOND on refresh';
    END IF;
END //
DELIMITER ;
CALL _fix_emr_connections_drift();
DROP PROCEDURE IF EXISTS _fix_emr_connections_drift;

SET foreign_key_checks = 1;

-- =============================================================================
-- Verification queries — run these after applying to confirm the fix.
-- =============================================================================
-- SELECT COUNT(*) FROM information_schema.columns
--   WHERE table_schema = DATABASE() AND table_name = 'users'
--     AND column_name IN ('full_name','mfa_recovery_codes','password_reset_token','password_reset_expires');
--   -- expect 4
--
-- SELECT COUNT(*) FROM information_schema.columns
--   WHERE table_schema = DATABASE() AND table_name = 'user_sessions'
--     AND column_name IN ('session_id','session_token_hash','refresh_token_hash','last_used_at','last_activity_at','updated_at','prev_refresh_token_hash');
--   -- expect 7
--
-- SELECT COUNT(*) FROM information_schema.columns
--   WHERE table_schema = DATABASE() AND table_name = 'emr_connections'
--     AND column_name IN ('display_name','db_user','db_password','base_url','client_secret','api_key','api_auth_type','is_active','extra_config','access_token','refresh_token_emr','token_expires_at');
--   -- expect 12
--
-- SHOW TABLES LIKE 'password_history';
-- SHOW TABLES LIKE 'raf_comorbidity_patterns';
-- SHOW TABLES LIKE 'raf_specificity_upgrades';
-- SHOW TABLES LIKE 'recapture_gaps';
-- =============================================================================
