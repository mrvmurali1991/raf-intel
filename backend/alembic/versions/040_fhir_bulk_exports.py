"""Add fhir_bulk_exports and fhir_bulk_export_files tables.

Revision ID: 040_fhir_bulk_exports
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

Tracks SMART Bulk Data $export lifecycle: kickoff, polling, manifest storage,
per-file download status, and resource counts for auditing and re-processing.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "040_fhir_bulk_exports"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not insp.has_table("fhir_bulk_exports"):
        op.execute(
            sa.text(
                """
                CREATE TABLE fhir_bulk_exports (
                    id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id        VARCHAR(64)  NOT NULL,
                    ehr_id           INT          NOT NULL,
                    kickoff_url      TEXT         NOT NULL,
                    polling_url      TEXT         NULL,
                    status           ENUM('queued','in_progress','complete','failed')
                                     NOT NULL DEFAULT 'queued',
                    started_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at     DATETIME     NULL,
                    manifest_json    LONGTEXT     NULL,
                    error            TEXT         NULL,
                    resources_count  INT          NULL,
                    since_iso        DATETIME     NULL,
                    group_id         VARCHAR(128) NULL,
                    PRIMARY KEY (id),
                    INDEX idx_fbe_tenant_status (tenant_id, status),
                    INDEX idx_fbe_ehr_id (ehr_id),
                    INDEX idx_fbe_started_at (started_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        )

    if not insp.has_table("fhir_bulk_export_files"):
        op.execute(
            sa.text(
                """
                CREATE TABLE fhir_bulk_export_files (
                    id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    export_id           INT UNSIGNED NOT NULL,
                    resource_type       VARCHAR(64)  NOT NULL,
                    output_url          TEXT         NOT NULL,
                    ndjson_size_bytes   BIGINT       NULL,
                    rows_count          INT          NULL,
                    downloaded_at       DATETIME     NULL,
                    processed           TINYINT(1)   NOT NULL DEFAULT 0,
                    PRIMARY KEY (id),
                    INDEX idx_fbef_export_id (export_id),
                    INDEX idx_fbef_processed (processed),
                    CONSTRAINT fk_fbef_export
                        FOREIGN KEY (export_id)
                        REFERENCES fhir_bulk_exports (id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("fhir_bulk_export_files"):
        op.execute(sa.text("DROP TABLE fhir_bulk_export_files"))
    if insp.has_table("fhir_bulk_exports"):
        op.execute(sa.text("DROP TABLE fhir_bulk_exports"))
