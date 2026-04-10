-- =============================================================================
-- RAF Intelligence System - Migration 012
-- Annual Wellness Visit (AWV) Scheduling Integration
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. AWV_SCHEDULES
--    Core scheduling record for each patient's AWV in a given calendar year.
--    One row per patient per schedule_year. Status advances through the
--    outreach and visit workflow lifecycle.
-- =============================================================================
CREATE TABLE IF NOT EXISTS awv_schedules (
  id                    INT UNSIGNED        NOT NULL AUTO_INCREMENT,
  patient_id            INT UNSIGNED        NOT NULL                      COMMENT 'OpenEMR patient pid',
  provider_npi          VARCHAR(10)         NULL      DEFAULT NULL        COMMENT 'Rendering provider NPI',
  schedule_year         SMALLINT UNSIGNED   NOT NULL                      COMMENT 'Calendar year this AWV applies to',
  status                ENUM(
                          'eligible',
                          'outreach_pending',
                          'scheduled',
                          'completed',
                          'declined',
                          'no_show'
                        )                   NOT NULL DEFAULT 'eligible'   COMMENT 'Lifecycle status of the AWV scheduling record',
  eligibility_date      DATE                NULL      DEFAULT NULL        COMMENT 'Date patient became eligible for AWV (1 year after prior AWV or Medicare enrollment)',
  scheduled_date        DATETIME            NULL      DEFAULT NULL        COMMENT 'Confirmed appointment date and time',
  completed_date        DATE                NULL      DEFAULT NULL        COMMENT 'Date AWV was actually completed',
  visit_type            ENUM(
                          'initial_awv',
                          'subsequent_awv',
                          'welcome_to_medicare'
                        )                   NULL      DEFAULT NULL        COMMENT 'AWV CPT category: G0438=initial, G0439=subsequent, G0402=Welcome to Medicare',
  location              VARCHAR(255)        NULL      DEFAULT NULL        COMMENT 'Practice location or facility name',
  notes                 TEXT                NULL                          COMMENT 'Free-text scheduling notes',
  outreach_attempts     TINYINT UNSIGNED    NOT NULL DEFAULT 0            COMMENT 'Total number of outreach contact attempts logged',
  last_outreach_date    DATE                NULL      DEFAULT NULL        COMMENT 'Most recent date outreach was attempted',
  decline_reason        VARCHAR(500)        NULL      DEFAULT NULL        COMMENT 'Patient-stated reason for declining (when status=declined)',
  hcc_gaps_to_review    JSON                NULL                          COMMENT 'Array of HCC codes with open gaps identified for this AWV',
  estimated_raf_impact  DECIMAL(8,4)        NULL      DEFAULT NULL        COMMENT 'Estimated RAF score change if all HCC gaps are closed at this visit',
  tenant_id             VARCHAR(50)         NOT NULL DEFAULT 'default'    COMMENT 'Multi-tenant discriminator',
  created_at            DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_awv_patient_year (patient_id, schedule_year),
  KEY idx_awv_provider_npi     (provider_npi),
  KEY idx_awv_status           (status),
  KEY idx_awv_schedule_year    (schedule_year),
  KEY idx_awv_scheduled_date   (scheduled_date),
  KEY idx_awv_completed_date   (completed_date),
  KEY idx_awv_tenant           (tenant_id),
  KEY idx_awv_tenant_year      (tenant_id, schedule_year),
  KEY idx_awv_tenant_status    (tenant_id, status),
  KEY idx_awv_outreach         (outreach_attempts, last_outreach_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AWV scheduling lifecycle record: one row per patient per calendar year';


-- =============================================================================
-- 2. AWV_OUTREACH_LOG
--    Detailed log of every outreach contact attempt made for a scheduled AWV.
--    Multiple rows per awv_schedules record.
-- =============================================================================
CREATE TABLE IF NOT EXISTS awv_outreach_log (
  id              INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  awv_id          INT UNSIGNED  NOT NULL                      COMMENT 'FK -> awv_schedules.id',
  method          ENUM(
                    'phone',
                    'email',
                    'sms',
                    'mail'
                  )             NOT NULL                      COMMENT 'Outreach channel used',
  outcome         ENUM(
                    'no_answer',
                    'left_message',
                    'scheduled',
                    'declined',
                    'wrong_number'
                  )             NOT NULL                      COMMENT 'Result of the contact attempt',
  contact_date    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Date and time the outreach was performed',
  contacted_by    INT UNSIGNED  NULL      DEFAULT NULL        COMMENT 'User ID of the staff member who made the contact',
  notes           TEXT          NULL                          COMMENT 'Free-text notes about the contact attempt',
  created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_ol_awv_id       (awv_id),
  KEY idx_ol_contact_date (contact_date),
  KEY idx_ol_method       (method),
  KEY idx_ol_outcome      (outcome),
  CONSTRAINT fk_ol_awv
    FOREIGN KEY (awv_id)
    REFERENCES awv_schedules (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Outreach contact attempt log per AWV scheduling record';


-- =============================================================================
-- 3. AWV_CHECKLISTS
--    Structured pre-visit, during-visit, and post-visit checklist items.
--    Generated automatically from the patient's open HCC gaps and AWV protocols.
-- =============================================================================
CREATE TABLE IF NOT EXISTS awv_checklists (
  id               INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  awv_id           INT UNSIGNED  NOT NULL                      COMMENT 'FK -> awv_schedules.id',
  checklist_type   ENUM(
                     'pre_visit',
                     'during_visit',
                     'post_visit'
                   )             NOT NULL                      COMMENT 'Phase of the AWV workflow this item belongs to',
  item_name        VARCHAR(255)  NOT NULL                      COMMENT 'Short identifier / title of the checklist item',
  item_description TEXT          NULL                          COMMENT 'Detailed instruction or context for the checklist item',
  completed        TINYINT(1)    NOT NULL DEFAULT 0            COMMENT '1=item has been completed, 0=pending',
  completed_by     INT UNSIGNED  NULL      DEFAULT NULL        COMMENT 'User ID of staff who marked the item complete',
  completed_at     DATETIME      NULL      DEFAULT NULL        COMMENT 'Timestamp when the item was marked complete',
  created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_cl_awv_id         (awv_id),
  KEY idx_cl_checklist_type (checklist_type),
  KEY idx_cl_completed      (completed),
  CONSTRAINT fk_cl_awv
    FOREIGN KEY (awv_id)
    REFERENCES awv_schedules (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Checklist items for pre-visit preparation, during-visit workflows, and post-visit follow-up';


-- =============================================================================
-- 4. AWV_VISIT_RESULTS
--    Clinical outcomes captured after an AWV is completed.
--    One row per completed AWV; RAF scores are snapshotted before and after.
-- =============================================================================
CREATE TABLE IF NOT EXISTS awv_visit_results (
  id                         INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  awv_id                     INT UNSIGNED  NOT NULL UNIQUE               COMMENT 'FK -> awv_schedules.id; one result row per visit',
  conditions_reviewed        SMALLINT      NOT NULL DEFAULT 0            COMMENT 'Total number of conditions reviewed during the visit',
  conditions_confirmed       SMALLINT      NOT NULL DEFAULT 0            COMMENT 'Conditions confirmed and documented at the visit',
  new_conditions_identified  SMALLINT      NOT NULL DEFAULT 0            COMMENT 'Net-new conditions identified that were not previously coded',
  hcc_codes_captured         JSON          NULL                          COMMENT 'Array of HCC codes that were successfully captured/confirmed at this visit',
  raf_score_before           DECIMAL(8,4)  NULL      DEFAULT NULL        COMMENT 'Patient RAF score immediately before the visit',
  raf_score_after            DECIMAL(8,4)  NULL      DEFAULT NULL        COMMENT 'Patient RAF score recalculated after visit coding is complete',
  notes                      TEXT          NULL                          COMMENT 'Clinical notes or summary from the provider',
  created_at                 DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                 DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_vr_awv_id (awv_id),
  CONSTRAINT fk_vr_awv
    FOREIGN KEY (awv_id)
    REFERENCES awv_schedules (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Clinical outcomes and RAF impact captured after each completed Annual Wellness Visit';


-- =============================================================================
-- Record migration
-- =============================================================================
INSERT IGNORE INTO schema_migrations (version) VALUES ('012_awv_scheduling.sql');
