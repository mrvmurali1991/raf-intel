-- =============================================================================
-- Migration: add_specialty_hcc_priors
-- Adds specialty-level HCC priors and a specialty alias table so that
-- suspect detection / AWV ranking can be calibrated to the kind of
-- panel a provider actually carries.
--
-- A cardiologist's panel is enriched in CHF / AFib / AMI;  a nephrologist's
-- panel skews CKD / ESRD / transplant.  These priors let the suspect engine
-- multiply (or de-weight) baseline scores accordingly.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- kg_specialty_hcc_priors
-- One row per (specialty, hcc_code).  prior_weight is a multiplier vs. the
-- generic-PCP baseline (1.0 == no change).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_specialty_hcc_priors (
    id                    INT UNSIGNED NOT NULL AUTO_INCREMENT,
    specialty             VARCHAR(120) NOT NULL COMMENT 'Canonical specialty name (e.g. "Cardiology")',
    hcc_code              VARCHAR(20)  NOT NULL,
    prior_weight          DECIMAL(6,4) NOT NULL COMMENT 'Multiplier vs baseline panel; 1.0 = baseline',
    panel_prevalence_pct  DECIMAL(5,2) NULL     COMMENT 'Typical %% of panel with this HCC for this specialty',
    source                VARCHAR(120) NOT NULL COMMENT 'AAFP-survey | MEDPAR-specialty-mix | curated',
    notes                 TEXT,
    is_active             TINYINT(1)   NOT NULL DEFAULT 1,
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_specialty_hcc (specialty, hcc_code),
    KEY idx_specialty (specialty),
    KEY idx_hcc       (hcc_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Specialty-level HCC priors used to calibrate suspect detection.';


-- -----------------------------------------------------------------------------
-- kg_specialty_aliases
-- Free-text specialty strings appear in many forms in source EHRs ("IM",
-- "Internal Med", "Internal Medicine", "GenInternalMedicine"...).  This
-- alias table maps any raw form to a canonical name used by the priors table.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_specialty_aliases (
    id                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    raw_specialty        VARCHAR(255) NOT NULL,
    canonical_specialty  VARCHAR(120) NOT NULL,
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_raw_specialty (raw_specialty),
    KEY idx_canonical (canonical_specialty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Mapping of free-text specialty strings to canonical specialty names.';
