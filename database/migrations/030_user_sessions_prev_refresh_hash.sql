-- 030_user_sessions_prev_refresh_hash.sql
--
-- Adds the prev_refresh_token_hash column to user_sessions so the
-- refresh-token rotation flow in auth_service.refresh_access_token() can
-- compare the previous-generation hash to the current one (defends against
-- token replay during a rotation race).
--
-- Without this column /api/auth/refresh raises:
--   1054 (42S22): Unknown column 'prev_refresh_token_hash' in 'field list'
-- which leaves the frontend's auth-context spinning on cold load.
--
-- Idempotent: uses an INFORMATION_SCHEMA existence check so safe to re-run.

DROP PROCEDURE IF EXISTS _add_prev_refresh_hash;
DELIMITER //
CREATE PROCEDURE _add_prev_refresh_hash()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'user_sessions'
          AND COLUMN_NAME  = 'prev_refresh_token_hash'
    ) THEN
        ALTER TABLE user_sessions
            ADD COLUMN prev_refresh_token_hash VARCHAR(128) NULL DEFAULT NULL
                COMMENT 'Hash of the previous refresh token, kept across one rotation to detect replay';
    END IF;
END //
DELIMITER ;
CALL _add_prev_refresh_hash();
DROP PROCEDURE IF EXISTS _add_prev_refresh_hash;
