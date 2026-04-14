"""Add fhir_encounters table and fhir_id column to patient_medications.

Revision ID: 007_fhir_encounter_medication_storage
Revises: 006_add_performance_indexes
Create Date: 2026-04-14 00:00:00.000000

Creates fhir_encounters to store encounter metadata from FHIR sync (date,
status, type) so the patient detail endpoint can return real encounter rows
for FHIR patients, rather than empty lists.

Also adds a fhir_id column to patient_medications so that MedicationRequest
resources synced from FHIR can be upserted idempotently.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_fhir_encounter_medication_storage"
down_revision: Union[str, None] = "006_add_performance_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. fhir_encounters — stores per-encounter metadata from FHIR sync
    # ------------------------------------------------------------------
    if not _table_exists("fhir_encounters"):
        op.create_table(
            "fhir_encounters",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("fhir_id", sa.String(255), nullable=False),
            sa.Column("raf_patient_id", sa.Integer, nullable=False),
            sa.Column("connection_id", sa.Integer, nullable=False),
            sa.Column("encounter_date", sa.Date, nullable=True),
            sa.Column("status", sa.String(50), nullable=True),
            sa.Column("encounter_type", sa.String(100), nullable=True),
            sa.Column("encounter_surrogate", sa.BigInteger, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("fhir_id", "connection_id", name="uq_fhir_enc_fhir_conn"),
            sa.Index("idx_fe_raf_patient_id", "raf_patient_id"),
            sa.Index("idx_fe_encounter_date", "encounter_date"),
        )

    # ------------------------------------------------------------------
    # 2. patient_medications — add fhir_id for idempotent FHIR upserts
    # ------------------------------------------------------------------
    if _table_exists("patient_medications"):
        if not _column_exists("patient_medications", "fhir_id"):
            op.add_column(
                "patient_medications",
                sa.Column("fhir_id", sa.String(100), nullable=True),
            )
            op.execute(
                sa.text(
                    "ALTER TABLE patient_medications "
                    "ADD UNIQUE INDEX uq_pm_fhir_id (fhir_id)"
                )
            )
        # status column may not exist — audit.py uses is_active, patient_service uses status
        if not _column_exists("patient_medications", "status"):
            op.add_column(
                "patient_medications",
                sa.Column(
                    "status",
                    sa.String(20),
                    nullable=False,
                    server_default="active",
                ),
            )
    else:
        # Create the table from scratch if it doesn't exist yet
        op.create_table(
            "patient_medications",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("patient_id", sa.Integer, nullable=False),
            sa.Column("medication_name", sa.String(255), nullable=False),
            sa.Column("dosage", sa.String(255), nullable=True),
            sa.Column("form", sa.String(100), nullable=True),
            sa.Column("frequency", sa.String(100), nullable=True),
            sa.Column("purpose", sa.Text, nullable=True),
            sa.Column("start_date", sa.Date, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
            sa.Column("prescriber_id", sa.Integer, nullable=True),
            sa.Column("fhir_id", sa.String(100), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("fhir_id", name="uq_pm_fhir_id"),
            sa.Index("idx_pm_patient_id", "patient_id"),
        )


def downgrade() -> None:
    if _table_exists("fhir_encounters"):
        op.drop_table("fhir_encounters")
    if _table_exists("patient_medications") and _column_exists("patient_medications", "fhir_id"):
        op.execute(
            sa.text("ALTER TABLE patient_medications DROP INDEX uq_pm_fhir_id")
        )
        op.drop_column("patient_medications", "fhir_id")
