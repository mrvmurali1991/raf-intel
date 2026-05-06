-- =============================================================================
-- Migration: AI-Suggested Recoding for Recapture Gaps
-- Adds:
--   - recapture_gaps         (persisted gap records, FK target for suggestions)
--   - recapture_ai_suggestions (Gemini-extracted evidence quotes per gap)
--
-- The recapture_gaps table mirrors the live OpenEMR-derived gaps so we can
-- attach durable AI suggestions, accept/reject metadata, and audit trail.
-- The OpenEMR-side query in services/openemr_connector.get_recapture_gaps()
-- continues to be the source of truth for "what is currently a gap"; this
-- table holds the snapshot the coder is acting on.
-- =============================================================================

USE raf_intelligence;

-- ---------------------------------------------------------------------------
-- recapture_gaps: persisted snapshot of an open recapture gap
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recapture_gaps (
  id              INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  tenant_id       INT UNSIGNED     NOT NULL DEFAULT 1,
  patient_id      INT UNSIGNED     NOT NULL,
  icd10_code      VARCHAR(10)      NOT NULL,
  hcc_code        VARCHAR(16)      NULL,
  condition_label VARCHAR(255)     NULL,
  payment_year    YEAR             NOT NULL,
  status          ENUM('open','closed','dismissed') NOT NULL DEFAULT 'open',
  evidence_phrase TEXT             NULL,
  meat_element    ENUM('M','E','A','T') NULL,
  source_note_id  VARCHAR(100)     NULL,
  encounter_date  DATE             NULL,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_recap_patient_year (patient_id, payment_year),
  KEY idx_recap_status (status),
  KEY idx_recap_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Persisted recapture gap snapshot (one row per patient/icd10/year)';


-- ---------------------------------------------------------------------------
-- recapture_ai_suggestions: Gemini-extracted evidence quotes for a gap
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recapture_ai_suggestions (
  id               INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  gap_id           INT UNSIGNED     NOT NULL,
  evidence_phrase  TEXT             NOT NULL,
  confidence       DECIMAL(5,4)     NOT NULL,
  meat_element     ENUM('M','E','A','T') NULL,
  encounter_date   DATE             NULL,
  source_note_id   VARCHAR(100)     NULL,
  llm_model_used   VARCHAR(100)     NULL,
  status           ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
  reviewed_by      VARCHAR(128)     NULL,
  reviewed_at      DATETIME         NULL,
  created_at       DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  INDEX idx_gap (gap_id),
  INDEX idx_status (status),
  CONSTRAINT fk_recap_ai_suggestions_gap
    FOREIGN KEY (gap_id) REFERENCES recapture_gaps(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Gemini-extracted MEAT evidence suggestions for recapture gaps';
