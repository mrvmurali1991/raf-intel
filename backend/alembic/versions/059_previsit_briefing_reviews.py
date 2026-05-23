"""Create previsit_briefing_reviews with tenant_id from day one.

Revision ID: 059_previsit_briefing_reviews
Revises: 058_add_bi_export_forecast_resources
Create Date: 2026-05-24

The MD huddle endpoint (/api/md/today, /api/md/today/reviewed/{patient_id})
was selecting/inserting into previsit_briefing_reviews but the table had
no migration and no tenant_id column. Without tenant_id the SELECT and
INSERT bleed across tenants whenever two tenants happen to use the same
provider_id integer (which is normal since provider_id is per-OpenEMR).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "059_previsit_briefing_reviews"
down_revision: Union[str, Sequence[str], None] = "058_add_bi_export_forecast_resources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_unique_key(table: str, key_name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(
        idx.get("name") == key_name for idx in insp.get_indexes(table)
    )


def upgrade() -> None:
    if not _has_table("previsit_briefing_reviews"):
        op.execute(
            sa.text(
                """
                CREATE TABLE previsit_briefing_reviews (
                    id                   INT AUTO_INCREMENT PRIMARY KEY,
                    tenant_id            VARCHAR(64)  NOT NULL,
                    provider_id          INT          NOT NULL,
                    patient_id           INT          NOT NULL,
                    reviewed_date        DATE         NOT NULL,
                    reviewed_by_user_id  INT          NULL,
                    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_pbr_tenant_provider_patient_date
                              (tenant_id, provider_id, patient_id, reviewed_date),
                    INDEX idx_pbr_tenant_date (tenant_id, reviewed_date),
                    INDEX idx_pbr_provider_date (provider_id, reviewed_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
        )
    else:
        # Table exists from a prior runtime auto-create — backfill tenant_id.
        if not _has_column("previsit_briefing_reviews", "tenant_id"):
            op.execute(
                sa.text(
                    "ALTER TABLE previsit_briefing_reviews "
                    "ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1' "
                    "AFTER id"
                )
            )
            # Drop the default so future inserts must supply the value.
            op.execute(
                sa.text(
                    "ALTER TABLE previsit_briefing_reviews "
                    "ALTER COLUMN tenant_id DROP DEFAULT"
                )
            )
        # Add the tenant-scoped unique key so ON DUPLICATE KEY UPDATE in
        # md_today_mark_reviewed deduplicates correctly. Without this key
        # concurrent double-taps create duplicate review rows.
        if not _has_unique_key(
            "previsit_briefing_reviews",
            "uq_pbr_tenant_provider_patient_date",
        ):
            op.execute(
                sa.text(
                    "ALTER TABLE previsit_briefing_reviews "
                    "ADD UNIQUE KEY uq_pbr_tenant_provider_patient_date "
                    "(tenant_id, provider_id, patient_id, reviewed_date)"
                )
            )


def downgrade() -> None:
    """No-op — dropping the table would lose huddle review history."""
    pass
