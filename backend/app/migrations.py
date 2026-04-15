"""
DEPRECATED: All schema changes must go through Alembic migrations in
backend/alembic/versions/. These functions remain only for legacy compatibility
and will be removed.

Historical note: this module used to be the central auto-DDL runner that
executed ``CREATE TABLE IF NOT EXISTS`` statements at application startup.
That behavior bypassed Alembic and caused schema drift between environments.
The module is retained so that stale imports do not break the app, but all
entry points now emit ``DeprecationWarning`` and the decorator-time
registration of DDL steps has been neutralized (no import-time side effects).
"""

from __future__ import annotations

import logging
import warnings
from typing import Callable

logger = logging.getLogger(__name__)

_DEPRECATION_MESSAGE = (
    "app.migrations auto-DDL is deprecated; use Alembic migrations in "
    "backend/alembic/versions/ instead. This function is a no-op shim."
)

# ---------------------------------------------------------------------------
# DDL registry
# ---------------------------------------------------------------------------
# Each entry is a callable that executes one or more CREATE TABLE statements.
# Order matters: tables referenced by foreign keys must appear first.

_ddl_steps: list[tuple[str, Callable[[], None]]] = []


def register(step_name: str):
    """DEPRECATED: decorator is now a no-op; DDL is no longer auto-run.

    Previously this appended the decorated function to ``_ddl_steps`` at
    import time. That import-time side effect has been neutralized so that
    merely importing ``app.migrations`` no longer schedules any DDL work.
    """

    def decorator(fn: Callable[[], None]):
        # Intentionally do NOT append to _ddl_steps — import-time side
        # effects are neutralized. Return the function unchanged so that
        # callers that reference it directly still resolve.
        return fn

    return decorator


# ---------------------------------------------------------------------------
# DDL step implementations
# ---------------------------------------------------------------------------
# Import the modules that register their tables.  Each module calls
# ``register`` at import time which populates _ddl_steps.


def _execute(sql: str) -> None:
    """Execute a single SQL statement against the RAF Intelligence DB."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(sql)


def _column_exists(table_name: str, column_name: str) -> bool:
    """Return True when *column_name* exists on *table_name* in the current DB."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None


def _add_column_if_missing(table_name: str, column_name: str, definition_sql: str) -> None:
    """Add a column using portable SQL only when it does not already exist."""
    if _column_exists(table_name, column_name):
        return
    _execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}")


# ---- Core tables -----------------------------------------------------------


