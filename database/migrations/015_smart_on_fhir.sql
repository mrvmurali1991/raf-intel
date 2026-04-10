-- =============================================================================
-- Migration 015: SMART on FHIR App Launch Support
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Adds tables to support SMART on FHIR EHR-launch and
--              standalone-launch flows for Epic, Cerner, athenahealth, and
--              generic FHIR R4 servers.  Covers app registrations, per-session
--              OAuth2 state + token storage, and a short-lived FHIR resource
--              cache keyed to launch sessions.
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. SMART_APP_REGISTRATIONS
--    One row per EHR tenant / app registration.
--    client_secret_encrypted is AES-256-GCM ciphertext; decrypted at the
--    application layer only — never stored or logged as plaintext.
-- =============================================================================

CREATE TABLE IF NOT EXISTS smart_app_registrations (
  id                       INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  name                     VARCHAR(200)   NOT NULL                         COMMENT 'Human-readable label, e.g. "Epic MyChart – Acme Health"',
  ehr_vendor               ENUM('epic','cerner','athenahealth','generic')
                                          NOT NULL DEFAULT 'generic'       COMMENT 'EHR vendor; controls vendor-specific SMART behaviour',
  client_id                VARCHAR(255)   NOT NULL                         COMMENT 'OAuth2 client_id issued by the EHR',
  client_secret_encrypted  TEXT           NULL DEFAULT NULL                COMMENT 'AES-256-GCM ciphertext of client_secret (NULL for public clients)',
  redirect_uri             VARCHAR(500)   NOT NULL                         COMMENT 'Registered OAuth2 redirect URI',
  scopes                   TEXT           NOT NULL                         COMMENT 'Space-separated SMART scopes, e.g. "launch patient/*.read"',
  launch_url               VARCHAR(500)   NULL DEFAULT NULL                COMMENT 'EHR-launch URL registered in the EHR app gallery',
  fhir_base_url            VARCHAR(500)   NOT NULL                         COMMENT 'FHIR R4 base URL for this registration',
  token_endpoint           VARCHAR(500)   NOT NULL                         COMMENT 'OAuth2 token endpoint',
  authorize_endpoint       VARCHAR(500)   NOT NULL                         COMMENT 'OAuth2 authorization endpoint',
  status                   ENUM('active','inactive')
                                          NOT NULL DEFAULT 'active'        COMMENT 'Registration status; inactive registrations are rejected at launch',
  tenant_id                VARCHAR(50)    NOT NULL DEFAULT 'default'       COMMENT 'Logical tenant / organisation identifier',
  created_at               DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at               DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sar_tenant        (tenant_id),
  KEY idx_sar_vendor        (ehr_vendor),
  KEY idx_sar_status        (status),
  KEY idx_sar_client_id     (client_id),
  KEY idx_sar_tenant_status (tenant_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='SMART on FHIR app registrations per EHR / tenant';


-- =============================================================================
-- 2. SMART_LAUNCH_SESSIONS
--    One row per in-flight or completed SMART launch.
--    PKCE code_verifier and all tokens are stored encrypted.
--    Sessions expire naturally via token_expires_at; a background job may
--    update status to "expired" for housekeeping, but is not required.
-- =============================================================================

CREATE TABLE IF NOT EXISTS smart_launch_sessions (
  id                        INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  registration_id           INT UNSIGNED   NOT NULL                         COMMENT 'FK → smart_app_registrations.id',
  launch_token              VARCHAR(128)   NULL DEFAULT NULL                COMMENT 'Opaque launch parameter supplied by the EHR on EHR-launch',
  state_param               VARCHAR(128)   NOT NULL                         COMMENT 'CSRF state parameter generated at launch initiation',
  code_verifier             VARCHAR(256)   NOT NULL                         COMMENT 'PKCE code_verifier (plain); code_challenge = BASE64URL(SHA256(verifier))',
  access_token_encrypted    TEXT           NULL DEFAULT NULL                COMMENT 'AES-256-GCM ciphertext of the SMART access token',
  refresh_token_encrypted   TEXT           NULL DEFAULT NULL                COMMENT 'AES-256-GCM ciphertext of the SMART refresh token (if issued)',
  patient_fhir_id           VARCHAR(128)   NULL DEFAULT NULL                COMMENT 'FHIR Patient.id from launch context or token response',
  practitioner_fhir_id      VARCHAR(128)   NULL DEFAULT NULL                COMMENT 'FHIR Practitioner.id from launch context',
  encounter_fhir_id         VARCHAR(128)   NULL DEFAULT NULL                COMMENT 'FHIR Encounter.id from launch context (EHR-launch only)',
  token_expires_at          DATETIME       NULL DEFAULT NULL                COMMENT 'UTC expiry derived from access token expires_in',
  status                    ENUM('initiated','authorized','active','expired','error')
                                           NOT NULL DEFAULT 'initiated'     COMMENT 'Session lifecycle state',
  error_message             TEXT           NULL DEFAULT NULL                COMMENT 'Set when status = error; never contains PHI',
  tenant_id                 VARCHAR(50)    NOT NULL DEFAULT 'default'       COMMENT 'Logical tenant / organisation identifier',
  created_at                DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_sls_state   (state_param),
  KEY idx_sls_registration  (registration_id),
  KEY idx_sls_patient       (patient_fhir_id),
  KEY idx_sls_practitioner  (practitioner_fhir_id),
  KEY idx_sls_status        (status),
  KEY idx_sls_tenant        (tenant_id),
  KEY idx_sls_expires       (token_expires_at),
  CONSTRAINT fk_sls_registration
    FOREIGN KEY (registration_id)
    REFERENCES smart_app_registrations (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-launch OAuth2 session state for SMART on FHIR flows';


-- =============================================================================
-- 3. SMART_CONTEXT_CACHE
--    Short-lived cache of FHIR resources fetched during an active session.
--    resource_data stores the raw FHIR JSON; TTL enforcement is at the
--    application layer.  The cache is keyed by (session_id, resource_type,
--    resource_id) so reads are O(1) with the covering index below.
-- =============================================================================

CREATE TABLE IF NOT EXISTS smart_context_cache (
  id            INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  session_id    INT UNSIGNED   NOT NULL                         COMMENT 'FK → smart_launch_sessions.id',
  resource_type VARCHAR(64)    NOT NULL                         COMMENT 'FHIR resource type, e.g. "Patient", "Encounter", "Practitioner"',
  resource_id   VARCHAR(128)   NOT NULL                         COMMENT 'FHIR resource logical id',
  resource_data JSON           NOT NULL                         COMMENT 'Full FHIR resource JSON as returned by the server',
  fetched_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'UTC timestamp of the fetch; used for cache invalidation',
  PRIMARY KEY (id),
  UNIQUE KEY uq_scc_session_type_id (session_id, resource_type, resource_id),
  KEY idx_scc_session    (session_id),
  KEY idx_scc_fetched_at (fetched_at),
  CONSTRAINT fk_scc_session
    FOREIGN KEY (session_id)
    REFERENCES smart_launch_sessions (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='FHIR resource cache for active SMART launch sessions';


-- =============================================================================
-- 4. Record this migration
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    VARCHAR(50) NOT NULL,
  applied_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version) VALUES ('015_smart_on_fhir.sql');

SELECT
  COUNT(*)                     AS tables_in_schema,
  NOW()                        AS applied_at,
  '015_smart_on_fhir.sql done' AS status
FROM information_schema.tables
WHERE table_schema = 'raf_intelligence'
  AND table_type   = 'BASE TABLE';
