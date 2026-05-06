-- =============================================================================
-- Migration: add_recapture_outreach
-- Adds two tables for the Member Outreach Automation Tracker feature:
--   * recapture_outreach_templates  — reusable message templates per channel
--   * recapture_outreach_events     — per-gap outreach attempts + outcomes
--
-- Idempotent: safe to re-run.  Run against the raf_intelligence database.
--
--   mysql -u root -p raf_intelligence < database/migrations/add_recapture_outreach.sql
-- =============================================================================

USE raf_intelligence;

CREATE TABLE IF NOT EXISTS recapture_outreach_templates (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id       VARCHAR(64) NOT NULL,
  channel         ENUM('sms','portal','phone','email','letter') NOT NULL,
  name            VARCHAR(200) NOT NULL,
  subject         VARCHAR(255) NULL,
  message_text    TEXT NOT NULL,
  trigger_rules   JSON NULL,
  is_active       TINYINT(1) NOT NULL DEFAULT 1,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                          ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_tpl_tenant  (tenant_id),
  KEY idx_tpl_channel (channel),
  KEY idx_tpl_active  (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Reusable outreach message templates for recapture campaigns';

CREATE TABLE IF NOT EXISTS recapture_outreach_events (
  id                    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id             VARCHAR(64) NOT NULL,
  gap_id                INT UNSIGNED NOT NULL,
  patient_id            VARCHAR(64) NOT NULL,
  template_id           INT UNSIGNED NULL,
  channel               ENUM('sms','portal','phone','email','letter') NOT NULL,
  status                ENUM('queued','sent','delivered','responded','failed','opted_out')
                            NOT NULL DEFAULT 'queued',
  scheduled_for         DATETIME NULL,
  sent_at               DATETIME NULL,
  delivered_at          DATETIME NULL,
  responded_at          DATETIME NULL,
  response_text         TEXT NULL,
  resulted_in_visit     TINYINT(1) NOT NULL DEFAULT 0,
  resulted_in_closure   TINYINT(1) NOT NULL DEFAULT 0,
  metadata              JSON NULL,
  created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_oe_tenant   (tenant_id),
  KEY idx_oe_gap      (gap_id),
  KEY idx_oe_patient  (patient_id),
  KEY idx_oe_status   (status),
  KEY idx_oe_channel  (channel),
  CONSTRAINT fk_oe_gap FOREIGN KEY (gap_id)
    REFERENCES recapture_gaps(id) ON DELETE CASCADE,
  CONSTRAINT fk_oe_template FOREIGN KEY (template_id)
    REFERENCES recapture_outreach_templates(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Per-gap outreach attempts (SMS/portal/phone/email/letter) and outcomes';
