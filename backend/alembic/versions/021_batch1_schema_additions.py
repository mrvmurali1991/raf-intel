"""Batch-1 additive schema changes.

Revision ID: 021_batch1_schema_additions
Revises: 020_raf_scores_audit_columns
Create Date: 2026-04-22

Changes applied (all additive, no DROP/TRUNCATE/RENAME):

A.  raf_patient_hcc — HCC withdrawal tracking columns + composite index.
B.  raf_hcc_withdrawals — new audit table for withdrawal events.
C.  raf_data_uploads — new table; content_hash on claims_batches.
D.  raf_meat_evidence — last_recomputed_at audit column.
E.  immutable_audit_log — new tamper-evident audit table.
F.  phi_access_log — verified tenant_id already present (VARCHAR 50 default 'unknown').
    Added composite index (tenant_id, accessed_at) for tenant-scoped PHI queries.
G.  raf_meat_evidence — composite index (patient_hcc_id, updated_at) for recompute hits.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_batch1_schema_additions"
down_revision: Union[str, None] = "020_raf_scores_audit_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _index_exists(table: str, index_name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(i["name"] == index_name for i in _inspector().get_indexes(table))


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    # ------------------------------------------------------------------
    # A. raf_patient_hcc — withdrawal columns
    # ------------------------------------------------------------------
    if _table_exists("raf_patient_hcc"):
        if not _column_exists("raf_patient_hcc", "is_withdrawn"):
            _x(
                "ALTER TABLE `raf_patient_hcc` "
                "ADD COLUMN `is_withdrawn` TINYINT(1) NOT NULL DEFAULT 0 "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        if not _column_exists("raf_patient_hcc", "withdrawn_at"):
            _x(
                "ALTER TABLE `raf_patient_hcc` "
                "ADD COLUMN `withdrawn_at` DATETIME NULL "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        if not _column_exists("raf_patient_hcc", "withdrawn_reason"):
            _x(
                "ALTER TABLE `raf_patient_hcc` "
                "ADD COLUMN `withdrawn_reason` VARCHAR(500) NULL "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        if not _column_exists("raf_patient_hcc", "withdrawn_by_user_id"):
            _x(
                "ALTER TABLE `raf_patient_hcc` "
                "ADD COLUMN `withdrawn_by_user_id` BIGINT NULL "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        if not _index_exists("raf_patient_hcc", "idx_rphcc_withdraw_filter"):
            _x(
                "ALTER TABLE `raf_patient_hcc` "
                "ADD INDEX `idx_rphcc_withdraw_filter` "
                "(`patient_id`, `hcc_code`, `measurement_year`, `is_withdrawn`) "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )

    # ------------------------------------------------------------------
    # B. raf_hcc_withdrawals — audit table
    # ------------------------------------------------------------------
    if not _table_exists("raf_hcc_withdrawals"):
        _x(
            """
            CREATE TABLE `raf_hcc_withdrawals` (
              `id`                    BIGINT AUTO_INCREMENT PRIMARY KEY,
              `patient_hcc_id`        BIGINT NULL,
              `patient_id`            BIGINT NULL,
              `hcc_code`              VARCHAR(20) NOT NULL,
              `measurement_year`      SMALLINT NOT NULL,
              `rejected_attestation_id` BIGINT NULL,
              `reason`                VARCHAR(500) NULL,
              `withdrawn_by_user_id`  BIGINT NULL,
              `withdrawn_at`          DATETIME DEFAULT CURRENT_TIMESTAMP,
              `tenant_id`             BIGINT NULL,
              INDEX `idx_rhw_patient` (`patient_id`, `measurement_year`),
              INDEX `idx_rhw_tenant`  (`tenant_id`, `withdrawn_at`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

    # ------------------------------------------------------------------
    # C1. raf_data_uploads — create table if missing
    # ------------------------------------------------------------------
    if not _table_exists("raf_data_uploads"):
        _x(
            """
            CREATE TABLE `raf_data_uploads` (
              `id`                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
              `tenant_id`           VARCHAR(50)  NOT NULL DEFAULT 'default',
              `uploaded_by`         INT UNSIGNED NULL,
              `filename`            VARCHAR(512) NOT NULL,
              `file_size_bytes`     BIGINT UNSIGNED NULL,
              `file_type`           VARCHAR(20)  NULL,
              `row_count_total`     INT UNSIGNED NOT NULL DEFAULT 0,
              `row_count_imported`  INT UNSIGNED NOT NULL DEFAULT 0,
              `row_count_failed`    INT UNSIGNED NOT NULL DEFAULT 0,
              `status`              VARCHAR(30)  NOT NULL DEFAULT 'processing',
              `error_summary`       TEXT NULL,
              `content_hash`        CHAR(64)     NULL,
              `completed_at`        DATETIME NULL,
              `created_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `updated_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (`id`),
              KEY `idx_rdu_tenant_created` (`tenant_id`, `created_at`),
              UNIQUE KEY `uq_rdu_tenant_hash` (`tenant_id`, `content_hash`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    else:
        # Table exists — just ensure content_hash and its unique index
        if not _column_exists("raf_data_uploads", "content_hash"):
            _x(
                "ALTER TABLE `raf_data_uploads` "
                "ADD COLUMN `content_hash` CHAR(64) NULL "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        if not _index_exists("raf_data_uploads", "uq_rdu_tenant_hash"):
            _x(
                "ALTER TABLE `raf_data_uploads` "
                "ADD UNIQUE INDEX `uq_rdu_tenant_hash` (`tenant_id`, `content_hash`) "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )

    # ------------------------------------------------------------------
    # C2. claims_batches — content_hash
    # ------------------------------------------------------------------
    if _table_exists("claims_batches"):
        if not _column_exists("claims_batches", "content_hash"):
            _x(
                "ALTER TABLE `claims_batches` "
                "ADD COLUMN `content_hash` CHAR(64) NULL "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        if not _index_exists("claims_batches", "uq_cb_tenant_hash"):
            _x(
                "ALTER TABLE `claims_batches` "
                "ADD UNIQUE INDEX `uq_cb_tenant_hash` (`tenant_id`, `content_hash`) "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )

    # ------------------------------------------------------------------
    # D. raf_meat_evidence — last_recomputed_at
    # ------------------------------------------------------------------
    if _table_exists("raf_meat_evidence"):
        if not _column_exists("raf_meat_evidence", "last_recomputed_at"):
            _x(
                "ALTER TABLE `raf_meat_evidence` "
                "ADD COLUMN `last_recomputed_at` DATETIME NULL "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        # Index for recompute query pattern: WHERE patient_hcc_id = X ORDER BY updated_at
        if not _index_exists("raf_meat_evidence", "idx_rme_hcc_updated"):
            _x(
                "ALTER TABLE `raf_meat_evidence` "
                "ADD INDEX `idx_rme_hcc_updated` (`patient_hcc_id`, `updated_at`) "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )

    # ------------------------------------------------------------------
    # E. immutable_audit_log
    # ------------------------------------------------------------------
    if not _table_exists("immutable_audit_log"):
        _x(
            """
            CREATE TABLE `immutable_audit_log` (
              `id`            BIGINT AUTO_INCREMENT PRIMARY KEY,
              `event_ts`      DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
              `event_type`    VARCHAR(100) NOT NULL,
              `actor_user_id` BIGINT NULL,
              `actor_email`   VARCHAR(255) NULL,
              `tenant_id`     BIGINT NULL,
              `patient_id`    BIGINT NULL,
              `resource`      VARCHAR(255) NULL,
              `action`        VARCHAR(50) NULL,
              `payload_json`  JSON NULL,
              `hash_prev`     CHAR(64) NULL,
              `hash_self`     CHAR(64) NULL,
              INDEX `idx_ial_ts`        (`event_ts`),
              INDEX `idx_ial_tenant_ts` (`tenant_id`, `event_ts`),
              INDEX `idx_ial_patient`   (`patient_id`, `event_ts`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

    # ------------------------------------------------------------------
    # F. phi_access_log — tenant_id already exists (VARCHAR 50 'unknown').
    #    Add composite index for tenant-scoped PHI access queries.
    # ------------------------------------------------------------------
    if _table_exists("phi_access_log"):
        if not _index_exists("phi_access_log", "idx_pal_tenant_accessed"):
            _x(
                "ALTER TABLE `phi_access_log` "
                "ADD INDEX `idx_pal_tenant_accessed` (`tenant_id`, `accessed_at`) "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )


# ---------------------------------------------------------------------------
# downgrade  (safe no-ops — never drop columns in production)
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Intentionally left as no-op.
    # Dropping columns on production requires explicit DBA sign-off.
    pass
