"""Add reveleer_charts_pulled and reveleer_suspects_pushed tables.

Revision ID: 047_reveleer_sync
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

Tracks the bi-directional Reveleer integration:
  - reveleer_charts_pulled: chart metadata for every chart downloaded from Reveleer.
  - reveleer_suspects_pushed: per-suspect push outcome back to Reveleer's queue.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047_reveleer_sync"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return insp.has_table(name)


def upgrade() -> None:
    if not _table_exists("reveleer_charts_pulled"):
        op.execute(
            sa.text(
                """
                CREATE TABLE reveleer_charts_pulled (
                    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    tenant_id       VARCHAR(64)  NOT NULL,
                    reveleer_chart_id VARCHAR(128) NOT NULL,
                    raf_patient_id  INT UNSIGNED NULL,
                    filename        VARCHAR(255) NOT NULL DEFAULT '',
                    mimetype        VARCHAR(64)  NOT NULL DEFAULT 'application/octet-stream',
                    size_bytes      INT UNSIGNED NOT NULL DEFAULT 0,
                    pulled_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    processed       TINYINT      NOT NULL DEFAULT 0,
                    suspects_extracted INT        NOT NULL DEFAULT 0,
                    UNIQUE KEY uq_reveleer_chart_id (reveleer_chart_id),
                    INDEX idx_rcp_tenant_pulled (tenant_id, pulled_at),
                    INDEX idx_rcp_patient (raf_patient_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )

    if not _table_exists("reveleer_suspects_pushed"):
        op.execute(
            sa.text(
                """
                CREATE TABLE reveleer_suspects_pushed (
                    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    tenant_id           VARCHAR(64)  NOT NULL,
                    raf_suspect_id      INT UNSIGNED NOT NULL,
                    pushed_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reveleer_response_id VARCHAR(128) NULL,
                    status              ENUM('success','failed','pending') NOT NULL DEFAULT 'pending',
                    error_text          TEXT NULL,
                    UNIQUE KEY uq_rsp_suspect (raf_suspect_id),
                    INDEX idx_rsp_tenant_pushed (tenant_id, pushed_at),
                    INDEX idx_rsp_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def downgrade() -> None:
    if _table_exists("reveleer_suspects_pushed"):
        op.execute(sa.text("DROP TABLE reveleer_suspects_pushed"))
    if _table_exists("reveleer_charts_pulled"):
        op.execute(sa.text("DROP TABLE reveleer_charts_pulled"))
