"""Add hie_patient_matches and hie_queries_log tables for HIE network integration.

Revision ID: 044_hie_queries
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

CommonWell and Carequality HIE adapter persistence layer.
Tracks patient demographic matches and all queries made to HIE networks for
audit, deduplication, and performance monitoring.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044_hie_queries"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return insp.has_table(table)


def upgrade() -> None:
    if not _table_exists("hie_patient_matches"):
        op.execute(
            sa.text(
                """
                CREATE TABLE hie_patient_matches (
                    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id        VARCHAR(64)     NOT NULL,
                    raf_patient_id   INT             NOT NULL,
                    network          ENUM('commonwell','carequality','other') NOT NULL,
                    hie_patient_id   VARCHAR(128)    NOT NULL,
                    confidence       DECIMAL(5,4)    NOT NULL DEFAULT 0.0000,
                    matched_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_queried_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    document_count   INT             NOT NULL DEFAULT 0,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_hie_match (tenant_id, raf_patient_id, network, hie_patient_id),
                    INDEX idx_hpm_tenant_patient (tenant_id, raf_patient_id),
                    INDEX idx_hpm_network        (network),
                    INDEX idx_hpm_queried        (last_queried_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        )

    if not _table_exists("hie_queries_log"):
        op.execute(
            sa.text(
                """
                CREATE TABLE hie_queries_log (
                    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id           VARCHAR(64)     NOT NULL,
                    network             ENUM('commonwell','carequality','other') NOT NULL,
                    raf_patient_id      INT             NOT NULL,
                    query_type          VARCHAR(64)     NOT NULL
                                            COMMENT 'discover_patient|list_document_references|fetch_binary',
                    status              VARCHAR(32)     NOT NULL
                                            COMMENT 'success|error',
                    latency_ms          INT             NOT NULL DEFAULT 0,
                    documents_returned  INT             NOT NULL DEFAULT 0,
                    error_text          VARCHAR(500)    NULL,
                    queried_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_hql_tenant_patient (tenant_id, raf_patient_id),
                    INDEX idx_hql_network        (network),
                    INDEX idx_hql_queried_at     (queried_at),
                    INDEX idx_hql_status         (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        )


def downgrade() -> None:
    if _table_exists("hie_queries_log"):
        op.execute(sa.text("DROP TABLE hie_queries_log"))
    if _table_exists("hie_patient_matches"):
        op.execute(sa.text("DROP TABLE hie_patient_matches"))
