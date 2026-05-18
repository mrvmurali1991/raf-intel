"""Add radv_chart_requests table for CMS-mandated chart-pull tracking.

Revision ID: 051_chart_requests
Revises: 050_metrics_cache
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051_chart_requests"
down_revision: Union[str, None] = "050_metrics_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("radv_chart_requests"):
        return
    op.execute(
        sa.text(
            """
            CREATE TABLE radv_chart_requests (
                id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                tenant_id       VARCHAR(64)     NOT NULL,
                audit_run_id    BIGINT UNSIGNED NOT NULL,
                patient_id      BIGINT UNSIGNED NOT NULL,
                requested_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status          ENUM('requested','received','coded','disputed','cleared')
                                NOT NULL DEFAULT 'requested',
                provider_id     BIGINT UNSIGNED NULL,
                due_date        DATE            NULL,
                received_at     DATETIME        NULL,
                notes           TEXT            NULL,
                sha256_hash     CHAR(64)        NOT NULL,
                created_by      INT UNSIGNED    NULL,
                updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_rcr_tenant_run   (tenant_id, audit_run_id),
                INDEX idx_rcr_tenant_status (tenant_id, status),
                INDEX idx_rcr_due_date     (due_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("radv_chart_requests"):
        op.execute(sa.text("DROP TABLE radv_chart_requests"))
