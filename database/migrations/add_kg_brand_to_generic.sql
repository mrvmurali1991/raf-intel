-- =============================================================================
-- Migration: add_kg_brand_to_generic
-- Adds the brand-name <-> generic-name mapping table used by the polypharmacy
-- and brand-bridge services to resolve common US trade names (Ozempic,
-- Eliquis, Lipitor, ...) back to their generic ingredients (semaglutide,
-- apixaban, atorvastatin) and through to ATC.
--
-- Source data: FDA Orange Book + DailyMed + curated reference list maintained
-- in backend/scripts/seed_brand_to_generic.py.
--
-- Idempotent: safe to re-run.  Run against the raf_intelligence database.
--
--   mysql -u root -p raf_intelligence < database/migrations/add_kg_brand_to_generic.sql
-- =============================================================================

USE raf_intelligence;

CREATE TABLE IF NOT EXISTS kg_brand_to_generic (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  brand_name VARCHAR(120) NOT NULL,
  generic_name VARCHAR(120) NOT NULL,
  rxcui_brand VARCHAR(20) NULL,
  rxcui_generic VARCHAR(20) NULL,
  atc_code VARCHAR(20) NULL,
  manufacturer VARCHAR(120) NULL,
  notes TEXT,
  is_active TINYINT(1) DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_brand (brand_name),
  INDEX idx_generic (generic_name),
  INDEX idx_atc (atc_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Brand name -> generic ingredient mapping (FDA Orange Book + curated).';
