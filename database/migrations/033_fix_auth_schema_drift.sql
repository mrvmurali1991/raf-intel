-- =============================================================================
-- Migration 033: Fix auth schema drift between auth_service.py and 005_authentication.sql
--
-- auth_service.py was extended over time (full_name display field, MFA
-- recovery codes, password-reset-on-users, hashed session tokens, session_id
-- UUID lookups, idle-timeout tracking) but 005_authentication.sql was never
-- updated to match, and no later migration closed the gap. This caused
-- POST /api/auth/login to fail with "Internal server error" — the root cause
-- traced through two sequential "Unknown column" errors:
--   1054: Unknown column 'full_name' in 'field list'          (users)
--   1054: Unknown column 'session_id' in 'field list'          (user_sessions)
--
-- This migration is idempotent (INFORMATION_SCHEMA-guarded, same pattern as
-- 030_user_sessions_prev_refresh_hash.sql) so it is safe to re-run.
-- =============================================================================

USE raf_intelligence;

DROP PROCEDURE IF EXISTS _fix_auth_schema_drift;
DELIMITER //
CREATE PROCEDURE _fix_auth_schema_drift()
BEGIN
    -- -------------------------------------------------------------------
    -- users.full_name — ensure it exists (may already have been added
    -- manually; this makes that state reproducible for fresh environments)
    -- -------------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'full_name'
    ) THEN
        ALTER TABLE users
            ADD COLUMN full_name VARCHAR(200) NULL
                COMMENT 'Denormalized display name; auth_service.py reads/writes this directly';
    END IF;

    -- Backfill any NULL/empty full_name from first_name + last_name so the
    -- UI does not show a blank name for existing rows.
    UPDATE users
    SET full_name = TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')))
    WHERE full_name IS NULL OR full_name = '';

    -- -------------------------------------------------------------------
    -- users.mfa_recovery_codes — used by enable_mfa / verify_mfa_code / disable_mfa
    -- -------------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'mfa_recovery_codes'
    ) THEN
        ALTER TABLE users
            ADD COLUMN mfa_recovery_codes JSON NULL
                COMMENT 'JSON array of argon2id-hashed one-time MFA recovery codes';
    END IF;

    -- -------------------------------------------------------------------
    -- users.password_reset_token / password_reset_expires — code stores the
    -- reset token directly on users (the separate password_reset_tokens
    -- table created by 005 is unused dead code).
    -- -------------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'password_reset_token'
    ) THEN
        ALTER TABLE users
            ADD COLUMN password_reset_token VARCHAR(255) NULL
                COMMENT 'SHA-256 hash of the emailed plaintext reset token',
            ADD INDEX idx_users_password_reset_token (password_reset_token);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'password_reset_expires'
    ) THEN
        ALTER TABLE users
            ADD COLUMN password_reset_expires DATETIME NULL;
    END IF;

    -- -------------------------------------------------------------------
    -- user_sessions — rename to the *_hash names auth_service.py uses, and
    -- add the columns it depends on (session_id UUID lookup key,
    -- last_activity_at / last_used_at for idle timeout + session listing,
    -- updated_at for the refresh-token rotation grace window).
    -- -------------------------------------------------------------------
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'session_token'
    ) AND NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'session_token_hash'
    ) THEN
        ALTER TABLE user_sessions
            RENAME COLUMN session_token TO session_token_hash;
    END IF;

    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'refresh_token'
    ) AND NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'refresh_token_hash'
    ) THEN
        ALTER TABLE user_sessions
            RENAME COLUMN refresh_token TO refresh_token_hash;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'session_id'
    ) THEN
        ALTER TABLE user_sessions
            ADD COLUMN session_id VARCHAR(36) NULL
                COMMENT 'UUID session identifier; primary lookup key used by auth_service.py'
                AFTER id,
            ADD UNIQUE KEY uq_user_sessions_session_id (session_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'last_activity_at'
    ) THEN
        ALTER TABLE user_sessions
            ADD COLUMN last_activity_at DATETIME NULL
                COMMENT 'HIPAA idle-timeout tracking';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'last_used_at'
    ) THEN
        ALTER TABLE user_sessions
            ADD COLUMN last_used_at DATETIME NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions' AND COLUMN_NAME = 'updated_at'
    ) THEN
        ALTER TABLE user_sessions
            ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
    END IF;

    -- refresh_expires_at is NOT NULL in 005 but auth_service.py's INSERT
    -- never supplies it — relax so login's session INSERT does not fail.
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_sessions'
          AND COLUMN_NAME = 'refresh_expires_at' AND IS_NULLABLE = 'NO'
    ) THEN
        ALTER TABLE user_sessions
            MODIFY COLUMN refresh_expires_at DATETIME NULL;
    END IF;
END //
DELIMITER ;
CALL _fix_auth_schema_drift();
DROP PROCEDURE IF EXISTS _fix_auth_schema_drift;
