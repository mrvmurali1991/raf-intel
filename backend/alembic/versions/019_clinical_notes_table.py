"""clinical_notes: unified store for free-text clinical notes from every source system.

Revision ID: 019_clinical_notes_table
Revises: 018_raf_recompute_inbox
Create Date: 2026-04-17

Creates the ``clinical_notes`` table which holds the raw free-text clinical
documentation (progress notes, SOAP notes, discharge summaries, consult letters,
etc.) pulled from every backing source system (``openemr_fhir``,
``openemr_local``, future EMRs).

The table is designed around two access patterns:

1. **Idempotent ingestion** — the FHIR/local sync paths upsert notes keyed by
   (``tenant_id``, ``source_system``, ``external_id``).  The unique key
   ``uk_clinical_notes_src_ext`` enforces that so repeated syncs stay safe.

2. **MEAT reader lookups** — the AI MEAT extractor (see
   ``backend/app/services/meat_evidence_service.py``) scans recent notes for a
   patient by date.  The composite index on (``patient_id``, ``note_date``)
   supports that range-scoped lookup.

Foreign keys mirror the types already used throughout the schema:
  * ``patient_id``   → ``patients.id``    (INT UNSIGNED, matches FK pattern
                                           established by migrations 002/017
                                           and ``emr_manager.py`` upserts)
  * ``encounter_id`` → ``encounters.id``  (INT UNSIGNED NULL, matches the
                                           ``encounter_id INT UNSIGNED NOT NULL``
                                           column on ``raf_meat_evidence`` per
                                           ``meat_evidence_service.py``)

MySQL-native migration: MEDIUMTEXT for the note body (OpenEMR clinical notes
routinely exceed TEXT's 64 KB ceiling), TIMESTAMP with CURRENT_TIMESTAMP
defaults (plus ON UPDATE for ``updated_at``), mysql_engine/charset set
explicitly per the pattern in migrations 015 / 017.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import INTEGER as MYSQL_INTEGER, MEDIUMTEXT


revision: str = "019_clinical_notes_table"
down_revision: Union[str, None] = "018_raf_recompute_inbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clinical_notes",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(
                MYSQL_INTEGER(unsigned=True), "mysql"
            ),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "tenant_id",
            sa.String(50),
            nullable=False,
            server_default="default",
        ),
        sa.Column(
            "patient_id",
            MYSQL_INTEGER(unsigned=True),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "encounter_id",
            MYSQL_INTEGER(unsigned=True),
            sa.ForeignKey("encounters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # e.g. "openemr_fhir", "openemr_local"
        sa.Column("source_system", sa.String(50), nullable=False),
        # The FHIR resource id (or source-system equivalent) — enables idempotent
        # upserts when combined with tenant_id + source_system.
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("note_date", sa.Date, nullable=True),
        sa.Column("note_type", sa.String(100), nullable=True),
        sa.Column("text", MEDIUMTEXT, nullable=False),
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
            "tenant_id",
            "source_system",
            "external_id",
            name="uk_clinical_notes_src_ext",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_clinical_notes_patient_date",
        "clinical_notes",
        ["patient_id", "note_date"],
    )
    op.create_index(
        "idx_clinical_notes_encounter",
        "clinical_notes",
        ["encounter_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_clinical_notes_encounter", table_name="clinical_notes")
    op.drop_index("idx_clinical_notes_patient_date", table_name="clinical_notes")
    op.drop_table("clinical_notes")
