-- =============================================================================
-- Migration 005: User Authentication & Authorization
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Depends on: 003_providers.sql (providers table)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. USERS
--    Application users with multi-tenant support, MFA, and account lockout
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
  id                     INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id              VARCHAR(50)     NOT NULL DEFAULT 'default',
  email                  VARCHAR(255)    NOT NULL,
  password_hash          VARCHAR(255)    NOT NULL                        COMMENT 'bcrypt hash',
  first_name             VARCHAR(100)    NOT NULL,
  last_name              VARCHAR(100)    NOT NULL,
  role                   ENUM('admin','manager','clinician','coder','auditor','viewer')
                                         NOT NULL DEFAULT 'viewer',
  title                  VARCHAR(100)    NULL                            COMMENT 'e.g. VP Risk Adjustment, Medical Coder',
  npi                    VARCHAR(10)     NULL                            COMMENT 'NPI if this user is also a provider',
  provider_id            INT UNSIGNED    NULL                            COMMENT 'FK to providers if linked',
  avatar_url             VARCHAR(500)    NULL,
  is_active              TINYINT(1)      NOT NULL DEFAULT 1,
  email_verified         TINYINT(1)      NOT NULL DEFAULT 0,
  last_login_at          DATETIME        NULL,
  password_changed_at    DATETIME        NULL,
  failed_login_attempts  INT UNSIGNED    NOT NULL DEFAULT 0,
  locked_until           DATETIME        NULL                            COMMENT 'Account lockout expiry after repeated failed attempts',
  must_change_password   TINYINT(1)      NOT NULL DEFAULT 0              COMMENT '1 = user must set a new password before accessing the application',
  mfa_enabled            TINYINT(1)      NOT NULL DEFAULT 0,
  mfa_secret             VARCHAR(255)    NULL                            COMMENT 'TOTP secret, stored encrypted at rest',
  created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_tenant_email        (tenant_id, email),
  KEY idx_users_role                      (role),
  KEY idx_users_is_active                 (is_active),
  KEY idx_users_provider_id               (provider_id),
  KEY idx_users_tenant_id                 (tenant_id),
  CONSTRAINT fk_users_provider_id
    FOREIGN KEY (provider_id)
    REFERENCES providers (id)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Application users with role-based access, MFA, and account lockout support';


