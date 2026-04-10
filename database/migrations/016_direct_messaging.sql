-- =============================================================================
-- RAF Intelligence System - Migration 016: Direct Messaging
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- Direct Messaging is the healthcare-standard encrypted email protocol
-- (S/MIME over SMTP) used for secure provider-to-provider exchange of
-- clinical documents.  Direct addresses follow the form
-- provider@direct.hospital.org and are governed by the DirectTrust
-- accreditation framework.
--
-- Tables created:
--   direct_trust_anchors  – trusted CA certificates and trust bundles
--   direct_addresses      – managed Direct addresses with certificates
--   direct_messages       – inbound and outbound message records
--   direct_attachments    – per-message attachment metadata
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. DIRECT_TRUST_ANCHORS
--    Stores trusted CA certificates used to validate sender certificates.
--    Trust anchors are typically loaded from a DirectTrust trust bundle URL
--    (a signed PKCS#7 bundle) or added manually for bilateral agreements.
-- =============================================================================
CREATE TABLE IF NOT EXISTS direct_trust_anchors (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'   COMMENT 'Multi-tenant discriminator',
  name              VARCHAR(255)      NOT NULL                     COMMENT 'Human-readable label, e.g. "DirectTrust Production Bundle"',
  organization      VARCHAR(255)          NULL DEFAULT NULL        COMMENT 'Issuing organisation name',
  certificate_pem   TEXT              NOT NULL                     COMMENT 'PEM-encoded CA certificate',
  trust_bundle_url  VARCHAR(512)          NULL DEFAULT NULL        COMMENT 'URL to fetch an updated PKCS#7 trust bundle',
  status            ENUM(
                      'trusted',
                      'untrusted',
                      'expired'
                    )                 NOT NULL DEFAULT 'trusted'   COMMENT 'Trust evaluation status',
  expires_at        DATETIME              NULL DEFAULT NULL        COMMENT 'Certificate NotAfter timestamp (UTC)',
  created_at        DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_tenant  (tenant_id),
  INDEX idx_status  (status),
  INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Trusted CA certificates for validating Direct message signatures';


-- =============================================================================
-- 2. DIRECT_ADDRESSES
--    One row per managed Direct address.  Each address owns an X.509
--    certificate used for S/MIME signing and encryption.  Private keys are
--    stored AES-256 encrypted at the application layer before being written
--    here; the plaintext key never touches the database.
-- =============================================================================
CREATE TABLE IF NOT EXISTS direct_addresses (
  id                      INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id               VARCHAR(50)       NOT NULL DEFAULT 'default'  COMMENT 'Multi-tenant discriminator',
  user_id                 INT UNSIGNED      NOT NULL                    COMMENT 'FK to raf_users.id — owning user',
  provider_npi            VARCHAR(10)           NULL DEFAULT NULL       COMMENT 'NPI of the associated provider',
  direct_address          VARCHAR(255)      NOT NULL                    COMMENT 'Direct address, e.g. drsmith@direct.hospital.org',
  display_name            VARCHAR(255)          NULL DEFAULT NULL       COMMENT 'Friendly name shown in address book',
  certificate_pem         TEXT                  NULL DEFAULT NULL       COMMENT 'PEM-encoded end-entity certificate',
  private_key_encrypted   TEXT                  NULL DEFAULT NULL       COMMENT 'AES-256-GCM encrypted PKCS#8 private key (base64)',
  trust_anchor_id         INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'FK to direct_trust_anchors.id for the issuing CA',
  status                  ENUM(
                            'active',
                            'inactive',
                            'pending_verification'
                          )                 NOT NULL DEFAULT 'pending_verification' COMMENT 'Lifecycle status of this address',
  verified_at             DATETIME              NULL DEFAULT NULL       COMMENT 'When domain ownership was confirmed',
  created_at              DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at              DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_direct_address (direct_address),
  INDEX idx_tenant      (tenant_id),
  INDEX idx_user        (user_id),
  INDEX idx_status      (status),
  INDEX idx_trust_anchor (trust_anchor_id),
  CONSTRAINT fk_da_trust_anchor
    FOREIGN KEY (trust_anchor_id) REFERENCES direct_trust_anchors (id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Managed Direct addresses with S/MIME certificates';


-- =============================================================================
-- 3. DIRECT_MESSAGES
--    Central message store for both inbound and outbound Direct messages.
--    Status transitions:
--      Outbound: draft → queued → sent → delivered  (or failed)
--      Inbound:  received → read
--    MDN (Message Disposition Notifications) update delivered/read timestamps.
-- =============================================================================
CREATE TABLE IF NOT EXISTS direct_messages (
  id              INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id       VARCHAR(50)       NOT NULL DEFAULT 'default'    COMMENT 'Multi-tenant discriminator',
  direction       ENUM(
                    'inbound',
                    'outbound'
                  )                 NOT NULL                      COMMENT 'Message flow direction',
  from_address    VARCHAR(255)      NOT NULL                      COMMENT 'Sender Direct address',
  to_address      VARCHAR(255)      NOT NULL                      COMMENT 'Primary recipient Direct address',
  subject         VARCHAR(500)          NULL DEFAULT NULL         COMMENT 'Message subject line',
  body            TEXT                  NULL DEFAULT NULL         COMMENT 'Plain-text or HTML message body',
  has_attachments TINYINT(1)        NOT NULL DEFAULT 0            COMMENT '1 if one or more attachments are present',
  patient_id      INT UNSIGNED          NULL DEFAULT NULL         COMMENT 'OpenEMR pid if message is linked to a patient',
  message_id      VARCHAR(255)          NULL DEFAULT NULL         COMMENT 'RFC 2822 Message-ID header value (globally unique)',
  in_reply_to     VARCHAR(255)          NULL DEFAULT NULL         COMMENT 'RFC 2822 In-Reply-To header for threading',
  status          ENUM(
                    'draft',
                    'queued',
                    'sent',
                    'delivered',
                    'failed',
                    'received',
                    'read'
                  )                 NOT NULL DEFAULT 'draft'      COMMENT 'Current message status',
  error_message   TEXT                  NULL DEFAULT NULL         COMMENT 'Delivery failure details when status=failed',
  sent_at         DATETIME              NULL DEFAULT NULL         COMMENT 'When the message was handed to the MTA',
  received_at     DATETIME              NULL DEFAULT NULL         COMMENT 'When the message was received by the local MTA',
  read_at         DATETIME              NULL DEFAULT NULL         COMMENT 'When the recipient opened/acknowledged the message',
  created_at      DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_message_id (message_id),
  INDEX idx_tenant        (tenant_id),
  INDEX idx_direction     (direction),
  INDEX idx_from          (from_address(64)),
  INDEX idx_to            (to_address(64)),
  INDEX idx_patient       (patient_id),
  INDEX idx_status        (status),
  INDEX idx_in_reply_to   (in_reply_to(64)),
  INDEX idx_created       (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Direct Message records — inbound and outbound';


-- =============================================================================
-- 4. DIRECT_ATTACHMENTS
--    One row per attachment per message.  file_path is the server-side path
--    (or object-storage key) where the decrypted content is staged.
--    C-CDA documents are parsed asynchronously; parsed=1 and ccda_document_id
--    are set once the pipeline completes.
-- =============================================================================
CREATE TABLE IF NOT EXISTS direct_attachments (
  id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  tenant_id         VARCHAR(50)       NOT NULL DEFAULT 'default'  COMMENT 'Multi-tenant discriminator',
  message_id        INT UNSIGNED      NOT NULL                    COMMENT 'FK to direct_messages.id',
  filename          VARCHAR(255)      NOT NULL                    COMMENT 'Original attachment filename',
  content_type      VARCHAR(255)      NOT NULL                    COMMENT 'MIME content-type, e.g. text/xml',
  file_size         INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'File size in bytes',
  file_path         VARCHAR(512)          NULL DEFAULT NULL       COMMENT 'Server-side path or object-storage key',
  attachment_type   ENUM(
                      'ccda',
                      'pdf',
                      'image',
                      'other'
                    )                 NOT NULL DEFAULT 'other'    COMMENT 'Semantic type for routing to parsers',
  parsed            TINYINT(1)        NOT NULL DEFAULT 0          COMMENT '1 once the document has been processed by the parsing pipeline',
  ccda_document_id  INT UNSIGNED          NULL DEFAULT NULL       COMMENT 'FK to documents.id once a C-CDA is imported',

  PRIMARY KEY (id),
  INDEX idx_tenant      (tenant_id),
  INDEX idx_message     (message_id),
  INDEX idx_type        (attachment_type),
  INDEX idx_parsed      (parsed),
  CONSTRAINT fk_da_message
    FOREIGN KEY (message_id) REFERENCES direct_messages (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Attachment metadata for Direct messages';
