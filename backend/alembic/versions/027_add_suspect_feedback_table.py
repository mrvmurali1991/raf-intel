"""Add suspect_feedback table for clinician AI feedback.

Revision ID: 027_add_suspect_feedback_table
Revises: 026_auto_sync_observability
Create Date: 2026-05-16

Changes:
  suspect_feedback (new table):
    id          INT PK AUTO_INCREMENT
    suspect_id  VARCHAR(64) NOT NULL   — raf_suspect_conditions.id (string form)
    tenant_id   INT NOT NULL
    user_id     INT NOT NULL
    sentiment   ENUM('helpful','incorrect','irrelevant') NOT NULL
    comment     TEXT NULL
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    INDEX idx_tenant_suspect (tenant_id, suspect_id)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027_add_suspect_feedback_table"
down_revision: Union[str, None] = "026_auto_sync_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    if not _table_exists("suspect_feedback"):
        _x(
            """
            CREATE TABLE `suspect_feedback` (
                `id`         INT          NOT NULL AUTO_INCREMENT,
                `suspect_id` VARCHAR(64)  NOT NULL COMMENT 'raf_suspect_conditions.id',
                `tenant_id`  INT          NOT NULL,
                `user_id`    INT          NOT NULL,
                `sentiment`  ENUM('helpful','incorrect','irrelevant') NOT NULL,
                `comment`    TEXT         NULL,
                `created_at` TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                INDEX `idx_tenant_suspect` (`tenant_id`, `suspect_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='Clinician thumbs-up/down feedback on AI-generated suspect conditions'
            """
        )


def downgrade() -> None:
    if _table_exists("suspect_feedback"):
        _x("DROP TABLE `suspect_feedback`")
