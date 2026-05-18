"""Add ehr_writeback_queue table for Problem List write-back intents.

Revision ID: 052_ehr_writeback_queue
Revises: 050_metrics_cache
Create Date: 2026-05-18

Queues provider-attested HCC conditions for async SMART-on-FHIR
Condition resource write-back to the patient's EHR Problem List.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052_ehr_writeback_queue"
down_revision: Union[str, None] = "050_metrics_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("ehr_writeback_queue"):
        return
    op.execute(
        sa.text(
            """
            CREATE TABLE ehr_writeback_queue (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                tenant_id       VARCHAR(64)  NOT NULL,
                patient_id      INT          NOT NULL,
                icd10           VARCHAR(16)  NOT NULL,
                hcc_code        VARCHAR(16)  NULL,
                evidence_text   TEXT         NULL,
                attested_by     VARCHAR(255) NULL,
                attested_at     DATETIME     NULL,
                status          ENUM('queued','sent','failed') NOT NULL DEFAULT 'queued',
                last_attempt_at DATETIME     NULL,
                error_detail    TEXT         NULL,
                created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                             ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_ewq_tenant_status (tenant_id, status),
                INDEX idx_ewq_patient       (patient_id),
                INDEX idx_ewq_created       (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("ehr_writeback_queue"):
        op.drop_table("ehr_writeback_queue")
