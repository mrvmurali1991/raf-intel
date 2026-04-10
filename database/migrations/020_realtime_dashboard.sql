-- =============================================================================
-- Migration 020: Real-Time Dashboard Support
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Adds tables for persistent dashboard layout configs and
--              transient alert notifications delivered via SSE/WebSocket.
--              Alerts are soft-deleted by marking is_read; the read_at
--              timestamp provides an audit trail.
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. DASHBOARD_CONFIGS
--    One row per saved layout.  A user may have multiple named dashboards;
--    exactly one can be flagged is_default = TRUE per user.
-- =============================================================================

CREATE TABLE IF NOT EXISTS dashboard_configs (
  id           INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  user_id      INT            NOT NULL                        COMMENT 'FK → users.id (not enforced cross-DB)',
  name         VARCHAR(200)   NOT NULL                        COMMENT 'Human-readable label, e.g. "My RAF Overview"',
  layout       JSON           NOT NULL                        COMMENT 'Grid layout descriptor: breakpoints, positions, sizes',
  widgets      JSON           NOT NULL                        COMMENT 'Array of widget definitions: type, title, config',
  is_default   TINYINT(1)     NOT NULL DEFAULT 0              COMMENT '1 = show this layout on login',
  tenant_id    VARCHAR(64)    NOT NULL DEFAULT 'default'      COMMENT 'Multi-tenant partition key',
  created_at   DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at   DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                                        ON UPDATE CURRENT_TIMESTAMP(3),

  PRIMARY KEY (id),
  INDEX idx_dc_user       (user_id),
  INDEX idx_dc_tenant     (tenant_id),
  INDEX idx_dc_user_default (user_id, is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Saved dashboard layout and widget configurations per user';


-- =============================================================================
-- 2. DASHBOARD_ALERTS
--    Persisted notifications pushed to connected clients via SSE/WebSocket.
--    Written by application services; read/dismissed by the frontend.
-- =============================================================================

CREATE TABLE IF NOT EXISTS dashboard_alerts (
  id             INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  alert_type     ENUM(
                   'raf_change',
                   'new_suspect',
                   'gap_closed',
                   'attestation_needed',
                   'awv_due',
                   'claim_processed',
                   'system'
                 )              NOT NULL                        COMMENT 'Semantic category for icon / routing on the frontend',
  severity       ENUM('info', 'warning', 'critical')
                               NOT NULL DEFAULT 'info'          COMMENT 'Visual urgency level',
  title          VARCHAR(300)  NOT NULL                         COMMENT 'Short, single-line summary (shown in the badge pop-over)',
  message        TEXT          NULL                             COMMENT 'Optional expanded detail rendered in alert drawer',
  patient_id     VARCHAR(64)   NULL DEFAULT NULL                COMMENT 'OpenEMR pid when alert relates to a specific patient',
  provider_npi   VARCHAR(20)   NULL DEFAULT NULL                COMMENT 'NPI when alert relates to a specific provider',
  metadata       JSON          NULL DEFAULT NULL                COMMENT 'Arbitrary extra context (claim_id, gap_id, score delta, …)',
  is_read        TINYINT(1)    NOT NULL DEFAULT 0               COMMENT '0 = unread (badge visible), 1 = dismissed',
  user_id        INT           NOT NULL                         COMMENT 'Recipient user; FK → users.id (not enforced cross-DB)',
  tenant_id      VARCHAR(64)   NOT NULL DEFAULT 'default'       COMMENT 'Multi-tenant partition key',
  created_at     DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  read_at        DATETIME(3)   NULL DEFAULT NULL                COMMENT 'Timestamp set when user marks alert read',

  PRIMARY KEY (id),
  INDEX idx_da_user_unread  (user_id, is_read, created_at DESC),
  INDEX idx_da_tenant       (tenant_id),
  INDEX idx_da_patient      (patient_id),
  INDEX idx_da_type_sev     (alert_type, severity),
  INDEX idx_da_created      (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Persisted real-time alerts delivered to dashboard clients';
