"""Widen emr_pid columns to VARCHAR(200) to support FHIR UUIDs.

Revision ID: 011_widen_emr_pid_for_fhir_uuids
Revises: 010_fhir_medications_observations
Create Date: 2026-04-15 00:00:00.000000

Previously FHIR sync hashed the UUID into a numeric emr_pid, which broke
lookups against fhir_conditions/encounters/medications that key on the UUID.
This migration widens the column so the UUID can be stored directly.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_widen_emr_pid_for_fhir_uuids"
down_revision: Union[str, None] = "010_fhir_medications_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_type(table: str, column: str) -> str | None:
    """Return the current column type as a lowercase string, or None."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT COLUMN_TYPE FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :tbl AND column_name = :col"
        ),
        {"tbl": table, "col": column},
    )
    row = result.fetchone()
    return row[0].lower() if row else None


def upgrade() -> None:
    # Widen patients.emr_pid if it is currently an integer type
    col = _column_type("patients", "emr_pid")
    if col and "int" in col:
        op.alter_column(
            "patients",
            "emr_pid",
            existing_type=sa.Integer(),
            type_=sa.String(200),
            existing_nullable=False,
            nullable=False,
        )

    # Widen emr_patient_matches.emr_pid if it is currently an integer type
    col2 = _column_type("emr_patient_matches", "emr_pid")
    if col2 and "int" in col2:
        op.alter_column(
            "emr_patient_matches",
            "emr_pid",
            existing_type=sa.Integer(),
            type_=sa.String(200),
            existing_nullable=False,
            nullable=False,
        )


def downgrade() -> None:
    # Note: downgrade will lose UUID data that doesn't fit in INT
    op.alter_column(
        "emr_patient_matches",
        "emr_pid",
        existing_type=sa.String(200),
        type_=sa.Integer(),
        existing_nullable=False,
        nullable=False,
    )
    op.alter_column(
        "patients",
        "emr_pid",
        existing_type=sa.String(200),
        type_=sa.Integer(),
        existing_nullable=False,
        nullable=False,
    )
