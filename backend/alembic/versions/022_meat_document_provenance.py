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
import sqlalchemy as sa

revision: str = "022_meat_document_provenance"
down_revision: Union[str, None] = "021_batch1_schema_additions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers (inlined — do not import across migration files)
# ---------------------------------------------------------------------------

def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _index_exists(table: str, index_name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(i["name"] == index_name for i in _inspector().get_indexes(table))


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # A. Provenance columns — each guarded so the migration is safe to
    #    replay on production where columns may already have been added
    #    out-of-band.
    # ------------------------------------------------------------------
    if not _column_exists("raf_meat_evidence", "document_upload_id"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `document_upload_id` BIGINT NULL "
            "COMMENT 'FK hint → raf_data_uploads.id'"
        )
    if not _column_exists("raf_meat_evidence", "document_hash"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `document_hash` VARCHAR(64) NULL "
            "COMMENT 'SHA-256 hex of the source uploaded file'"
        )
    if not _column_exists("raf_meat_evidence", "document_page"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `document_page` INT NULL "
            "COMMENT '1-based page number within the source document (PDFs)'"
        )
    if not _column_exists("raf_meat_evidence", "document_offset_start"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `document_offset_start` INT NULL "
            "COMMENT 'Character/byte start offset of excerpt within source document'"
        )
    if not _column_exists("raf_meat_evidence", "document_offset_end"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `document_offset_end` INT NULL "
            "COMMENT 'Character/byte end offset of excerpt within source document'"
        )
    if not _column_exists("raf_meat_evidence", "context_classification"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `context_classification` VARCHAR(32) NULL "
            "COMMENT 'Document context type e.g. progress_note, discharge, lab'"
        )
    if not _column_exists("raf_meat_evidence", "measurement_year"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `measurement_year` SMALLINT NULL "
            "COMMENT 'Explicit measurement year tag for cross-year evidence joins'"
        )

    # ------------------------------------------------------------------
    # B. Indexes — guarded by both _index_exists and _column_exists so a
    #    partial replay (column added, index not yet) is handled cleanly.
    # ------------------------------------------------------------------
    if (
        not _index_exists("raf_meat_evidence", "idx_rme_doc_hash")
        and _column_exists("raf_meat_evidence", "document_hash")
    ):
        _x(
            "CREATE INDEX `idx_rme_doc_hash` "
            "ON `raf_meat_evidence` (`document_hash`)"
        )

    if (
        not _index_exists("raf_meat_evidence", "idx_rme_upload_ctx")
        and _column_exists("raf_meat_evidence", "document_upload_id")
        and _column_exists("raf_meat_evidence", "context_classification")
    ):
        _x(
            "CREATE INDEX `idx_rme_upload_ctx` "
            "ON `raf_meat_evidence` (`document_upload_id`, `context_classification`)"
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop indexes first (avoids dependency errors).
    drop_idx = [
        "DROP INDEX IF EXISTS idx_rme_doc_hash ON raf_meat_evidence",
        "DROP INDEX IF EXISTS idx_rme_upload_ctx ON raf_meat_evidence",
    ]
    for stmt in drop_idx:
        try:
            op.execute(sa.text(stmt))
        except Exception:
            pass

    # Drop provenance columns — reverse order, each guarded.
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
        op.execute(sa.text(stmt))
