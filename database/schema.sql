-- =============================================================================
-- RAF Intelligence System - Complete Database Schema
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
-- =============================================================================

CREATE DATABASE IF NOT EXISTS raf_intelligence
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE raf_intelligence;

-- =============================================================================
-- 1. HCC_ICD10_CROSSWALK
--    Maps ICD-10 codes to HCC V28 categories
-- =============================================================================
CREATE TABLE IF NOT EXISTS hcc_icd10_crosswalk (
  id              INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  icd10_code      VARCHAR(10)      NOT NULL,
  icd10_description VARCHAR(500)   NOT NULL DEFAULT '',
  hcc_code        SMALLINT UNSIGNED NOT NULL,
  hcc_label       VARCHAR(255)     NOT NULL DEFAULT '',
  effective_year  YEAR             NOT NULL DEFAULT 2024,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_crosswalk_code_year (icd10_code, hcc_code, effective_year),
  KEY idx_icd10_code      (icd10_code),
  KEY idx_hcc_code        (hcc_code),
  KEY idx_effective_year  (effective_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='ICD-10 to HCC V28 mapping table';


-- =============================================================================
-- 2. HCC_RAF_COEFFICIENTS
--    RAF weight per HCC per model segment
-- =============================================================================
CREATE TABLE IF NOT EXISTS hcc_raf_coefficients (
  id              INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  hcc_code        SMALLINT UNSIGNED NOT NULL,
  model_segment   ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
  coefficient     DECIMAL(8,4)     NOT NULL,
  model_year      YEAR             NOT NULL DEFAULT 2024,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_coeff_hcc_seg_year (hcc_code, model_segment, model_year),
  KEY idx_hcc_code       (hcc_code),
  KEY idx_model_segment  (model_segment),
  KEY idx_model_year     (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='RAF coefficient weights per HCC per model segment';


-- =============================================================================
-- 3. HCC_DEMOGRAPHIC_COEFFICIENTS
--    Age/sex base scores per model segment
-- =============================================================================
CREATE TABLE IF NOT EXISTS hcc_demographic_coefficients (
  id              INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  model_segment   ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
  age_band        VARCHAR(20)      NOT NULL COMMENT 'e.g. 0-34, 35-44, 45-54, 55-59, 60-64, 65-69, 70-74, 75-79, 80-84, 85-89, 90-94, 95+',
  sex             ENUM('M','F')    NOT NULL,
  coefficient     DECIMAL(8,4)     NOT NULL,
  model_year      YEAR             NOT NULL DEFAULT 2024,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_demo_seg_age_sex_year (model_segment, age_band, sex, model_year),
  KEY idx_model_segment (model_segment),
  KEY idx_age_band      (age_band),
  KEY idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Demographic base score coefficients per model segment';


-- =============================================================================
-- 4. HCC_HIERARCHY_RULES
--    Which HCC trumps (supersedes) which
-- =============================================================================
CREATE TABLE IF NOT EXISTS hcc_hierarchy_rules (
  id              INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  hcc_code        SMALLINT UNSIGNED NOT NULL COMMENT 'The lower-severity HCC that gets trumped',
  trumped_by_hcc  SMALLINT UNSIGNED NOT NULL COMMENT 'The higher-severity HCC that takes precedence',
  model_year      YEAR             NOT NULL DEFAULT 2024,
  created_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_hierarchy_pair_year (hcc_code, trumped_by_hcc, model_year),
  KEY idx_hcc_code       (hcc_code),
  KEY idx_trumped_by_hcc (trumped_by_hcc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='HCC hierarchy rules: lower HCC is suppressed when higher HCC is present';


-- =============================================================================
-- 5. HCC_INTERACTION_TERMS
--    Condition combination bonus RAF scores
-- =============================================================================
CREATE TABLE IF NOT EXISTS hcc_interaction_terms (
  id                  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  term_name           VARCHAR(100)  NOT NULL,
  hcc_codes_required  JSON          NOT NULL COMMENT 'Array of HCC codes that must all be present',
  model_segment       ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
  coefficient         DECIMAL(8,4)  NOT NULL,
  model_year          YEAR          NOT NULL DEFAULT 2024,
  created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_interaction_name_seg_year (term_name, model_segment, model_year),
  KEY idx_model_segment (model_segment),
  KEY idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Interaction term bonuses for combinations of HCC conditions';


-- =============================================================================
-- 6. RAF_PATIENT_DEMOGRAPHICS
--    Patient-level RAF factors (links to OpenEMR pid)
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_patient_demographics (
  id               INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  patient_id       INT UNSIGNED    NOT NULL COMMENT 'OpenEMR pid',
  measurement_year YEAR            NOT NULL,
  age_band         VARCHAR(20)     NOT NULL,
  sex              ENUM('M','F')   NOT NULL,
  dual_status      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '1 = Medicare/Medicaid dual eligible',
  disabled         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '1 = qualifies via disability',
  model_segment    ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL DEFAULT 'CNA',
  created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_patient_year (patient_id, measurement_year),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_dual_status      (dual_status),
  KEY idx_disabled         (disabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Patient demographic factors for RAF calculation, linked to OpenEMR pid';


-- =============================================================================
-- 7. RAF_PATIENT_HCC
--    Per-patient HCC tracking with encounter linkage
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_patient_hcc (
  id                   INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  patient_id           INT UNSIGNED  NOT NULL COMMENT 'OpenEMR pid',
  measurement_year     YEAR          NOT NULL,
  hcc_code             SMALLINT UNSIGNED NOT NULL,
  icd10_codes          JSON          NOT NULL  COMMENT 'Array of ICD-10 codes that mapped to this HCC',
  source_encounter_ids JSON          NOT NULL  COMMENT 'Array of OpenEMR encounter IDs',
  raf_coefficient      DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  meat_status          ENUM('complete','partial','missing') NOT NULL DEFAULT 'missing',
  is_trumped           TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '1 = suppressed by hierarchy rule',
  trumped_by_hcc       SMALLINT UNSIGNED NULL DEFAULT NULL,
  created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_patient_hcc_year (patient_id, hcc_code, measurement_year),
  KEY idx_patient_id       (patient_id),
  KEY idx_hcc_code         (hcc_code),
  KEY idx_measurement_year (measurement_year),
  KEY idx_meat_status      (meat_status),
  KEY idx_is_trumped       (is_trumped),
  CONSTRAINT fk_phcc_demographics
    FOREIGN KEY (patient_id, measurement_year)
    REFERENCES raf_patient_demographics (patient_id, measurement_year)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-patient HCC conditions with supporting encounter references and MEAT status';


-- =============================================================================
-- 8. RAF_SCORES
--    Calculated RAF scores with full component breakdown
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_scores (
  id                   INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  patient_id           INT UNSIGNED  NOT NULL COMMENT 'OpenEMR pid',
  measurement_year     YEAR          NOT NULL,
  score_type           VARCHAR(50)   NOT NULL DEFAULT 'prospective' COMMENT 'prospective, concurrent, etc.',
  model_segment        ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL DEFAULT 'CNA',
  demographic_score    DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  disease_score        DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  interaction_score    DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  total_raw            DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  normalization_factor DECIMAL(8,4)  NOT NULL DEFAULT 1.0000,
  final_raf            DECIMAL(8,4)  NOT NULL DEFAULT 0.0000,
  hcc_count            SMALLINT      NOT NULL DEFAULT 0,
  calculated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_score_patient_year_type_seg (patient_id, measurement_year, score_type, model_segment),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_final_raf        (final_raf),
  KEY idx_score_type       (score_type),
  CONSTRAINT fk_scores_demographics
    FOREIGN KEY (patient_id, measurement_year)
    REFERENCES raf_patient_demographics (patient_id, measurement_year)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Final calculated RAF scores with full demographic/disease/interaction breakdown';


-- =============================================================================
-- 9. RAF_SUSPECT_CONDITIONS
--    AI-flagged missing diagnoses for provider review
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_suspect_conditions (
  id               INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  patient_id       INT UNSIGNED    NOT NULL COMMENT 'OpenEMR pid',
  measurement_year YEAR            NOT NULL,
  suspect_hcc      SMALLINT UNSIGNED NOT NULL,
  suspect_icd10    VARCHAR(10)     NOT NULL,
  evidence_type    ENUM('medication','lab','imaging','referral','historical') NOT NULL,
  evidence_detail  JSON            NOT NULL  COMMENT 'Structured evidence: source values, dates, note refs',
  confidence_score DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT '0.0000 to 1.0000',
  status           ENUM('open','accepted','dismissed','coded') NOT NULL DEFAULT 'open',
  reviewed_by      VARCHAR(100)    NULL DEFAULT NULL,
  reviewed_at      DATETIME        NULL DEFAULT NULL,
  created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_suspect_hcc      (suspect_hcc),
  KEY idx_suspect_icd10    (suspect_icd10),
  KEY idx_evidence_type    (evidence_type),
  KEY idx_confidence_score (confidence_score),
  KEY idx_status           (status),
  KEY idx_patient_year_hcc (patient_id, measurement_year, suspect_hcc),
  CONSTRAINT fk_suspect_demographics
    FOREIGN KEY (patient_id, measurement_year)
    REFERENCES raf_patient_demographics (patient_id, measurement_year)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AI-identified suspect conditions flagged for provider coding review';


-- =============================================================================
-- 10. RAF_MEAT_EVIDENCE
--     MEAT (Monitor/Evaluate/Assess/Treat) documentation per diagnosis
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_meat_evidence (
  id                   INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  patient_hcc_id       INT UNSIGNED  NOT NULL COMMENT 'FK to raf_patient_hcc.id',
  encounter_id         INT UNSIGNED  NOT NULL COMMENT 'OpenEMR encounter ID',
  encounter_date       DATE          NOT NULL,
  meat_m               TEXT          NULL COMMENT 'Monitor documentation',
  meat_e               TEXT          NULL COMMENT 'Evaluate documentation',
  meat_a               TEXT          NULL COMMENT 'Assess documentation',
  meat_t               TEXT          NULL COMMENT 'Treat documentation',
  meat_m_present       TINYINT(1)    NOT NULL DEFAULT 0,
  meat_e_present       TINYINT(1)    NOT NULL DEFAULT 0,
  meat_a_present       TINYINT(1)    NOT NULL DEFAULT 0,
  meat_t_present       TINYINT(1)    NOT NULL DEFAULT 0,
  completeness_score   DECIMAL(5,4)  NOT NULL DEFAULT 0.0000 COMMENT '0.0-1.0 based on MEAT components present',
  raw_note_excerpt     TEXT          NULL COMMENT 'Relevant excerpt from clinical note',
  created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_patient_hcc_id  (patient_hcc_id),
  KEY idx_encounter_id    (encounter_id),
  KEY idx_encounter_date  (encounter_date),
  KEY idx_completeness    (completeness_score),
  CONSTRAINT fk_meat_patient_hcc
    FOREIGN KEY (patient_hcc_id)
    REFERENCES raf_patient_hcc (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='MEAT documentation evidence per patient HCC per encounter';


-- =============================================================================
-- 11. RAF_MEDICATION_SIGNALS
--     Drug name/class to suspect diagnosis inference rules
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_medication_signals (
  id                 INT UNSIGNED   NOT NULL AUTO_INCREMENT,
  drug_name_pattern  VARCHAR(255)   NOT NULL COMMENT 'Regex or LIKE pattern for drug name matching',
  drug_class         VARCHAR(100)   NOT NULL DEFAULT '' COMMENT 'Pharmacological class label',
  suspect_icd10      VARCHAR(10)    NOT NULL,
  suspect_hcc        SMALLINT UNSIGNED NOT NULL,
  confidence_base    DECIMAL(5,4)   NOT NULL DEFAULT 0.7000 COMMENT 'Base confidence before evidence stacking',
  notes              VARCHAR(500)   NOT NULL DEFAULT '',
  is_active          TINYINT(1)     NOT NULL DEFAULT 1,
  created_at         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_drug_class    (drug_class),
  KEY idx_suspect_icd10 (suspect_icd10),
  KEY idx_suspect_hcc   (suspect_hcc),
  KEY idx_is_active     (is_active),
  FULLTEXT KEY ftx_drug_name (drug_name_pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Medication signal rules: drug patterns mapped to suspect HCC diagnoses';


-- =============================================================================
-- 12. RAF_LAB_SIGNALS
--     Lab value threshold rules to suspect diagnosis mapping
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_lab_signals (
  id                  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  lab_name_pattern    VARCHAR(255)  NOT NULL COMMENT 'LIKE pattern for lab test name',
  lab_loinc_code      VARCHAR(20)   NOT NULL DEFAULT '' COMMENT 'LOINC code for structured matching',
  threshold_operator  ENUM('<','<=','>','>=','=','!=','BETWEEN') NOT NULL,
  threshold_value     DECIMAL(12,4) NULL COMMENT 'Single threshold value',
  threshold_low       DECIMAL(12,4) NULL COMMENT 'Lower bound for BETWEEN operator',
  threshold_high      DECIMAL(12,4) NULL COMMENT 'Upper bound for BETWEEN operator',
  threshold_unit      VARCHAR(30)   NOT NULL DEFAULT '',
  suspect_icd10       VARCHAR(10)   NOT NULL,
  suspect_hcc         SMALLINT UNSIGNED NOT NULL,
  confidence_base     DECIMAL(5,4)  NOT NULL DEFAULT 0.7500,
  notes               VARCHAR(500)  NOT NULL DEFAULT '',
  is_active           TINYINT(1)    NOT NULL DEFAULT 1,
  created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_lab_loinc     (lab_loinc_code),
  KEY idx_suspect_icd10 (suspect_icd10),
  KEY idx_suspect_hcc   (suspect_hcc),
  KEY idx_is_active     (is_active),
  FULLTEXT KEY ftx_lab_name (lab_name_pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Lab signal rules: abnormal lab thresholds mapped to suspect HCC diagnoses';


-- =============================================================================
-- 13. RAF_NLP_JOBS
--     Processing job tracking for NLP/AI pipeline
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_nlp_jobs (
  id                  INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  job_type            VARCHAR(100)  NOT NULL COMMENT 'e.g. note_extraction, meat_scoring, suspect_detection',
  target_id           INT UNSIGNED  NOT NULL COMMENT 'ID of the entity being processed (encounter, patient, etc.)',
  target_type         VARCHAR(50)   NOT NULL DEFAULT 'encounter' COMMENT 'encounter, patient, document',
  status              ENUM('queued','running','completed','failed','cancelled') NOT NULL DEFAULT 'queued',
  model_used          VARCHAR(100)  NOT NULL DEFAULT '' COMMENT 'Model name/version used for inference',
  processing_time_ms  INT UNSIGNED  NULL COMMENT 'Wall-clock processing time in milliseconds',
  result_summary      JSON          NULL COMMENT 'Structured summary of job output',
  error_message       TEXT          NULL,
  queued_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at          DATETIME      NULL,
  completed_at        DATETIME      NULL,
  created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_job_type    (job_type),
  KEY idx_target      (target_type, target_id),
  KEY idx_status      (status),
  KEY idx_queued_at   (queued_at),
  KEY idx_model_used  (model_used)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='NLP and AI processing job queue and result tracking';


-- =============================================================================
-- 14. RAF_AUDIT_PACKAGES
--     Generated audit reports for patients
-- =============================================================================
CREATE TABLE IF NOT EXISTS raf_audit_packages (
  id               INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  patient_id       INT UNSIGNED    NOT NULL COMMENT 'OpenEMR pid',
  measurement_year YEAR            NOT NULL,
  generated_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  file_path        VARCHAR(500)    NOT NULL DEFAULT '',
  status           ENUM('generating','ready','failed','archived') NOT NULL DEFAULT 'generating',
  package_version  VARCHAR(20)     NOT NULL DEFAULT '1.0',
  generated_by     VARCHAR(100)    NULL DEFAULT NULL,
  file_size_bytes  INT UNSIGNED    NULL,
  checksum_sha256  CHAR(64)        NULL,
  created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_patient_id       (patient_id),
  KEY idx_measurement_year (measurement_year),
  KEY idx_status           (status),
  KEY idx_generated_at     (generated_at),
  KEY idx_patient_year     (patient_id, measurement_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Generated RAF audit report packages with file references';


-- =============================================================================
-- SEED DATA: raf_medication_signals (30+ high-value medication rules)
-- =============================================================================

INSERT INTO raf_medication_signals
  (drug_name_pattern, drug_class, suspect_icd10, suspect_hcc, confidence_base, notes)
VALUES
  -- Diabetes (HCC18 = uncontrolled/complicated, HCC19 = controlled)
  ('insulin%',                     'Insulin',                         'E11.9',  19,  0.8500, 'Any insulin use strongly suggests Type 2 Diabetes'),
  ('insulin%',                     'Insulin',                         'E11.65', 18,  0.7500, 'Insulin with hyperglycemia suggests uncontrolled DM HCC18'),
  ('metformin%',                   'Biguanide',                       'E11.9',  19,  0.8000, 'Metformin is first-line for Type 2 Diabetes'),
  ('glipizide%',                   'Sulfonylurea',                    'E11.9',  19,  0.8000, 'Sulfonylurea use indicates Type 2 Diabetes'),
  ('glyburide%',                   'Sulfonylurea',                    'E11.9',  19,  0.8000, 'Sulfonylurea use indicates Type 2 Diabetes'),
  ('glimepiride%',                 'Sulfonylurea',                    'E11.9',  19,  0.8000, 'Sulfonylurea use indicates Type 2 Diabetes'),
  ('sitagliptin%',                 'DPP-4 Inhibitor',                 'E11.9',  19,  0.8200, 'DPP-4 inhibitor indicates Type 2 Diabetes'),
  ('empagliflozin%',               'SGLT2 Inhibitor',                 'E11.9',  19,  0.8200, 'SGLT2 inhibitor indicates Type 2 Diabetes, also cardioprotective'),
  ('dapagliflozin%',               'SGLT2 Inhibitor',                 'E11.9',  19,  0.8200, 'SGLT2 inhibitor indicates Type 2 Diabetes'),
  ('semaglutide%',                 'GLP-1 Agonist',                   'E11.9',  19,  0.8200, 'GLP-1 agonist indicates Type 2 Diabetes'),
  ('liraglutide%',                 'GLP-1 Agonist',                   'E11.9',  19,  0.8200, 'GLP-1 agonist indicates Type 2 Diabetes'),

  -- Congestive Heart Failure (HCC85)
  ('furosemide%',                  'Loop Diuretic',                   'I50.9',  85,  0.7500, 'Loop diuretic: high specificity for CHF/volume overload'),
  ('torsemide%',                   'Loop Diuretic',                   'I50.9',  85,  0.7500, 'Loop diuretic: high specificity for CHF'),
  ('bumetanide%',                  'Loop Diuretic',                   'I50.9',  85,  0.7500, 'Loop diuretic: high specificity for CHF'),
  ('sacubitril%valsartan%',        'ARNI',                            'I50.2',  85,  0.9200, 'Entresto (sacubitril/valsartan) is exclusively for HFrEF HCC85'),
  ('sacubitril%',                  'ARNI',                            'I50.2',  85,  0.9200, 'Sacubitril component: exclusively used in HFrEF'),
  ('carvedilol%',                  'Beta Blocker (non-selective)',     'I50.9',  85,  0.7000, 'Carvedilol FDA-approved for CHF; also used in HTN'),
  ('metoprolol succinate%',        'Beta Blocker (selective)',         'I50.9',  85,  0.7000, 'Metoprolol succinate FDA-approved for CHF'),
  ('digoxin%',                     'Cardiac Glycoside',               'I50.9',  85,  0.8500, 'Digoxin used almost exclusively for CHF and AFib rate control'),

  -- Atrial Fibrillation (HCC96)
  ('warfarin%',                    'Vitamin K Antagonist',            'I48.91', 96,  0.7500, 'Warfarin anticoagulation strongly suggests AFib or VTE'),
  ('apixaban%',                    'Factor Xa Inhibitor (DOAC)',       'I48.91', 96,  0.8000, 'Apixaban prescribed primarily for AFib stroke prevention'),
  ('rivaroxaban%',                 'Factor Xa Inhibitor (DOAC)',       'I48.91', 96,  0.7800, 'Rivaroxaban prescribed primarily for AFib stroke prevention'),
  ('dabigatran%',                  'Direct Thrombin Inhibitor (DOAC)', 'I48.91', 96,  0.8000, 'Dabigatran prescribed exclusively for AFib stroke prevention'),
  ('edoxaban%',                    'Factor Xa Inhibitor (DOAC)',       'I48.91', 96,  0.8000, 'Edoxaban prescribed primarily for AFib stroke prevention'),
  ('amiodarone%',                  'Antiarrhythmic Class III',         'I48.91', 96,  0.8500, 'Amiodarone used for rhythm control in AFib and serious arrhythmias'),
  ('dronedarone%',                 'Antiarrhythmic',                   'I48.91', 96,  0.9000, 'Dronedarone indicated exclusively for AFib/AFL'),

  -- COPD (HCC111)
  ('tiotropium%',                  'LAMA Bronchodilator',             'J44.1',  111, 0.9000, 'Tiotropium is indicated exclusively for COPD maintenance'),
  ('umeclidinium%',                'LAMA Bronchodilator',             'J44.1',  111, 0.9000, 'LAMA: exclusively for COPD'),
  ('roflumilast%',                 'PDE4 Inhibitor',                  'J44.1',  111, 0.9500, 'Roflumilast indicated exclusively for severe COPD'),
  ('fluticasone%salmeterol%',      'ICS/LABA Combination',            'J44.1',  111, 0.7500, 'Advair/Wixela: used in COPD and severe asthma'),
  ('budesonide%formoterol%',       'ICS/LABA Combination',            'J44.1',  111, 0.7500, 'Symbicort: used in COPD and severe asthma'),

  -- Dementia (HCC52)
  ('donepezil%',                   'Cholinesterase Inhibitor',        'G30.9',  52,  0.9200, 'Donepezil indicated exclusively for Alzheimer dementia'),
  ('memantine%',                   'NMDA Receptor Antagonist',        'G30.9',  52,  0.9200, 'Memantine indicated exclusively for moderate-severe Alzheimer'),
  ('rivastigmine%',                'Cholinesterase Inhibitor',        'G30.9',  52,  0.9000, 'Rivastigmine for Alzheimer and Parkinson dementia'),
  ('galantamine%',                 'Cholinesterase Inhibitor',        'G30.9',  52,  0.9000, 'Galantamine indicated exclusively for Alzheimer dementia'),

  -- Parkinson Disease (HCC78)
  ('levodopa%carbidopa%',          'Dopaminergic',                    'G20',    78,  0.9500, 'Carbidopa-levodopa is cornerstone therapy for Parkinson disease'),
  ('pramipexole%',                 'Dopamine Agonist',                'G20',    78,  0.8500, 'Pramipexole used for Parkinson disease and RLS'),
  ('ropinirole%',                  'Dopamine Agonist',                'G20',    78,  0.8500, 'Ropinirole used for Parkinson disease and RLS'),
  ('rasagiline%',                  'MAO-B Inhibitor',                 'G20',    78,  0.9500, 'Rasagiline indicated exclusively for Parkinson disease'),
  ('selegiline%',                  'MAO-B Inhibitor',                 'G20',    78,  0.9200, 'Selegiline used primarily for Parkinson disease'),

  -- Transplant (HCC186)
  ('tacrolimus%',                  'Calcineurin Inhibitor',           'Z94.0',  186, 0.9500, 'Tacrolimus is a transplant immunosuppressant - kidney transplant'),
  ('cyclosporine%',                'Calcineurin Inhibitor',           'Z94.0',  186, 0.9200, 'Cyclosporine used for transplant and autoimmune conditions'),
  ('mycophenolate%',               'Antimetabolite Immunosuppressant','Z94.0',  186, 0.9000, 'Mycophenolate (CellCept) primary use is organ transplant maintenance'),
  ('sirolimus%',                   'mTOR Inhibitor',                  'Z94.0',  186, 0.9200, 'Sirolimus/rapamycin used for transplant immunosuppression'),

  -- CKD / Hypertensive CKD (HCC137/138)
  ('sevelamer%',                   'Phosphate Binder',                'N18.3',  138, 0.8500, 'Sevelamer used exclusively for CKD-related hyperphosphatemia'),
  ('cinacalcet%',                  'Calcimimetic',                    'N18.4',  137, 0.9000, 'Cinacalcet used for secondary hyperparathyroidism in CKD/dialysis'),
  ('epoetin%',                     'Erythropoiesis Stimulating Agent','N18.4',  137, 0.9000, 'Epoetin alfa used for CKD-related anemia'),
  ('darbepoetin%',                 'Erythropoiesis Stimulating Agent','N18.4',  137, 0.9000, 'Darbepoetin used for CKD-related anemia'),

  -- Morbid Obesity (HCC22)
  ('orlistat%',                    'Lipase Inhibitor',                'E66.01', 22,  0.8000, 'Orlistat prescribed for obesity management'),
  ('phentermine%topiramate%',      'Anorectic Combination',           'E66.01', 22,  0.8500, 'Qsymia indicated for chronic weight management in obesity'),
  ('naltrexone%bupropion%',        'Anorectic Combination',           'E66.01', 22,  0.8500, 'Contrave indicated for chronic weight management in obesity'),

  -- HIV/AIDS (HCC1)
  ('tenofovir%',                   'Nucleoside RT Inhibitor (ART)',    'B20',    1,   0.9500, 'ART component: indicates active HIV treatment'),
  ('emtricitabine%',               'Nucleoside RT Inhibitor (ART)',    'B20',    1,   0.9500, 'ART component: indicates active HIV treatment'),
  ('dolutegravir%',                'Integrase Inhibitor (ART)',        'B20',    1,   0.9800, 'Dolutegravir is an HIV integrase inhibitor'),
  ('bictegravir%',                 'Integrase Inhibitor (ART)',        'B20',    1,   0.9800, 'Bictegravir component of Biktarvy: HIV ART'),

  -- Rheumatoid Arthritis / Autoimmune (HCC40)
  ('methotrexate%',                'DMARD (Antimetabolite)',           'M05.9',  40,  0.8000, 'Methotrexate anchor DMARD for RA; also used in psoriasis/cancer'),
  ('adalimumab%',                  'TNF Inhibitor (Biologic)',         'M05.9',  40,  0.9000, 'Humira: biologic DMARD for RA and IBD'),
  ('etanercept%',                  'TNF Inhibitor (Biologic)',         'M05.9',  40,  0.9000, 'Enbrel: biologic DMARD primarily for RA and PsA'),
  ('rituximab%',                   'Anti-CD20 Biologic',              'M05.9',  40,  0.8500, 'Rituximab used in RA refractory to TNF inhibitors'),

  -- Schizophrenia / Psychosis (HCC57)
  ('clozapine%',                   'Atypical Antipsychotic',          'F20.9',  57,  0.9500, 'Clozapine is reserved for treatment-resistant schizophrenia'),
  ('paliperidone%',                'Atypical Antipsychotic',          'F20.9',  57,  0.8500, 'Paliperidone/Invega primarily used in schizophrenia'),

  -- Major Depression / Bipolar (HCC59)
  ('lithium%',                     'Mood Stabilizer',                 'F31.9',  59,  0.9000, 'Lithium is first-line for bipolar disorder mood stabilization'),
  ('valproate%',                   'Mood Stabilizer / Anticonvulsant','F31.9',  59,  0.8000, 'Valproate used for bipolar mania and seizure disorders');


-- =============================================================================
-- SEED DATA: raf_lab_signals (20+ lab value threshold rules)
-- =============================================================================

INSERT INTO raf_lab_signals
  (lab_name_pattern, lab_loinc_code, threshold_operator, threshold_value, threshold_low, threshold_high, threshold_unit, suspect_icd10, suspect_hcc, confidence_base, notes)
VALUES
  -- CKD staging via eGFR (LOINC 98980-6 estimated by CKD-EPI)
  ('eGFR%',            '98980-6',  '<',       60.0000, NULL,    NULL,    'mL/min/1.73m2', 'N18.3',  138, 0.8000, 'eGFR < 60 = CKD Stage 3 HCC138'),
  ('eGFR%',            '98980-6',  '<',       45.0000, NULL,    NULL,    'mL/min/1.73m2', 'N18.3',  138, 0.8500, 'eGFR 30-44 = CKD Stage 3b, still maps HCC138'),
  ('eGFR%',            '98980-6',  '<',       30.0000, NULL,    NULL,    'mL/min/1.73m2', 'N18.4',  137, 0.9000, 'eGFR < 30 = CKD Stage 4 HCC137'),
  ('eGFR%',            '98980-6',  '<',       15.0000, NULL,    NULL,    'mL/min/1.73m2', 'N18.5',  136, 0.9500, 'eGFR < 15 = CKD Stage 5 / ESRD HCC136'),
  ('creatinine%',      '2160-0',   '>',        1.5000, NULL,    NULL,    'mg/dL',         'N18.3',  138, 0.6500, 'Elevated creatinine suggests CKD - confirm with eGFR'),
  ('UACR%',            '9318-7',   '>=',      30.0000, NULL,    NULL,    'mg/g',          'N18.3',  138, 0.7000, 'Microalbuminuria (UACR >= 30) = CKD marker'),
  ('UACR%',            '9318-7',   '>=',     300.0000, NULL,    NULL,    'mg/g',          'N18.3',  138, 0.8500, 'Macroalbuminuria (UACR >= 300) = CKD marker'),

  -- Diabetes via HbA1c (LOINC 4548-4)
  ('HbA1c%',           '4548-4',   '>=',       6.5000, NULL,    NULL,    '%',             'E11.9',  19,  0.8500, 'HbA1c >= 6.5% meets ADA diagnostic threshold for diabetes'),
  ('HbA1c%',           '4548-4',   '>=',       9.0000, NULL,    NULL,    '%',             'E11.65', 18,  0.8500, 'HbA1c >= 9.0% indicates poorly controlled DM HCC18'),
  ('HbA1c%',           '4548-4',   'BETWEEN',  5.7000, 5.7000,  6.4000, '%',             'R73.09', 19,  0.6000, 'HbA1c 5.7-6.4% = prediabetes, watch for DM progression'),
  ('fasting glucose%', '1558-6',   '>=',     126.0000, NULL,    NULL,    'mg/dL',         'E11.9',  19,  0.7500, 'Fasting glucose >= 126 meets ADA diagnostic threshold'),
  ('fasting glucose%', '1558-6',   '>=',     200.0000, NULL,    NULL,    'mg/dL',         'E11.65', 18,  0.8000, 'Fasting glucose >= 200 with symptoms = uncontrolled DM'),

  -- Heart Failure via BNP/NT-proBNP (LOINC 42637-9 / 33762-6)
  ('BNP%',             '42637-9',  '>',      100.0000, NULL,    NULL,    'pg/mL',         'I50.9',  85,  0.7500, 'BNP > 100 pg/mL is diagnostic threshold for CHF'),
  ('BNP%',             '42637-9',  '>',      400.0000, NULL,    NULL,    'pg/mL',         'I50.9',  85,  0.9000, 'BNP > 400 pg/mL indicates decompensated CHF HCC85'),
  ('NT-proBNP%',       '33762-6',  '>',      300.0000, NULL,    NULL,    'pg/mL',         'I50.9',  85,  0.7500, 'NT-proBNP > 300 suggests acute CHF'),
  ('NT-proBNP%',       '33762-6',  '>',     900.0000,  NULL,    NULL,    'pg/mL',         'I50.9',  85,  0.8500, 'NT-proBNP > 900 indicates high likelihood of CHF HCC85'),

  -- Obesity via BMI (LOINC 39156-5)
  ('BMI%',             '39156-5',  '>=',      30.0000, NULL,    NULL,    'kg/m2',         'E66.9',  22,  0.7500, 'BMI >= 30 meets criteria for obesity'),
  ('BMI%',             '39156-5',  '>=',      35.0000, NULL,    NULL,    'kg/m2',         'E66.09', 22,  0.8500, 'BMI >= 35 = Class II obesity, higher risk'),
  ('BMI%',             '39156-5',  '>=',      40.0000, NULL,    NULL,    'kg/m2',         'E66.01', 22,  0.9500, 'BMI >= 40 = morbid obesity HCC22'),

  -- Dyslipidemia / Atherosclerosis
  ('LDL%',             '13457-7',  '>',      190.0000, NULL,    NULL,    'mg/dL',         'E78.5',  0,   0.8000, 'LDL > 190 suggests familial hypercholesterolemia'),
  ('total cholesterol%','2093-3',  '>',      240.0000, NULL,    NULL,    'mg/dL',         'E78.5',  0,   0.7000, 'Total cholesterol > 240 = hypercholesterolemia'),

  -- Anemia (relevant for CKD HCC)
  ('hemoglobin%',      '718-7',    '<',       10.0000, NULL,    NULL,    'g/dL',          'D63.1',  0,   0.7500, 'Hemoglobin < 10 suggests moderate anemia; rule out CKD cause'),
  ('hemoglobin%',      '718-7',    '<',        8.0000, NULL,    NULL,    'g/dL',          'D63.1',  0,   0.8500, 'Hemoglobin < 8 indicates severe anemia requiring workup'),

  -- Liver Disease (HCC27/28)
  ('ALT%',             '1742-6',   '>',      120.0000, NULL,    NULL,    'U/L',           'K76.0',  27,  0.7000, 'ALT > 3x ULN suggests hepatocellular injury - evaluate for NAFLD'),
  ('AST%',             '1920-8',   '>',      120.0000, NULL,    NULL,    'U/L',           'K76.0',  27,  0.7000, 'AST > 3x ULN suggests hepatocellular injury'),
  ('albumin%',         '1751-7',   '<',        3.0000, NULL,    NULL,    'g/dL',          'K74.60', 27,  0.8000, 'Albumin < 3 with liver disease suggests cirrhosis HCC27'),
  ('INR%',             '6301-6',   '>',        1.5000, NULL,    NULL,    'ratio',         'K74.60', 27,  0.7500, 'Elevated INR not on anticoagulation suggests hepatic synthetic dysfunction'),

  -- Thyroid
  ('TSH%',             '3016-3',   '>',       10.0000, NULL,    NULL,    'mIU/L',         'E03.9',  0,   0.8000, 'TSH > 10 = overt hypothyroidism, if untreated consider E03.9'),
  ('TSH%',             '3016-3',   '<',        0.0500, NULL,    NULL,    'mIU/L',         'E05.90', 0,   0.8000, 'TSH < 0.05 = overt hyperthyroidism HCC'),

  -- Potassium (relevant for CKD, CHF management)
  ('potassium%',       '2823-3',   '>',        5.5000, NULL,    NULL,    'mEq/L',         'E87.5',  0,   0.7500, 'Hyperkalemia > 5.5 in CKD/CHF patients - may indicate progression');


-- =============================================================================
-- End of RAF Intelligence System Schema
-- =============================================================================
