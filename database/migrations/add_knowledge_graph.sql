-- =============================================================================
-- Migration: add_knowledge_graph
-- Foundation tables for the clinical knowledge-graph used by the
-- SNOMED CT mapping service (concept resolution, SNOMED → ICD-10
-- → HCC traversal).
--
-- Idempotent: safe to re-run.  Run against the raf_intelligence database.
--
--   mysql -u root -p raf_intelligence < database/migrations/add_knowledge_graph.sql
--
-- Notes
-- -----
-- * Schema is documented and shared with the SNOMED CT mapping service
--   (backend/app/services/knowledge_graph/snomed_service.py).
-- * Both tables use utf8mb4_0900_ai_ci to match the project standard.
-- * Owned by Agent 1 (foundation); Agent 2 (this branch) seeds SNOMED
--   concepts + maps_to edges into them.
-- =============================================================================

USE raf_intelligence;

-- ---------------------------------------------------------------------------
-- Concepts table -- one row per ontology concept (SNOMED, ICD-10, HCC, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_graph_concepts (
  id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  concept_uri     VARCHAR(255)     NOT NULL
                                   COMMENT 'Canonical URI, e.g. snomed:44054006',
  ontology        VARCHAR(32)      NOT NULL
                                   COMMENT 'snomed | icd10 | hcc | rxnorm | loinc',
  code            VARCHAR(64)      NOT NULL
                                   COMMENT 'Native code within the ontology',
  preferred_label VARCHAR(512)     NOT NULL,
  semantic_type   VARCHAR(128)     NULL
                                   COMMENT 'Disorder | Finding | Procedure | etc.',
  definition      TEXT             NULL,
  is_active       TINYINT(1)       NOT NULL DEFAULT 1,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_kg_concept_uri (concept_uri),
  UNIQUE KEY uq_kg_ontology_code (ontology, code),
  KEY idx_kg_concept_label (preferred_label(191)),
  KEY idx_kg_concept_ontology (ontology, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Knowledge-graph concept nodes (SNOMED, ICD-10, HCC, ...).';

-- ---------------------------------------------------------------------------
-- Edges table -- typed relations between concepts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
  id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  src_concept_id  BIGINT UNSIGNED  NOT NULL,
  dst_concept_id  BIGINT UNSIGNED  NOT NULL,
  edge_type       VARCHAR(64)      NOT NULL
                                   COMMENT 'maps_to | is_a | finding_site | causes | ...',
  weight          DECIMAL(6,4)     NOT NULL DEFAULT 1.0000,
  source          VARCHAR(64)      NULL
                                   COMMENT 'CMS-V28 | CMS-V24 | UMLS | manual | ...',
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_kg_edge (src_concept_id, dst_concept_id, edge_type, source),
  KEY idx_kg_edge_src   (src_concept_id, edge_type),
  KEY idx_kg_edge_dst   (dst_concept_id, edge_type),
  KEY idx_kg_edge_type  (edge_type),
  KEY idx_kg_edge_source (source),
  CONSTRAINT fk_kg_edge_src
    FOREIGN KEY (src_concept_id) REFERENCES knowledge_graph_concepts(id)
    ON DELETE CASCADE,
  CONSTRAINT fk_kg_edge_dst
    FOREIGN KEY (dst_concept_id) REFERENCES knowledge_graph_concepts(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Typed relations between knowledge_graph_concepts rows.';
