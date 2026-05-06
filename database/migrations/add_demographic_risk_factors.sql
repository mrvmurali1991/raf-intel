-- =============================================================================
-- Migration: add_demographic_risk_factors
--   Demographic risk modulation table for SUSPECT-DETECTION priors.
--
--   This is intentionally LAYERED ON TOP of the official CMS HCC model:
--     - hcc_raf_coefficients holds the OFFICIAL CMS coefficients (CNA/CFA/...)
--       that power the RAF score the payer is paid on.  Those stay untouched.
--     - kg_demographic_risk_factors holds curated FINER-GRAINED priors
--       (age x sex x dual x conditional-on-prior-HCC) used ONLY by the suspect
--       detection / prior probability layer to better rank which open suspects
--       deserve clinician attention.
--
--   Example: a 67-year-old female dual-eligible with prior CHF coding has a
--   higher prior probability of CKD than a 67-year-old male non-dual with no
--   history.  CMS' segment lumps both under "CFA aged 65-69" — this table
--   restores the missing nuance for triage purposes.
--
--   Naming follows the kg_* convention used by the knowledge graph subsystem
--   (knowledge_graph_concepts, knowledge_graph_edges).
--
-- Idempotent: safe to re-run.
-- Apply with:
--   mysql -u <user> -p raf_intelligence < database/migrations/add_demographic_risk_factors.sql
-- =============================================================================

USE raf_intelligence;

CREATE TABLE IF NOT EXISTS kg_demographic_risk_factors (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  hcc_code          VARCHAR(20)       NOT NULL
                     COMMENT 'Target HCC whose suspect-prior is being modulated',
  age_min           TINYINT           NOT NULL DEFAULT 0,
  age_max           TINYINT           NOT NULL DEFAULT 120,
  sex               ENUM('M','F','U') NULL DEFAULT NULL
                     COMMENT 'NULL = applies to any sex',
  dual_status       ENUM('dual','non_dual','any') NOT NULL DEFAULT 'any',
  disabled          TINYINT(1)        NULL DEFAULT NULL
                     COMMENT 'NULL = ignore, 1 = applies to disabled, 0 = applies to non-disabled',
  institutional     TINYINT(1)        NULL DEFAULT NULL
                     COMMENT 'NULL = ignore, 1 = applies to institutional, 0 = applies to community',
  -- Prior probability multiplier vs the baseline CMS coefficient.
  -- e.g. 1.5000 means 50% higher prior probability for this cohort.
  prior_multiplier  DECIMAL(6,4)      NOT NULL DEFAULT 1.0000,
  -- For comorbidity-conditioned priors: if the patient already has any of
  -- the listed HCCs, this multiplier applies.  NULL = unconditional.
  conditional_on_hccs JSON            NULL DEFAULT NULL
                     COMMENT 'JSON array of HCC codes (strings) the patient must already have',
  source            VARCHAR(120)      NOT NULL
                     COMMENT 'Citation, e.g. MEDPAR-2023, CMS-CCW, curated-AAFP-2024',
  source_notes      TEXT              NULL DEFAULT NULL,
  is_active         TINYINT(1)        NOT NULL DEFAULT 1,
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_hcc       (hcc_code),
  KEY idx_age       (age_min, age_max),
  KEY idx_demo      (sex, dual_status),
  KEY idx_active    (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Demographic and conditional risk-factor multipliers for suspect-detection priors. NOT used by official RAF calc.';
