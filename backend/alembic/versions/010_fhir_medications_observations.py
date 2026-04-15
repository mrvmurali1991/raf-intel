"""Add fhir_medications and fhir_observations tables for FHIR resource sync.

Revision ID: 010_fhir_medications_observations
Revises: 009_consent_management
Create Date: 2026-04-15 00:00:00.000000

Creates fhir_medications and fhir_observations tables to store MedicationRequest
and Observation resources synced from FHIR, improving data quality coverage
from ~40% to 80%+.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_fhir_medications_observations"
down_revision: Union[str, None] = "009_consent_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. fhir_medications — stores MedicationRequest resources
    # ------------------------------------------------------------------
    if not _table_exists("fhir_medications"):
        op.create_table(
            "fhir_medications",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("connection_id", sa.Integer, nullable=False),
            sa.Column("fhir_resource_id", sa.String(200), nullable=False),
            sa.Column("fhir_patient_id", sa.String(200), nullable=True),
            sa.Column("medication_code", sa.String(50), nullable=True),
            sa.Column("medication_display", sa.String(500), nullable=True),
            sa.Column("status", sa.String(50), nullable=True),
            sa.Column("intent", sa.String(50), nullable=True),
            sa.Column("authored_on", sa.Date, nullable=True),
            sa.Column("dosage_text", sa.Text, nullable=True),
            sa.Column("raw_json", sa.Text(length=4294967295), nullable=True),  # LONGTEXT
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "connection_id", "fhir_resource_id", name="uq_conn_fhir_med"
            ),
            sa.Index("idx_fhir_med_patient", "fhir_patient_id"),
            sa.Index("idx_fhir_med_connection", "connection_id"),
        )

    # ------------------------------------------------------------------
    # 2. fhir_observations — stores Observation resources
    # ------------------------------------------------------------------
    if not _table_exists("fhir_observations"):
        op.create_table(
            "fhir_observations",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("connection_id", sa.Integer, nullable=False),
            sa.Column("fhir_resource_id", sa.String(200), nullable=False),
            sa.Column("fhir_patient_id", sa.String(200), nullable=True),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("code", sa.String(50), nullable=True),
            sa.Column("code_display", sa.String(500), nullable=True),
            sa.Column("value_numeric", sa.Numeric(precision=10, scale=4), nullable=True),
            sa.Column("value_string", sa.String(500), nullable=True),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column("effective_date", sa.Date, nullable=True),
            sa.Column("status", sa.String(50), nullable=True),
            sa.Column("raw_json", sa.Text(length=4294967295), nullable=True),  # LONGTEXT
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "connection_id", "fhir_resource_id", name="uq_conn_fhir_obs"
            ),
            sa.Index("idx_fhir_obs_patient", "fhir_patient_id"),
            sa.Index("idx_fhir_obs_connection", "connection_id"),
            sa.Index("idx_fhir_obs_category", "category"),
            sa.Index("idx_fhir_obs_code", "code"),
        )


def downgrade() -> None:
    if _table_exists("fhir_observations"):
        op.drop_table("fhir_observations")
    if _table_exists("fhir_medications"):
        op.drop_table("fhir_medications")
