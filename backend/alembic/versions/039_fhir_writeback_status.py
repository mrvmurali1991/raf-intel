"""Add fhir_writeback_* columns to raf_suspect_conditions for async hand-off.

Revision ID: 039_fhir_writeback_status
Revises: 038_audit_timestamp_tokens
Create Date: 2026-05-18

When `async_writeback=true` on accept, the FHIR Condition POST runs in a
Celery task instead of blocking the accept handler. This migration tracks
the async lifecycle.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "039_fhir_writeback_status"
down_revision: Union[str, None] = "038_audit_timestamp_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("raf_suspect_conditions", "fhir_writeback_status"):
        op.execute(
            sa.text(
                """ALTER TABLE raf_suspect_conditions
                   ADD COLUMN fhir_writeback_status ENUM('pending','sent','failed','reversed') NULL,
                   ADD COLUMN fhir_writeback_attempts INT DEFAULT 0,
                   ADD COLUMN fhir_writeback_last_error VARCHAR(500) NULL,
                   ADD COLUMN fhir_writeback_async_at DATETIME NULL,
                   ADD INDEX idx_rsc_writeback_status (fhir_writeback_status)"""
            )
        )


def downgrade() -> None:
    if _column_exists("raf_suspect_conditions", "fhir_writeback_status"):
        op.execute(
            sa.text(
                """ALTER TABLE raf_suspect_conditions
                   DROP INDEX idx_rsc_writeback_status,
                   DROP COLUMN fhir_writeback_status,
                   DROP COLUMN fhir_writeback_attempts,
                   DROP COLUMN fhir_writeback_last_error,
                   DROP COLUMN fhir_writeback_async_at"""
            )
        )
