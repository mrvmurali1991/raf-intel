"""audit_timestamp_tokens — RFC 3161 TSA token storage for audit-chain heads.

Revision ID: 038_audit_timestamp_tokens
Revises: 036_radv_lcb_dollars, 777f6498bc76
Create Date: 2026-05-17

Stores one row per RFC 3161 timestamping operation.  Each row records the
chain-head SHA-256 hash that was submitted to the TSA, the inclusive DB
entry-ID range covered by that chain segment, the TSA endpoint URL used,
the raw DER-encoded TimeStampToken bytes, and the timestamp of generation.

Two indexes support the two most common lookup patterns:
  - Fast lookup by chain-head hash (used by the verify endpoint).
  - Range scans across entry-ID bounds (used by chain re-verification).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "038_audit_timestamp_tokens"
down_revision: Union[str, tuple] = ("036_radv_lcb_dollars", "777f6498bc76")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_timestamp_tokens (
            id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            chain_head_hash         CHAR(64)        NOT NULL,
            covers_entry_id_start   BIGINT UNSIGNED NOT NULL,
            covers_entry_id_end     BIGINT UNSIGNED NOT NULL,
            tsa_url                 VARCHAR(255)    NOT NULL,
            token_bytes             MEDIUMBLOB      NOT NULL,
            token_generated_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_tsk_head  (chain_head_hash),
            INDEX idx_tsk_range (covers_entry_id_start, covers_entry_id_end)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_timestamp_tokens")
