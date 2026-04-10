-- =============================================================================
-- RAF Intelligence System - Migration 003: Provider Data Model & Scorecards
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Depends on: schema.sql (raf_patient_demographics, raf_suspect_conditions)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. PROVIDERS
--    Registry of providers/doctors participating in RAF management.
--    NPI is the authoritative national identifier; tenant_id supports
--    multi-practice deployments sharing one database instance.
-- =============================================================================
CREATE TABLE IF NOT EXISTS providers (
  id                   INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id            VARCHAR(50)     NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  npi                  VARCHAR(10)     NOT NULL                     COMMENT 'National Provider Identifier (10-digit)',
  first_name           VARCHAR(100)    NOT NULL DEFAULT '',
  last_name            VARCHAR(100)    NOT NULL DEFAULT '',
  credential           VARCHAR(20)     NULL DEFAULT NULL            COMMENT 'MD, DO, NP, PA, etc.',
  specialty            VARCHAR(100)    NULL DEFAULT NULL            COMMENT 'e.g. Internal Medicine, Cardiology',
  specialty_category   ENUM('pcp','specialist','hospitalist','other')
                                       NOT NULL DEFAULT 'pcp',
  practice_name        VARCHAR(255)    NULL DEFAULT NULL,
  email                VARCHAR(255)    NULL DEFAULT NULL,
  phone                VARCHAR(20)     NULL DEFAULT NULL,
  openemr_user_id      INT UNSIGNED    NULL DEFAULT NULL            COMMENT 'FK to OpenEMR users.id (nullable — not all providers have a portal account)',
  status               ENUM('active','inactive')
                                       NOT NULL DEFAULT 'active',
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_provider_tenant_npi    (tenant_id, npi),
  KEY idx_provider_specialty           (specialty),
  KEY idx_provider_specialty_category  (specialty_category),
  KEY idx_provider_status              (status),
  KEY idx_provider_openemr_user        (openemr_user_id),
  KEY idx_provider_last_name           (last_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Registry of providers participating in RAF management, keyed by NPI';


-- =============================================================================
-- 2. PROVIDER_PATIENT_PANEL
--    Defines the patient population attributed or assigned to each provider.
--    A patient may appear in multiple panels (e.g. attributed to PCP and
--    seen by a specialist), distinguished by panel_type.
-- =============================================================================
CREATE TABLE IF NOT EXISTS provider_patient_panel (
  id                   INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  provider_id          INT UNSIGNED    NOT NULL,
  patient_id           INT UNSIGNED    NOT NULL                     COMMENT 'OpenEMR pid',
  panel_type           ENUM('attributed','assigned','seen')
                                       NOT NULL DEFAULT 'attributed' COMMENT 'attributed=payer-assigned; assigned=practice-assigned; seen=encounter-based',
  attribution_date     DATE            NOT NULL,
  last_visit_date      DATE            NULL DEFAULT NULL,
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_panel_provider_patient  (provider_id, patient_id, panel_type),
  KEY idx_panel_patient_id             (patient_id),
  KEY idx_panel_panel_type             (panel_type),
  KEY idx_panel_attribution_date       (attribution_date),
  KEY idx_panel_last_visit_date        (last_visit_date),
  CONSTRAINT fk_panel_provider
    FOREIGN KEY (provider_id)
    REFERENCES providers (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Patient panel membership per provider with attribution type and visit tracking';


-- =============================================================================
-- 3. PROVIDER_SCORECARD_SNAPSHOTS
--    Point-in-time performance snapshot for a provider within a measurement
--    year. Multiple snapshots per year track trending over time (e.g. monthly
--    or quarterly cadence). Revenue figures are in USD.
-- =============================================================================
CREATE TABLE IF NOT EXISTS provider_scorecard_snapshots (
  id                           INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  provider_id                  INT UNSIGNED    NOT NULL,
  measurement_year             YEAR            NOT NULL,
  snapshot_date                DATE            NOT NULL,
  -- Panel counts
  total_patients               INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'Total attributed/assigned patients in panel',
  patients_with_raf            INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'Patients with at least one coded HCC',
  -- RAF summary
  average_raf                  DECIMAL(8,4)    NOT NULL DEFAULT 0.0000 COMMENT 'Mean final_raf across panel',
  -- HCC capture metrics
  total_hccs_captured          INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'HCC conditions actively coded this year',
  total_hccs_possible          INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'Known + suspect HCC opportunities',
  hcc_capture_rate             DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT 'total_hccs_captured / total_hccs_possible; range 0–1',
  recapture_rate               DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT 'Chronic HCCs from prior year re-coded in current year; range 0–1',
  -- Suspect condition pipeline
  suspect_conditions_open      INT UNSIGNED    NOT NULL DEFAULT 0,
  suspect_conditions_accepted  INT UNSIGNED    NOT NULL DEFAULT 0,
  suspect_conditions_dismissed INT UNSIGNED    NOT NULL DEFAULT 0,
  -- Revenue
  revenue_opportunity          DECIMAL(12,2)   NOT NULL DEFAULT 0.00 COMMENT 'Total potential revenue from uncaptured HCCs (USD)',
  revenue_captured             DECIMAL(12,2)   NOT NULL DEFAULT 0.00 COMMENT 'Revenue from HCCs coded this year (USD)',
  -- Documentation quality
  avg_meat_completeness        DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT 'Mean MEAT completeness score across panel HCCs; range 0–1',
  documentation_quality_score  DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT 'Composite: MEAT completeness + ICD specificity + recapture rate; range 0–1',
  -- Benchmarking
  percentile_rank              DECIMAL(5,2)    NULL DEFAULT NULL    COMMENT 'Provider rank vs peer cohort (0.00–100.00); NULL until benchmarks are calculated',
  created_at                   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_scorecard_provider_year_date (provider_id, measurement_year, snapshot_date),
  KEY idx_scorecard_measurement_year         (measurement_year),
  KEY idx_scorecard_snapshot_date            (snapshot_date),
  KEY idx_scorecard_average_raf              (average_raf),
  KEY idx_scorecard_hcc_capture_rate         (hcc_capture_rate),
  KEY idx_scorecard_percentile_rank          (percentile_rank),
  CONSTRAINT fk_scorecard_provider
    FOREIGN KEY (provider_id)
    REFERENCES providers (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Point-in-time provider performance snapshots used for trending and benchmarking';


-- =============================================================================
-- 4. PROVIDER_HCC_PERFORMANCE
--    Per-HCC breakdown of capture rates for each provider and measurement
--    year. Enables drill-down from scorecard summary to specific conditions
--    where a provider under- or over-performs vs peers.
-- =============================================================================
CREATE TABLE IF NOT EXISTS provider_hcc_performance (
  id                       INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  provider_id              INT UNSIGNED    NOT NULL,
  measurement_year         YEAR            NOT NULL,
  hcc_code                 SMALLINT UNSIGNED NOT NULL,
  patients_with_condition  INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'Patients where this HCC is known or suspected',
  patients_coded           INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'Patients where this HCC was coded in the encounter',
  patients_uncoded         INT UNSIGNED    NOT NULL DEFAULT 0   COMMENT 'patients_with_condition minus patients_coded',
  capture_rate             DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT 'patients_coded / patients_with_condition; range 0–1',
  avg_meat_score           DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT 'Mean MEAT completeness for this HCC across the panel; range 0–1',
  revenue_at_stake         DECIMAL(10,2)   NOT NULL DEFAULT 0.00  COMMENT 'Estimated revenue from uncoded patients for this HCC (USD)',
  created_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_hcc_perf_provider_year_hcc (provider_id, measurement_year, hcc_code),
  KEY idx_hcc_perf_hcc_code                (hcc_code),
  KEY idx_hcc_perf_measurement_year        (measurement_year),
  KEY idx_hcc_perf_capture_rate            (capture_rate),
  KEY idx_hcc_perf_revenue_at_stake        (revenue_at_stake),
  CONSTRAINT fk_hcc_perf_provider
    FOREIGN KEY (provider_id)
    REFERENCES providers (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_hcc_perf_crosswalk
    FOREIGN KEY (hcc_code)
    REFERENCES hcc_icd10_crosswalk (hcc_code)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-HCC capture rates and revenue at stake per provider per measurement year';


-- =============================================================================
-- 5. PROVIDER_ALERTS
--    Actionable, patient-level alerts surfaced to providers.
--    Alerts are generated by the RAF engine and dismissed or resolved by
--    clinical staff. A NULL hcc_code is valid for non-HCC alert types
--    (e.g. awv_due).
-- =============================================================================
CREATE TABLE IF NOT EXISTS provider_alerts (
  id           INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  provider_id  INT UNSIGNED    NOT NULL,
  alert_type   ENUM(
                 'suspect_condition',   -- AI-flagged HCC not yet coded
                 'recapture_due',       -- Chronic condition not yet recaptured this year
                 'meat_incomplete',     -- Existing HCC lacks adequate MEAT documentation
                 'awv_due',             -- Annual Wellness Visit overdue
                 'coding_specificity'   -- Unspecified ICD-10 used; more specific code available
               )               NOT NULL,
  patient_id   INT UNSIGNED    NOT NULL                     COMMENT 'OpenEMR pid',
  hcc_code     SMALLINT UNSIGNED NULL DEFAULT NULL          COMMENT 'Relevant HCC; NULL for non-HCC alerts such as awv_due',
  message      TEXT            NOT NULL,
  priority     ENUM('high','medium','low')
                               NOT NULL DEFAULT 'medium',
  status       ENUM('active','acknowledged','resolved')
                               NOT NULL DEFAULT 'active',
  created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at  DATETIME        NULL DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_alert_provider_id    (provider_id),
  KEY idx_alert_patient_id     (patient_id),
  KEY idx_alert_type           (alert_type),
  KEY idx_alert_priority       (priority),
  KEY idx_alert_status         (status),
  KEY idx_alert_hcc_code       (hcc_code),
  -- Composite: primary inbox query — provider's open alerts ordered by priority
  KEY idx_alert_provider_status_priority (provider_id, status, priority),
  CONSTRAINT fk_alert_provider
    FOREIGN KEY (provider_id)
    REFERENCES providers (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Actionable patient-level alerts routed to providers for RAF gap closure';
