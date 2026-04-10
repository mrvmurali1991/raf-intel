-- =============================================================================
-- Migration 007: Multi-EMR Connection Registry
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
-- Description: Unified registry for all EMR/EHR connections regardless of
--              integration type (direct DB, FHIR R4, REST API, HL7v2).
--              Supersedes vendor-specific one-off connection tables and
--              provides a single surface for connection management, sync
--              scheduling, and audit history.
--
-- Tables added:
--   1. emr_connections     — unified connection configuration per tenant
--   2. emr_sync_log        — sync run history for all connection types
--   3. emr_vendor_presets  — factory templates for known EMR vendors
--
-- Dependencies:
--   001_fhir_integration.sql must be applied first (fhir_connections FK)
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. EMR_CONNECTIONS
--    Central registry for every EMR integration regardless of how it connects.
--    Supports four connection types:
--      direct_db   — direct MySQL/PostgreSQL connection to the EMR database
--      fhir_r4     — FHIR R4 REST endpoint (links to existing fhir_connections)
--      rest_api    — vendor proprietary REST API
--      hl7v2       — HL7 v2.x message interface (future use)
--
--    All secret material (passwords, client secrets, API keys) is stored as
--    AES-256-GCM ciphertext with the _encrypted suffix.  Decryption is handled
--    exclusively at the application layer and must never appear in logs.
-- =============================================================================
CREATE TABLE IF NOT EXISTS emr_connections (
  -- -------------------------------------------------------------------
  -- Identity
  -- -------------------------------------------------------------------
  id                       INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  tenant_id                VARCHAR(50)     NOT NULL DEFAULT 'default'      COMMENT 'Logical tenant / organisation identifier',
  name                     VARCHAR(200)    NOT NULL                        COMMENT 'Human-readable label for this connection',
  vendor                   VARCHAR(50)     NOT NULL                        COMMENT 'EMR vendor key: openemr | epic | cerner | athenahealth | allscripts | eclinicalworks | drchrono | nextgen | greenway | practice_fusion | generic_fhir | generic_rest',
  connection_type          ENUM('direct_db','fhir_r4','rest_api','hl7v2')
                                           NOT NULL                        COMMENT 'Integration protocol used to communicate with the EMR',
  status                   ENUM('active','inactive','error','testing')
                                           NOT NULL DEFAULT 'inactive'     COMMENT 'Operational status: inactive until explicitly activated and tested',

  -- -------------------------------------------------------------------
  -- Direct-DB fields (connection_type = direct_db)
  -- -------------------------------------------------------------------
  db_host                  VARCHAR(255)    NULL DEFAULT NULL               COMMENT 'Hostname or IP of the EMR database server',
  db_port                  SMALLINT UNSIGNED
                                           NULL DEFAULT NULL               COMMENT 'TCP port; typically 3306 (MySQL) or 5432 (PostgreSQL)',
  db_name                  VARCHAR(100)    NULL DEFAULT NULL               COMMENT 'Database / schema name on the target server',
  db_username              VARCHAR(100)    NULL DEFAULT NULL               COMMENT 'Database login username',
  db_password_encrypted    TEXT            NULL DEFAULT NULL               COMMENT 'AES-256-GCM ciphertext of the database password',
  db_ssl_enabled           TINYINT(1)      NOT NULL DEFAULT 0              COMMENT '1 = require TLS for the database connection',
  db_type                  ENUM('mysql','postgresql')
                                           NULL DEFAULT NULL               COMMENT 'Database engine type; required when connection_type = direct_db',

  -- -------------------------------------------------------------------
  -- FHIR fields (connection_type = fhir_r4)
  -- -------------------------------------------------------------------
  fhir_base_url            VARCHAR(500)    NULL DEFAULT NULL               COMMENT 'Root FHIR R4 base URL, e.g. https://ehr.example.com/fhir/R4',
  fhir_connection_id       INT UNSIGNED    NULL DEFAULT NULL               COMMENT 'FK -> fhir_connections.id; links to existing FHIR connection record if one exists',

  -- -------------------------------------------------------------------
  -- REST API fields (connection_type = rest_api)
  -- -------------------------------------------------------------------
  api_base_url             VARCHAR(500)    NULL DEFAULT NULL               COMMENT 'Base URL for the vendor REST API, e.g. https://api.platform.athenahealth.com',
  api_version              VARCHAR(20)     NULL DEFAULT NULL               COMMENT 'API version string, e.g. v1, 2023-09-01',

  -- -------------------------------------------------------------------
  -- Shared authentication (all connection types)
  -- -------------------------------------------------------------------
  auth_type                ENUM('oauth2','smart_on_fhir','basic','api_key','none')
                                           NOT NULL DEFAULT 'none'         COMMENT 'Authentication scheme; none is valid only for internal/trusted direct-DB connections',
  client_id                VARCHAR(255)    NULL DEFAULT NULL               COMMENT 'OAuth2 / SMART client_id or basic-auth username override',
  client_secret_encrypted  TEXT            NULL DEFAULT NULL               COMMENT 'AES-256-GCM ciphertext of the OAuth2 client_secret',
  token_url                VARCHAR(500)    NULL DEFAULT NULL               COMMENT 'OAuth2 token endpoint; NULL when auth_type = basic | api_key | none',
  api_key_encrypted        TEXT            NULL DEFAULT NULL               COMMENT 'AES-256-GCM ciphertext of the API key; used when auth_type = api_key',
  scope                    VARCHAR(1000)   NULL DEFAULT NULL               COMMENT 'Space-separated OAuth2 / SMART scopes to request',

  -- -------------------------------------------------------------------
  -- Sync configuration
  -- -------------------------------------------------------------------
  sync_enabled             TINYINT(1)      NOT NULL DEFAULT 0              COMMENT '1 = automated sync is enabled for this connection',
  sync_interval_minutes    INT             NOT NULL DEFAULT 60             COMMENT 'Polling interval in minutes when cron is not set',
  sync_cron                VARCHAR(100)    NULL DEFAULT NULL               COMMENT 'Optional cron expression overriding sync_interval_minutes, e.g. 0 2 * * *',

  -- -------------------------------------------------------------------
  -- Operational timestamps
  -- -------------------------------------------------------------------
  last_sync_at             DATETIME        NULL DEFAULT NULL               COMMENT 'Wall-clock timestamp of the most recent completed sync',
  last_test_at             DATETIME        NULL DEFAULT NULL               COMMENT 'Wall-clock timestamp of the most recent connectivity test',
  last_test_success        TINYINT(1)      NULL DEFAULT NULL               COMMENT '1 = last connectivity test passed; 0 = failed; NULL = never tested',

  -- -------------------------------------------------------------------
  -- Extensibility
  -- -------------------------------------------------------------------
  field_mappings           JSON            NULL DEFAULT NULL               COMMENT 'Vendor-specific field-name overrides; keys are canonical RAF field names, values are source field names',
  config_overrides         JSON            NULL DEFAULT NULL               COMMENT 'Arbitrary vendor-specific configuration bag; merged with emr_vendor_presets.default_config at runtime',

  -- -------------------------------------------------------------------
  -- Audit
  -- -------------------------------------------------------------------
  created_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_tenant_id       (tenant_id),
  KEY idx_vendor          (vendor),
  KEY idx_connection_type (connection_type),
  KEY idx_status          (status),
  KEY idx_tenant_vendor   (tenant_id, vendor),
  KEY idx_last_sync_at    (last_sync_at),
  KEY idx_fhir_conn_id    (fhir_connection_id),

  CONSTRAINT fk_emrconn_fhir_connection
    FOREIGN KEY (fhir_connection_id)
    REFERENCES fhir_connections (id)
    ON DELETE SET NULL ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Unified registry of all EMR connections (direct-DB, FHIR R4, REST API, HL7v2) per tenant';


-- =============================================================================
-- 2. EMR_SYNC_LOG
--    Immutable audit trail of every sync operation across all connection types.
--    A row is inserted when a sync starts and updated on completion or failure.
--    Do not delete rows; use status = cancelled to void an in-progress run.
-- =============================================================================
CREATE TABLE IF NOT EXISTS emr_sync_log (
  id                   INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  emr_connection_id    INT UNSIGNED   NOT NULL                        COMMENT 'FK -> emr_connections.id',
  sync_type            ENUM('full','incremental','test')
                                      NOT NULL                        COMMENT 'full = all history; incremental = delta since last sync; test = connectivity probe only',
  records_fetched      INT UNSIGNED   NOT NULL DEFAULT 0              COMMENT 'Total records / resources returned by the source EMR',
  records_processed    INT UNSIGNED   NOT NULL DEFAULT 0              COMMENT 'Records successfully written to local tables',
  records_failed       INT UNSIGNED   NOT NULL DEFAULT 0              COMMENT 'Records that raised a processing error',
  status               ENUM('running','completed','failed','cancelled')
                                      NOT NULL DEFAULT 'running'      COMMENT 'Lifecycle state of this sync run',
  started_at           DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Wall-clock start of the sync run',
  completed_at         DATETIME       NULL DEFAULT NULL               COMMENT 'Wall-clock end; NULL while status = running',
  error_message        TEXT           NULL DEFAULT NULL               COMMENT 'Last error detail when status = failed',
  details              JSON           NULL DEFAULT NULL               COMMENT 'Structured run metadata: resource types synced, page counts, warnings, etc.',

  PRIMARY KEY (id),
  KEY idx_emr_connection_id (emr_connection_id),
  KEY idx_status            (status),
  KEY idx_sync_type         (sync_type),
  KEY idx_started_at        (started_at),
  KEY idx_conn_status_time  (emr_connection_id, status, started_at),

  CONSTRAINT fk_emrsynclog_connection
    FOREIGN KEY (emr_connection_id)
    REFERENCES emr_connections (id)
    ON DELETE CASCADE ON UPDATE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Audit log of all EMR sync operations; one row per sync run per connection';


-- =============================================================================
-- 3. EMR_VENDOR_PRESETS
--    Factory templates for known EMR vendors.  The application merges these
--    defaults with emr_connections.config_overrides at connection-build time
--    so that administrators do not have to fill in every field from scratch.
--
--    default_config JSON schema (illustrative, not enforced by DB):
--      {
--        "db_port":         3306,
--        "db_type":         "mysql",
--        "scope":           "patient/*.read",
--        "api_version":     "v1",
--        "field_mappings":  { ... }
--      }
-- =============================================================================
CREATE TABLE IF NOT EXISTS emr_vendor_presets (
  id                   INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  vendor               VARCHAR(50)    NOT NULL                        COMMENT 'Vendor key — must match emr_connections.vendor values',
  display_name         VARCHAR(100)   NOT NULL                        COMMENT 'Human-readable product name shown in the admin UI',
  logo_url             VARCHAR(500)   NULL DEFAULT NULL               COMMENT 'URL to the vendor logo image (CDN or static asset path)',
  connection_type      ENUM('direct_db','fhir_r4','rest_api','hl7v2')
                                      NOT NULL                        COMMENT 'Default / recommended connection type for this vendor',
  default_auth_type    ENUM('oauth2','smart_on_fhir','basic','api_key','none')
                                      NOT NULL DEFAULT 'oauth2'       COMMENT 'Default authentication scheme for this vendor',
  default_config       JSON           NOT NULL                        COMMENT 'Default connection parameters merged into new connections at creation time',
  setup_instructions   TEXT           NULL DEFAULT NULL               COMMENT 'Markdown-formatted setup guide shown in the admin connection wizard',
  documentation_url    VARCHAR(500)   NULL DEFAULT NULL               COMMENT 'Link to official vendor API or integration documentation',
  notes                TEXT           NULL DEFAULT NULL               COMMENT 'Internal operational notes, known quirks, version caveats',

  PRIMARY KEY (id),
  UNIQUE KEY uq_vendor_preset (vendor)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Factory configuration templates and setup guidance for known EMR vendors';


-- =============================================================================
-- SEED: emr_vendor_presets
--    INSERT IGNORE is safe to re-run; existing rows are skipped.
--    Update specific rows via:
--      UPDATE emr_vendor_presets SET ... WHERE vendor = '...';
-- =============================================================================
INSERT IGNORE INTO emr_vendor_presets
  (vendor, display_name, logo_url, connection_type, default_auth_type, default_config, setup_instructions, documentation_url, notes)
VALUES

-- ---------------------------------------------------------------------------
-- OpenEMR — direct MySQL connection (self-hosted)
-- ---------------------------------------------------------------------------
(
  'openemr',
  'OpenEMR',
  NULL,
  'direct_db',
  'basic',
  JSON_OBJECT(
    'db_port',    3306,
    'db_type',    'mysql',
    'db_name',    'openemr',
    'db_username','openemr',
    'db_ssl_enabled', 0,
    'field_mappings', JSON_OBJECT(
      'patient_id',    'pid',
      'first_name',    'fname',
      'last_name',     'lname',
      'date_of_birth', 'DOB',
      'icd10_code',    'diagnosis'
    )
  ),
  '## OpenEMR Direct Database Connection

### Prerequisites
- OpenEMR 6.0 or later
- Network access from the RAF Intelligence server to the OpenEMR MySQL host on port 3306
- A dedicated read-only MySQL user (recommended: never use the `openemr` root account)

### Step 1 — Create a read-only database user
Log in to the OpenEMR MySQL instance and run:

```sql
CREATE USER ''raf_reader''@''<RAF_SERVER_IP>'' IDENTIFIED BY ''<strong-password>'';
GRANT SELECT ON openemr.* TO ''raf_reader''@''<RAF_SERVER_IP>'';
FLUSH PRIVILEGES;
```

### Step 2 — Fill in connection fields
| Field | Value |
|-------|-------|
| DB Host | IP or hostname of the OpenEMR MySQL server |
| DB Port | 3306 (default) |
| DB Name | openemr |
| DB Username | raf_reader (or the user created above) |
| DB Password | password set in Step 1 |
| DB SSL Enabled | Recommended: ON if the server is not on a private VLAN |

### Step 3 — Test the connection
Click **Test Connection** in the admin panel.  A successful test will show the OpenEMR version string read from the `globals` table.

### Step 4 — Enable sync
Set **Sync Enabled = Yes** and choose a **Sync Interval** (default: 60 minutes).  The initial full sync may take several minutes depending on patient volume.',
  'https://www.open-emr.org/wiki/index.php/OpenEMR_API',
  'Default field mappings assume standard OpenEMR schema; custom installations may require overrides via config_overrides.'
),

-- ---------------------------------------------------------------------------
-- Epic — FHIR R4 via SMART on FHIR
-- ---------------------------------------------------------------------------
(
  'epic',
  'Epic MyChart / Epic FHIR',
  NULL,
  'fhir_r4',
  'smart_on_fhir',
  JSON_OBJECT(
    'scope',       'patient/*.read launch/patient openid fhirUser',
    'fhir_version','R4',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'name[0].given[0]',
      'last_name',     'name[0].family',
      'date_of_birth', 'birthDate'
    )
  ),
  '## Epic FHIR R4 Connection (SMART on FHIR)

### Prerequisites
- Epic instance with FHIR R4 enabled (Epic August 2021 or later)
- An approved application registered in Epic''s App Orchard or your organisation''s local Epic sandbox
- Your registered **Client ID** and, if using confidential client flow, a **Client Secret**

### Step 1 — Register your application in Epic
1. Navigate to **Epic on FHIR** (https://fhir.epic.com) or your organisation''s Epic App Orchard.
2. Create a new application with the following settings:
   - Application Type: **Clinician-facing** or **Backend System**
   - FHIR Version: **R4**
   - Redirect URI: `https://<your-raf-server>/auth/epic/callback`
3. Note the **Client ID** issued after registration.

### Step 2 — Locate the FHIR base URL
The FHIR R4 base URL follows the pattern:
```
https://<epic-host>/api/FHIR/R4
```
Your Epic administrator can confirm the exact URL.  You can also discover it via the `.well-known/smart-configuration` endpoint.

### Step 3 — Fill in connection fields
| Field | Value |
|-------|-------|
| FHIR Base URL | `https://<epic-host>/api/FHIR/R4` |
| Auth Type | SMART on FHIR |
| Client ID | From Step 1 |
| Client Secret | From Step 1 (confidential clients only) |
| Token URL | Auto-discovered from FHIR metadata, or manually: `https://<epic-host>/oauth2/token` |
| Scope | `patient/*.read launch/patient openid fhirUser` |

### Step 4 — Test and activate
Click **Test Connection** to verify token exchange and a sample Patient read.  Epic sandbox environments require a test patient context; production requires provider authorization.',
  'https://fhir.epic.com/Documentation',
  'Epic rate-limits FHIR calls per client per minute; set sync_interval_minutes >= 30 for large patient populations to avoid 429 errors.'
),

-- ---------------------------------------------------------------------------
-- Cerner — FHIR R4 via OAuth2
-- ---------------------------------------------------------------------------
(
  'cerner',
  'Oracle Health (Cerner) Millennium',
  NULL,
  'fhir_r4',
  'oauth2',
  JSON_OBJECT(
    'scope',       'system/Patient.read system/Condition.read system/Encounter.read system/DiagnosticReport.read',
    'fhir_version','R4',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'name[0].given[0]',
      'last_name',     'name[0].family',
      'date_of_birth', 'birthDate'
    )
  ),
  '## Cerner Millennium FHIR R4 Connection

### Prerequisites
- Cerner Millennium with FHIR R4 enabled
- Application registered at **Cerner FHIR Code Console** (https://code.cerner.com)
- System-level OAuth2 credentials (client credentials flow for backend integrations)

### Step 1 — Register your application
1. Sign in to https://code.cerner.com and create a new application.
2. Choose **System Account** for server-to-server access.
3. Request the following scopes:
   - `system/Patient.read`
   - `system/Condition.read`
   - `system/Encounter.read`
   - `system/DiagnosticReport.read`
4. Note the **Client ID** and **Client Secret**.

### Step 2 — Locate FHIR base URL and token endpoint
- FHIR R4 base URL: `https://<cerner-host>/r4/<tenant-id>`
- Token URL: `https://authorization.cerner.com/tenants/<tenant-id>/protocols/oauth2/profiles/smart-v1/token`

Both values are available in your Cerner system configuration or from your Cerner TAM.

### Step 3 — Fill in connection fields
| Field | Value |
|-------|-------|
| FHIR Base URL | `https://<cerner-host>/r4/<tenant-id>` |
| Auth Type | OAuth2 |
| Client ID | From Step 1 |
| Client Secret | From Step 1 |
| Token URL | From Step 2 |
| Scope | `system/*.read` (or explicit resource scopes) |

### Step 4 — Test
Click **Test Connection**.  A successful test returns HTTP 200 from the FHIR metadata endpoint and completes a client credentials token exchange.',
  'https://fhir.cerner.com/millennium/r4/',
  'Cerner requires tenant-scoped token URLs; a single client credential set is scoped to one Cerner tenant/organisation.'
),

-- ---------------------------------------------------------------------------
-- athenahealth — REST API (proprietary) via OAuth2
-- ---------------------------------------------------------------------------
(
  'athenahealth',
  'athenahealth',
  NULL,
  'rest_api',
  'oauth2',
  JSON_OBJECT(
    'api_base_url', 'https://api.platform.athenahealth.com',
    'api_version',  'v1',
    'scope',        'athena/service/Athenanet.MDP.*',
    'token_url',    'https://api.platform.athenahealth.com/oauth2/v1/token',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'patientid',
      'first_name',    'firstname',
      'last_name',     'lastname',
      'date_of_birth', 'dob'
    )
  ),
  '## athenahealth REST API Connection

### Prerequisites
- athenahealth Marketplace partner account or direct API access agreement
- Registered application in the athenahealth Developer Portal (https://developer.athenahealth.com)
- Practice ID (used in all API URL paths)

### Step 1 — Register your application
1. Log in to https://developer.athenahealth.com and create a new application.
2. Select **Production** for live data or **Preview** for sandbox testing.
3. Note the **Client ID** and **Client Secret**.

### Step 2 — Fill in connection fields
| Field | Value |
|-------|-------|
| API Base URL | `https://api.platform.athenahealth.com` |
| API Version | `v1` |
| Auth Type | OAuth2 |
| Client ID | From Step 1 |
| Client Secret | From Step 1 |
| Token URL | `https://api.platform.athenahealth.com/oauth2/v1/token` |
| Scope | `athena/service/Athenanet.MDP.*` |

### Step 3 — Set the Practice ID
Add the following to **Config Overrides**:
```json
{ "practice_id": "<your-athenahealth-practice-id>" }
```

### Step 4 — Test and enable sync
The practice ID is required before testing.  The initial sync fetches active patients and their problem lists.',
  'https://developer.athenahealth.com/docs/read/Welcome_to_More_Physician_Locations',
  'API rate limits: 1000 requests per minute for production; use sync_interval_minutes >= 60 for large practices.'
),

-- ---------------------------------------------------------------------------
-- Allscripts — REST API via OAuth2
-- ---------------------------------------------------------------------------
(
  'allscripts',
  'Allscripts (Veradigm)',
  NULL,
  'rest_api',
  'oauth2',
  JSON_OBJECT(
    'api_version',  'v1',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'ID',
      'first_name',    'FirstName',
      'last_name',     'LastName',
      'date_of_birth', 'DateOfBirth'
    )
  ),
  NULL,
  'https://developer.allscripts.com/',
  'Allscripts Unity API uses a non-standard session token mechanism; verify token_url with your Allscripts technical contact.'
),

-- ---------------------------------------------------------------------------
-- eClinicalWorks — FHIR R4 via OAuth2
-- ---------------------------------------------------------------------------
(
  'eclinicalworks',
  'eClinicalWorks',
  NULL,
  'fhir_r4',
  'oauth2',
  JSON_OBJECT(
    'scope',       'system/Patient.read system/Condition.read system/Encounter.read',
    'fhir_version','R4',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'name[0].given[0]',
      'last_name',     'name[0].family',
      'date_of_birth', 'birthDate'
    )
  ),
  NULL,
  'https://developer.eclinicalworks.com/developer/apis/fhir-r4',
  'eCW FHIR R4 availability requires eCW v12 or later and must be enabled per-practice by eCW support.'
),

-- ---------------------------------------------------------------------------
-- DrChrono — REST API via OAuth2
-- ---------------------------------------------------------------------------
(
  'drchrono',
  'DrChrono',
  NULL,
  'rest_api',
  'oauth2',
  JSON_OBJECT(
    'api_base_url', 'https://app.drchrono.com/api',
    'api_version',  'v4',
    'scope',        'patients:read diagnoses:read clinical:read',
    'token_url',    'https://drchrono.com/o/token/',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'first_name',
      'last_name',     'last_name',
      'date_of_birth', 'date_of_birth'
    )
  ),
  NULL,
  'https://app.drchrono.com/api-docs/',
  'DrChrono uses cursor-based pagination; the sync adapter must follow next-page cursors returned in the Link header.'
),

