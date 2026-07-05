-- ============================================================================
-- Migration: raf_comorbidity_patterns
-- ============================================================================
-- Comorbidity pattern detection for the suspect engine (Strategy 5).
--
-- When a patient has Condition A + Condition B, they very likely also have
-- Condition C (which may be uncoded).  This is the "knowledge graph lite"
-- approach used by RAAPID and similar engines at scale.
--
-- The table stores simple pairwise rules:
--   condition_a_icd + condition_b_icd  =>  suspect_icd10 (suspect_hcc)
--
-- condition_b_icd may be NULL for single-condition upgrade patterns
-- (e.g., DM + CKD already has a more-specific combined code).
--
-- Run with:
--   mysql -u root -p raf_intelligence < scripts/create_comorbidity_patterns.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS raf_comorbidity_patterns (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    condition_a_icd VARCHAR(10)   NOT NULL,
    condition_a_hcc SMALLINT UNSIGNED NULL,
    condition_b_icd VARCHAR(10)   NULL,
    condition_b_hcc SMALLINT UNSIGNED NULL,
    suspect_icd10   VARCHAR(10)   NOT NULL,
    suspect_hcc     SMALLINT UNSIGNED NOT NULL,
    confidence_base DECIMAL(5,4)  NOT NULL DEFAULT 0.6000,
    pattern_name    VARCHAR(100)  NOT NULL,
    notes           VARCHAR(500)  NOT NULL DEFAULT '',
    is_active       TINYINT(1)    NOT NULL DEFAULT 1,
    created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pattern (condition_a_icd, condition_b_icd, suspect_icd10),
    INDEX idx_condition_a (condition_a_icd),
    INDEX idx_condition_b (condition_b_icd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
