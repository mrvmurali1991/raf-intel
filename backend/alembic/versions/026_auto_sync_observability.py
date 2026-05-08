"""Add observability columns to auto_sync_status + create auto_sync_failed_pids table.

Revision ID: 026_auto_sync_observability
Revises: 025_auto_sync_status
Create Date: 2026-05-08

Changes:
  auto_sync_status:
    enabled             TINYINT(1) NOT NULL DEFAULT 1  — pause/resume flag
    total_synced_today  INT NOT NULL DEFAULT 0          — counter reset daily
    current_cycle_at    DATETIME NULL                   — cycle start timestamp (NULL when idle)
    last_error          TEXT NULL                       — last error string

  auto_sync_failed_pids (new table):
    emr_pid     INT PK                — OpenEMR pid that exhausted retries
    failed_at   DATETIME NOT NULL     — when the final failure occurred
    last_error  TEXT NULL             — last error message

  Note: patients is a VIEW over openemr.patient_data; we track failures in a
  separate table rather than modifying the underlying OpenEMR schema.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "026_auto_sync_observability"
down_revision: Union[str, None] = "025_auto_sync_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _col_exists(table: str, col: str) -> bool:
    try:
        return any(c["name"] == col for c in _inspector().get_columns(table))
    except Exception:
        return False


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    # auto_sync_status new columns
    if _table_exists("auto_sync_status"):
        if not _col_exists("auto_sync_status", "enabled"):
            _x("ALTER TABLE `auto_sync_status` ADD COLUMN `enabled` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Loop pause/resume flag'")
        if not _col_exists("auto_sync_status", "total_synced_today"):
            _x("ALTER TABLE `auto_sync_status` ADD COLUMN `total_synced_today` INT NOT NULL DEFAULT 0 COMMENT 'Patients synced since UTC midnight'")
        if not _col_exists("auto_sync_status", "current_cycle_at"):
            _x("ALTER TABLE `auto_sync_status` ADD COLUMN `current_cycle_at` DATETIME NULL COMMENT 'NULL=idle, non-NULL=cycle in progress'")
        if not _col_exists("auto_sync_status", "last_error"):
            _x("ALTER TABLE `auto_sync_status` ADD COLUMN `last_error` TEXT NULL COMMENT 'Last per-patient or cycle error string'")

    # Separate failure-tracking table (patients is a VIEW; cannot add columns)
    if not _table_exists("auto_sync_failed_pids"):
        _x(
            """
            CREATE TABLE `auto_sync_failed_pids` (
                `emr_pid`    INT      NOT NULL,
                `failed_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `last_error` TEXT     NULL,
                PRIMARY KEY (`emr_pid`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='EMR pids that exhausted auto-sync retries — skipped in future cycles'
            """
        )


def downgrade() -> None:
    if _table_exists("auto_sync_status"):
        for col in ("enabled", "total_synced_today", "current_cycle_at", "last_error"):
            if _col_exists("auto_sync_status", col):
                _x(f"ALTER TABLE `auto_sync_status` DROP COLUMN `{col}`")
    if _table_exists("auto_sync_failed_pids"):
        _x("DROP TABLE `auto_sync_failed_pids`")