-- ---------------------------------------------------------------------------
-- NextGen — FHIR R4 via OAuth2
-- ---------------------------------------------------------------------------
(
  'nextgen',
  'NextGen Healthcare',
  NULL,
  'fhir_r4',
  'oauth2',
  JSON_OBJECT(
    'scope',       'system/Patient.read system/Condition.read system/Encounter.read',
    'fhir_version','R4',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'name[0].given[0]',
      'last_name',     'name[0].family',
      'date_of_birth', 'birthDate'
    )
  ),
  NULL,
  'https://developer.nextgen.com/api',
  'NextGen FHIR endpoint URL varies by hosting model (cloud vs. on-premise); confirm base URL with the practice IT team.'
),

-- ---------------------------------------------------------------------------
-- Greenway Health — REST API via API key
-- ---------------------------------------------------------------------------
(
  'greenway',
  'Greenway Health (Intergy)',
  NULL,
  'rest_api',
  'api_key',
  JSON_OBJECT(
    'api_version',  'v1',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'PatientID',
      'first_name',    'FirstName',
      'last_name',     'LastName',
      'date_of_birth', 'DateOfBirth'
    )
  ),
  NULL,
  'https://developer.greenwayhealth.com/',
  'Greenway API key is scoped per integration user; create a dedicated integration account in Intergy with read-only permissions.'
),

