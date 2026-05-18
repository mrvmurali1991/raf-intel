"""Add metrics_cache table for persisted last_refreshed_at timestamps.

Revision ID: 050_metrics_cache
Revises: 049_raf_goals
Create Date: 2026-05-18

Provides a metrics_cache table so that _meta.last_computed_at reflects the
actual time the metric was last computed, not the current request time.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "050_metrics_cache"
down_revision: Union[str, None] = "049_raf_goals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("metrics_cache"):
        return
    op.execute(
        sa.text(
            """
            CREATE TABLE metrics_cache (
                id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                tenant_id       VARCHAR(64)  NOT NULL,
                metric_name     VARCHAR(64)  NOT NULL,
                scope           VARCHAR(64)  NOT NULL DEFAULT '',
                payment_year    SMALLINT     NOT NULL,
                value           DOUBLE       NOT NULL,
                last_refreshed_at DATETIME   NOT NULL,
                computed_at     DATETIME     NOT NULL,
                UNIQUE KEY uq_metrics_cache (tenant_id, metric_name, scope, payment_year),
                INDEX idx_mc_tenant (tenant_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("metrics_cache"):
        op.execute(sa.text("DROP TABLE metrics_cache"))
