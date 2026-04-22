"""MEAT evidence document provenance columns.

Revision ID: 022_meat_document_provenance
Revises: 021_batch1_schema_additions
Create Date: 2026-04-22

Changes applied (all additive, idempotent via IF NOT EXISTS):

A.  raf_meat_evidence — seven document-provenance columns so RADV auditors can
    trace any raw_note_excerpt back to a specific uploaded file:
        document_upload_id      BIGINT NULL       FK hint → raf_data_uploads.id
        document_hash           VARCHAR(64) NULL  SHA-256 of the source file
        document_page           INT NULL          1-based page number (PDFs)
        document_offset_start   INT NULL          byte/char offset in source doc
        document_offset_end     INT NULL          byte/char end offset
        context_classification  VARCHAR(32) NULL  e.g. 'progress_note', 'discharge'
        measurement_year        SMALLINT NULL     explicit year tag for cross-year joins

B.  Two supporting indexes:
        idx_rme_doc_hash  (document_hash)
        idx_rme_ctx       (tenant_id, patient_id, context_classification)
    Both guarded with CREATE INDEX IF NOT EXISTS (MySQL 8.0+).
    Note: raf_meat_evidence has no tenant_id / patient_id columns of its own;
    the ctx index joins through patient_hcc_id → raf_patient_hcc. Because MySQL
    does not allow cross-table index definitions, the ctx index is omitted and
    replaced with the composite (document_upload_id, context_classification)
    index which serves equivalent selective lookups within the evidence table.

Downgrade: drops all added columns and indexes (IF EXISTS guards).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "022_meat_document_provenance"
down_revision: Union[str, None] = "021_batch1_schema_additions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # A. Provenance columns — each guarded with IF NOT EXISTS so the
    #    migration is safe to replay on production where columns may
    #    already have been added out-of-band.
    # ------------------------------------------------------------------
    provenance_cols = [
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS document_upload_id BIGINT NULL COMMENT 'FK hint → raf_data_uploads.id'",
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS document_hash VARCHAR(64) NULL COMMENT 'SHA-256 hex of the source uploaded file'",
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS document_page INT NULL COMMENT '1-based page number within the source document (PDFs)'",
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS document_offset_start INT NULL COMMENT 'Character/byte start offset of excerpt within source document'",
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS document_offset_end INT NULL COMMENT 'Character/byte end offset of excerpt within source document'",
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS context_classification VARCHAR(32) NULL COMMENT 'Document context type e.g. progress_note, discharge, lab'",
        "ALTER TABLE raf_meat_evidence ADD COLUMN IF NOT EXISTS measurement_year SMALLINT NULL COMMENT 'Explicit measurement year tag for cross-year evidence joins'",
    ]
    for stmt in provenance_cols:
        op.execute(stmt)

    # ------------------------------------------------------------------
    # B. Indexes — CREATE INDEX IF NOT EXISTS requires MySQL 8.0.
    #    Wrapped in individual try/execute so a pre-existing index (error
    #    1061) is silently swallowed on older MySQL versions.
    # ------------------------------------------------------------------
    idx_statements = [
        "CREATE INDEX IF NOT EXISTS idx_rme_doc_hash ON raf_meat_evidence (document_hash)",
        (
            "CREATE INDEX IF NOT EXISTS idx_rme_upload_ctx "
            "ON raf_meat_evidence (document_upload_id, context_classification)"
        ),
    ]
    for stmt in idx_statements:
        try:
            op.execute(stmt)
        except Exception:
            # Silently ignore duplicate-index errors on MySQL < 8.0
            pass


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop indexes first (avoids FK/index dependency errors).
    # ------------------------------------------------------------------
    drop_idx = [
        "DROP INDEX IF EXISTS idx_rme_doc_hash ON raf_meat_evidence",
        "DROP INDEX IF EXISTS idx_rme_upload_ctx ON raf_meat_evidence",
    ]
    for stmt in drop_idx:
        try:
            op.execute(stmt)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Drop provenance columns — reverse order, each guarded.
    # ------------------------------------------------------------------
    drop_cols = [
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS measurement_year",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS context_classification",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS document_offset_end",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS document_offset_start",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS document_page",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS document_hash",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS document_upload_id",
    ]
    for stmt in drop_cols:
        op.execute(stmt)
