"""Add inovalon_patient_pulls and raf_external_observations tables.

Revision ID: 046_inovalon_pulls
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

inovalon_patient_pulls tracks every Electronic Record On Demand pull
request submitted to Inovalon per patient.  inovalon_pull_id carries a
UNIQUE constraint so duplicate pulls are silently skipped.

raf_external_observations stores structured lab/observation data sourced
from external partners (initially Inovalon EROND) for downstream MEAT
enrichment and gap-closure workflows.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046_inovalon_pulls"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return insp.has_table(table)


def upgrade() -> None:
    if not _table_exists("inovalon_patient_pulls"):
        op.execute(
            sa.text(
                """
                CREATE TABLE inovalon_patient_pulls (
                    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id           VARCHAR(64)     NOT NULL,
                    raf_patient_id      BIGINT UNSIGNED NOT NULL,
                    inovalon_pull_id    VARCHAR(128)    NOT NULL,
                    submitted_at        DATETIME        NULL,
                    completed_at        DATETIME        NULL,
                    status              VARCHAR(32)     NOT NULL DEFAULT 'submitted',
                    resources_returned  JSON            NULL,
                    bundle_size_bytes   INT             NULL,
                    error_text          TEXT            NULL,
                    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_inovalon_pull_id (inovalon_pull_id),
                    INDEX idx_inovalon_pulls_tenant_patient
                          (tenant_id, raf_patient_id),
                    INDEX idx_inovalon_pulls_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )

    if not _table_exists("raf_external_observations"):
        op.execute(
            sa.text(
                """
                CREATE TABLE raf_external_observations (
                    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id       VARCHAR(64)     NOT NULL,
                    raf_patient_id  BIGINT UNSIGNED NOT NULL,
                    loinc_code      VARCHAR(32)     NOT NULL,
                    value_numeric   DECIMAL(15,4)   NULL,
                    value_text      TEXT            NULL,
                    units           VARCHAR(32)     NULL,
                    observed_at     DATETIME        NOT NULL,
                    source          VARCHAR(64)     NOT NULL DEFAULT 'inovalon_erond',
                    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_ext_obs_tenant_patient_loinc_observed
                          (tenant_id, raf_patient_id, loinc_code, observed_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def downgrade() -> None:
    if _table_exists("raf_external_observations"):
        op.execute(sa.text("DROP TABLE raf_external_observations"))
    if _table_exists("inovalon_patient_pulls"):
        op.execute(sa.text("DROP TABLE inovalon_patient_pulls"))
