-- ============================================================================
-- Recapture MEAT Audit Trail — schema additions
-- ----------------------------------------------------------------------------
-- Adds dual-coder review workflow + MEAT evidence capture columns to
-- recapture_gaps so each recaptured HCC carries the audit trail CMS RADV
-- auditors expect (per Apixio / Cotiviti compliance baseline).
--
-- Columns
--   evidence_phrase         — free-text quoted snippet from chart note
--   evidence_source_url     — deep-link / FHIR ref so auditors can click through
--   meat_element            — which MEAT criterion the phrase satisfies
--   primary_coder_id        — users.id of the coder who attached evidence
--   primary_coded_at        — when evidence was first attached
--   secondary_coder_id      — users.id of the reviewing coder
--   secondary_approved_at   — when the reviewer approved
--   audit_status            — workflow state machine
--   audit_notes             — free-text notes from coders / reviewers
--
-- Use IF NOT EXISTS where MySQL supports it; otherwise wrap in idempotent
-- prepared blocks via the migration runner.  These columns are nullable so
-- the migration is safe on a populated table.
-- ============================================================================

ALTER TABLE recapture_gaps
    ADD COLUMN evidence_phrase TEXT NULL,
    ADD COLUMN evidence_source_url VARCHAR(500) NULL,
    ADD COLUMN meat_element ENUM('M','E','A','T','MULTI') NULL,
    ADD COLUMN primary_coder_id INT NULL,
    ADD COLUMN primary_coded_at DATETIME NULL,
    ADD COLUMN secondary_coder_id INT NULL,
    ADD COLUMN secondary_approved_at DATETIME NULL,
    ADD COLUMN audit_status ENUM('draft','primary_coded','review_pending','approved','rejected') NOT NULL DEFAULT 'draft',
    ADD COLUMN audit_notes TEXT NULL;

CREATE INDEX idx_audit_status ON recapture_gaps(audit_status);
