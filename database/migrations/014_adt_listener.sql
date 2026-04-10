-- =============================================================================
-- Migration 014: ADT Feed Real-Time Listener
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- Applies to database: raf_intelligence
--
-- Adds infrastructure for receiving HL7v2 ADT messages over MLLP/TCP in
-- real-time.  Three tables are created:
--
--   1. adt_connections    — MLLP/TCP listener configuration per tenant
--   2. adt_messages       — Audit log of every received ADT message
--   3. adt_subscriptions  — Webhook delivery subscriptions for ADT events
--
-- No foreign keys into OpenEMR tables are introduced.  The patient_id column
-- in adt_messages stores the OpenEMR pid resolved at processing time and is
-- nullable (message may arrive before the patient is registered locally).
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. ADT_CONNECTIONS
--    One row per configured MLLP/TCP listener.  The application layer starts
--    a background thread per connection whose status (active/inactive/error)
--    is reflected back here.
-- =============================================================================
CREATE TABLE IF NOT EXISTS adt_connections (
  id               INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  tenant_id        VARCHAR(50)      NOT NULL DEFAULT 'default'      COMMENT 'Logical tenant / organisation',
  name             VARCHAR(255)     NOT NULL                        COMMENT 'Human-readable label',
  host             VARCHAR(255)     NOT NULL DEFAULT '0.0.0.0'      COMMENT 'Bind address for inbound or remote host for outbound',
  port             INT UNSIGNED     NOT NULL DEFAULT 2575           COMMENT 'TCP port — MLLP default is 2575',
  direction        ENUM('inbound','outbound')
                                    NOT NULL DEFAULT 'inbound'      COMMENT 'inbound = we listen; outbound = we connect',
  protocol         ENUM('mllp','tcp')
                                    NOT NULL DEFAULT 'mllp'         COMMENT 'Framing protocol',
  status           ENUM('active','inactive','error')
                                    NOT NULL DEFAULT 'inactive'     COMMENT 'Runtime status updated by the listener thread',
  auto_process     TINYINT(1)       NOT NULL DEFAULT 1              COMMENT '1 = automatically parse and upsert patients on receipt',
  last_message_at  DATETIME         NULL DEFAULT NULL               COMMENT 'Timestamp of the most-recently received message',
  message_count    BIGINT UNSIGNED  NOT NULL DEFAULT 0              COMMENT 'Cumulative accepted message count',
  error_count      INT UNSIGNED     NOT NULL DEFAULT 0              COMMENT 'Cumulative parse/processing error count',
  created_at       DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_adt_conn_tenant  (tenant_id),
  KEY idx_adt_conn_status  (status),
  KEY idx_adt_conn_port    (port)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='ADT MLLP/TCP listener connection configurations';


-- =============================================================================
-- 2. ADT_MESSAGES
--    Append-only audit log.  Every message received (or attempted) by any
--    adt_connections listener is stored here regardless of processing outcome.
--    raw_message is MEDIUMTEXT to handle edge-case large messages (up to 16 MB).
-- =============================================================================
CREATE TABLE IF NOT EXISTS adt_messages (
  id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  connection_id   INT UNSIGNED     NOT NULL                        COMMENT 'FK to adt_connections.id',
  tenant_id       VARCHAR(50)      NOT NULL DEFAULT 'default',
  message_type    VARCHAR(20)      NOT NULL DEFAULT ''             COMMENT 'e.g. ADT_A01, ADT_A08',
  control_id      VARCHAR(100)     NOT NULL DEFAULT ''             COMMENT 'MSH-10 message control ID',
  raw_message     MEDIUMTEXT       NOT NULL                        COMMENT 'Full HL7v2 text as received (MLLP framing stripped)',
  patient_id      INT UNSIGNED     NULL DEFAULT NULL               COMMENT 'Resolved OpenEMR pid, NULL if patient not yet registered',
  patient_mrn     VARCHAR(100)     NOT NULL DEFAULT ''             COMMENT 'PID-3 CX.1 as extracted from message',
  patient_name    VARCHAR(255)     NOT NULL DEFAULT ''             COMMENT 'Formatted last, first from PID-5',
  event_datetime  DATETIME         NULL DEFAULT NULL               COMMENT 'EVN-2 or MSH-7 event date',
  status          ENUM('received','processed','error','ignored')
                                   NOT NULL DEFAULT 'received'     COMMENT 'Processing lifecycle state',
  error_message   TEXT             NULL DEFAULT NULL               COMMENT 'Error detail when status = error',
  processed_data  JSON             NULL DEFAULT NULL               COMMENT 'Structured extract: demographics, diagnoses, observations',
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_adt_msg_connection  (connection_id),
  KEY idx_adt_msg_tenant      (tenant_id),
  KEY idx_adt_msg_type        (message_type),
  KEY idx_adt_msg_control     (control_id),
  KEY idx_adt_msg_patient_id  (patient_id),
  KEY idx_adt_msg_mrn         (patient_mrn),
  KEY idx_adt_msg_status      (status),
  KEY idx_adt_msg_created     (created_at),
  KEY idx_adt_msg_conn_status (connection_id, status),

  CONSTRAINT fk_adt_msg_connection
    FOREIGN KEY (connection_id)
    REFERENCES adt_connections (id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Audit log of all received HL7v2 ADT messages';


-- =============================================================================
-- 3. ADT_SUBSCRIPTIONS
--    Lightweight webhook subscription table specific to ADT events.
--    Complements the general webhooks table; ADT subscriptions are matched by
--    event_type and fan-out is handled by the ADT listener service.
--
--    event_type values:
--      adt.admit        (A01)   adt.transfer     (A02)   adt.discharge  (A03)
--      adt.register     (A04)   adt.update       (A08)   adt.*          (wildcard)
-- =============================================================================
CREATE TABLE IF NOT EXISTS adt_subscriptions (
  id          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  tenant_id   VARCHAR(50)   NOT NULL DEFAULT 'default',
  event_type  VARCHAR(50)   NOT NULL                    COMMENT 'adt.admit / adt.transfer / adt.discharge / adt.register / adt.update / adt.*',
  webhook_url VARCHAR(2048) NOT NULL                    COMMENT 'HTTPS endpoint that will receive POST payloads',
  active      TINYINT(1)    NOT NULL DEFAULT 1           COMMENT '1 = enabled; 0 = paused',
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_adt_sub_tenant     (tenant_id),
  KEY idx_adt_sub_event_type (event_type),
  KEY idx_adt_sub_active     (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Webhook subscriptions for real-time ADT event notifications';


-- =============================================================================
-- Migration record
-- =============================================================================
INSERT IGNORE INTO schema_migrations (version) VALUES ('014_adt_listener.sql');
