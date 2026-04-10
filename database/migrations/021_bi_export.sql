-- =============================================================================
-- RAF Intelligence System - Migration 021: BI Tools Export
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- Provides connector configuration, dataset definitions, and audit logging
-- for Business Intelligence tool integrations including Tableau, PowerBI,
-- Looker, Metabase, and generic ODBC/API consumers.
--
-- Tables created:
--   bi_connections  – BI tool connection credentials and push configuration
--   bi_datasets     – pre-built and custom dataset definitions with refresh state
--   bi_export_log   – immutable audit trail of every export or push operation
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. BI_CONNECTIONS
--    Stores one record per configured BI tool integration.  Credentials are
--    stored encrypted; the raw secret is never persisted in plaintext.
-- =============================================================================
CREATE TABLE IF NOT EXISTS bi_connections (
  id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  name                VARCHAR(255)    NOT NULL                      COMMENT 'Human-readable label, e.g. "Tableau Cloud – Finance"',
  bi_tool             ENUM(
                        'tableau',
                        'powerbi',
                        'looker',
                        'metabase',
                        'generic_odbc',
                        'generic_api'
                      )               NOT NULL                      COMMENT 'Target BI platform type',
  connection_config   JSON                NULL DEFAULT NULL         COMMENT 'Non-secret config: server URL, site, workspace, etc.',
  api_key_encrypted   TEXT                NULL DEFAULT NULL         COMMENT 'AES-256-GCM encrypted API key / PAT',
  refresh_schedule    VARCHAR(50)         NULL DEFAULT NULL         COMMENT 'Cron expression for automatic push, e.g. "0 6 * * *"',
  last_sync_at        DATETIME            NULL DEFAULT NULL         COMMENT 'UTC timestamp of most recent successful push',
  status              ENUM(
                        'active',
                        'inactive',
                        'error'
                      )               NOT NULL DEFAULT 'active'    COMMENT 'Connection health state',
  error_message       TEXT                NULL DEFAULT NULL         COMMENT 'Last error detail when status = error',
  tenant_id           VARCHAR(50)     NOT NULL DEFAULT 'default'    COMMENT 'Multi-tenant discriminator',
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_tenant_tool  (tenant_id, bi_tool),
  INDEX idx_status       (status),
  INDEX idx_last_sync    (last_sync_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='BI tool connection registry with encrypted credentials';


-- =============================================================================
-- 2. BI_DATASETS
--    Defines datasets available for export.  Each row holds a parameterised
--    SQL template and the column schema that BI tools use to map fields.
--    File exports are written to storage and the path is recorded here.
-- =============================================================================
CREATE TABLE IF NOT EXISTS bi_datasets (
  id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  name                VARCHAR(255)    NOT NULL                      COMMENT 'Dataset display name',
  description         TEXT                NULL DEFAULT NULL         COMMENT 'Purpose and content summary',
  dataset_type        ENUM(
                        'raf_scores',
                        'patient_demographics',
                        'hcc_gaps',
                        'provider_performance',
                        'claims_summary',
                        'quality_metrics',
                        'financial',
                        'custom'
                      )               NOT NULL DEFAULT 'custom'    COMMENT 'Logical dataset category',
  query_template      TEXT                NULL DEFAULT NULL         COMMENT 'Parameterised SQL; use :param_name placeholders',
  columns_config      JSON                NULL DEFAULT NULL         COMMENT 'Array of {name, type, description, phi} column descriptors',
  row_count           INT UNSIGNED        NULL DEFAULT NULL         COMMENT 'Row count from most recent refresh',
  last_refreshed_at   DATETIME            NULL DEFAULT NULL         COMMENT 'UTC timestamp of last successful data refresh',
  refresh_frequency   ENUM(
                        'hourly',
                        'daily',
                        'weekly',
                        'monthly',
                        'on_demand'
                      )               NOT NULL DEFAULT 'on_demand' COMMENT 'Automatic refresh cadence',
  file_path           VARCHAR(512)        NULL DEFAULT NULL         COMMENT 'Server-side path of most recent export file',
  format              ENUM(
                        'csv',
                        'json',
                        'parquet',
                        'xlsx'
                      )               NOT NULL DEFAULT 'csv'       COMMENT 'Default export file format',
  status              ENUM(
                        'ready',
                        'refreshing',
                        'error'
                      )               NOT NULL DEFAULT 'ready'     COMMENT 'Current dataset state',
  error_message       TEXT                NULL DEFAULT NULL         COMMENT 'Last error detail when status = error',
  tenant_id           VARCHAR(50)     NOT NULL DEFAULT 'default'    COMMENT 'Multi-tenant discriminator',
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_tenant_type  (tenant_id, dataset_type),
  INDEX idx_status       (status),
  INDEX idx_refreshed    (last_refreshed_at),
  INDEX idx_format       (format)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Dataset definitions for BI tool export, including pre-built analytics views';


-- =============================================================================
-- 3. BI_EXPORT_LOG
--    Append-only audit log of every export or push operation.  Rows are never
--    updated; a new row is inserted for each attempt.
-- =============================================================================
CREATE TABLE IF NOT EXISTS bi_export_log (
  id                  INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  dataset_id          INT UNSIGNED        NULL DEFAULT NULL         COMMENT 'FK → bi_datasets.id (NULL for ad-hoc exports)',
  connection_id       INT UNSIGNED        NULL DEFAULT NULL         COMMENT 'FK → bi_connections.id (NULL for file downloads)',
  export_type         ENUM(
                        'file',
                        'api_push',
                        'webhook'
                      )               NOT NULL DEFAULT 'file'      COMMENT 'Delivery mechanism',
  row_count           INT UNSIGNED        NULL DEFAULT NULL         COMMENT 'Number of data rows in this export',
  file_size           BIGINT UNSIGNED     NULL DEFAULT NULL         COMMENT 'Bytes written for file exports',
  duration_ms         INT UNSIGNED        NULL DEFAULT NULL         COMMENT 'Total wall-clock time for the export in milliseconds',
  status              ENUM(
                        'success',
                        'failed'
                      )               NOT NULL DEFAULT 'success'   COMMENT 'Outcome of this export attempt',
  error_message       TEXT                NULL DEFAULT NULL         COMMENT 'Failure detail when status = failed',
  exported_by         INT UNSIGNED        NULL DEFAULT NULL         COMMENT 'user_id from users table',
  tenant_id           VARCHAR(50)     NOT NULL DEFAULT 'default'    COMMENT 'Multi-tenant discriminator',
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_dataset    (dataset_id),
  INDEX idx_connection (connection_id),
  INDEX idx_tenant     (tenant_id),
  INDEX idx_status     (status),
  INDEX idx_created    (created_at),
  INDEX idx_user       (exported_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable audit log of every BI export and push operation';
