-- =============================================================================
-- Migration: add_phi_access_log
-- Purpose:   Persistent audit trail for every authenticated API request that
--            touches Protected Health Information.  Required for HIPAA
--            §164.312(b) audit controls, HITRUST Domain 12, SOC 2 CC7.2.
--
-- This table is the durable backing store for the phi_audit logger and the
-- new app/middleware/audit_log_middleware.py.
--
-- IMPORTANT:
--   * This table MUST NOT contain PHI field values themselves -- only
--     metadata (user, tenant, action, resource type, resource ID, IP,
--     status, timestamp, optional non-PHI context).
--   * Forward this table to an immutable / WORM sink (S3 Object Lock,
--     CloudWatch Logs, Splunk) for tamper protection.  In MySQL we cannot
--     truly enforce append-only; revoke UPDATE/DELETE from the application
--     account at the GRANT level (see notes at bottom).
--   * Retention: keep a minimum of 6 years (HIPAA).  Hot retention 12 months
--     in MySQL, then archive.
--
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- =============================================================================

USE raf_intelligence;

CREATE TABLE IF NOT EXISTS phi_access_log (
  id                  BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,

  -- Who
  user_id             BIGINT UNSIGNED   NULL          COMMENT 'authenticated user id; NULL for anonymous / pre-auth',
  user_email          VARCHAR(255)      NULL          COMMENT 'denormalized for forensic readability; never PHI',
  tenant_id           BIGINT UNSIGNED   NULL          COMMENT 'tenant scope of the request',
  user_role           VARCHAR(64)       NULL          COMMENT 'role at time of request (provider/coder/auditor/...)',

  -- What
  action              VARCHAR(64)       NOT NULL      COMMENT 'http verb or semantic action: GET/POST/.../EXPORT/RECALC',
  resource_type       VARCHAR(64)       NULL          COMMENT 'patient/encounter/raf_calculation/audit_package/...',
  resource_id         VARCHAR(128)      NULL          COMMENT 'integer or uuid identifier of the resource; NEVER PHI',
  http_method         VARCHAR(8)        NOT NULL,
  request_path        VARCHAR(512)      NOT NULL      COMMENT 'normalized path; path params replaced with :name to avoid PHI',
  query_string_hash   CHAR(64)          NULL          COMMENT 'SHA-256 of normalized query string -- never raw',

  -- How / Where
  status_code         SMALLINT UNSIGNED NOT NULL,
  ip_address          VARBINARY(16)     NULL          COMMENT 'IPv4 or IPv6 packed bytes',
  user_agent_hash     CHAR(64)          NULL          COMMENT 'SHA-256 of UA string (do not store raw to limit fingerprinting)',
  request_id          CHAR(36)          NOT NULL      COMMENT 'UUID per request, also returned in X-Request-Id header',

  -- Timing
  duration_ms         INT UNSIGNED      NULL,
  occurred_at         DATETIME(3)       NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  -- Severity / classification
  severity            ENUM('INFO','LOW','MEDIUM','HIGH','CRITICAL') NOT NULL DEFAULT 'INFO',
  is_phi_access       TINYINT(1)        NOT NULL DEFAULT 0
                                                      COMMENT '1 if request touched PHI tables',
  is_break_glass      TINYINT(1)        NOT NULL DEFAULT 0,
  break_glass_reason  VARCHAR(500)      NULL          COMMENT 'never PHI; justification text',

  -- Optional non-PHI metadata payload (e.g., {count: 42, model_segment: "CNA"})
  metadata_json       JSON              NULL,

  PRIMARY KEY (id),
  KEY idx_phi_log_user_time     (user_id, occurred_at),
  KEY idx_phi_log_tenant_time   (tenant_id, occurred_at),
  KEY idx_phi_log_resource      (resource_type, resource_id),
  KEY idx_phi_log_request       (request_id),
  KEY idx_phi_log_severity_time (severity, occurred_at),
  KEY idx_phi_log_break_glass   (is_break_glass, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='HIPAA / HITRUST / SOC 2 audit trail. PHI metadata only. Append-only.';

-- -----------------------------------------------------------------------------
-- Recommended monthly partitioning to make retention pruning cheap.
-- Apply ONLY in environments large enough to justify partitioning overhead.
-- (Commented out by default; uncomment after capacity planning.)
-- -----------------------------------------------------------------------------
-- ALTER TABLE phi_access_log
--   PARTITION BY RANGE (TO_DAYS(occurred_at)) (
--     PARTITION p2026_01 VALUES LESS THAN (TO_DAYS('2026-02-01')),
--     PARTITION p2026_02 VALUES LESS THAN (TO_DAYS('2026-03-01')),
--     PARTITION p_future VALUES LESS THAN MAXVALUE
--   );

-- -----------------------------------------------------------------------------
-- Append-only enforcement (run as DB super-user, NOT application user):
--
--   GRANT SELECT, INSERT ON raf_intelligence.phi_access_log TO 'raf_app'@'%';
--   REVOKE UPDATE, DELETE ON raf_intelligence.phi_access_log FROM 'raf_app'@'%';
--
-- A separate housekeeping account (with DELETE) handles 6-year retention
-- pruning via a scheduled job, with its own audit trail.
-- -----------------------------------------------------------------------------