-- ---------------------------------------------------------------------------
-- Practice Fusion — REST API via OAuth2
-- ---------------------------------------------------------------------------
(
  'practice_fusion',
  'Practice Fusion',
  NULL,
  'rest_api',
  'oauth2',
  JSON_OBJECT(
    'api_version',  'v1',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'Guid',
      'first_name',    'FirstName',
      'last_name',     'LastName',
      'date_of_birth', 'DateOfBirth'
    )
  ),
  NULL,
  'https://developer.practicefusion.com/',
  'Practice Fusion was acquired by Veradigm (Allscripts); verify API availability with your account representative.'
),

-- ---------------------------------------------------------------------------
-- Generic FHIR R4 — any standards-compliant FHIR R4 endpoint
-- ---------------------------------------------------------------------------
(
  'generic_fhir',
  'Generic FHIR R4 Endpoint',
  NULL,
  'fhir_r4',
  'oauth2',
  JSON_OBJECT(
    'scope',       'patient/*.read',
    'fhir_version','R4',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'name[0].given[0]',
      'last_name',     'name[0].family',
      'date_of_birth', 'birthDate'
    )
  ),
  '## Generic FHIR R4 Endpoint Connection

### Overview
Use this preset for any FHIR R4-compliant server not covered by a named vendor preset.  The adapter follows the standard FHIR R4 REST specification and SMART on FHIR authorization framework.

