"""Add raf_radv_audit_runs + raf_radv_audit_records (RADV Audit Defense workflow).

Revision ID: 030_add_radv_audit_runs
Revises: 029_edps_per_hcc_reject_reasons
Create Date: 2026-05-17

Adds support for CMS Risk Adjustment Data Validation (RADV) mock-audit
defense workflow.  Drives:

  - Sampler (random / stratified-by-HCC / high-risk-first) — picks N
    patients from a payment-year cohort for mock-audit prep.
  - Per-record evidence packaging / chart-request orchestration.
  - MAO-004 batch reject re-submission tracking.
  - Mock-audit revenue exposure simulation (× ~55× CMS extrapolation).
  - CAP (corrective action plan) tracking.

Schema
------

raf_radv_audit_runs
    id              BIGINT UNSIGNED PK
    tenant_id       VARCHAR(64) NOT NULL
    name            VARCHAR(255) NOT NULL
    payment_year    INT NOT NULL          -- e.g. 2025
    sample_size     INT NOT NULL          -- e.g. 200 (post-2024 CMS rule)
    sample_method   ENUM('random','stratified_hcc','high_risk_first')
    status          ENUM('prep','reviewing','complete','exported')
    created_by      INT NOT NULL          -- users.id
    assumed_fail_rate DECIMAL(5,4) NULL   -- last-saved simulator input
    notes           TEXT NULL
    created_at / updated_at  DATETIME

raf_radv_audit_records
    id                            BIGINT UNSIGNED PK
    audit_run_id                  BIGINT UNSIGNED NOT NULL FK
    tenant_id                     VARCHAR(64) NOT NULL
    patient_id                    INT NOT NULL              -- patients.id
    sampled_hcc_codes             JSON NOT NULL             -- e.g. ["18","85"]
    evidence_status               ENUM('pending','complete','missing_meat',
                                       'chart_requested') DEFAULT 'pending'
    evidence_package_url          VARCHAR(1024) NULL
    reviewer_user_id              INT NULL
    reviewer_notes                TEXT NULL
    final_decision                ENUM('pending','defensible','undefensible',
                                       'needs_remediation') DEFAULT 'pending'
    extrapolated_exposure_dollars DECIMAL(14,2) DEFAULT 0
    edps_rejected                 TINYINT(1) DEFAULT 0
    created_at / updated_at       DATETIME

Permissions seeded: radv:read, radv:write.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_add_radv_audit_runs"
down_revision: Union[str, None] = "029_edps_per_hcc_reject_reasons"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    if not _table_exists("raf_radv_audit_runs"):
        _x(
            """
            CREATE TABLE `raf_radv_audit_runs` (
                `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`          VARCHAR(64)     NOT NULL,
                `name`               VARCHAR(255)    NOT NULL,
                `payment_year`       INT             NOT NULL,
                `sample_size`        INT             NOT NULL,
                `sample_method`      ENUM('random','stratified_hcc','high_risk_first')
                                     NOT NULL DEFAULT 'random',
                `status`             ENUM('prep','reviewing','complete','exported')
                                     NOT NULL DEFAULT 'prep',
                `created_by`         INT             NOT NULL,
                `assumed_fail_rate`  DECIMAL(5,4)    NULL,
                `notes`              TEXT            NULL,
                `created_at`         DATETIME        NULL DEFAULT CURRENT_TIMESTAMP,
                `updated_at`         DATETIME        NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                INDEX `idx_radv_runs_tenant` (`tenant_id`),
                INDEX `idx_radv_runs_tenant_year` (`tenant_id`, `payment_year`),
                INDEX `idx_radv_runs_status` (`status`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='RADV mock-audit run header — sampling + status'
            """
        )

    if not _table_exists("raf_radv_audit_records"):
        _x(
            """
            CREATE TABLE `raf_radv_audit_records` (
                `id`                            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `audit_run_id`                  BIGINT UNSIGNED NOT NULL,
                `tenant_id`                     VARCHAR(64)     NOT NULL,
                `patient_id`                    INT             NOT NULL,
                `sampled_hcc_codes`             JSON            NOT NULL,
                `evidence_status`               ENUM('pending','complete','missing_meat','chart_requested')
                                                NOT NULL DEFAULT 'pending',
                `evidence_package_url`          VARCHAR(1024)   NULL,
                `reviewer_user_id`              INT             NULL,
                `reviewer_notes`                TEXT            NULL,
                `final_decision`                ENUM('pending','defensible','undefensible','needs_remediation')
                                                NOT NULL DEFAULT 'pending',
                `extrapolated_exposure_dollars` DECIMAL(14,2)   NOT NULL DEFAULT 0,
                `edps_rejected`                 TINYINT(1)      NOT NULL DEFAULT 0,
                `created_at`                    DATETIME        NULL DEFAULT CURRENT_TIMESTAMP,
                `updated_at`                    DATETIME        NULL DEFAULT CURRENT_TIMESTAMP
                                                ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                INDEX `idx_radv_rec_run`         (`audit_run_id`),
                INDEX `idx_radv_rec_run_decision` (`audit_run_id`, `final_decision`),
                INDEX `idx_radv_rec_tenant`      (`tenant_id`),
                INDEX `idx_radv_rec_patient`     (`tenant_id`, `patient_id`),
                CONSTRAINT `fk_radv_rec_run`
                    FOREIGN KEY (`audit_run_id`) REFERENCES `raf_radv_audit_runs` (`id`)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='RADV mock-audit per-record evidence + decision tracking'
            """
        )

    # ------------------------------------------------------------------
    # Permissions seed — radv:read / radv:write
    # ------------------------------------------------------------------
    # The codebase uses `role_default_permissions(role, resource, action)`
    # (see auth_service._seed_default_permissions). Grant:
    #   admin/manager/auditor -> radv:read
    #   admin/manager         -> radv:write
    # Idempotent via INSERT IGNORE so re-running is safe.
    try:
        _x(
            """
            INSERT IGNORE INTO role_default_permissions (role, resource, action)
            VALUES
              ('admin',   'radv', 'read'),
              ('admin',   'radv', 'write'),
              ('manager', 'radv', 'read'),
              ('manager', 'radv', 'write'),
              ('auditor', 'radv', 'read'),
              ('coder',   'radv', 'read'),
              ('coder',   'radv', 'write')
            """
        )
    except Exception:
        # role_default_permissions absent in some legacy envs — skip silently.
        pass


def downgrade() -> None:
    if _table_exists("raf_radv_audit_records"):
        _x("DROP TABLE `raf_radv_audit_records`")
    if _table_exists("raf_radv_audit_runs"):
        _x("DROP TABLE `raf_radv_audit_runs`")
    try:
        _x("DELETE FROM role_default_permissions WHERE resource = 'radv'")
    except Exception:
        pass
