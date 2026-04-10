-- =============================================================================
-- RAF Intelligence — Database Migration
-- Version: 2026-04 — ESRD Segments, New Enrollee, Frailty, Sweep Period
-- =============================================================================
-- Run this migration ONCE on an existing deployment to add support for:
--   1. ESRD model segments (ESRD_DLY, ESRD_FG, ESRD_NE) in all ENUMs
--   2. New Enrollee segments (NE, NE_CNA, NE_CND, NE_CFA, NE_CFD, NE_CPA, NE_CPD)
--   3. enrollment_months column in raf_patient_demographics
--   4. sweep_period + dos_start + dos_end columns in raf_scores
--   5. frailty_addend + frailty_adl_count + plan_type columns in raf_scores
--   6. new_enrollee flag column in raf_scores
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Extend model_segment ENUM in raf_patient_demographics
-- ---------------------------------------------------------------------------
-- NOTE: MySQL MODIFY COLUMN on an ENUM is idempotent — re-running is safe.
ALTER TABLE raf_patient_demographics
    MODIFY COLUMN model_segment ENUM(
        'CNA','CND','CFA','CFD','CPA','CPD','INS',
        'NE','NE_CNA','NE_CND','NE_CFA','NE_CFD','NE_CPA','NE_CPD',
        'ESRD_DLY','ESRD_FG','ESRD_NE'
    ) NOT NULL DEFAULT 'CNA';

-- ---------------------------------------------------------------------------
-- 2. Add enrollment_months and plan_type to raf_patient_demographics
-- ---------------------------------------------------------------------------
ALTER TABLE raf_patient_demographics
    ADD COLUMN IF NOT EXISTS enrollment_months TINYINT UNSIGNED NOT NULL DEFAULT 12
        COMMENT 'Months of Part B enrollment in the measurement year (1-12)',
    ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) NOT NULL DEFAULT 'MA'
        COMMENT 'CMS plan type: MA, PACE, FIDE_SNP, etc.';

-- ---------------------------------------------------------------------------
-- 3. Extend model_segment ENUM in raf_scores
-- ---------------------------------------------------------------------------
ALTER TABLE raf_scores
    MODIFY COLUMN model_segment ENUM(
        'CNA','CND','CFA','CFD','CPA','CPD','INS',
        'NE','NE_CNA','NE_CND','NE_CFA','NE_CFD','NE_CPA','NE_CPD',
        'ESRD_DLY','ESRD_FG','ESRD_NE'
    ) NOT NULL DEFAULT 'CNA';

-- ---------------------------------------------------------------------------
-- 4. Add new fields to raf_scores
-- ---------------------------------------------------------------------------
ALTER TABLE raf_scores
    ADD COLUMN IF NOT EXISTS new_enrollee BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT 'True if patient has < 12 months Part B enrollment (NE demographic-only model)',
    ADD COLUMN IF NOT EXISTS enrollment_months TINYINT UNSIGNED NOT NULL DEFAULT 12
        COMMENT 'Months of Part B enrollment used in this score calculation',
    ADD COLUMN IF NOT EXISTS esrd_segment VARCHAR(20) NULL DEFAULT NULL
        COMMENT 'ESRD segment if applicable: ESRD_DLY, ESRD_FG, ESRD_NE',
    ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) NOT NULL DEFAULT 'MA'
        COMMENT 'CMS plan type used in this calculation',
    ADD COLUMN IF NOT EXISTS frailty_adl_count TINYINT UNSIGNED NULL DEFAULT NULL
        COMMENT 'Number of ADL impairments (0-6) from frailty assessment',
    ADD COLUMN IF NOT EXISTS frailty_addend DECIMAL(8,4) NULL DEFAULT NULL
        COMMENT 'CMS frailty adjustment addend applied to payment RAF',
    ADD COLUMN IF NOT EXISTS pre_frailty_raf DECIMAL(8,4) NULL DEFAULT NULL
        COMMENT 'Payment RAF before frailty adjustment (for audit trail)',
    ADD COLUMN IF NOT EXISTS sweep_period VARCHAR(20) NULL DEFAULT NULL
        COMMENT 'CMS sweep period applied: initial, midyear, final',
    ADD COLUMN IF NOT EXISTS dos_start DATE NULL DEFAULT NULL
        COMMENT 'Date-of-service window start for sweep filtering',
    ADD COLUMN IF NOT EXISTS dos_end DATE NULL DEFAULT NULL
        COMMENT 'Date-of-service window end for sweep filtering';

-- ---------------------------------------------------------------------------
-- 5. Extend model_segment ENUM in hcc_raf_coefficients (if table exists)
-- ---------------------------------------------------------------------------
ALTER TABLE hcc_raf_coefficients
    MODIFY COLUMN model_segment ENUM(
        'CNA','CND','CFA','CFD','CPA','CPD','INS',
        'NE','NE_CNA','NE_CND','NE_CFA','NE_CFD','NE_CPA','NE_CPD',
        'ESRD_DLY','ESRD_FG','ESRD_NE'
    ) NOT NULL DEFAULT 'CNA';

