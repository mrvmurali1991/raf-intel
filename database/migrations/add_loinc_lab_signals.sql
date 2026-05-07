-- =============================================================================
-- LOINC integration + lab signal graph
-- =============================================================================
-- Adds the kg_lab_signals table that links LOINC codes (laboratory tests) to
-- knowledge_graph_concepts (suggested conditions) with threshold rules.
--
-- Prerequisite: knowledge_graph_concepts and knowledge_graph_edges tables must
-- already exist (Agent 1 / kg base migration). This migration depends on the
-- foreign key target knowledge_graph_concepts(id).
--
-- Charset / collation: utf8mb4 / utf8mb4_0900_ai_ci (MySQL 8.0+).
-- =============================================================================

CREATE TABLE IF NOT EXISTS kg_lab_signals (
  id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  loinc_code          VARCHAR(20)  NOT NULL,
  test_name           VARCHAR(255) NOT NULL,
  unit                VARCHAR(40)  NULL,
  threshold_low       DECIMAL(10,4) NULL,
  threshold_high      DECIMAL(10,4) NULL,
  threshold_meaning   ENUM('above','below','outside','within') NOT NULL,
  signals_concept_id  BIGINT UNSIGNED NOT NULL,
  confidence          DECIMAL(5,4) DEFAULT 0.7000,
  source              VARCHAR(80)  DEFAULT 'curated',
  notes               TEXT,
  is_active           TINYINT(1) DEFAULT 1,
  created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_loinc (loinc_code),
  INDEX idx_signals (signals_concept_id),
  CONSTRAINT fk_kg_lab_signals_concept
    FOREIGN KEY (signals_concept_id)
    REFERENCES knowledge_graph_concepts(id) ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='LOINC test code -> condition concept signal rules';
