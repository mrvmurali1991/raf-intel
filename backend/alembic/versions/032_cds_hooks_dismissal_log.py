"""cds_hooks_dismissal_log

Revision ID: 032_cds_hooks_dismissal_log
Revises: 77cd8ea4ca45
Create Date: 2026-05-17 00:00:00.000000+00:00

Adds cds_hooks_shown table for per-patient/per-suspect dedup and
CDS Hooks 2.0 §5 feedback tracking.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "032_cds_hooks_dismissal_log"
down_revision: Union[str, None] = "77cd8ea4ca45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cds_hooks_shown (
            id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            tenant_id      VARCHAR(64)  NOT NULL,
            patient_id     INT          NOT NULL,
            suspect_id     BIGINT UNSIGNED NOT NULL,
            hook_instance  VARCHAR(128) NOT NULL,
            hook_name      VARCHAR(64)  NOT NULL,
            card_uuid      VARCHAR(64)  NOT NULL DEFAULT '',
            shown_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
            user_npi       VARCHAR(32)  NULL,
            status         ENUM('shown','dismissed','accepted','suppressed_dup') DEFAULT 'shown',
            feedback_reason TEXT         NULL,
            INDEX idx_cds_dedup       (tenant_id, patient_id, suspect_id, shown_at),
            INDEX idx_cds_hookinstance (hook_instance),
            INDEX idx_cds_card_uuid   (card_uuid)
        ) ENGINE=InnoDB
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cds_hooks_shown")
