-- =============================================================================
-- Migration: add_atc_hierarchy
-- Adds WHO ATC (Anatomical Therapeutic Chemical) classification + RxNorm bridge.
--
-- Tables:
--   knowledge_graph_concepts   (created if missing — owned by Agent 1, idempotent)
--   knowledge_graph_edges      (created if missing — owned by Agent 1, idempotent)
--   kg_atc_classes             (5-level ATC hierarchy)
--   kg_rxnorm_to_atc           (drug name / RxCUI / NDC -> ATC bridge)
--
-- Idempotent: safe to re-run.  Run against the raf_intelligence database.
--
--   mysql -u root -p raf_intelligence < database/migrations/add_atc_hierarchy.sql
-- =============================================================================

USE raf_intelligence;

-- ---------------------------------------------------------------------------
-- Defensive: create knowledge_graph_concepts / edges if Agent 1 migration has
-- not yet been applied.  These are minimal forms; Agent 1 may extend.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_graph_concepts (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ontology      VARCHAR(40)  NOT NULL,             -- 'atc', 'icd10', 'hcc', 'rxnorm', 'snomed'
  code          VARCHAR(64)  NOT NULL,
  display_name  VARCHAR(255) NOT NULL,
  description   TEXT,
  metadata      JSON         NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ontology_code (ontology, code),
  KEY idx_ontology (ontology),
  KEY idx_display (display_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Knowledge-graph concept nodes (multi-ontology).';

CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_concept_id BIGINT UNSIGNED NOT NULL,
  target_concept_id BIGINT UNSIGNED NOT NULL,
  relation        VARCHAR(60)  NOT NULL,           -- 'has_indication', 'is_a', 'treats', 'maps_to_hcc'
  weight          DECIMAL(5,4) DEFAULT 1.0000,
  metadata        JSON         NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_edge (source_concept_id, target_concept_id, relation),
  KEY idx_source (source_concept_id),
  KEY idx_target (target_concept_id),
  KEY idx_relation (relation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Knowledge-graph edges between concept nodes.';

-- ---------------------------------------------------------------------------
-- ATC classes: 5-level hierarchy.
--   Level 1: A   (anatomical main group, "Alimentary tract and metabolism")
--   Level 2: A10 ("Drugs used in diabetes")
--   Level 3: A10B ("Blood glucose lowering drugs, excl. insulins")
--   Level 4: A10BA ("Biguanides")
--   Level 5: A10BA02 ("metformin")
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_atc_classes (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  atc_code VARCHAR(20) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  level TINYINT NOT NULL,                            -- 1-5
  parent_atc_code VARCHAR(20) NULL,
  concept_id BIGINT UNSIGNED NOT NULL,                  -- FK to knowledge_graph_concepts (ontology=atc)
  indication_concept_ids JSON NULL,                  -- [concept_id, ...] for primary indications
  is_active TINYINT(1) DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_parent (parent_atc_code),
  INDEX idx_level (level),
  CONSTRAINT fk_atc_concept
    FOREIGN KEY (concept_id) REFERENCES knowledge_graph_concepts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='WHO ATC classification — 5-level drug hierarchy.';

-- ---------------------------------------------------------------------------
-- RxNorm bridge: maps drug names + NDCs to ATC + concept.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_rxnorm_to_atc (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  rxcui VARCHAR(20) NULL,                            -- RxNorm Concept Unique Identifier
  drug_name VARCHAR(255) NOT NULL,
  ndc VARCHAR(20) NULL,
  atc_code VARCHAR(20) NOT NULL,
  is_brand TINYINT(1) DEFAULT 0,
  is_generic TINYINT(1) DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_drug (drug_name(80)),
  INDEX idx_rxcui (rxcui),
  INDEX idx_ndc (ndc),
  INDEX idx_atc (atc_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Drug-name / RxCUI / NDC -> ATC code bridge.';
