"""Add raf_qa_reviews table for multi-rater QA workflow (Reveleer pattern).

Revision ID: 028_add_qa_reviews_table
Revises: 027_add_suspect_feedback_table
Create Date: 2026-05-16

Adds the multi-rater QA workflow table. Each accepted suspect may be sent to
a secondary QA reviewer who confirms or disputes; disagreements escalate to
a tier-2 reviewer for adjudication.

Schema:
  raf_qa_reviews:
    id                       BIGINT UNSIGNED PK
    tenant_id                VARCHAR(64) NOT NULL
    suspect_id               INT UNSIGNED NULL  -- references form_suspects(id)
    raf_patient_hcc_id       INT UNSIGNED NULL  -- references raf_patient_hccs(id)
    primary_rater_user_id    INT NOT NULL
    primary_rating           ENUM('accept','reject','unclear') NOT NULL
    primary_note             TEXT NULL
    secondary_rater_user_id  INT NULL
    secondary_rating         ENUM('accept','reject','unclear') NULL
    secondary_note           TEXT NULL
    tier2_rater_user_id      INT NULL
    tier2_rating             ENUM('accept','reject','unclear') NULL
    tier2_note               TEXT NULL
    final_outcome            ENUM('accepted','rejected','escalated','pending')
                             NOT NULL DEFAULT 'pending'
    created_at / updated_at  DATETIME
    INDEX(tenant_id), INDEX(suspect_id), INDEX(final_outcome)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "028_add_qa_reviews_table"
down_revision: Union[str, None] = "027_add_suspect_feedback_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    if not _table_exists("raf_qa_reviews"):
        _x(
            """
            CREATE TABLE `raf_qa_reviews` (
                `id`                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`               VARCHAR(64)     NOT NULL,
                `suspect_id`              INT UNSIGNED    NULL,
                `raf_patient_hcc_id`      INT UNSIGNED    NULL,
                `primary_rater_user_id`   INT             NOT NULL,
                `primary_rating`          ENUM('accept','reject','unclear') NOT NULL,
                `primary_note`            TEXT            NULL,
                `secondary_rater_user_id` INT             NULL,
                `secondary_rating`        ENUM('accept','reject','unclear') NULL,
                `secondary_note`          TEXT            NULL,
                `tier2_rater_user_id`     INT             NULL,
                `tier2_rating`            ENUM('accept','reject','unclear') NULL,
                `tier2_note`              TEXT            NULL,
                `final_outcome`           ENUM('accepted','rejected','escalated','pending')
                                          NOT NULL DEFAULT 'pending',
                `created_at`              DATETIME        NULL DEFAULT CURRENT_TIMESTAMP,
                `updated_at`              DATETIME        NULL DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                INDEX `idx_qa_tenant` (`tenant_id`),
                INDEX `idx_qa_suspect` (`suspect_id`),
                INDEX `idx_qa_outcome` (`final_outcome`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='Multi-rater QA review workflow (Reveleer-style dual review)'
            """
        )


def downgrade() -> None:
    if _table_exists("raf_qa_reviews"):
        _x("DROP TABLE `raf_qa_reviews`")
