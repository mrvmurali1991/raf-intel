-- 029_recapture_gaps_irr_labels.sql
--
-- Adds independent coder label columns to recapture_gaps so the
-- inter-rater reliability (IRR) calculation can graduate from simple
-- proportion-agreement to full Cohen's kappa.
--
-- Background (Tier 5 item #13):
--   The current IRR metric in meat_audit_service.compute_audit_readiness()
--   measures the proportion of secondary-reviewed gaps that the secondary
--   coder approved.  This conflates "the secondary coder clicked OK" with
--   "the two coders made independent HCC accept/reject decisions and
--   agreed".  True kappa requires that each coder assigns a label
--   independently before they see the other's decision.
--
-- Schema design:
--   primary_coder_label   — The primary coder's independent HCC category
--                           judgment: 'accept' | 'reject' | NULL (not yet set)
--   secondary_coder_label — The secondary coder's independent label.
--
--   When BOTH columns are non-NULL, the IRR service switches from
--   proportion_agreement to Cohen's kappa (with chance correction).
--   When either column is NULL the service falls back to the legacy
--   proportion_agreement metric so existing rows are unaffected.
--
-- Workflow integration:
--   1. Primary coder submits a gap → sets primary_coder_label via the dual-
--      coder MEAT audit flow (POST /api/recapture/gaps/{id}/primary-review).
--   2. Secondary coder independently reviews the same gap → sets
--      secondary_coder_label before seeing the primary's label
--      (POST /api/recapture/gaps/{id}/secondary-review).
--   3. The IRR endpoint aggregates all rows where both labels are non-NULL and
--      computes κ = (p_o – p_e) / (1 – p_e).

-- MySQL 8.0 does not support ADD COLUMN IF NOT EXISTS on ALTER TABLE, so
-- each column add is wrapped in a procedural existence check against
-- INFORMATION_SCHEMA so this migration is safe to re-run.

DROP PROCEDURE IF EXISTS _add_irr_label_columns;
DELIMITER //
CREATE PROCEDURE _add_irr_label_columns()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'recapture_gaps'
          AND COLUMN_NAME  = 'primary_coder_label'
    ) THEN
        ALTER TABLE recapture_gaps
            ADD COLUMN primary_coder_label
                ENUM('accept', 'reject') NULL DEFAULT NULL
                COMMENT 'Independent HCC label set by the primary coder before dual-coder review';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'recapture_gaps'
          AND COLUMN_NAME  = 'secondary_coder_label'
    ) THEN
        ALTER TABLE recapture_gaps
            ADD COLUMN secondary_coder_label
                ENUM('accept', 'reject') NULL DEFAULT NULL
                COMMENT 'Independent HCC label set by the secondary coder before dual-coder review';
    END IF;
END //
DELIMITER ;
CALL _add_irr_label_columns();
DROP PROCEDURE IF EXISTS _add_irr_label_columns;
