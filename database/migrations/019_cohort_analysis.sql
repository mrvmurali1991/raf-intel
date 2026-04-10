-- =============================================================================
-- RAF Intelligence System - Migration 019: Cohort Analysis
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- Provides population health cohort management with dynamic membership,
-- point-in-time snapshots, and side-by-side cohort comparisons.
--
-- Tables created:
--   cohorts              – cohort definitions and summary statistics
--   cohort_members       – patient membership (with soft-remove support)
--   cohort_snapshots     – historical point-in-time metric captures
--   cohort_comparisons   – persisted two-cohort comparison results
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. COHORTS
--    Defines a named patient population with criteria driving membership.
--    criteria is a JSON object whose shape depends on cohort_type.
--
--    Example criteria shapes:
--      chronic_condition : {"hcc_codes": ["HCC18", "HCC19"]}
--      risk_tier         : {"risk_tiers": ["very_high", "high"]}
--      provider_panel    : {"provider_ids": [5, 12]}
--      payer             : {"payer_names": ["Medicare Advantage"]}
--      geographic        : {"zip_codes": ["10001"], "states": ["NY"]}
--      age_group         : {"min_age": 65, "max_age": 74}
--      custom            : any combination of the above
-- =============================================================================
CREATE TABLE IF NOT EXISTS cohorts (
  id                  INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id           VARCHAR(50)       NOT NULL DEFAULT 'default'  COMMENT 'Multi-tenant discriminator',
  name                VARCHAR(255)      NOT NULL                    COMMENT 'Human-readable cohort name',
  description         TEXT                  NULL DEFAULT NULL       COMMENT 'Optional longer description',
  cohort_type         ENUM(
                        'custom',
                        'chronic_condition',
                        'risk_tier',
                        'provider_panel',
                        'payer',
                        'geographic',
                        'age_group'
                      )                 NOT NULL DEFAULT 'custom'   COMMENT 'Category drives criteria interpretation',
  criteria            JSON              NOT NULL                    COMMENT 'Membership filter definition (type-dependent)',
  patient_count       INT UNSIGNED      NOT NULL DEFAULT 0          COMMENT 'Cached member count, refreshed on each membership refresh',
  avg_raf_score       DECIMAL(8,4)          NULL DEFAULT NULL       COMMENT 'Cached average RAF score across active members',
  total_raf_revenue   DECIMAL(12,2)         NULL DEFAULT NULL       COMMENT 'Projected total RAF revenue (active members)',
  status              ENUM('active','archived')
                                        NOT NULL DEFAULT 'active'   COMMENT 'Archived cohorts are read-only',
  created_by          INT                   NULL DEFAULT NULL       COMMENT 'User ID that created this cohort',
  created_at          DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_tenant_status   (tenant_id, status),
  INDEX idx_cohort_type     (cohort_type),
  INDEX idx_created_by      (created_by),
  INDEX idx_updated_at      (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Cohort definitions for population health analysis';


-- =============================================================================
-- 2. COHORT_MEMBERS
--    Many-to-many between cohorts and patients with soft-remove via removed_at.
--    UNIQUE KEY prevents duplicate active memberships; removed patients can be
--    re-added by clearing removed_at / setting is_active = TRUE.
-- =============================================================================
CREATE TABLE IF NOT EXISTS cohort_members (
  id          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  cohort_id   INT UNSIGNED  NOT NULL                    COMMENT 'FK → cohorts.id',
  patient_id  INT           NOT NULL                    COMMENT 'OpenEMR patient_data.pid',
  added_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  removed_at  DATETIME          NULL DEFAULT NULL       COMMENT 'NULL = still active member',
  is_active   TINYINT(1)    NOT NULL DEFAULT 1          COMMENT '1 = current member, 0 = removed',

  PRIMARY KEY (id),
  UNIQUE KEY uq_cohort_patient (cohort_id, patient_id),
  INDEX idx_cohort_active  (cohort_id, is_active),
  INDEX idx_patient        (patient_id),
  CONSTRAINT fk_cm_cohort
    FOREIGN KEY (cohort_id) REFERENCES cohorts (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Individual patient members of a cohort';


-- =============================================================================
-- 3. COHORT_SNAPSHOTS
--    Point-in-time metric captures for trend analysis.
--    Each snapshot records aggregate stats for a cohort on a given date so
--    changes in RAF score, risk distribution, revenue, etc. can be tracked.
--
--    JSON column contents (guidance):
--      gender_distribution     : {"M": 120, "F": 95, "U": 3}
--      top_hccs                : [{"code": "HCC18", "count": 42, "prevalence": 0.19}, ...]
--      risk_tier_distribution  : {"very_high": 20, "high": 45, "moderate": 60, ...}
--      metrics                 : arbitrary additional metrics (extensible)
-- =============================================================================
CREATE TABLE IF NOT EXISTS cohort_snapshots (
  id                      INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  cohort_id               INT UNSIGNED    NOT NULL                  COMMENT 'FK → cohorts.id',
  tenant_id               VARCHAR(50)     NOT NULL DEFAULT 'default',
  snapshot_date           DATE            NOT NULL                  COMMENT 'Date this snapshot was taken',
  patient_count           INT UNSIGNED    NOT NULL DEFAULT 0,
  avg_raf_score           DECIMAL(8,4)        NULL DEFAULT NULL,
  avg_age                 DECIMAL(5,2)        NULL DEFAULT NULL,
  gender_distribution     JSON                NULL DEFAULT NULL,
  top_hccs                JSON                NULL DEFAULT NULL,
  risk_tier_distribution  JSON                NULL DEFAULT NULL,
  total_revenue           DECIMAL(12,2)       NULL DEFAULT NULL,
  metrics                 JSON                NULL DEFAULT NULL     COMMENT 'Extensible additional metrics',
  created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_cohort_date   (cohort_id, snapshot_date),
  INDEX idx_tenant_date   (tenant_id, snapshot_date),
  CONSTRAINT fk_cs_cohort
    FOREIGN KEY (cohort_id) REFERENCES cohorts (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Historical snapshots of cohort aggregate metrics';


-- =============================================================================
-- 4. COHORT_COMPARISONS
--    Persisted results of a side-by-side two-cohort statistical comparison.
--
--    JSON column contents (guidance):
--      metrics_a / metrics_b        : {"avg_raf": 1.42, "patient_count": 218, ...}
--      differences                  : {"avg_raf_delta": 0.23, "avg_raf_pct_change": 16.2, ...}
--      statistical_significance     : {"avg_raf_p_value": 0.003, "avg_raf_significant": true, ...}
-- =============================================================================
CREATE TABLE IF NOT EXISTS cohort_comparisons (
  id                        INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id                 VARCHAR(50)     NOT NULL DEFAULT 'default',
  name                      VARCHAR(255)        NULL DEFAULT NULL   COMMENT 'Optional label for the comparison',
  cohort_a_id               INT UNSIGNED    NOT NULL                COMMENT 'FK → cohorts.id (reference cohort)',
  cohort_b_id               INT UNSIGNED    NOT NULL                COMMENT 'FK → cohorts.id (comparison cohort)',
  comparison_date           DATE            NOT NULL                COMMENT 'Date on which the comparison was run',
  metrics_a                 JSON                NULL DEFAULT NULL   COMMENT 'Aggregate metrics for cohort A',
  metrics_b                 JSON                NULL DEFAULT NULL   COMMENT 'Aggregate metrics for cohort B',
  differences               JSON                NULL DEFAULT NULL   COMMENT 'Computed delta between A and B',
  statistical_significance  JSON                NULL DEFAULT NULL   COMMENT 'p-values and significance flags per metric',
  created_by                INT                 NULL DEFAULT NULL,
  created_at                DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_tenant_date     (tenant_id, comparison_date),
  INDEX idx_cohort_a        (cohort_a_id),
  INDEX idx_cohort_b        (cohort_b_id),
  CONSTRAINT fk_cc_cohort_a
    FOREIGN KEY (cohort_a_id) REFERENCES cohorts (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_cc_cohort_b
    FOREIGN KEY (cohort_b_id) REFERENCES cohorts (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Persisted side-by-side cohort comparison results';
