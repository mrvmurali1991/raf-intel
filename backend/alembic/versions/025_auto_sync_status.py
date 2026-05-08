"""Add auto_sync_status table for polling loop health tracking.

Revision ID: 025_auto_sync_status
Revises: 024_suspect_override_columns
Create Date: 2026-05-08

Changes:
  Creates auto_sync_status table with columns:
    id              INT PK AUTO_INCREMENT
    last_run_at     DATETIME NULL — UTC timestamp of the last completed cycle
    new_patients    INT NOT NULL DEFAULT 0 — count of new patients found in last cycle
    errors_json     TEXT NULL — JSON array of per-patient error strings from last cycle
    duration_ms     INT NULL — wall-clock milliseconds for the last cycle

  Only ever has a single row (id=1); INSERT … ON DUPLICATE KEY UPDATE is used.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "025_auto_sync_status"
down_revision: Union[str, None] = "024_suspect_override_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    if not _table_exists("auto_sync_status"):
        _x(
            """
            CREATE TABLE `auto_sync_status` (
                `id`            INT          NOT NULL AUTO_INCREMENT,
                `last_run_at`   DATETIME     NULL     COMMENT 'UTC timestamp of last completed cycle',
                `new_patients`  INT          NOT NULL DEFAULT 0,
                `errors_json`   TEXT         NULL     COMMENT 'JSON array of per-patient error strings',
                `duration_ms`   INT          NULL     COMMENT 'Wall-clock ms for the last cycle',
                PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def downgrade() -> None:
    if _table_exists("auto_sync_status"):
        _x("DROP TABLE `auto_sync_status`")
