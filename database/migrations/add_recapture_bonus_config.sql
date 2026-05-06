-- Migration: add_recapture_bonus_config
--
-- Configuration table for the recapture bonus / coder incentive tracker.
-- Plans that bonus EARLY-year recapture closure see higher rates; the
-- per-tenant config row stores the flat bonus per closed gap and a JSON
-- map of month -> multiplier so coders see a "close now or lose it" curve.
--
-- This table is idempotent: ``CREATE TABLE IF NOT EXISTS`` lets the
-- service code seed-on-read for any tenant that has never been configured.
--
-- Column notes
-- ------------
-- * tenant_id          VARCHAR(64), UNIQUE — one config row per tenant.
-- * bonus_per_closure_default DECIMAL(8,2) — flat $ paid per closed gap.
-- * month_multipliers  JSON                 — {"1": 2.0, ..., "12": 0.3}
-- * active             TINYINT(1)           — kill switch without dropping the row.

CREATE TABLE IF NOT EXISTS recapture_bonus_config (
    id                          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id                   VARCHAR(64)  NOT NULL UNIQUE,
    bonus_per_closure_default   DECIMAL(8,2) NOT NULL DEFAULT 25.00,
    month_multipliers           JSON         NULL,
    active                      TINYINT(1)   NOT NULL DEFAULT 1,
    created_at                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                              ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_recapture_bonus_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
