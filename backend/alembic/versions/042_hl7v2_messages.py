"""Add hl7v2_sources and hl7v2_messages_received tables.

Revision ID: 042_hl7v2_messages
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

Supports the HL7 v2 MDM (Medical Document Management) ingest pipeline.
Two tables are added:

  hl7v2_sources
      Registry of trusted HL7 interface engine sources (Mirth, Rhapsody, …).
      Each source has a per-tenant HMAC secret used to authenticate inbound
      HTTP POSTs.

  hl7v2_messages_received
      Audit log + processing state for every inbound MDM message.  The
      (tenant_id, msg_control_id) pair is unique to enforce idempotency at
      the database level (in addition to the application-level check).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "042_hl7v2_messages"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return insp.has_table(table)


def upgrade() -> None:
    if not _table_exists("hl7v2_sources"):
        op.execute(
            sa.text(
                """
                CREATE TABLE hl7v2_sources (
                    id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id    VARCHAR(64)  NOT NULL,
                    name         VARCHAR(255) NOT NULL COMMENT 'Human label e.g. "Mirth Channel — MainHospital"',
                    hmac_secret  VARCHAR(128) NOT NULL COMMENT 'API key / shared secret for this source',
                    last_seen_at DATETIME     NULL,
                    is_active    TINYINT(1)   NOT NULL DEFAULT 1,
                    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_hl7v2_sources_secret (hmac_secret),
                    KEY idx_hl7v2_sources_tenant (tenant_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )

    if not _table_exists("hl7v2_messages_received"):
        op.execute(
            sa.text(
                """
                CREATE TABLE hl7v2_messages_received (
                    id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
                    tenant_id           VARCHAR(64)  NOT NULL,
                    source_id           INT UNSIGNED NOT NULL,
                    msg_control_id      VARCHAR(255) NOT NULL COMMENT 'MSH-10 message control id',
                    msg_type            VARCHAR(20)  NOT NULL COMMENT 'e.g. MDM^T02',
                    raw_message         MEDIUMTEXT   NOT NULL,
                    patient_external_id VARCHAR(255) NOT NULL DEFAULT '',
                    received_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status              ENUM('received','parsed','extracted','failed')
                                        NOT NULL DEFAULT 'received',
                    suspects_extracted  INT          NOT NULL DEFAULT 0,
                    error_text          TEXT         NULL,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_hl7v2_msg_ctrl (tenant_id, msg_control_id),
                    KEY idx_hl7v2_msg_tenant_status (tenant_id, status),
                    KEY idx_hl7v2_msg_source (source_id),
                    CONSTRAINT fk_hl7v2_msg_source
                        FOREIGN KEY (source_id) REFERENCES hl7v2_sources (id)
                        ON DELETE RESTRICT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def downgrade() -> None:
    if _table_exists("hl7v2_messages_received"):
        op.execute(sa.text("DROP TABLE hl7v2_messages_received"))
    if _table_exists("hl7v2_sources"):
        op.execute(sa.text("DROP TABLE hl7v2_sources"))
