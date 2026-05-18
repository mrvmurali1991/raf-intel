"""Add raf_hcc_rejections table for two-way HCC review (DOJ-compliant audit chain).

Revision ID: 053_hcc_rejections
Revises: 052_ehr_writeback_queue
Create Date: 2026-05-18

Reveleer 2026 guidance: add-only risk adjustment is a DOJ red flag.
Coders must be able to reject prior-year HCCs after retrospective review,
with an immutable, reason-coded, SHA-256-chained audit record.

Rejected HCCs are excluded from the recapture queue for the payment year
and cannot be re-accepted without a second rejection-of-rejection entry
(audit trail preserved in both directions).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "053_hcc_rejections"
down_revision: Union[str, None] = "052_ehr_writeback_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("raf_hcc_rejections"):
        return
    op.execute(
        sa.text(
            """
            CREATE TABLE raf_hcc_rejections (
                id                     INT AUTO_INCREMENT PRIMARY KEY,
                tenant_id              VARCHAR(64)   NOT NULL,
                patient_id             INT           NOT NULL,
                hcc_code               VARCHAR(16)   NOT NULL,
                payment_year           SMALLINT      NOT NULL,
                rejected_by            INT           NOT NULL COMMENT 'user_id',
                rejected_at            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reason_code            ENUM(
                    'not_supported_in_chart',
                    'incorrect_specificity',
                    'resolved_condition',
                    'documentation_insufficient',
                    'coder_error',
                    'provider_dispute'
                )                                    NOT NULL,
                reason_text            TEXT          NULL     COMMENT 'optional free-form, max 500 chars',
                prior_year_documented  TINYINT(1)    NOT NULL DEFAULT 0,
                sha256_hash            VARCHAR(64)   NOT NULL COMMENT 'SHA-256 of (prev_hash|tenant|patient|hcc|year|reason_code|rejected_at)',
                INDEX idx_hcc_rej_tenant_patient (tenant_id, patient_id),
                INDEX idx_hcc_rej_hcc_year       (hcc_code, payment_year),
                INDEX idx_hcc_rej_rejected_at    (rejected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='Immutable audit record of coder-rejected HCC gaps — DOJ-compliant two-way review.';
            """
        )
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("raf_hcc_rejections"):
        op.drop_table("raf_hcc_rejections")
