-- Migration: Knowledge-Graph Evidence Rules
-- Adds the kg_evidence_rules table that backs the literature-attributed
-- clinical rules engine (RAF/HCC suspect generation).
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS kg_evidence_rules (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  rule_name VARCHAR(255) NOT NULL,
  rule_description TEXT,
  trigger_logic ENUM('all','any') NOT NULL DEFAULT 'all',
  trigger_conditions JSON NOT NULL,
  output_hcc VARCHAR(20) NOT NULL,
  output_icd10 VARCHAR(16) NULL,
  confidence DECIMAL(5,4) DEFAULT 0.7500,
  source_type ENUM(
    'CMS-HCC-spec',
    'AHA-CodingClinic',
    'AAFP',
    'USPSTF',
    'ACC-AHA-guideline',
    'ADA-guideline',
    'GOLD-guideline',
    'KDIGO',
    'APA-DSM5',
    'peer-reviewed',
    'curated'
  ) NOT NULL,
  source_citation TEXT NOT NULL,
  source_url VARCHAR(500),
  source_year SMALLINT,
  model_version VARCHAR(20) DEFAULT 'V28',
  is_active TINYINT(1) DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_rule_name (rule_name),
  INDEX idx_output_hcc (output_hcc),
  INDEX idx_source_type (source_type)
) CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Defensive: Agent 1 owns these but if absent we still want kg_* to load.
CREATE TABLE IF NOT EXISTS knowledge_graph_concepts (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  concept_code VARCHAR(64) NOT NULL,
  concept_type VARCHAR(32) NOT NULL,
  display_name VARCHAR(255),
  metadata JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_kgc_code_type (concept_code, concept_type)
) CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  src_id INT UNSIGNED NOT NULL,
  dst_id INT UNSIGNED NOT NULL,
  edge_type VARCHAR(64) NOT NULL,
  weight DECIMAL(6,4) DEFAULT 1.0000,
  metadata JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_kge_src (src_id),
  INDEX idx_kge_dst (dst_id),
  INDEX idx_kge_type (edge_type)
) CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
