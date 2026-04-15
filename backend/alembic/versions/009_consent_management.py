"""Add patient_consents table for consent management.

Revision ID: 009_consent_management
Revises: 008_add_missing_indexes_and_fks
Create Date: 2026-04-14 00:00:00.000000

Adds the ``patient_consents`` table to track patient consent for data
sharing, research use, and other HIPAA-required consent categories.
"""

revision = "009_consent_management"
down_revision = "008_add_missing_indexes_and_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa

    op.execute("""
        CREATE TABLE IF NOT EXISTS patient_consents (
            id              BIGINT AUTO_INCREMENT PRIMARY KEY,
            patient_id      BIGINT          NOT NULL,
            tenant_id       VARCHAR(50)     NOT NULL,
            consent_type    VARCHAR(100)    NOT NULL,
            granted         TINYINT(1)      NOT NULL DEFAULT 0,
            granted_at      DATETIME        NULL,
            expires_at      DATETIME        NULL,
            revoked_at      DATETIME        NULL,
            details         TEXT            NULL,
            created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_consent_patient_tenant (patient_id, tenant_id),
            INDEX idx_consent_type (consent_type),
            UNIQUE KEY uq_consent_patient_type (patient_id, tenant_id, consent_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def downgrade() -> None:
    from alembic import op
    op.execute("DROP TABLE IF EXISTS patient_consents")
