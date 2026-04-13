-- Migration: add_bundle_tables.sql
-- Created:    2026-04-12
-- Purpose:    Add four tables required for CMS Bundle 1 RAF submission pipeline:
--               enrollment, normalized_encounters, normalized_diagnoses, recapture_gaps
-- Database:   MySQL, utf8mb4_unicode_ci
-- Run order:  Must run AFTER patients and raf_patient_demographics tables exist.
--             normalized_diagnoses depends on normalized_encounters, so order below is strict.

-- ---------------------------------------------------------------------------
-- 1. enrollment
--    Patient enrollment / eligibility tracking for CMS Bundle 1.
--    One row per patient per plan period. MBI + plan_id identify a coverage span.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enrollment (
    enrollment_id          BIGINT       PRIMARY KEY AUTO_INCREMENT,
    patient_id             INT          NOT NULL,
    tenant_id              VARCHAR(50)  DEFAULT 'default',
    mbi                    VARCHAR(32),              -- Medicare Beneficiary Identifier
    plan_id                VARCHAR(50),              -- H contract / PBP
    coverage_start         DATE,
    coverage_end           DATE,
    dual_status            VARCHAR(20),              -- Full, Partial, Non-Dual, FBDE, PBDE, etc.
    orec                   VARCHAR(10),              -- Original Reason for Entitlement Code
    institutional_status   BOOLEAN      DEFAULT FALSE,
    esrd_status            BOOLEAN      DEFAULT FALSE,
    raf_demographic_score  DECIMAL(6,3),
    age_band               VARCHAR(20),
    disability_status      BOOLEAN      DEFAULT FALSE,
    created_at             TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_enrollment_patient (patient_id),
    INDEX idx_enrollment_tenant  (tenant_id),
    INDEX idx_enrollment_mbi     (mbi),
    INDEX idx_enrollment_plan    (plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 2. normalized_encounters
--    Local mirror of OpenEMR encounters, used as the authoritative source for
--    CMS submission. Linked back to OpenEMR via openemr_encounter_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS normalized_encounters (
    encounter_id          BIGINT       PRIMARY KEY AUTO_INCREMENT,
    patient_id            INT          NOT NULL,
    tenant_id             VARCHAR(50)  DEFAULT 'default',
    openemr_encounter_id  INT,                      -- FK to OpenEMR form_encounter
    provider_npi          VARCHAR(20),
    provider_id           INT,
    encounter_date        DATE         NOT NULL,
    encounter_type        VARCHAR(50),              -- office_visit, telehealth, inpatient, etc.
    facility              VARCHAR(255),
    facility_tin          VARCHAR(20),
    place_of_service      VARCHAR(10),
    status                VARCHAR(20)  DEFAULT 'active', -- active, cancelled, entered-in-error
    created_at            TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_ne_patient  (patient_id),
    INDEX idx_ne_tenant   (tenant_id),
    INDEX idx_ne_date     (encounter_date),
    INDEX idx_ne_provider (provider_npi),
    INDEX idx_ne_openemr  (openemr_encounter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 3. normalized_diagnoses
--    Local mirror of diagnoses linked to normalized_encounters.
--    Tracks HCC mapping version (V24/V28) and diagnosis source for audit.
--    Depends on normalized_encounters; must be created after it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS normalized_diagnoses (
    diagnosis_id   BIGINT       PRIMARY KEY AUTO_INCREMENT,
    encounter_id   BIGINT       NOT NULL,
    patient_id     INT          NOT NULL,
    tenant_id      VARCHAR(50)  DEFAULT 'default',
    icd10_code     VARCHAR(10)  NOT NULL,
    description    VARCHAR(500),
    is_primary     BOOLEAN      DEFAULT FALSE,
    source         VARCHAR(50)  DEFAULT 'emr',      -- emr, ai, imported, claims, manual
    hcc_code       VARCHAR(10),
    model_version  VARCHAR(10),                     -- V24, V28
    status         VARCHAR(20)  DEFAULT 'active',   -- active, deleted, entered-in-error
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (encounter_id) REFERENCES normalized_encounters(encounter_id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id)   REFERENCES patients(id)                        ON DELETE CASCADE,
    INDEX idx_nd_encounter (encounter_id),
    INDEX idx_nd_patient   (patient_id),
    INDEX idx_nd_icd10     (icd10_code),
    INDEX idx_nd_hcc       (hcc_code, model_version),
    INDEX idx_nd_tenant    (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 4. recapture_gaps
--    Persistent storage for HCC recapture gap detection.
--    A unique constraint on (patient_id, hcc_code, prior_year, current_year)
--    prevents duplicate gap rows across pipeline re-runs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recapture_gaps (
    id                  BIGINT        PRIMARY KEY AUTO_INCREMENT,
    patient_id          INT           NOT NULL,
    tenant_id           VARCHAR(50)   DEFAULT 'default',
    hcc_code            VARCHAR(10)   NOT NULL,
    icd10_code          VARCHAR(10),
    prior_year          INT           NOT NULL,
    current_year        INT           NOT NULL,
    status              VARCHAR(20)   DEFAULT 'open', -- open, recaptured, dismissed
    last_encounter_date DATE,
    provider_npi        VARCHAR(20),
    revenue_impact      DECIMAL(10,2),
    resolved_at         TIMESTAMP     NULL,
    resolved_by         VARCHAR(100),
    created_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_rg_patient (patient_id),
    INDEX idx_rg_tenant  (tenant_id),
    INDEX idx_rg_status  (status),
    INDEX idx_rg_hcc     (hcc_code),
    INDEX idx_rg_years   (prior_year, current_year),
    UNIQUE KEY uk_rg_patient_hcc_year (patient_id, hcc_code, prior_year, current_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Seed: populate enrollment from existing patients + raf_patient_demographics
--
-- Uses INSERT IGNORE so the statement is idempotent on re-runs.
-- Only inserts patients that do not already have an enrollment row.
-- Demographic flags default to 0 / FALSE when no demographics row exists.
-- ---------------------------------------------------------------------------
INSERT IGNORE INTO enrollment
    (patient_id, tenant_id, mbi, institutional_status, esrd_status, disability_status)
SELECT
    p.id,
    p.tenant_id,
    p.mbi,
    COALESCE(d.institutional, 0),
    0,
    COALESCE(d.disabled,      0)
FROM patients p
LEFT JOIN raf_patient_demographics d ON d.patient_id = p.id;
