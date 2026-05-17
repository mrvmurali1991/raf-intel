"""merge_028_hedis_030_radv_030_meat

Revision ID: 77cd8ea4ca45
Revises: 028_hedis_hei_patient_segmentation, 030_add_radv_audit_runs, 030_meat_evidence_offsets
Create Date: 2026-05-17 13:21:28.778954+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77cd8ea4ca45'
down_revision: Union[str, None] = ('028_hedis_hei_patient_segmentation', '030_add_radv_audit_runs', '030_meat_evidence_offsets')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
