-- =============================================================================
-- RAF Intelligence System - Migration 022: Financial Reconciliation
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- Provides full financial reconciliation between projected RAF-based revenue
-- and actual CMS payment records, including revenue forecasting and sweep
-- adjustment modeling.
--
-- Tables created:
--   payment_import_batches     – CMS payment file import tracking
--   cms_payment_records        – Individual CMS capitation/sweep payment rows
--   financial_reconciliation   – Patient-level projected vs actual comparison
--   revenue_forecasts          – Forward-looking revenue forecast snapshots
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. PAYMENT_IMPORT_BATCHES
--    Tracks every CMS payment file uploaded to the system.  One row per file.
-- =============================================================================
CREATE TABLE IF NOT EXISTS payment_import_batches (
  id               INT UNSIGNED       NOT NULL AUTO_INCREMENT,
  tenant_id        VARCHAR(50)        NOT NULL DEFAULT 'default'         COMMENT 'Multi-tenant discriminator',
  filename         VARCHAR(512)       NOT NULL                           COMMENT 'Original uploaded filename',
  file_type        ENUM(
                     'mao_payment',
                     'capitation_report',
                     'sweep_file',
                     'custom_csv'
                   )                  NOT NULL DEFAULT 'custom_csv'      COMMENT 'CMS file type',
  record_count     INT UNSIGNED       NOT NULL DEFAULT 0                 COMMENT 'Number of payment records parsed',
  total_amount     DECIMAL(14,2)      NOT NULL DEFAULT 0.00              COMMENT 'Sum of all payment amounts in the file',
  payment_period   VARCHAR(20)            NULL DEFAULT NULL              COMMENT 'Period covered, e.g. 2025-01 or 2025-Q1',
  status           ENUM(
                     'uploaded',
                     'processing',
                     'completed',
                     'error'
                   )                  NOT NULL DEFAULT 'uploaded'        COMMENT 'Import lifecycle status',
  error_message    TEXT                   NULL DEFAULT NULL              COMMENT 'Error detail when status = error',
  imported_by      INT UNSIGNED           NULL DEFAULT NULL              COMMENT 'FK to auth_users.id',
  created_at       DATETIME           NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_pib_tenant          (tenant_id),
  INDEX idx_pib_status          (status),
  INDEX idx_pib_payment_period  (payment_period),
  INDEX idx_pib_tenant_period   (tenant_id, payment_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='CMS payment file import batches';


-- =============================================================================
-- 2. CMS_PAYMENT_RECORDS
--    One row per member per payment line in a CMS capitation/sweep file.
-- =============================================================================
CREATE TABLE IF NOT EXISTS cms_payment_records (
  id                   INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id            VARCHAR(50)       NOT NULL DEFAULT 'default'      COMMENT 'Multi-tenant discriminator',
  batch_id             INT UNSIGNED      NOT NULL                        COMMENT 'FK to payment_import_batches.id',
  payment_year         INT              NOT NULL                        COMMENT 'CMS payment year, e.g. 2025',
  payment_month        TINYINT UNSIGNED      NULL DEFAULT NULL           COMMENT '1-12 for monthly capitation, NULL for sweeps',
  patient_id           INT UNSIGNED          NULL DEFAULT NULL           COMMENT 'Matched OpenEMR patient_data.pid',
  member_id            VARCHAR(50)       NOT NULL                        COMMENT 'CMS MBI or internal member ID from the file',
  plan_id              VARCHAR(50)           NULL DEFAULT NULL           COMMENT 'CMS H-number / plan identifier',
  cms_raf_score        DECIMAL(8,4)          NULL DEFAULT NULL           COMMENT 'RAF score as reported by CMS',
  cms_payment_amount   DECIMAL(12,2)     NOT NULL DEFAULT 0.00           COMMENT 'Gross payment amount from CMS',
  payment_type         ENUM(
                         'monthly_capitation',
                         'mid_year_sweep',
                         'final_sweep',
                         'retroactive'
                       )                 NOT NULL DEFAULT 'monthly_capitation' COMMENT 'Nature of the payment',
  adjustment_reason    VARCHAR(512)          NULL DEFAULT NULL           COMMENT 'CMS-provided adjustment description if any',
  received_date        DATE                  NULL DEFAULT NULL           COMMENT 'Date the payment file was received from CMS',
  file_source          VARCHAR(255)          NULL DEFAULT NULL           COMMENT 'Source filename or CMS report ID',
  created_at           DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_cpr_tenant          (tenant_id),
  INDEX idx_cpr_batch           (batch_id),
  INDEX idx_cpr_patient         (patient_id),
  INDEX idx_cpr_member          (member_id),
  INDEX idx_cpr_payment_year    (payment_year),
  INDEX idx_cpr_payment_type    (payment_type),
  INDEX idx_cpr_tenant_year     (tenant_id, payment_year),
  INDEX idx_cpr_year_month      (payment_year, payment_month),

  CONSTRAINT fk_cpr_batch FOREIGN KEY (batch_id)
    REFERENCES payment_import_batches (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual CMS payment lines parsed from capitation and sweep files';


-- =============================================================================
-- 3. FINANCIAL_RECONCILIATION
--    Patient-level comparison of projected vs actual CMS RAF and revenue.
--    One row per patient per reconciliation_period.
-- =============================================================================
CREATE TABLE IF NOT EXISTS financial_reconciliation (
  id                    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id             VARCHAR(50)       NOT NULL DEFAULT 'default'     COMMENT 'Multi-tenant discriminator',
  reconciliation_period VARCHAR(20)       NOT NULL                       COMMENT 'e.g. 2025-01, 2025-Q2, 2025',
  patient_id            INT UNSIGNED      NOT NULL                       COMMENT 'OpenEMR patient_data.pid',
  projected_raf         DECIMAL(8,4)          NULL DEFAULT NULL          COMMENT 'Internal projected RAF from raf_scores',
  actual_cms_raf        DECIMAL(8,4)          NULL DEFAULT NULL          COMMENT 'RAF score CMS used for payment',
  raf_variance          DECIMAL(8,4)          NULL DEFAULT NULL          COMMENT 'projected_raf - actual_cms_raf',
  projected_revenue     DECIMAL(12,2)         NULL DEFAULT NULL          COMMENT 'Revenue projected from internal RAF',
  actual_revenue        DECIMAL(12,2)         NULL DEFAULT NULL          COMMENT 'Actual CMS payment received',
  revenue_variance      DECIMAL(12,2)         NULL DEFAULT NULL          COMMENT 'projected_revenue - actual_revenue',
  variance_reason       ENUM(
                          'coding_gap',
                          'hierarchy_change',
                          'sweep_adjustment',
                          'demographic_change',
                          'model_version',
                          'submission_timing',
                          'other'
                        )                     NULL DEFAULT NULL          COMMENT 'Primary reason for the variance',
  status                ENUM(
                          'matched',
                          'underpaid',
                          'overpaid',
                          'unreconciled'
                        )                 NOT NULL DEFAULT 'unreconciled' COMMENT 'Reconciliation outcome',
  notes                 TEXT                  NULL DEFAULT NULL          COMMENT 'Analyst notes',
  created_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_fr_tenant_period_patient (tenant_id, reconciliation_period, patient_id),
  INDEX idx_fr_tenant             (tenant_id),
  INDEX idx_fr_period             (reconciliation_period),
  INDEX idx_fr_patient            (patient_id),
  INDEX idx_fr_status             (status),
  INDEX idx_fr_variance_reason    (variance_reason),
  INDEX idx_fr_tenant_period      (tenant_id, reconciliation_period),
  INDEX idx_fr_revenue_variance   (revenue_variance)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Patient-level financial reconciliation: projected vs actual CMS payment';


-- =============================================================================
-- 4. REVENUE_FORECASTS
--    Periodic snapshots of forward-looking revenue estimates.
-- =============================================================================
CREATE TABLE IF NOT EXISTS revenue_forecasts (
  id                      INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id               VARCHAR(50)       NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  forecast_period         VARCHAR(20)       NOT NULL                     COMMENT 'Target period, e.g. 2025-Q3 or 2025',
  forecast_type           ENUM(
                            'monthly',
                            'quarterly',
                            'annual'
                          )                 NOT NULL DEFAULT 'monthly'   COMMENT 'Granularity of the forecast',
  patient_count           INT UNSIGNED      NOT NULL DEFAULT 0           COMMENT 'Number of members included',
  avg_projected_raf       DECIMAL(8,4)      NOT NULL DEFAULT 0.0000      COMMENT 'Population mean projected RAF',
  total_projected_revenue DECIMAL(14,2)     NOT NULL DEFAULT 0.00        COMMENT 'Base revenue from current RAF scores',
  gap_closure_revenue     DECIMAL(14,2)     NOT NULL DEFAULT 0.00        COMMENT 'Additional revenue from closing identified HCC gaps',
  sweep_adjustment        DECIMAL(14,2)     NOT NULL DEFAULT 0.00        COMMENT 'Expected mid-year or final sweep delta',
  net_forecast            DECIMAL(14,2)     NOT NULL DEFAULT 0.00        COMMENT 'total_projected_revenue + gap_closure_revenue + sweep_adjustment',
  confidence_level        ENUM(
                            'high',
                            'medium',
                            'low'
                          )                 NOT NULL DEFAULT 'medium'    COMMENT 'Analyst confidence in the estimate',
  assumptions             JSON                  NULL DEFAULT NULL        COMMENT 'Key assumptions used in the forecast (JSON object)',
  created_by              INT UNSIGNED          NULL DEFAULT NULL        COMMENT 'FK to auth_users.id',
  created_at              DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_rf_tenant          (tenant_id),
  INDEX idx_rf_period          (forecast_period),
  INDEX idx_rf_type            (forecast_type),
  INDEX idx_rf_confidence      (confidence_level),
  INDEX idx_rf_tenant_period   (tenant_id, forecast_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Revenue forecast snapshots based on current RAF pipeline';
