"""Add HEI segmentation columns to patients + seed demo values.

Revision ID: 028_hedis_hei_patient_segmentation
Revises: 027_add_suspect_feedback_table
Create Date: 2026-05-17

Changes
-------
patients (existing):
    + medicaid_eligibility VARCHAR(32) NULL
        One of: 'none', 'full', 'qmb', 'qmb_plus', 'smb', 'smb_plus',
                'fbde' (full-benefit dual), 'qi_1', 'lis_only', NULL.
        See CMS Medicaid eligibility codes for the canonical list.

    + lis_flag             TINYINT(1) NOT NULL DEFAULT 0
        Part D Low Income Subsidy enrollee.

    + disability_flag      TINYINT(1) NOT NULL DEFAULT 0
        Medicare entitled under age 65 due to disability.

Demo seeding
------------
After adding the columns we populate them deterministically for every
existing patient using ``MD5(id)`` so the demo always shows a stable
disparity distribution (~22% dual / ~13% LIS / ~12% disability / ~53%
other).  Real customers' data is never overwritten if any patient row
already has a non-NULL medicaid_eligibility value (we skip seeding when
that is the case).

NCQA / NCQA-licensing notice
-----------------------------
This migration is part of the HEDIS + Star Ratings + HEI MVP.  The
classifier sourced from these columns implements the CMS-4201-F published
HEI segmentation rule and does NOT reproduce any NCQA copyrighted spec.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "028_hedis_hei_patient_segmentation"
down_revision: Union[str, None] = "027_add_suspect_feedback_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _column_exists(table: str, column: str) -> bool:
    insp = _inspector()
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    if not _inspector().has_table("patients"):
        # Nothing to do — patients table will get the columns at creation
        # time on a fresh deploy.
        return

    if not _column_exists("patients", "medicaid_eligibility"):
        _x(
            "ALTER TABLE `patients` "
            "ADD COLUMN `medicaid_eligibility` VARCHAR(32) NULL "
            "COMMENT 'CMS HEI: dual-eligibility code (none/full/qmb_plus/fbde/...)'"
        )
    if not _column_exists("patients", "lis_flag"):
        _x(
            "ALTER TABLE `patients` "
            "ADD COLUMN `lis_flag` TINYINT(1) NOT NULL DEFAULT 0 "
            "COMMENT 'CMS HEI: Part D Low Income Subsidy enrollee'"
        )
    if not _column_exists("patients", "disability_flag"):
        _x(
            "ALTER TABLE `patients` "
            "ADD COLUMN `disability_flag` TINYINT(1) NOT NULL DEFAULT 0 "
            "COMMENT 'CMS HEI: Medicare entitled under age 65 due to disability'"
        )

    # Add an index — segmentation queries filter by these flags frequently.
    try:
        _x(
            "CREATE INDEX `idx_patients_hei_segments` ON `patients` "
            "(`medicaid_eligibility`, `lis_flag`, `disability_flag`)"
        )
    except Exception:
        # MySQL raises 1061 if the index already exists; safe to ignore.
        pass

    # ---------------------------------------------------------------------
    # Demo seeding
    # ---------------------------------------------------------------------
    #
    # Only seed when *every* patient currently has medicaid_eligibility IS
    # NULL — i.e. the data is fresh.  This prevents overwriting any
    # real-customer dataset that was already populated out-of-band.

    bind = op.get_bind()
    res = bind.execute(
        sa.text(
            "SELECT COUNT(*) AS n FROM `patients` "
            "WHERE medicaid_eligibility IS NOT NULL"
        )
    ).fetchone()
    already_seeded = int(res[0] if res else 0)
    if already_seeded > 0:
        return

    # Deterministic seeding via MD5(id) buckets.
    # 0-21 -> dual, 22-34 -> lis, 35-46 -> disability, 47-99 -> other.
    _x(
        """
        UPDATE `patients`
        SET
            medicaid_eligibility = CASE
                WHEN (CONV(SUBSTRING(MD5(CAST(id AS CHAR)), 1, 2), 16, 10) % 100) < 22 THEN 'full'
                ELSE 'none'
            END,
            lis_flag = CASE
                WHEN (CONV(SUBSTRING(MD5(CAST(id AS CHAR)), 1, 2), 16, 10) % 100) BETWEEN 22 AND 34
                THEN 1 ELSE 0
            END,
            disability_flag = CASE
                WHEN (CONV(SUBSTRING(MD5(CAST(id AS CHAR)), 1, 2), 16, 10) % 100) BETWEEN 35 AND 46
                THEN 1 ELSE 0
            END
        WHERE medicaid_eligibility IS NULL
        """
    )


def downgrade() -> None:
    if not _inspector().has_table("patients"):
        return
    try:
        _x("DROP INDEX `idx_patients_hei_segments` ON `patients`")
    except Exception:
        pass
    for col in ("disability_flag", "lis_flag", "medicaid_eligibility"):
        if _column_exists("patients", col):
            _x(f"ALTER TABLE `patients` DROP COLUMN `{col}`")