-- =============================================================================
-- 2. USER_SESSIONS
--    Active JWT session tracking with refresh token lifecycle management
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_sessions (
  id                   INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  user_id              INT UNSIGNED    NOT NULL,
  session_token        VARCHAR(500)    NOT NULL                          COMMENT 'SHA-256 hash of the issued JWT',
  refresh_token        VARCHAR(500)    NOT NULL                          COMMENT 'SHA-256 hash of the refresh token',
  ip_address           VARCHAR(45)     NOT NULL                          COMMENT 'IPv4 or IPv6 source address',
  user_agent           VARCHAR(500)    NULL,
  expires_at           DATETIME        NOT NULL,
  refresh_expires_at   DATETIME        NOT NULL,
  is_revoked           TINYINT(1)      NOT NULL DEFAULT 0,
  revoked_at           DATETIME        NULL,
  created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sessions_user_id              (user_id),
  UNIQUE KEY idx_sessions_session_token  (session_token(64)),
  KEY idx_sessions_expires_at           (expires_at),
  KEY idx_sessions_is_revoked           (is_revoked),
  KEY idx_sessions_revocation_lookup    (user_id, is_revoked, expires_at),
  CONSTRAINT fk_sessions_user_id
    FOREIGN KEY (user_id)
    REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Active JWT and refresh token sessions; used for token validation and forced revocation';


-- =============================================================================
-- 3. USER_PERMISSIONS
--    Granular per-user permission overrides on top of role defaults
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_permissions (
  id           INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  user_id      INT UNSIGNED    NOT NULL,
  resource     ENUM('patients','encounters','raf_scores','suspects','documents',
                    'claims','fhir','providers','audit','reports','settings','users')
                               NOT NULL,
  action       ENUM('read','write','delete','export','admin')
                               NOT NULL,
  granted      TINYINT(1)      NOT NULL DEFAULT 1                        COMMENT '1 = allow, 0 = explicit deny',
  granted_by   INT UNSIGNED    NULL                                      COMMENT 'Admin user who set this permission',
  created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_permissions_user_resource_action (user_id, resource, action),
  KEY idx_permissions_user_id                    (user_id),
  KEY idx_permissions_granted_by                 (granted_by),
  CONSTRAINT fk_permissions_user_id
    FOREIGN KEY (user_id)
    REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_permissions_granted_by
    FOREIGN KEY (granted_by)
    REFERENCES users (id)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Granular per-user permission overrides; takes precedence over role_default_permissions';


-- =============================================================================
-- 4. AUDIT_LOG
--    Comprehensive immutable audit trail covering all PHI access and mutations.
--    Supersedes the partial phi_audit logger. Uses BIGINT PK for high volume.
-- =============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id                   BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  user_id              INT UNSIGNED     NULL                             COMMENT 'NULL for system-initiated actions',
  session_id           INT UNSIGNED     NULL,
  action               VARCHAR(100)     NOT NULL                         COMMENT 'Dot-notation event, e.g. patient.view, raf.calculate, user.login',
  resource_type        VARCHAR(50)      NOT NULL,
  resource_id          VARCHAR(100)     NULL,
  patient_id           INT UNSIGNED     NULL                             COMMENT 'Denormalized OpenEMR pid for PHI access reporting',
  ip_address           VARCHAR(45)      NULL,
  user_agent           VARCHAR(500)     NULL,
  request_method       VARCHAR(10)      NULL,
  request_path         VARCHAR(500)     NULL,
  request_body_hash    VARCHAR(64)      NULL                             COMMENT 'SHA-256 of request body for non-repudiation',
  response_status      INT UNSIGNED     NULL,
  details              JSON             NULL,
  created_at           DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_audit_user_id                 (user_id),
  KEY idx_audit_action                  (action),
  KEY idx_audit_resource_type           (resource_type),
  KEY idx_audit_patient_id              (patient_id),
  KEY idx_audit_session_id              (session_id),
  KEY idx_audit_time_action             (created_at, action)            COMMENT 'Supports time-range queries filtered by action',
  CONSTRAINT fk_audit_user_id
    FOREIGN KEY (user_id)
    REFERENCES users (id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_audit_session_id
    FOREIGN KEY (session_id)
    REFERENCES user_sessions (id)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Immutable audit trail for all user actions, PHI access, and system events';


-- =============================================================================
-- 5. PASSWORD_RESET_TOKENS
--    Single-use tokens for password recovery flows
-- =============================================================================
CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id           INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  user_id      INT UNSIGNED    NOT NULL,
  token_hash   VARCHAR(255)    NOT NULL                                  COMMENT 'SHA-256 hash of the plaintext reset token',
  expires_at   DATETIME        NOT NULL,
  used_at      DATETIME        NULL,
  created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_prt_token_hash  (token_hash),
  KEY idx_prt_user_id     (user_id),
  CONSTRAINT fk_prt_user_id
    FOREIGN KEY (user_id)
    REFERENCES users (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Single-use password reset tokens; token_hash is SHA-256 of the emailed plaintext token';


-- =============================================================================
-- 6. ROLE_DEFAULT_PERMISSIONS
--    Baseline permission matrix per role; evaluated when no user-level
--    override exists in user_permissions
-- =============================================================================
CREATE TABLE IF NOT EXISTS role_default_permissions (
  id        INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  role      ENUM('admin','manager','clinician','coder','auditor','viewer')
                            NOT NULL,
  resource  ENUM('patients','encounters','raf_scores','suspects','documents',
                 'claims','fhir','providers','audit','reports','settings','users')
                            NOT NULL,
  action    ENUM('read','write','delete','export','admin')
                            NOT NULL,
  granted   TINYINT(1)      NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_rdp_role_resource_action  (role, resource, action),
  KEY idx_rdp_role                        (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Default permission matrix per role; application falls back here when no user_permissions row exists';


-- =============================================================================
-- SEED: role_default_permissions
-- =============================================================================

-- --------------------------------------------------------------------
-- admin: full access to every resource and every action
-- --------------------------------------------------------------------
INSERT IGNORE INTO role_default_permissions (role, resource, action, granted) VALUES
  -- patients
  ('admin', 'patients',   'read',   1), ('admin', 'patients',   'write',  1),
  ('admin', 'patients',   'delete', 1), ('admin', 'patients',   'export', 1),
  ('admin', 'patients',   'admin',  1),
  -- encounters
  ('admin', 'encounters', 'read',   1), ('admin', 'encounters', 'write',  1),
  ('admin', 'encounters', 'delete', 1), ('admin', 'encounters', 'export', 1),
  ('admin', 'encounters', 'admin',  1),
  -- raf_scores
  ('admin', 'raf_scores', 'read',   1), ('admin', 'raf_scores', 'write',  1),
  ('admin', 'raf_scores', 'delete', 1), ('admin', 'raf_scores', 'export', 1),
  ('admin', 'raf_scores', 'admin',  1),
  -- suspects
  ('admin', 'suspects',   'read',   1), ('admin', 'suspects',   'write',  1),
  ('admin', 'suspects',   'delete', 1), ('admin', 'suspects',   'export', 1),
  ('admin', 'suspects',   'admin',  1),
  -- documents
  ('admin', 'documents',  'read',   1), ('admin', 'documents',  'write',  1),
  ('admin', 'documents',  'delete', 1), ('admin', 'documents',  'export', 1),
  ('admin', 'documents',  'admin',  1),
  -- claims
  ('admin', 'claims',     'read',   1), ('admin', 'claims',     'write',  1),
  ('admin', 'claims',     'delete', 1), ('admin', 'claims',     'export', 1),
  ('admin', 'claims',     'admin',  1),
  -- fhir
  ('admin', 'fhir',       'read',   1), ('admin', 'fhir',       'write',  1),
  ('admin', 'fhir',       'delete', 1), ('admin', 'fhir',       'export', 1),
  ('admin', 'fhir',       'admin',  1),
  -- providers
  ('admin', 'providers',  'read',   1), ('admin', 'providers',  'write',  1),
  ('admin', 'providers',  'delete', 1), ('admin', 'providers',  'export', 1),
  ('admin', 'providers',  'admin',  1),
  -- audit
  ('admin', 'audit',      'read',   1), ('admin', 'audit',      'write',  1),
  ('admin', 'audit',      'delete', 1), ('admin', 'audit',      'export', 1),
  ('admin', 'audit',      'admin',  1),
  -- reports
  ('admin', 'reports',    'read',   1), ('admin', 'reports',    'write',  1),
  ('admin', 'reports',    'delete', 1), ('admin', 'reports',    'export', 1),
  ('admin', 'reports',    'admin',  1),
  -- settings
  ('admin', 'settings',   'read',   1), ('admin', 'settings',   'write',  1),
  ('admin', 'settings',   'delete', 1), ('admin', 'settings',   'export', 1),
  ('admin', 'settings',   'admin',  1),
  -- users
  ('admin', 'users',      'read',   1), ('admin', 'users',      'write',  1),
  ('admin', 'users',      'delete', 1), ('admin', 'users',      'export', 1),
  ('admin', 'users',      'admin',  1);

-- --------------------------------------------------------------------
-- manager: read + write + export on all resources;
--          no delete on users or settings; no admin action anywhere
-- --------------------------------------------------------------------
INSERT IGNORE INTO role_default_permissions (role, resource, action, granted) VALUES
  ('manager', 'patients',   'read',   1), ('manager', 'patients',   'write',  1),
  ('manager', 'patients',   'delete', 1), ('manager', 'patients',   'export', 1),
  ('manager', 'encounters', 'read',   1), ('manager', 'encounters', 'write',  1),
  ('manager', 'encounters', 'delete', 1), ('manager', 'encounters', 'export', 1),
  ('manager', 'raf_scores', 'read',   1), ('manager', 'raf_scores', 'write',  1),
  ('manager', 'raf_scores', 'delete', 1), ('manager', 'raf_scores', 'export', 1),
  ('manager', 'suspects',   'read',   1), ('manager', 'suspects',   'write',  1),
  ('manager', 'suspects',   'delete', 1), ('manager', 'suspects',   'export', 1),
  ('manager', 'documents',  'read',   1), ('manager', 'documents',  'write',  1),
  ('manager', 'documents',  'delete', 1), ('manager', 'documents',  'export', 1),
  ('manager', 'claims',     'read',   1), ('manager', 'claims',     'write',  1),
  ('manager', 'claims',     'delete', 1), ('manager', 'claims',     'export', 1),
  ('manager', 'fhir',       'read',   1), ('manager', 'fhir',       'write',  1),
  ('manager', 'fhir',       'export', 1),
  ('manager', 'providers',  'read',   1), ('manager', 'providers',  'write',  1),
  ('manager', 'providers',  'export', 1),
  ('manager', 'audit',      'read',   1), ('manager', 'audit',      'export', 1),
  ('manager', 'reports',    'read',   1), ('manager', 'reports',    'write',  1),
  ('manager', 'reports',    'export', 1),
  -- settings: read + write + export only; no delete
  ('manager', 'settings',   'read',   1), ('manager', 'settings',   'write',  1),
  ('manager', 'settings',   'export', 1),
  -- users: read + write + export only; no delete
  ('manager', 'users',      'read',   1), ('manager', 'users',      'write',  1),
  ('manager', 'users',      'export', 1);

-- --------------------------------------------------------------------
-- clinician: read + write on clinical data; read + export on reports
-- --------------------------------------------------------------------
INSERT IGNORE INTO role_default_permissions (role, resource, action, granted) VALUES
  ('clinician', 'patients',   'read',   1), ('clinician', 'patients',   'write',  1),
  ('clinician', 'encounters', 'read',   1), ('clinician', 'encounters', 'write',  1),
  ('clinician', 'raf_scores', 'read',   1), ('clinician', 'raf_scores', 'write',  1),
  ('clinician', 'suspects',   'read',   1), ('clinician', 'suspects',   'write',  1),
  ('clinician', 'documents',  'read',   1), ('clinician', 'documents',  'write',  1),
  ('clinician', 'reports',    'read',   1), ('clinician', 'reports',    'export', 1);

-- --------------------------------------------------------------------
-- coder: read + write on clinical + claims data; read on reports
-- --------------------------------------------------------------------
INSERT IGNORE INTO role_default_permissions (role, resource, action, granted) VALUES
  ('coder', 'patients',   'read',   1), ('coder', 'patients',   'write',  1),
  ('coder', 'encounters', 'read',   1), ('coder', 'encounters', 'write',  1),
  ('coder', 'raf_scores', 'read',   1), ('coder', 'raf_scores', 'write',  1),
  ('coder', 'suspects',   'read',   1), ('coder', 'suspects',   'write',  1),
  ('coder', 'documents',  'read',   1), ('coder', 'documents',  'write',  1),
  ('coder', 'claims',     'read',   1), ('coder', 'claims',     'write',  1),
  ('coder', 'reports',    'read',   1);

-- --------------------------------------------------------------------
-- auditor: read + export on all resources; admin action on audit only
-- --------------------------------------------------------------------
INSERT IGNORE INTO role_default_permissions (role, resource, action, granted) VALUES
  ('auditor', 'patients',   'read',   1), ('auditor', 'patients',   'export', 1),
  ('auditor', 'encounters', 'read',   1), ('auditor', 'encounters', 'export', 1),
  ('auditor', 'raf_scores', 'read',   1), ('auditor', 'raf_scores', 'export', 1),
  ('auditor', 'suspects',   'read',   1), ('auditor', 'suspects',   'export', 1),
  ('auditor', 'documents',  'read',   1), ('auditor', 'documents',  'export', 1),
  ('auditor', 'claims',     'read',   1), ('auditor', 'claims',     'export', 1),
  ('auditor', 'fhir',       'read',   1), ('auditor', 'fhir',       'export', 1),
  ('auditor', 'providers',  'read',   1), ('auditor', 'providers',  'export', 1),
  ('auditor', 'audit',      'read',   1), ('auditor', 'audit',      'export', 1),
  ('auditor', 'audit',      'admin',  1),
  ('auditor', 'reports',    'read',   1), ('auditor', 'reports',    'export', 1),
  ('auditor', 'settings',   'read',   1),
  ('auditor', 'users',      'read',   1), ('auditor', 'users',      'export', 1);

-- --------------------------------------------------------------------
-- viewer: read-only on all resources
-- --------------------------------------------------------------------
INSERT IGNORE INTO role_default_permissions (role, resource, action, granted) VALUES
  ('viewer', 'patients',   'read', 1),
  ('viewer', 'encounters', 'read', 1),
  ('viewer', 'raf_scores', 'read', 1),
  ('viewer', 'suspects',   'read', 1),
  ('viewer', 'documents',  'read', 1),
  ('viewer', 'claims',     'read', 1),
  ('viewer', 'fhir',       'read', 1),
  ('viewer', 'providers',  'read', 1),
  ('viewer', 'audit',      'read', 1),
  ('viewer', 'reports',    'read', 1),
  ('viewer', 'settings',   'read', 1),
  ('viewer', 'users',      'read', 1);


-- =============================================================================
-- SEED: default admin user
--   email:    admin@raf.health
--   password: admin123  (bcrypt cost 12)
--   role:     admin
--
-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
-- WARNING: THIS PASSWORD MUST BE CHANGED ON FIRST LOGIN.
-- The default credential "admin123" is well-known and provides full admin
-- access.  Leaving it in place is a critical security vulnerability.
-- The must_change_password flag is set to 1; the application MUST enforce a
-- password change before granting access to any protected resource.
-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
-- =============================================================================
INSERT IGNORE INTO users (
  tenant_id,
  email,
  password_hash,
  first_name,
  last_name,
  role,
  title,
  is_active,
  email_verified,
  must_change_password,
  password_changed_at
) VALUES (
  'default',
  'admin@raf.health',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/o8X8GVZF2',  -- bcrypt('admin123', 12)
  'System',
  'Administrator',
  'admin',
  'System Administrator',
  1,
  1,
  1,               -- must_change_password: force password reset on first login
  CURRENT_TIMESTAMP
);
