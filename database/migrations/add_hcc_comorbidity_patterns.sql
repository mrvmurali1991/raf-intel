-- =============================================================================
-- Migration: add_hcc_comorbidity_patterns
-- Purpose:   Curated rules engine that recognises HCC comorbidity patterns
--            (e.g. "DM + retinopathy + nephropathy = uncontrolled with chronic
--            complications HCC 18, not HCC 19").
--
-- Each row in kg_comorbidity_patterns is a single rule with AND-semantics over
-- the contents of `required_evidence`.  Evidence "facts" are encoded as a JSON
-- object with up to four buckets:
--    {
--      "hccs":                 ["19", "108"],
--      "icds":                 ["E11.9", "H35"],
--      "atc_codes":            ["A10A", "N05AH02"],
--      "loinc_with_threshold": [{"loinc": "33914-3", "op": "<", "value": 60}]
--    }
-- A pattern matches when EVERY listed fact is present in the patient's
-- evidence set.  ICD/HCC codes match by prefix (so "H35" matches H35.00 ..
-- H35.9), ATC codes match by prefix (so "A10A" matches A10AB01 etc.), and
-- LOINC entries support the comparison operators >, <, >=, <=, =.
--
-- A pattern that UPGRADES from a less-severe HCC sets `upgrades_from_hcc`
-- (e.g. an HCC 19 patient whose retinopathy is recorded should be promoted
-- to HCC 18).  Otherwise `upgrades_from_hcc` is NULL and the pattern simply
-- ASSERTS the output HCC.
-- =============================================================================

CREATE TABLE IF NOT EXISTS kg_comorbidity_patterns (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  pattern_name VARCHAR(255) NOT NULL,
  description TEXT,
  -- Trigger: comma-separated list of HCC codes / ICD-10 codes / ATC codes / LOINC codes that must ALL be present
  required_evidence JSON NOT NULL,
  -- Output: HCC to suggest (or upgrade to)
  output_hcc VARCHAR(20) NOT NULL,
  output_icd10 VARCHAR(16) NULL,
  -- If this pattern UPGRADES from a less-severe HCC, list which
  upgrades_from_hcc VARCHAR(20) NULL,
  confidence DECIMAL(5,4) DEFAULT 0.8000,
  source VARCHAR(120) NOT NULL,
  source_url VARCHAR(500),
  model_version VARCHAR(20) DEFAULT 'V28',
  is_active TINYINT(1) DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_output (output_hcc),
  INDEX idx_upgrade (upgrades_from_hcc),
  INDEX idx_source (source(40))
) ENGINE=InnoDB CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Curated HCC comorbidity rules — see backend/scripts/seed_comorbidity_patterns.py';
