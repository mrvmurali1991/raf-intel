"""AI pipeline result tables: ai_hcc_candidates, ai_suspect_candidates, ai_meat_evidence.

Revision ID: 017_ai_pipeline_tables
Revises: 016_ai_audit_log
Create Date: 2026-04-16

Converted from backend/migrations/add_ai_pipeline_tables.sql (Agent 8).
Parent table ``ai_analysis_runs`` must exist (created in 014).

MySQL-native: JSON (not JSONB), TIMESTAMP without TZ, CURRENT_TIMESTAMP defaults,
patient_id as INT to match existing ``patients.id`` column,
mysql_engine/charset set on every table, sa.Enum for fixed-vocabulary fields.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017_ai_pipeline_tables"
down_revision: Union[str, None] = "016_ai_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_hcc_candidates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.Integer, nullable=False),
        sa.Column("icd10", sa.String(16), nullable=False),
        sa.Column("hcc", sa.String(32), nullable=False),
        sa.Column("hcc_label", sa.String(255), nullable=True),
        sa.Column(
            "model_version",
            sa.Enum("V24", "V28", name="ai_hcc_model_version"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum("blind", "contextual", "suspect", name="ai_hcc_source"),
            nullable=False,
        ),
        sa.Column(
            "mapper_source",
            sa.Enum("csv", "hccinfhir", name="ai_hcc_mapper_source"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("note_id", sa.BigInteger, nullable=True),
        sa.Column(
            "gate_passed",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("gate_reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_ai_hcc_candidates_run", "ai_hcc_candidates", ["run_id"]
    )
    op.create_index(
        "idx_ai_hcc_candidates_patient", "ai_hcc_candidates", ["patient_id"]
    )

    op.create_table(
        "ai_suspect_candidates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.Integer, nullable=False),
        sa.Column("hcc", sa.String(32), nullable=True),
        sa.Column("icd10", sa.String(16), nullable=True),
        # which Agent-7 rule fired
        sa.Column("rule_id", sa.String(64), nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        # [{type:'lab',id:...}, ...]
        sa.Column("evidence_refs", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ai_suspect_run", "ai_suspect_candidates", ["run_id"])
    op.create_index(
        "idx_ai_suspect_patient", "ai_suspect_candidates", ["patient_id"]
    )

    op.create_table(
        "ai_meat_evidence",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.BigInteger,
            sa.ForeignKey("ai_hcc_candidates.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "suspect_candidate_id",
            sa.BigInteger,
            sa.ForeignKey("ai_suspect_candidates.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "meat_type",
            sa.Enum(
                "monitor", "evaluate", "assess", "treat", name="ai_meat_type"
            ),
            nullable=False,
        ),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("note_id", sa.BigInteger, nullable=True),
        sa.Column("note_span_start", sa.Integer, nullable=True),
        sa.Column("note_span_end", sa.Integer, nullable=True),
        sa.Column("strength", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "candidate_id IS NOT NULL OR suspect_candidate_id IS NOT NULL",
            name="ck_ai_meat_evidence_candidate_xor",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ai_meat_run", "ai_meat_evidence", ["run_id"])
    op.create_index(
        "idx_ai_meat_candidate", "ai_meat_evidence", ["candidate_id"]
    )
    op.create_index(
        "idx_ai_meat_suspect", "ai_meat_evidence", ["suspect_candidate_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_ai_meat_suspect", table_name="ai_meat_evidence")
    op.drop_index("idx_ai_meat_candidate", table_name="ai_meat_evidence")
    op.drop_index("idx_ai_meat_run", table_name="ai_meat_evidence")
    op.drop_table("ai_meat_evidence")

    op.drop_index(
        "idx_ai_suspect_patient", table_name="ai_suspect_candidates"
    )
    op.drop_index("idx_ai_suspect_run", table_name="ai_suspect_candidates")
    op.drop_table("ai_suspect_candidates")

    op.drop_index(
        "idx_ai_hcc_candidates_patient", table_name="ai_hcc_candidates"
    )
    op.drop_index("idx_ai_hcc_candidates_run", table_name="ai_hcc_candidates")
    op.drop_table("ai_hcc_candidates")