### Step 1 — Discover the FHIR base URL
The FHIR R4 base URL is the root from which all resource paths are appended:
```
<fhir_base_url>/metadata          # capability statement
<fhir_base_url>/Patient           # patient search
<fhir_base_url>/Condition?...     # condition queries
```

Most FHIR servers publish a SMART configuration document at:
```
<fhir_base_url>/.well-known/smart-configuration
```
This document contains the `token_endpoint` and supported scopes.

### Step 2 — Register your client
Register a confidential client application with the FHIR server''s authorization server and obtain a **Client ID** and **Client Secret**.

### Step 3 — Fill in connection fields
| Field | Value |
|-------|-------|
| FHIR Base URL | Root URL of the FHIR R4 server |
| Auth Type | OAuth2 or SMART on FHIR |
| Client ID | From client registration |
| Client Secret | From client registration |
| Token URL | From `.well-known/smart-configuration` or server documentation |
| Scope | `patient/*.read` (minimum); add resource-specific scopes if required |

### Step 4 — Field mapping
If the source server uses non-standard extensions, add custom **Field Mappings** using FHIRPath expressions to map source fields to RAF canonical names.',
  'https://hl7.org/fhir/R4/',
  'Verify the server supports the FHIR R4 search parameters used by the sync adapter (Patient?_id, Condition?patient, Encounter?patient, DiagnosticReport?patient).'
),

-- ---------------------------------------------------------------------------
-- Generic REST — any proprietary REST API
-- ---------------------------------------------------------------------------
(
  'generic_rest',
  'Generic REST API',
  NULL,
  'rest_api',
  'api_key',
  JSON_OBJECT(
    'api_version',  'v1',
    'field_mappings', JSON_OBJECT(
      'patient_id',    'id',
      'first_name',    'first_name',
      'last_name',     'last_name',
      'date_of_birth', 'dob'
    )
  ),
  NULL,
  NULL,
  'Generic REST preset; all field_mappings and config_overrides must be populated manually to match the target API schema.'
);