-- ---------------------------------------------------------------------------
-- 6. Extend model_segment ENUM in hcc_demographic_coefficients (if table exists)
-- ---------------------------------------------------------------------------
ALTER TABLE hcc_demographic_coefficients
    MODIFY COLUMN model_segment ENUM(
        'CNA','CND','CFA','CFD','CPA','CPD','INS',
        'NE','NE_CNA','NE_CND','NE_CFA','NE_CFD','NE_CPA','NE_CPD',
        'ESRD_DLY','ESRD_FG','ESRD_NE'
    ) NOT NULL DEFAULT 'CNA';

-- ---------------------------------------------------------------------------
-- 7. Create frailty_assessments table (new)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS frailty_assessments (
    id                  INT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    patient_id          INT UNSIGNED    NOT NULL,
    measurement_year    SMALLINT        NOT NULL,
    assessment_date     DATE            NULL,
    assessor_name       VARCHAR(200)    NULL,
    assessment_tool     VARCHAR(100)    NULL DEFAULT 'HRA',
    plan_type           VARCHAR(20)     NOT NULL DEFAULT 'PACE',
    -- 6 Core ADLs
    bathing_impaired    BOOLEAN         NOT NULL DEFAULT FALSE,
    dressing_impaired   BOOLEAN         NOT NULL DEFAULT FALSE,
    eating_impaired     BOOLEAN         NOT NULL DEFAULT FALSE,
    toileting_impaired  BOOLEAN         NOT NULL DEFAULT FALSE,
    transferring_impaired BOOLEAN       NOT NULL DEFAULT FALSE,
    continence_impaired BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Computed
    adl_count           TINYINT UNSIGNED NOT NULL DEFAULT 0,
    frailty_addend      DECIMAL(8,4)    NOT NULL DEFAULT 0.0000,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_frailty_patient_year (patient_id, measurement_year),
    INDEX idx_frailty_patient (patient_id),
    INDEX idx_frailty_year (measurement_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='CMS Frailty ADL assessments for PACE and FIDE-SNP plans';

-- ---------------------------------------------------------------------------
-- 8. Create raf_sweep_windows reference table (new)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raf_sweep_windows (
    id              TINYINT UNSIGNED    AUTO_INCREMENT PRIMARY KEY,
    payment_year    SMALLINT            NOT NULL,
    sweep_name      ENUM('initial','midyear','final') NOT NULL,
    dos_start       DATE                NOT NULL,
    dos_end         DATE                NOT NULL,
    cms_deadline    VARCHAR(50)         NULL,
    notes           TEXT                NULL,
    UNIQUE KEY uq_sweep_year_name (payment_year, sweep_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='CMS RAF sweep window definitions per payment year';

-- Populate sweep windows for PY2024-2027
INSERT IGNORE INTO raf_sweep_windows (payment_year, sweep_name, dos_start, dos_end, cms_deadline, notes) VALUES
-- PY2024 (encounter year 2023)
(2024, 'initial', '2023-01-01', '2023-03-31', 'March 2024',   'Q1 diagnoses only'),
(2024, 'midyear', '2023-01-01', '2023-06-30', 'September 2024','H1 diagnoses cumulative'),
(2024, 'final',   '2023-01-01', '2023-12-31', 'January 2025', 'Full year diagnoses'),
-- PY2025 (encounter year 2024)
(2025, 'initial', '2024-01-01', '2024-03-31', 'March 2025',   'Q1 diagnoses only'),
(2025, 'midyear', '2024-01-01', '2024-06-30', 'September 2025','H1 diagnoses cumulative'),
(2025, 'final',   '2024-01-01', '2024-12-31', 'January 2026', 'Full year diagnoses'),
-- PY2026 (encounter year 2025)
(2026, 'initial', '2025-01-01', '2025-03-31', 'March 2026',   'Q1 diagnoses only'),
(2026, 'midyear', '2025-01-01', '2025-06-30', 'September 2026','H1 diagnoses cumulative'),
(2026, 'final',   '2025-01-01', '2025-12-31', 'January 2027', 'Full year diagnoses'),
-- PY2027 (encounter year 2026)
(2027, 'initial', '2026-01-01', '2026-03-31', 'March 2027',   'Q1 diagnoses only'),
(2027, 'midyear', '2026-01-01', '2026-06-30', 'September 2027','H1 diagnoses cumulative'),
(2027, 'final',   '2026-01-01', '2026-12-31', 'January 2028', 'Full year diagnoses');

-- ---------------------------------------------------------------------------
-- Done
-- ---------------------------------------------------------------------------
SELECT 'RAF Intelligence migration v2026-04 completed successfully.' AS migration_status;