@register("raf_jobs")
def _jobs_table() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS raf_jobs (
            id            VARCHAR(36)   PRIMARY KEY,
            task_name     VARCHAR(120)  NOT NULL,
            status        VARCHAR(20)   NOT NULL DEFAULT 'PENDING',
            progress      INT           NOT NULL DEFAULT 0,
            total         INT           NOT NULL DEFAULT 0,
            tenant_id     INT,
            submitted_by  INT,
            args_json     TEXT,
            result_json   TEXT,
            error_message TEXT,
            started_at    DATETIME,
            finished_at   DATETIME,
            created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_status (status),
            INDEX idx_tenant (tenant_id),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # Ensure columns exist if table was created before they were added
    for col, defn in [
        ("finished_at", "DATETIME"),
        ("started_at", "DATETIME"),
        ("error_message", "TEXT"),
        ("result_json", "TEXT"),
        ("args_json", "TEXT"),
        ("submitted_by", "INT"),
        ("tenant_id", "INT"),
    ]:
        try:
            _execute(f"ALTER TABLE raf_jobs ADD COLUMN {col} {defn}")
        except Exception:
            pass  # column already exists


@register("raf_user_notification_preferences")
def _notification_prefs_table() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS raf_user_notification_preferences (
            user_id             INT             PRIMARY KEY,
            analysis_complete   TINYINT(1)      NOT NULL DEFAULT 1,
            submission_deadline TINYINT(1)      NOT NULL DEFAULT 1,
            care_gap_alerts     TINYINT(1)      NOT NULL DEFAULT 1,
            suspect_alerts      TINYINT(1)      NOT NULL DEFAULT 1,
            sync_failure_alerts TINYINT(1)      NOT NULL DEFAULT 1,
            security_alerts     TINYINT(1)      NOT NULL DEFAULT 1,
            updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("auth_tables")
def _auth_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            email                   VARCHAR(255) NOT NULL,
            password_hash           VARCHAR(255) NOT NULL,
            full_name               VARCHAR(255),
            role                    VARCHAR(20) NOT NULL DEFAULT 'viewer',
            tenant_id               INT,
            is_active               TINYINT(1) NOT NULL DEFAULT 1,
            avatar_url              VARCHAR(500),
            failed_login_attempts   INT NOT NULL DEFAULT 0,
            locked_until            DATETIME,
            last_login_at           DATETIME,
            password_changed_at     DATETIME,
            password_reset_token    VARCHAR(255),
            password_reset_expires  DATETIME,
            mfa_enabled             TINYINT(1) NOT NULL DEFAULT 0,
            mfa_secret              TEXT,
            mfa_recovery_codes      TEXT,
            created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_users_email (email),
            INDEX idx_users_role (role),
            INDEX idx_users_active (is_active),
            INDEX idx_users_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS role_default_permissions (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            role        VARCHAR(20) NOT NULL,
            resource    VARCHAR(50) NOT NULL,
            action      VARCHAR(20) NOT NULL,
            granted     TINYINT(1) NOT NULL DEFAULT 1,
            UNIQUE KEY uq_role_resource_action (role, resource, action),
            INDEX idx_role (role)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS user_permissions (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            user_id     INT NOT NULL,
            resource    VARCHAR(50) NOT NULL,
            action      VARCHAR(20) NOT NULL,
            granted     TINYINT(1) NOT NULL DEFAULT 1,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_user_resource_action (user_id, resource, action),
            INDEX idx_user_permissions_user (user_id),
            CONSTRAINT fk_user_permissions_user
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            session_id          VARCHAR(64) NOT NULL,
            user_id             INT NOT NULL,
            session_token_hash  VARCHAR(128) NOT NULL,
            refresh_token_hash  VARCHAR(128) NOT NULL,
            ip_address          VARCHAR(45),
            user_agent          VARCHAR(500),
            expires_at          DATETIME NOT NULL,
            last_used_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_activity_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_revoked          TINYINT(1) NOT NULL DEFAULT 0,
            created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_session_id (session_id),
            INDEX idx_sessions_user (user_id),
            INDEX idx_sessions_expires (expires_at),
            INDEX idx_sessions_revoked (is_revoked),
            CONSTRAINT fk_user_sessions_user
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id              BIGINT AUTO_INCREMENT PRIMARY KEY,
            user_id         INT,
            action          VARCHAR(100) NOT NULL,
            resource_type   VARCHAR(50),
            resource_id     VARCHAR(100),
            patient_id      INT,
            ip_address      VARCHAR(45),
            user_agent      VARCHAR(500),
            request_method  VARCHAR(10),
            request_path    VARCHAR(500),
            response_status INT,
            details         JSON,
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_audit_user (user_id),
            INDEX idx_audit_action (action),
            INDEX idx_audit_patient (patient_id),
            INDEX idx_audit_created (created_at),
            CONSTRAINT fk_audit_user
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("cohorts")
def _cohorts_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS cohorts (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            description TEXT,
            filters_json TEXT,
            created_by  INT,
            tenant_id   VARCHAR(100) DEFAULT 'default',
            status      VARCHAR(20) DEFAULT 'active',
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_cohorts_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("cohorts", "status", "VARCHAR(20) DEFAULT 'active'")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_members (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            cohort_id   INT NOT NULL,
            patient_id  INT NOT NULL,
            is_active   TINYINT(1) NOT NULL DEFAULT 1,
            added_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_cohort (cohort_id),
            INDEX idx_patient (patient_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("cohort_members", "is_active", "TINYINT(1) NOT NULL DEFAULT 1")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_snapshots (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            cohort_id   INT NOT NULL,
            snapshot_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metrics_json TEXT,
            INDEX idx_cohort (cohort_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_comparisons (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            cohort_a_id INT NOT NULL,
            cohort_b_id INT NOT NULL,
            compared_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            result_json TEXT,
            INDEX idx_cohort_a (cohort_a_id),
            INDEX idx_cohort_b (cohort_b_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("care_gap_tasks")
def _care_gap_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS care_gap_tasks (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            patient_id  INT NOT NULL,
            provider_id INT,
            hcc_code    VARCHAR(20),
            hcc_description VARCHAR(500),
            icd10_code  VARCHAR(20),
            status      VARCHAR(20) NOT NULL DEFAULT 'open',
            priority    VARCHAR(10) NOT NULL DEFAULT 'medium',
            assigned_to INT,
            due_date    DATE,
            notes       TEXT,
            evidence_summary TEXT,
            suspect_condition_id INT,
            created_by  INT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            tenant_id   VARCHAR(100) DEFAULT 'default',
            gap_type    VARCHAR(50) DEFAULT 'hcc',
            updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_patient (patient_id),
            INDEX idx_status (status),
            INDEX idx_assigned (assigned_to),
            INDEX idx_care_gap_tasks_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("care_gap_tasks", "tenant_id", "VARCHAR(100) DEFAULT 'default'")
    _add_column_if_missing("care_gap_tasks", "gap_type", "VARCHAR(50) DEFAULT 'hcc'")
    _add_column_if_missing("care_gap_tasks", "provider_id", "INT")
    _add_column_if_missing("care_gap_tasks", "hcc_description", "VARCHAR(500)")
    _add_column_if_missing("care_gap_tasks", "notes", "TEXT")
    _add_column_if_missing("care_gap_tasks", "evidence_summary", "TEXT")
    _add_column_if_missing("care_gap_tasks", "suspect_condition_id", "INT")
    _add_column_if_missing("care_gap_tasks", "created_by", "INT")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS care_gap_comments (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            task_id     INT NOT NULL,
            user_id     INT NOT NULL,
            comment     TEXT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_task (task_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS care_gap_history (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            task_id     INT NOT NULL,
            action      VARCHAR(50) NOT NULL,
            actor_id    INT,
            details_json TEXT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_task (task_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("emr_connections")
def _emr_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS emr_connections (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            base_url    VARCHAR(500) NOT NULL,
            api_key     VARCHAR(500),
            auth_type   VARCHAR(20) NOT NULL DEFAULT 'api_key',
            is_active   TINYINT(1) NOT NULL DEFAULT 1,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # Backward-compatible schema expansion for older installs.
    _add_column_if_missing("emr_connections", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT 'default'")
    _add_column_if_missing("emr_connections", "display_name", "VARCHAR(200) NOT NULL DEFAULT ''")
    _add_column_if_missing("emr_connections", "vendor", "VARCHAR(100) NOT NULL DEFAULT 'generic'")
    _add_column_if_missing("emr_connections", "connection_type", "VARCHAR(30) NOT NULL DEFAULT 'direct_db'")
    _add_column_if_missing("emr_connections", "db_type", "VARCHAR(20)")
    _add_column_if_missing("emr_connections", "db_host", "VARCHAR(255)")
    _add_column_if_missing("emr_connections", "db_port", "INT")
    _add_column_if_missing("emr_connections", "db_name", "VARCHAR(255)")
    _add_column_if_missing("emr_connections", "db_user", "VARCHAR(255)")
    _add_column_if_missing("emr_connections", "db_password", "TEXT")
    _add_column_if_missing("emr_connections", "token_url", "VARCHAR(500)")
    _add_column_if_missing("emr_connections", "client_id", "VARCHAR(255)")
    _add_column_if_missing("emr_connections", "client_secret", "TEXT")
    _add_column_if_missing("emr_connections", "scope", "VARCHAR(500)")
    _add_column_if_missing("emr_connections", "api_base_url", "VARCHAR(500)")
    _add_column_if_missing("emr_connections", "api_key", "TEXT")
    _add_column_if_missing("emr_connections", "api_auth_type", "VARCHAR(20) NOT NULL DEFAULT 'bearer'")
    _add_column_if_missing("emr_connections", "field_mappings", "JSON")
    _add_column_if_missing("emr_connections", "extra_config", "JSON")
    _add_column_if_missing("emr_connections", "last_test_at", "DATETIME")
    _add_column_if_missing("emr_connections", "last_test_success", "TINYINT(1)")
    _add_column_if_missing("emr_connections", "sync_enabled", "TINYINT(1) NOT NULL DEFAULT 0")
    _add_column_if_missing("emr_connections", "sync_interval_minutes", "INT")
    _add_column_if_missing("emr_connections", "sync_cron", "VARCHAR(100)")
    _add_column_if_missing("emr_connections", "last_sync_at", "DATETIME")
    if _column_exists("emr_connections", "name"):
        _execute(
            """
            UPDATE emr_connections
            SET display_name = COALESCE(NULLIF(display_name, ''), name)
            WHERE (display_name = '' OR display_name IS NULL) AND name IS NOT NULL
            """
        )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS emr_sync_log (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            connection_id INT NOT NULL,
            sync_type   VARCHAR(50) NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            records_synced INT NOT NULL DEFAULT 0,
            error_message TEXT,
            started_at  DATETIME,
            finished_at DATETIME,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_connection (connection_id),
            INDEX idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS emr_vendor_presets (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            vendor      VARCHAR(100) NOT NULL,
            display_name VARCHAR(200),
            config_json TEXT NOT NULL,
            connection_type VARCHAR(50) DEFAULT 'api',
            default_port INT,
            default_db_name VARCHAR(100),
            fhir_version VARCHAR(20),
            notes       TEXT,
            default_mappings TEXT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("emr_vendor_presets", "display_name", "VARCHAR(200)")
    _add_column_if_missing("emr_vendor_presets", "connection_type", "VARCHAR(50) DEFAULT 'api'")
    _add_column_if_missing("emr_vendor_presets", "default_port", "INT")
    _add_column_if_missing("emr_vendor_presets", "default_db_name", "VARCHAR(100)")
    _add_column_if_missing("emr_vendor_presets", "fhir_version", "VARCHAR(20)")
    _add_column_if_missing("emr_vendor_presets", "notes", "TEXT")
    _add_column_if_missing("emr_vendor_presets", "default_mappings", "TEXT")


@register("emr_patient_matches")
def _patient_match_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS emr_patient_matches (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            external_id VARCHAR(200) NOT NULL,
            emr_pid     INT NOT NULL,
            match_score DECIMAL(5,4) NOT NULL DEFAULT 1.0,
            match_method VARCHAR(30) NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'matched',
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_external (external_id),
            INDEX idx_emr_pid (emr_pid)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS emr_unmatched_patients (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            external_id VARCHAR(200) NOT NULL,
            patient_data_json TEXT,
            last_attempt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            failure_reason TEXT,
            INDEX idx_external (external_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("webhooks")
def _webhook_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS webhooks (
            id          VARCHAR(50) PRIMARY KEY,
            url         VARCHAR(500) NOT NULL,
            events      JSON NOT NULL,
            secret      VARCHAR(200),
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            is_active   TINYINT(1) DEFAULT 1,
            description VARCHAR(500),
            tenant_id   VARCHAR(100) DEFAULT 'default',
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_webhooks_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("webhooks", "is_active", "TINYINT(1) DEFAULT 1")
    _add_column_if_missing("webhooks", "description", "VARCHAR(500)")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            webhook_id  VARCHAR(50) NOT NULL,
            event_type  VARCHAR(50) NOT NULL,
            payload_json TEXT,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            response_code INT,
            response_body TEXT,
            attempts    INT NOT NULL DEFAULT 0,
            next_retry  DATETIME,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_webhook (webhook_id),
            INDEX idx_status (status),
            INDEX idx_retry (next_retry)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("documents")
def _document_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            patient_id  INT NOT NULL,
            document_type VARCHAR(50) NOT NULL,
            file_name   VARCHAR(500),
            file_path   VARCHAR(500),
            file_size   BIGINT,
            mime_type   VARCHAR(100),
            uploaded_by INT,
            status      VARCHAR(20) NOT NULL DEFAULT 'uploaded',
            tenant_id   VARCHAR(100) DEFAULT 'default',
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_patient (patient_id),
            INDEX idx_type (document_type),
            INDEX idx_status (status),
            INDEX idx_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS document_analysis (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            document_id INT NOT NULL,
            analysis_json TEXT,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_document (document_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS document_diagnosis_lines (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            document_id VARCHAR(50),
            analysis_id INT NOT NULL,
            icd10_code  VARCHAR(20),
            description TEXT,
            status      VARCHAR(20) DEFAULT 'active',
            hcc_code    VARCHAR(20),
            hcc_label   VARCHAR(200),
            raf_weight  DECIMAL(8,4),
            confidence  DECIMAL(5,4),
            meat_score  INT,
            meat_monitor TEXT,
            meat_evaluate TEXT,
            meat_assess TEXT,
            meat_treat  TEXT,
            supporting_text TEXT,
            is_new_hcc  TINYINT(1) DEFAULT 0,
            review_status VARCHAR(20) DEFAULT 'pending',
            source      VARCHAR(50),
            INDEX idx_analysis (analysis_id),
            INDEX idx_document (document_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("document_diagnosis_lines", "is_new_hcc", "TINYINT(1) DEFAULT 0")
    _add_column_if_missing("document_diagnosis_lines", "review_status", "VARCHAR(20) DEFAULT 'pending'")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS document_batches (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(200),
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            total_files INT NOT NULL DEFAULT 0,
            processed_files INT NOT NULL DEFAULT 0,
            created_by  INT,
            tenant_id   VARCHAR(100) DEFAULT 'default',
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_status (status),
            INDEX idx_document_batches_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS document_batch_items (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            batch_id    INT NOT NULL,
            document_id INT,
            file_name   VARCHAR(500),
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_message TEXT,
            INDEX idx_batch (batch_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("raf_awv_tracking")
def _awv_table() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS raf_awv_tracking (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            patient_id  INT NOT NULL,
            awv_date    DATE,
            status      VARCHAR(20) NOT NULL DEFAULT 'scheduled',
            provider_npi VARCHAR(20),
            notes       TEXT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_patient (patient_id),
            INDEX idx_date (awv_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("providers")
def _provider_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS providers (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            openemr_user_id INT,
            npi             VARCHAR(20),
            first_name      VARCHAR(100) NOT NULL DEFAULT '',
            last_name       VARCHAR(100) NOT NULL DEFAULT '',
            full_name       VARCHAR(200),
            specialty       VARCHAR(100),
            email           VARCHAR(255),
            phone           VARCHAR(50),
            status          VARCHAR(20) NOT NULL DEFAULT 'active',
            is_active       TINYINT(1) NOT NULL DEFAULT 1,
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_npi (npi),
            INDEX idx_openemr_user_id (openemr_user_id),
            INDEX idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # Backward-compatible columns for older provider schema revisions.
    _add_column_if_missing("providers", "openemr_user_id", "INT")
    _add_column_if_missing("providers", "first_name", "VARCHAR(100) NOT NULL DEFAULT ''")
    _add_column_if_missing("providers", "last_name", "VARCHAR(100) NOT NULL DEFAULT ''")
    _add_column_if_missing("providers", "full_name", "VARCHAR(200)")
    _add_column_if_missing("providers", "email", "VARCHAR(255)")
    _add_column_if_missing("providers", "phone", "VARCHAR(50)")
    _add_column_if_missing("providers", "status", "VARCHAR(20) NOT NULL DEFAULT 'active'")
    _add_column_if_missing("providers", "is_active", "TINYINT(1) NOT NULL DEFAULT 1")
    _add_column_if_missing(
        "providers",
        "updated_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    )
    # Derive split names from full_name where needed.
    _execute(
        """
        UPDATE providers
        SET
            first_name = COALESCE(
                NULLIF(first_name, ''),
                TRIM(SUBSTRING_INDEX(COALESCE(full_name, ''), ' ', 1))
            ),
            last_name = COALESCE(
                NULLIF(last_name, ''),
                TRIM(
                    SUBSTRING(
                        COALESCE(full_name, ''),
                        LENGTH(SUBSTRING_INDEX(COALESCE(full_name, ''), ' ', 1)) + 1
                    )
                )
            )
        WHERE
            (first_name IS NULL OR first_name = '' OR last_name IS NULL OR last_name = '')
            AND full_name IS NOT NULL
            AND full_name != ''
        """
    )
    # Keep full_name populated for any legacy readers.
    _execute(
        """
        UPDATE providers
        SET full_name = TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')))
        WHERE (full_name IS NULL OR full_name = '')
          AND (first_name IS NOT NULL OR last_name IS NOT NULL)
        """
    )
    # Map legacy active flag to modern status where status is missing.
    _execute(
        """
        UPDATE providers
        SET status = CASE
            WHEN COALESCE(is_active, 1) = 1 THEN 'active'
            ELSE 'inactive'
        END
        WHERE status IS NULL OR status = ''
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS provider_patient_panel (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            provider_id INT NOT NULL,
            patient_id  INT NOT NULL,
            attribution VARCHAR(30) NOT NULL DEFAULT 'manual',
            assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_provider_patient (provider_id, patient_id),
            INDEX idx_provider (provider_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing(
        "provider_patient_panel",
        "attribution",
        "VARCHAR(30) NOT NULL DEFAULT 'manual'",
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS provider_scorecard_snapshots (
            id                          INT AUTO_INCREMENT PRIMARY KEY,
            provider_id                 INT NOT NULL,
            measurement_year            INT NOT NULL DEFAULT 0,
            total_patients              INT NOT NULL DEFAULT 0,
            patients_with_scores        INT NOT NULL DEFAULT 0,
            average_raf                 DECIMAL(8,4),
            hcc_capture_rate            DECIMAL(8,4),
            recapture_rate              DECIMAL(8,4),
            suspects_open               INT NOT NULL DEFAULT 0,
            suspects_accepted           INT NOT NULL DEFAULT 0,
            suspects_dismissed          INT NOT NULL DEFAULT 0,
            revenue_opportunity         DECIMAL(14,2) NOT NULL DEFAULT 0.00,
            meat_completeness_avg       DECIMAL(8,4),
            documentation_quality_score DECIMAL(8,4),
            percentile_rank             DECIMAL(8,4),
            snapshot_date               DATE,
            metrics_json                TEXT,
            calculated_at               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_provider (provider_id),
            INDEX idx_measurement_year (measurement_year),
            INDEX idx_calculated_at (calculated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("provider_scorecard_snapshots", "measurement_year", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("provider_scorecard_snapshots", "total_patients", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("provider_scorecard_snapshots", "patients_with_scores", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("provider_scorecard_snapshots", "average_raf", "DECIMAL(8,4)")
    _add_column_if_missing("provider_scorecard_snapshots", "hcc_capture_rate", "DECIMAL(8,4)")
    _add_column_if_missing("provider_scorecard_snapshots", "recapture_rate", "DECIMAL(8,4)")
    _add_column_if_missing("provider_scorecard_snapshots", "suspects_open", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("provider_scorecard_snapshots", "suspects_accepted", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("provider_scorecard_snapshots", "suspects_dismissed", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing(
        "provider_scorecard_snapshots",
        "revenue_opportunity",
        "DECIMAL(14,2) NOT NULL DEFAULT 0.00",
    )
    _add_column_if_missing("provider_scorecard_snapshots", "meat_completeness_avg", "DECIMAL(8,4)")
    _add_column_if_missing(
        "provider_scorecard_snapshots",
        "documentation_quality_score",
        "DECIMAL(8,4)",
    )
    _add_column_if_missing("provider_scorecard_snapshots", "percentile_rank", "DECIMAL(8,4)")
    _add_column_if_missing("provider_scorecard_snapshots", "snapshot_date", "DATE")
    _add_column_if_missing(
        "provider_scorecard_snapshots",
        "calculated_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    )
    _execute(
        """
        UPDATE provider_scorecard_snapshots
        SET measurement_year = YEAR(COALESCE(snapshot_date, created_at, NOW()))
        WHERE measurement_year IS NULL OR measurement_year = 0
        """
    )
    _execute(
        """
        UPDATE provider_scorecard_snapshots
        SET calculated_at = COALESCE(calculated_at, created_at, NOW())
        WHERE calculated_at IS NULL
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS provider_alerts (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            provider_id     INT NOT NULL,
            patient_id      INT,
            alert_type      VARCHAR(50) NOT NULL,
            title           VARCHAR(255) NOT NULL DEFAULT '',
            description     TEXT,
            hcc_code        VARCHAR(20),
            icd10_code      VARCHAR(20),
            status          VARCHAR(20) NOT NULL DEFAULT 'active',
            acknowledged_at DATETIME,
            message         TEXT,
            is_read         TINYINT(1) NOT NULL DEFAULT 0,
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_provider (provider_id),
            INDEX idx_status (status),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("provider_alerts", "patient_id", "INT")
    _add_column_if_missing("provider_alerts", "title", "VARCHAR(255) NOT NULL DEFAULT ''")
    _add_column_if_missing("provider_alerts", "description", "TEXT")
    _add_column_if_missing("provider_alerts", "hcc_code", "VARCHAR(20)")
    _add_column_if_missing("provider_alerts", "icd10_code", "VARCHAR(20)")
    _add_column_if_missing("provider_alerts", "status", "VARCHAR(20) NOT NULL DEFAULT 'active'")
    _add_column_if_missing("provider_alerts", "acknowledged_at", "DATETIME")
    _add_column_if_missing("provider_alerts", "message", "TEXT")
    _add_column_if_missing("provider_alerts", "is_read", "TINYINT(1) NOT NULL DEFAULT 0")
    _execute(
        """
        UPDATE provider_alerts
        SET title = COALESCE(NULLIF(title, ''), LEFT(COALESCE(message, ''), 255))
        WHERE title IS NULL OR title = ''
        """
    )
    _execute(
        """
        UPDATE provider_alerts
        SET status = CASE
            WHEN COALESCE(is_read, 0) = 1 THEN 'acknowledged'
            ELSE 'active'
        END
        WHERE status IS NULL OR status = ''
        """
    )
    _execute(
        """
        UPDATE provider_alerts
        SET acknowledged_at = COALESCE(acknowledged_at, created_at)
        WHERE status = 'acknowledged' AND acknowledged_at IS NULL
        """
    )


@register("claims")
def _claims_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS claims_batches (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            batch_uuid              VARCHAR(36) NOT NULL UNIQUE,
            filename                VARCHAR(500) NOT NULL,
            file_format             VARCHAR(20) NOT NULL,
            file_size               BIGINT NOT NULL DEFAULT 0,
            status                  VARCHAR(20) NOT NULL DEFAULT 'uploaded',
            uploaded_by             VARCHAR(255),
            claim_count             INT NOT NULL DEFAULT 0,
            matched_patient_count   INT NOT NULL DEFAULT 0,
            unique_patient_count    INT NOT NULL DEFAULT 0,
            unique_provider_count   INT NOT NULL DEFAULT 0,
            total_charges           DECIMAL(14,2) NOT NULL DEFAULT 0.00,
            error_message           TEXT,
            created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_claims_batches_status (status),
            INDEX idx_claims_batches_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("claims_batches", "batch_uuid", "VARCHAR(36)")
    _add_column_if_missing("claims_batches", "filename", "VARCHAR(500)")
    _add_column_if_missing("claims_batches", "file_format", "VARCHAR(20)")
    _add_column_if_missing("claims_batches", "file_size", "BIGINT NOT NULL DEFAULT 0")
    _add_column_if_missing("claims_batches", "status", "VARCHAR(20) NOT NULL DEFAULT 'uploaded'")
    _add_column_if_missing("claims_batches", "uploaded_by", "VARCHAR(255)")
    _add_column_if_missing("claims_batches", "claim_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("claims_batches", "matched_patient_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("claims_batches", "unique_patient_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("claims_batches", "unique_provider_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing(
        "claims_batches",
        "total_charges",
        "DECIMAL(14,2) NOT NULL DEFAULT 0.00",
    )
    _add_column_if_missing("claims_batches", "error_message", "TEXT")
    _add_column_if_missing(
        "claims_batches",
        "updated_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS claims_records (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            batch_id             INT NOT NULL,
            source_claim_id      VARCHAR(120),
            patient_name         VARCHAR(255),
            patient_dob          DATE,
            patient_gender       VARCHAR(20),
            member_id            VARCHAR(120),
            provider_npi         VARCHAR(30),
            provider_name        VARCHAR(255),
            date_of_service      DATE,
            icd10_codes          TEXT,
            cpt_codes            TEXT,
            charges              DECIMAL(14,2) NOT NULL DEFAULT 0.00,
            payer_name           VARCHAR(255),
            place_of_service     VARCHAR(30),
            claim_type           VARCHAR(30) NOT NULL DEFAULT 'professional',
            facility_type        VARCHAR(80),
            admission_date       DATE,
            discharge_date       DATE,
            admission_type       VARCHAR(80),
            admission_source     VARCHAR(80),
            discharge_status     VARCHAR(80),
            admitting_diagnosis  VARCHAR(20),
            principal_diagnosis  VARCHAR(20),
            openemr_pid          INT,
            created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_claims_records_batch (batch_id),
            INDEX idx_claims_records_openemr_pid (openemr_pid),
            INDEX idx_claims_records_dos (date_of_service)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("claims_records", "openemr_pid", "INT")
    _add_column_if_missing("claims_records", "updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")

    _execute(
        """
        CREATE TABLE IF NOT EXISTS claims_diagnoses (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            batch_id        INT NOT NULL,
            claim_record_id INT NOT NULL,
            openemr_pid     INT,
            icd10_code      VARCHAR(20) NOT NULL,
            hcc_code        VARCHAR(20),
            hcc_label       VARCHAR(255),
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_claims_diag_batch (batch_id),
            INDEX idx_claims_diag_claim (claim_record_id),
            INDEX idx_claims_diag_icd10 (icd10_code),
            INDEX idx_claims_diag_hcc (hcc_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("claims_diagnoses", "openemr_pid", "INT")


@register("fhir")
def _fhir_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS fhir_connections (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            name              VARCHAR(200) NOT NULL,
            vendor            VARCHAR(50) NOT NULL DEFAULT 'generic',
            base_url          VARCHAR(500) NOT NULL,
            auth_type         VARCHAR(20) NOT NULL DEFAULT 'none',
            token_url         VARCHAR(500),
            client_id         VARCHAR(255),
            client_secret     TEXT,
            api_key           TEXT,
            scope             VARCHAR(500),
            is_active         TINYINT(1) NOT NULL DEFAULT 1,
            last_sync_at      DATETIME,
            last_sync_status  VARCHAR(30),
            last_sync_message VARCHAR(500),
            created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_fhir_connections_name (name),
            INDEX idx_fhir_connections_vendor (vendor),
            INDEX idx_fhir_connections_active (is_active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("fhir_connections", "vendor", "VARCHAR(50) NOT NULL DEFAULT 'generic'")
    _add_column_if_missing("fhir_connections", "auth_type", "VARCHAR(20) NOT NULL DEFAULT 'none'")
    _add_column_if_missing("fhir_connections", "token_url", "VARCHAR(500)")
    _add_column_if_missing("fhir_connections", "client_id", "VARCHAR(255)")
    _add_column_if_missing("fhir_connections", "client_secret", "TEXT")
    _add_column_if_missing("fhir_connections", "api_key", "TEXT")
    _add_column_if_missing("fhir_connections", "scope", "VARCHAR(500)")
    _add_column_if_missing("fhir_connections", "is_active", "TINYINT(1) NOT NULL DEFAULT 1")
    _add_column_if_missing("fhir_connections", "last_sync_at", "DATETIME")
    _add_column_if_missing("fhir_connections", "last_sync_status", "VARCHAR(30)")
    _add_column_if_missing("fhir_connections", "last_sync_message", "VARCHAR(500)")
    _add_column_if_missing(
        "fhir_connections",
        "updated_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS fhir_sync_logs (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            connection_id     INT NOT NULL,
            sync_type         VARCHAR(20) NOT NULL DEFAULT 'incremental',
            status            VARCHAR(20) NOT NULL DEFAULT 'pending',
            message           VARCHAR(500),
            patients_synced   INT NOT NULL DEFAULT 0,
            conditions_synced INT NOT NULL DEFAULT 0,
            encounters_synced INT NOT NULL DEFAULT 0,
            reports_synced    INT NOT NULL DEFAULT 0,
            started_at        DATETIME,
            completed_at      DATETIME,
            INDEX idx_fhir_sync_connection (connection_id),
            INDEX idx_fhir_sync_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("submission_batches")
def _submission_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS submission_batches (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            submission_type VARCHAR(30) NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            total_records INT NOT NULL DEFAULT 0,
            submitted_at DATETIME,
            response_json TEXT,
            created_by  INT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("submission_batches", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT '1'")
    _add_column_if_missing("submission_batches", "file_type", "VARCHAR(20)")
    _add_column_if_missing("submission_batches", "payment_year", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_batches", "sweep_type", "VARCHAR(20)")
    _add_column_if_missing("submission_batches", "record_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_batches", "valid_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_batches", "invalid_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_batches", "warning_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_batches", "file_path", "VARCHAR(500)")
    _add_column_if_missing("submission_batches", "file_hash", "VARCHAR(128)")
    _add_column_if_missing(
        "submission_batches",
        "updated_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    )
    if _column_exists("submission_batches", "submission_type"):
        _execute(
            """
            UPDATE submission_batches
            SET file_type = COALESCE(NULLIF(file_type, ''), submission_type)
            WHERE (file_type IS NULL OR file_type = '') AND submission_type IS NOT NULL
            """
        )
    if _column_exists("submission_batches", "total_records"):
        _execute(
            """
            UPDATE submission_batches
            SET record_count = COALESCE(record_count, total_records, 0)
            WHERE record_count IS NULL OR record_count = 0
            """
        )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS submission_records (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            batch_id    INT NOT NULL,
            patient_id  INT NOT NULL,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_message TEXT,
            INDEX idx_batch (batch_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("submission_records", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT '1'")
    _add_column_if_missing("submission_records", "hicn_mbi", "VARCHAR(64)")
    _add_column_if_missing("submission_records", "hcc_code", "VARCHAR(20)")
    _add_column_if_missing("submission_records", "icd10_code", "VARCHAR(20)")
    _add_column_if_missing("submission_records", "dos_from", "DATE")
    _add_column_if_missing("submission_records", "dos_through", "DATE")
    _add_column_if_missing("submission_records", "provider_npi", "VARCHAR(20)")
    _add_column_if_missing("submission_records", "provider_type", "VARCHAR(20)")
    _add_column_if_missing(
        "submission_records",
        "validation_status",
        "VARCHAR(20) NOT NULL DEFAULT 'pending'",
    )
    _add_column_if_missing("submission_records", "validation_errors", "TEXT")
    _add_column_if_missing("submission_records", "cms_status", "VARCHAR(20)")
    _add_column_if_missing("submission_records", "cms_error_code", "VARCHAR(20)")
    _add_column_if_missing("submission_records", "cms_error_message", "TEXT")
    _add_column_if_missing("submission_records", "payment_amount", "DECIMAL(14,2)")
    _add_column_if_missing("submission_records", "risk_score_adj", "DECIMAL(10,4)")
    _add_column_if_missing(
        "submission_records",
        "created_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    )
    if _column_exists("submission_records", "status"):
        _execute(
            """
            UPDATE submission_records
            SET validation_status = COALESCE(
                NULLIF(validation_status, ''),
                CASE
                    WHEN status IN ('invalid', 'warning', 'valid') THEN status
                    ELSE 'pending'
                END
            )
            WHERE validation_status IS NULL OR validation_status = ''
            """
        )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS submission_responses (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            record_id   INT NOT NULL,
            response_json TEXT,
            received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_record (record_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("submission_responses", "batch_id", "VARCHAR(64)")
    _add_column_if_missing("submission_responses", "response_type", "VARCHAR(20)")
    _add_column_if_missing("submission_responses", "file_name", "VARCHAR(500)")
    _add_column_if_missing("submission_responses", "raw_content", "MEDIUMTEXT")
    _add_column_if_missing(
        "submission_responses",
        "parsed_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    )
    _add_column_if_missing("submission_responses", "accepted_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_responses", "rejected_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_responses", "duplicate_count", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_responses", "total_payment", "DECIMAL(14,2)")
    _add_column_if_missing("submission_responses", "notes", "TEXT")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS submission_schedule (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            cron_expr   VARCHAR(50) NOT NULL,
            is_active   TINYINT(1) NOT NULL DEFAULT 1,
            last_run    DATETIME,
            next_run    DATETIME,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _add_column_if_missing("submission_schedule", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT '1'")
    _add_column_if_missing("submission_schedule", "payment_year", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing("submission_schedule", "sweep_type", "VARCHAR(20)")
    _add_column_if_missing("submission_schedule", "deadline_date", "DATE")
    _add_column_if_missing("submission_schedule", "description", "TEXT")
    _add_column_if_missing("submission_schedule", "is_custom", "TINYINT(1) NOT NULL DEFAULT 0")
    _add_column_if_missing(
        "submission_schedule",
        "updated_at",
        "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    )


@register("provider_attestations")
def _attestation_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS provider_attestations (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            patient_id              INT NOT NULL,
            encounter_id            INT,
            hcc_code                VARCHAR(20) NOT NULL,
            hcc_description         VARCHAR(500) DEFAULT '',
            icd10_code              VARCHAR(20) NOT NULL,
            icd10_description       VARCHAR(500) DEFAULT '',
            source                  VARCHAR(20) DEFAULT 'suspect',
            provider_npi            VARCHAR(10),
            provider_user_id        INT,
            batch_id                INT,
            status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
            attestation_type        VARCHAR(30),
            reject_reason           TEXT,
            deferred_until          DATE,
            clinical_justification  TEXT,
            evidence_references     JSON,
            signature_hash          VARCHAR(128),
            attested_at             DATETIME,
            ip_address              VARCHAR(45),
            user_agent              VARCHAR(500),
            tenant_id               VARCHAR(100) DEFAULT 'default',
            created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_pa_patient (patient_id),
            INDEX idx_pa_provider (provider_user_id),
            INDEX idx_pa_status (status),
            INDEX idx_pa_tenant (tenant_id),
            INDEX idx_pa_npi (provider_npi),
            INDEX idx_pa_batch (batch_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS attestation_batches (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            provider_npi        VARCHAR(10),
            provider_user_id    INT,
            total_conditions    INT DEFAULT 0,
            attested_count      INT DEFAULT 0,
            rejected_count      INT DEFAULT 0,
            deferred_count      INT DEFAULT 0,
            status              VARCHAR(20) NOT NULL DEFAULT 'in_progress',
            tenant_id           VARCHAR(100) DEFAULT 'default',
            started_at          DATETIME,
            completed_at        DATETIME,
            created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_ab_provider (provider_user_id),
            INDEX idx_ab_status (status),
            INDEX idx_ab_tenant (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS attestation_reminders (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            attestation_id      INT NOT NULL,
            reminder_type       VARCHAR(20) NOT NULL DEFAULT 'in_app',
            sent_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ar_attestation (attestation_id),
            INDEX idx_ar_type_sent (reminder_type, sent_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("awv_schedules")
def _awv_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS awv_schedules (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            patient_id              INT NOT NULL,
            tenant_id               VARCHAR(100) DEFAULT 'default',
            schedule_year           INT NOT NULL,
            provider_npi            VARCHAR(10),
            status                  VARCHAR(30) NOT NULL DEFAULT 'eligible',
            visit_type              VARCHAR(30),
            eligibility_date        DATE,
            scheduled_date          DATETIME,
            completed_date          DATE,
            location                VARCHAR(255),
            notes                   TEXT,
            decline_reason          VARCHAR(255),
            outreach_attempts       INT NOT NULL DEFAULT 0,
            last_outreach_date      DATE,
            hcc_gaps_to_review      JSON,
            estimated_raf_impact    DECIMAL(10,4),
            created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_awv_patient_year (patient_id, schedule_year),
            INDEX idx_awv_tenant (tenant_id),
            INDEX idx_awv_year (schedule_year),
            INDEX idx_awv_status (status),
            INDEX idx_awv_provider (provider_npi)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS awv_visit_results (
            id                          INT AUTO_INCREMENT PRIMARY KEY,
            awv_id                      INT NOT NULL,
            conditions_reviewed         INT DEFAULT 0,
            conditions_confirmed        INT DEFAULT 0,
            new_conditions_identified   INT DEFAULT 0,
            hcc_codes_captured          JSON,
            raf_score_before            DECIMAL(10,4),
            raf_score_after             DECIMAL(10,4),
            notes                       TEXT,
            created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_avr_awv (awv_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS awv_outreach_log (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            awv_id          INT NOT NULL,
            method          VARCHAR(20) NOT NULL,
            outcome         VARCHAR(30) NOT NULL,
            contact_date    DATETIME,
            contacted_by    INT,
            notes           TEXT,
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_aol_awv (awv_id),
            INDEX idx_aol_date (contact_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS awv_checklists (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            awv_id              INT NOT NULL,
            checklist_type      VARCHAR(30) NOT NULL,
            item_name           VARCHAR(255) NOT NULL,
            item_description    TEXT,
            completed           TINYINT(1) NOT NULL DEFAULT 0,
            completed_by        INT,
            completed_at        DATETIME,
            created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ac_awv (awv_id),
            INDEX idx_ac_type (checklist_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("clearinghouse_tables")
def _clearinghouse_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS clearinghouse_connections (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            tenant_id               VARCHAR(100) DEFAULT 'default',
            name                    VARCHAR(255) NOT NULL,
            vendor                  VARCHAR(30) DEFAULT 'custom',
            api_base_url            VARCHAR(512),
            api_key_encrypted       TEXT,
            api_secret_encrypted    TEXT,
            sender_id               VARCHAR(50),
            receiver_id             VARCHAR(50),
            submitter_id            VARCHAR(50),
            status                  VARCHAR(20) NOT NULL DEFAULT 'testing',
            test_mode               TINYINT(1) NOT NULL DEFAULT 1,
            transaction_count       INT NOT NULL DEFAULT 0,
            last_transaction_at     DATETIME,
            created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cc_name_tenant (name, tenant_id),
            INDEX idx_cc_tenant (tenant_id),
            INDEX idx_cc_vendor (vendor),
            INDEX idx_cc_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS eligibility_checks (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            tenant_id               VARCHAR(100) DEFAULT 'default',
            connection_id           INT,
            patient_id              INT,
            patient_name            VARCHAR(255),
            patient_dob             VARCHAR(10),
            member_id               VARCHAR(100),
            payer_id                VARCHAR(20),
            payer_name              VARCHAR(255),
            service_type            VARCHAR(30) DEFAULT 'health_benefit_plan',
            check_date              DATE,
            status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
            request_payload         LONGTEXT,
            response_payload        LONGTEXT,
            is_eligible             TINYINT(1),
            coverage_start          DATE,
            coverage_end            DATE,
            plan_name               VARCHAR(255),
            plan_number             VARCHAR(50),
            copay                   DECIMAL(10,2),
            coinsurance             DECIMAL(5,2),
            deductible              DECIMAL(10,2),
            deductible_remaining    DECIMAL(10,2),
            out_of_pocket_max       DECIMAL(10,2),
            medicare_part           VARCHAR(10),
            raf_relevant_info       JSON,
            error_message           TEXT,
            response_time_ms        INT,
            created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ec_tenant (tenant_id),
            INDEX idx_ec_connection (connection_id),
            INDEX idx_ec_patient (patient_id),
            INDEX idx_ec_payer (payer_id),
            INDEX idx_ec_status (status),
            INDEX idx_ec_date (check_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS eligibility_batch (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            tenant_id           VARCHAR(100) DEFAULT 'default',
            connection_id       INT,
            name                VARCHAR(255),
            total_checks        INT DEFAULT 0,
            completed           INT DEFAULT 0,
            failed              INT DEFAULT 0,
            status              VARCHAR(20) NOT NULL DEFAULT 'queued',
            created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_eb_tenant (tenant_id),
            INDEX idx_eb_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("coder_worklist_tables")
def _coder_worklist_tables() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS coder_worklist (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            tenant_id           VARCHAR(100) DEFAULT 'default',
            coder_user_id       INT NOT NULL,
            patient_id          INT NOT NULL,
            encounter_id        INT,
            review_type         VARCHAR(30) DEFAULT 'suspect_review',
            source              VARCHAR(20) DEFAULT 'manual',
            priority            INT NOT NULL DEFAULT 3,
            status              VARCHAR(20) NOT NULL DEFAULT 'queued',
            assigned_at         DATETIME,
            started_at          DATETIME,
            completed_at        DATETIME,
            due_date            DATE,
            hcc_codes           JSON,
            notes               TEXT,
            created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_cw_tenant (tenant_id),
            INDEX idx_cw_coder (coder_user_id),
            INDEX idx_cw_status (status),
            INDEX idx_cw_patient (patient_id),
            INDEX idx_cw_priority (priority)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS coder_worklist_actions (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            worklist_id     INT NOT NULL,
            user_id         INT NOT NULL,
            action          VARCHAR(30) NOT NULL,
            details         JSON,
            created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_cwa_worklist (worklist_id),
            INDEX idx_cwa_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS coder_productivity (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            coder_user_id       INT NOT NULL,
            tenant_id           VARCHAR(100) DEFAULT 'default',
            date                DATE NOT NULL,
            reviews_completed   INT NOT NULL DEFAULT 0,
            avg_time_minutes    DECIMAL(8,2),
            accuracy_rate       DECIMAL(5,4),
            created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_cp_coder_date (coder_user_id, tenant_id, date),
            INDEX idx_cp_coder (coder_user_id),
            INDEX idx_cp_tenant (tenant_id),
            INDEX idx_cp_date (date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("raf_coding_corrections")
def _retraining_table() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS raf_coding_corrections (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            patient_id  INT NOT NULL,
            encounter_id INT,
            hcc_code    VARCHAR(20),
            icd10_code  VARCHAR(20),
            original_value VARCHAR(100),
            corrected_value VARCHAR(100),
            corrected_by INT,
            reason      TEXT,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_patient (patient_id),
            INDEX idx_hcc (hcc_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("raf_encounter_analysis")
def _create_raf_encounter_analysis():
    _execute(
        """
        CREATE TABLE IF NOT EXISTS raf_encounter_analysis (
            id                    INT AUTO_INCREMENT PRIMARY KEY,
            encounter_id          INT NOT NULL,
            pid                   INT NOT NULL,
            analysis_json         JSON,
            overall_score         DECIMAL(6,4),
            dx_count              INT DEFAULT 0,
            suspect_count         INT DEFAULT 0,
            hcc_opportunity_count INT DEFAULT 0,
            routing               VARCHAR(50),
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
            patient_id            INT GENERATED ALWAYS AS (pid) STORED,
            analyzed_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_encounter (encounter_id),
            INDEX idx_pid (pid),
            INDEX idx_patient_id (patient_id),
            INDEX idx_analyzed_at (analyzed_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    # Ensure columns exist if table was created before they were added
    for col, defn in [
        ("analysis_json", "JSON"),
        ("dx_count", "INT DEFAULT 0"),
        ("suspect_count", "INT DEFAULT 0"),
        ("routing", "VARCHAR(50)"),
        ("pid", "INT"),
    ]:
        try:
            _execute(f"ALTER TABLE raf_encounter_analysis ADD COLUMN {col} {defn}")
        except Exception:
            pass


@register("emr_sync_log_sync_id")
def _add_sync_id_to_emr_sync_log():
    _add_column_if_missing("emr_sync_log", "sync_id", "VARCHAR(36) AFTER id")


@register("dashboard_alerts")
def _create_dashboard_alerts():
    _execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_alerts (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            alert_type  VARCHAR(50) NOT NULL,
            severity    VARCHAR(20) DEFAULT 'info',
            title       VARCHAR(255),
            message     TEXT,
            patient_id  INT,
            provider_npi VARCHAR(20),
            metadata    JSON,
            is_read     TINYINT(1) NOT NULL DEFAULT 0,
            user_id     INT,
            tenant_id   VARCHAR(50),
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user_tenant (user_id, tenant_id),
            INDEX idx_read (is_read)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("raf_scores_tenant_id")
def _raf_scores_tenant_id() -> None:
    """Add tenant_id to raf_scores, raf_patient_hcc, and raf_patient_demographics."""
    _add_column_if_missing("raf_scores", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT '1'")
    _add_column_if_missing("raf_patient_hcc", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT '1'")
    _add_column_if_missing("raf_patient_demographics", "tenant_id", "VARCHAR(50) NOT NULL DEFAULT '1'")



@register("password_history")
def _password_history_table() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS password_history (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            user_id       INT NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ph_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


@register("attestation_history")
def _attestation_history_table() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS attestation_history (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            attestation_id   INT NOT NULL,
            previous_status  VARCHAR(30),
            new_status       VARCHAR(30) NOT NULL,
            changed_by       INT,
            change_reason    TEXT,
            snapshot         JSON,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ah_attestation (attestation_id),
            INDEX idx_ah_changed_by (changed_by)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


# ---------------------------------------------------------------------------
# Post-migration: constraints and indexes
# ---------------------------------------------------------------------------


def _add_constraints_and_indexes() -> None:
    """
    Idempotent pass that adds composite indexes, missing updated_at columns,
    unique constraints, and CHECK constraints that cannot be expressed inline
    in the CREATE TABLE statements (e.g. because the table already existed).

    Every statement is wrapped in its own try/except so a pre-existing
    constraint or index never aborts the rest of the run.
    """
    from app.db import raf_cursor  # local import keeps module importable without DB

    # ------------------------------------------------------------------
    # 1. Composite indexes for high-traffic query patterns
    # ------------------------------------------------------------------
    _composite_indexes = [
        ("idx_cohort_members_active",    "cohort_members",        "(cohort_id, is_active)"),
        ("idx_care_gap_patient_status",  "care_gap_tasks",        "(patient_id, status)"),
        ("idx_care_gap_tenant_status",   "care_gap_tasks",        "(tenant_id, status, priority)"),
        ("idx_attestation_status_date",  "provider_attestations", "(status, created_at)"),
        ("idx_claims_diag_pid",          "claims_diagnoses",      "(openemr_pid, icd10_code)"),
        ("idx_provider_panel_patient",   "provider_patient_panel","(patient_id)"),
        ("idx_audit_resource",           "audit_log",             "(resource_type, resource_id)"),
        ("idx_webhook_delivery_status",  "webhook_deliveries",    "(webhook_id, status)"),
        ("idx_attestation_reminder_aid", "attestation_reminders", "(attestation_id, reminder_type, sent_at)"),
    ]
    for idx_name, tbl, cols in _composite_indexes:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.statistics "
                    "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s LIMIT 1",
                    (tbl, idx_name),
                )
                if cur.fetchone():
                    continue
                cur.execute(f"CREATE INDEX {idx_name} ON {tbl}{cols}")
            logger.debug("index applied: %s", idx_name)
        except Exception as exc:
            logger.warning("composite index %s skipped: %s", idx_name, exc)

    # ------------------------------------------------------------------
    # 2. Missing updated_at columns
    # ------------------------------------------------------------------
    _updated_at_tables = [
        "care_gap_comments",
        "care_gap_history",
        "document_analysis",
        "document_diagnosis_lines",
        "emr_patient_matches",
        "claims_diagnoses",
        "dashboard_alerts",
        "attestation_reminders",
    ]
    for tbl in _updated_at_tables:
        try:
            _add_column_if_missing(
                tbl,
                "updated_at",
                "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
            )
        except Exception as exc:
            logger.warning("updated_at column skipped for %s: %s", tbl, exc)

    # ------------------------------------------------------------------
    # 3. Unique constraints
    # ------------------------------------------------------------------

    # 3a. cohort_members(cohort_id, patient_id)
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'cohort_members' AND index_name = 'uq_cohort_member' LIMIT 1"
            )
            if not cur.fetchone():
                cur.execute("CREATE UNIQUE INDEX uq_cohort_member ON cohort_members(cohort_id, patient_id)")
    except Exception as exc:
        logger.warning("unique index uq_cohort_member skipped: %s", exc)

    # 3b. emr_patient_matches — backfill all columns written by the FHIR adapter
    try:
        _add_column_if_missing("emr_patient_matches", "first_name", "VARCHAR(100)")
    except Exception as exc:
        logger.warning("column first_name on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "last_name", "VARCHAR(100)")
    except Exception as exc:
        logger.warning("column last_name on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "date_of_birth", "DATE")
    except Exception as exc:
        logger.warning("column date_of_birth on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "sex", "CHAR(1)")
    except Exception as exc:
        logger.warning("column sex on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "mrn", "VARCHAR(50)")
    except Exception as exc:
        logger.warning("column mrn on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "match_status", "VARCHAR(20) DEFAULT 'auto'")
    except Exception as exc:
        logger.warning("column match_status on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "tenant_id", "INT")
    except Exception as exc:
        logger.warning("column tenant_id on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "raf_patient_id", "INT")
    except Exception as exc:
        logger.warning("column raf_patient_id on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "emr_connection_id", "INT")
    except Exception as exc:
        logger.warning("column emr_connection_id on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "emr_patient_id", "VARCHAR(255)")
    except Exception as exc:
        logger.warning("column emr_patient_id on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "patient_id", "INT DEFAULT 0")
    except Exception as exc:
        logger.warning("column patient_id on emr_patient_matches skipped: %s", exc)
    try:
        _add_column_if_missing("emr_patient_matches", "connection_id", "INT")
    except Exception as exc:
        logger.warning("column connection_id on emr_patient_matches skipped: %s", exc)
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'emr_patient_matches' AND index_name = 'uq_emr_match' LIMIT 1"
            )
            if not cur.fetchone():
                cur.execute("CREATE UNIQUE INDEX uq_emr_match ON emr_patient_matches(connection_id, emr_pid)")
    except Exception as exc:
        logger.warning("unique index uq_emr_match skipped: %s", exc)

    # 3c. providers(npi) — only when npi is NOT NULL for every existing row
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name    = 'providers'
                  AND index_name    = 'uq_provider_npi'
                LIMIT 1
                """
            )
            already_exists = cur.fetchone() is not None
        if not already_exists:
            with raf_cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM providers WHERE npi IS NULL")
                row = cur.fetchone()
                null_npi_count = row["cnt"] if row else 0
            if null_npi_count == 0:
                _execute(
                    "CREATE UNIQUE INDEX uq_provider_npi ON providers(npi)"
                )
            else:
                logger.info(
                    "uq_provider_npi skipped: %d provider row(s) have NULL npi",
                    null_npi_count,
                )
    except Exception as exc:
        logger.warning("unique index uq_provider_npi skipped: %s", exc)

    # 3d. patients(tenant_id, emr_pid, emr_connection_id) — prevents
    #      duplicate patients created by repeated FHIR sync runs.
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'patients' "
                "AND index_name = 'uq_patients_tenant_emrpid_conn' LIMIT 1"
            )
            if not cur.fetchone():
                # Remove duplicates first (keep highest id per group)
                cur.execute(
                    """
                    DELETE p1 FROM patients p1
                    INNER JOIN patients p2
                    ON  p1.tenant_id         = p2.tenant_id
                    AND p1.emr_pid           = p2.emr_pid
                    AND p1.emr_connection_id = p2.emr_connection_id
                    AND p1.id < p2.id
                    WHERE p1.emr_pid IS NOT NULL
                      AND p1.emr_pid != ''
                      AND p1.emr_connection_id IS NOT NULL
                    """
                )
                cur.execute(
                    "CREATE UNIQUE INDEX uq_patients_tenant_emrpid_conn "
                    "ON patients (tenant_id, emr_pid, emr_connection_id)"
                )
    except Exception as exc:
        logger.warning("unique index uq_patients_tenant_emrpid_conn skipped: %s", exc)

    # ------------------------------------------------------------------
    # 4. CHECK constraint on care_gap_tasks.priority (MySQL 8.0.16+)
    #    MySQL does not support IF NOT EXISTS on constraints, so we
    #    check information_schema first.
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE constraint_schema = DATABASE()
                  AND table_name        = 'care_gap_tasks'
                  AND constraint_name   = 'chk_priority'
                  AND constraint_type   = 'CHECK'
                LIMIT 1
                """
            )
            chk_exists = cur.fetchone() is not None
        if not chk_exists:
            _execute(
                "ALTER TABLE care_gap_tasks"
                " ADD CONSTRAINT chk_priority"
                " CHECK (priority IN ('low','medium','high','critical'))"
            )
    except Exception as exc:
        logger.warning("CHECK constraint chk_priority skipped: %s", exc)

    # ------------------------------------------------------------------
    # 5. Additional single-column indexes for FK / lookup performance
    # ------------------------------------------------------------------
    _extra_indexes = [
        ("idx_provider_panel_patient_id", "provider_patient_panel", "(patient_id)"),
        ("idx_claims_records_provider_npi", "claims_records", "(provider_npi)"),
        ("idx_claims_records_member_id",   "claims_records", "(member_id)"),
        ("idx_care_gap_tasks_provider_id", "care_gap_tasks", "(provider_id)"),
    ]
    for idx_name, tbl, cols in _extra_indexes:
        try:
            with raf_cursor() as cur:
                # Verify the table exists first
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = %s LIMIT 1",
                    (tbl,),
                )
                if not cur.fetchone():
                    continue
                cur.execute(
                    "SELECT 1 FROM information_schema.statistics "
                    "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s LIMIT 1",
                    (tbl, idx_name),
                )
                if cur.fetchone():
                    continue
                cur.execute(f"CREATE INDEX {idx_name} ON {tbl}{cols}")
            logger.debug("extra index applied: %s", idx_name)
        except Exception as exc:
            logger.warning("extra index %s skipped: %s", idx_name, exc)

    # ------------------------------------------------------------------
    # 6. Foreign keys — only add when both tables exist and no FK already
    # ------------------------------------------------------------------
    def _table_exists(name: str) -> bool:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = %s LIMIT 1",
                    (name,),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def _fk_exists(table: str, column: str) -> bool:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE table_schema = DATABASE() AND table_name = %s "
                    "AND column_name = %s AND referenced_table_name IS NOT NULL LIMIT 1",
                    (table, column),
                )
                return cur.fetchone() is not None
        except Exception:
            return True  # err on the side of NOT adding

    # Pick whichever patients table exists
    _patients_tbl = None
    for cand in ("raf_patient_demographics", "patients"):
        if _table_exists(cand):
            _patients_tbl = cand
            break

    _fk_specs = [
        ("cohort_members", "cohort_id", "cohorts", "id", "fk_cohort_members_cohort"),
        ("cohort_members", "patient_id", _patients_tbl, "patient_id", "fk_cohort_members_patient"),
        ("claims_records", "batch_id", "claims_batches", "id", "fk_claims_records_batch"),
    ]
    for child_tbl, child_col, parent_tbl, parent_col, fk_name in _fk_specs:
        if not parent_tbl:
            logger.info("FK %s skipped: parent table missing", fk_name)
            continue
        if not (_table_exists(child_tbl) and _table_exists(parent_tbl)):
            logger.info("FK %s skipped: table(s) missing", fk_name)
            continue
        if _fk_exists(child_tbl, child_col):
            continue
        try:
            _execute(
                f"ALTER TABLE {child_tbl} ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY ({child_col}) REFERENCES {parent_tbl}({parent_col}) "
                f"ON DELETE CASCADE"
            )
            logger.info("FK applied: %s", fk_name)
        except Exception as exc:
            logger.warning("FK %s skipped (likely orphaned data): %s", fk_name, exc)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all_migrations() -> dict[str, str]:
    """DEPRECATED: no-op shim retained for legacy callers.

    Schema changes must go through Alembic (``alembic upgrade head`` from
    the ``backend/`` directory). Calling this function now emits a
    ``DeprecationWarning`` and returns an empty result dict without
    executing any DDL.
    """
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
    logger.warning(
        "run_all_migrations() called but is deprecated and a no-op — "
        "use Alembic migrations instead."
    )
    return {}
