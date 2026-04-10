-- =============================================================================
-- RAF Intelligence System - Migration 018: Predictive Models
-- Engine: InnoDB | Charset: utf8mb4 | MySQL 8.0+
--
-- Adds ML-based predictive modeling infrastructure alongside the existing
-- rules-based suspect detection.  Models are trained offline via scikit-learn,
-- serialized to disk with joblib, and referenced here by file_path.
--
-- Tables created:
--   predictive_models    – model registry (metadata, metrics, status)
--   prediction_runs      – per-patient prediction records
--   prediction_batches   – batch scoring job records
--   feature_importance   – per-model feature ranking
-- =============================================================================

USE raf_intelligence;

-- =============================================================================
-- 1. PREDICTIVE_MODELS
--    Registry of trained ML models.  Each row represents one trained version
--    of a model type.  Only one model per (model_type, tenant_id) should be
--    status='active' at a time — enforced at the application layer.
-- =============================================================================
CREATE TABLE IF NOT EXISTS predictive_models (
  id                  INT UNSIGNED        NOT NULL AUTO_INCREMENT,
  name                VARCHAR(255)        NOT NULL                      COMMENT 'Human-readable model name',
  model_type          ENUM(
                        'raf_prediction',
                        'readmission_risk',
                        'mortality_risk',
                        'cost_prediction',
                        'hcc_likelihood'
                      )                   NOT NULL                      COMMENT 'Clinical prediction domain',
  version             VARCHAR(50)         NOT NULL DEFAULT '1.0.0'      COMMENT 'Semantic version string',
  description         TEXT                    NULL DEFAULT NULL          COMMENT 'Free-text description of training data and intent',
  algorithm           ENUM(
                        'gradient_boost',
                        'random_forest',
                        'logistic_regression',
                        'neural_net',
                        'ensemble'
                      )                   NOT NULL                      COMMENT 'Underlying sklearn algorithm family',
  features_config     JSON                    NULL DEFAULT NULL          COMMENT 'Feature names and preprocessing config used during training',
  hyperparameters     JSON                    NULL DEFAULT NULL          COMMENT 'sklearn estimator hyperparameters',
  training_metrics    JSON                    NULL DEFAULT NULL          COMMENT 'accuracy, auc, f1, precision, recall on hold-out set',
  status              ENUM(
                        'training',
                        'active',
                        'archived',
                        'failed'
                      )                   NOT NULL DEFAULT 'training'   COMMENT 'Lifecycle state',
  trained_at          DATETIME                NULL DEFAULT NULL          COMMENT 'UTC timestamp when training completed',
  training_samples    INT UNSIGNED            NULL DEFAULT NULL          COMMENT 'Number of samples used during training',
  file_path           VARCHAR(512)            NULL DEFAULT NULL          COMMENT 'Absolute path to joblib-serialized model artifact',
  tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default'    COMMENT 'Multi-tenant discriminator',
  created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_model_type        (model_type),
  INDEX idx_status            (status),
  INDEX idx_tenant_type_status(tenant_id, model_type, status),
  INDEX idx_trained_at        (trained_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Registry of trained ML predictive models';


-- =============================================================================
-- 2. PREDICTION_RUNS
--    One row per patient per model invocation (individual or batch member).
--    actual_value / actual_recorded_at are populated later for model validation.
-- =============================================================================
CREATE TABLE IF NOT EXISTS prediction_runs (
  id                  BIGINT UNSIGNED     NOT NULL AUTO_INCREMENT,
  model_id            INT UNSIGNED        NOT NULL                      COMMENT 'FK → predictive_models.id',
  patient_id          INT                 NOT NULL                      COMMENT 'OpenEMR patient_data.pid',
  run_type            ENUM(
                        'individual',
                        'batch'
                      )                   NOT NULL DEFAULT 'individual' COMMENT 'How this prediction was triggered',
  input_features      JSON                    NULL DEFAULT NULL          COMMENT 'Feature vector supplied to the model',
  predicted_value     DECIMAL(10,4)           NULL DEFAULT NULL          COMMENT 'Raw model output (probability or score)',
  confidence          DECIMAL(5,4)            NULL DEFAULT NULL          COMMENT 'Model confidence / max class probability',
  risk_tier           ENUM(
                        'very_high',
                        'high',
                        'moderate',
                        'low'
                      )                       NULL DEFAULT NULL          COMMENT 'Tier derived from predicted_value thresholds',
  contributing_factors JSON                   NULL DEFAULT NULL          COMMENT 'Top feature contributions (SHAP-style)',
  actual_value        DECIMAL(10,4)           NULL DEFAULT NULL          COMMENT 'Ground-truth value for validation',
  actual_recorded_at  DATETIME                NULL DEFAULT NULL          COMMENT 'When the actual outcome was recorded',
  batch_id            BIGINT UNSIGNED         NULL DEFAULT NULL          COMMENT 'FK → prediction_batches.id when run_type=batch',
  tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default',
  created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_model_patient  (model_id, patient_id),
  INDEX idx_patient        (patient_id),
  INDEX idx_batch          (batch_id),
  INDEX idx_risk_tier      (risk_tier),
  INDEX idx_tenant_model   (tenant_id, model_id),
  INDEX idx_created        (created_at),
  CONSTRAINT fk_pr_model   FOREIGN KEY (model_id) REFERENCES predictive_models(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Individual patient prediction results';


-- =============================================================================
-- 3. PREDICTION_BATCHES
--    Tracks a batch-scoring Celery job: how many patients were requested,
--    how many completed, and aggregate summary stats after the run finishes.
-- =============================================================================
CREATE TABLE IF NOT EXISTS prediction_batches (
  id                  BIGINT UNSIGNED     NOT NULL AUTO_INCREMENT,
  model_id            INT UNSIGNED        NOT NULL                      COMMENT 'FK → predictive_models.id',
  name                VARCHAR(255)        NOT NULL                      COMMENT 'Descriptive batch name',
  patient_count       INT UNSIGNED        NOT NULL DEFAULT 0            COMMENT 'Total patients requested',
  completed           INT UNSIGNED        NOT NULL DEFAULT 0            COMMENT 'Patients successfully scored so far',
  status              ENUM(
                        'queued',
                        'running',
                        'completed',
                        'failed'
                      )                   NOT NULL DEFAULT 'queued',
  started_at          DATETIME                NULL DEFAULT NULL,
  completed_at        DATETIME                NULL DEFAULT NULL,
  summary_stats       JSON                    NULL DEFAULT NULL          COMMENT 'mean/median/tier distribution after completion',
  tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default',
  created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  INDEX idx_model_id    (model_id),
  INDEX idx_status      (status),
  INDEX idx_tenant      (tenant_id),
  CONSTRAINT fk_pb_model FOREIGN KEY (model_id) REFERENCES predictive_models(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Batch scoring job tracking';


-- =============================================================================
-- 4. FEATURE_IMPORTANCE
--    Stores per-model feature importance rankings (from sklearn .feature_importances_
--    or logistic regression coefficients).  One row per feature per model version.
-- =============================================================================
CREATE TABLE IF NOT EXISTS feature_importance (
  id                  INT UNSIGNED        NOT NULL AUTO_INCREMENT,
  model_id            INT UNSIGNED        NOT NULL                      COMMENT 'FK → predictive_models.id',
  feature_name        VARCHAR(255)        NOT NULL,
  importance_score    DECIMAL(8,6)        NOT NULL DEFAULT 0.000000     COMMENT 'Normalised 0–1 importance weight',
  rank                INT UNSIGNED        NOT NULL                      COMMENT '1 = most important',
  category            ENUM(
                        'demographic',
                        'clinical',
                        'claims',
                        'utilization',
                        'pharmacy'
                      )                   NOT NULL DEFAULT 'clinical'   COMMENT 'Feature domain grouping',
  tenant_id           VARCHAR(50)         NOT NULL DEFAULT 'default',

  PRIMARY KEY (id),
  UNIQUE  KEY uq_model_feature  (model_id, feature_name),
  INDEX idx_model_rank          (model_id, rank),
  INDEX idx_category            (category),
  CONSTRAINT fk_fi_model        FOREIGN KEY (model_id) REFERENCES predictive_models(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Feature importance scores per trained model';
