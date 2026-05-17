-- Bulk FHIR ingest jobs table.
--
-- Tracks the lifecycle of large FHIR Bulk Data Access ($export) imports and
-- one-shot NDJSON uploads.  One row per "ingest run" — the Celery task
-- `raf.bulk_ingest.run` writes progress here every batch.
--
-- Status state machine:
--   pending → downloading → ingesting → completed
--                                    ↘ failed
--
-- Apply with:
--   docker exec raf-mysql sh -c 'mysql -uroot -proot raf_intelligence < /path/to/file'
--
-- Idempotent — uses CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS raf_bulk_ingest_jobs (
    id                 VARCHAR(64) PRIMARY KEY,
    tenant_id          VARCHAR(50)  NOT NULL,
    source_url         VARCHAR(2048),
    source_type        VARCHAR(40)  NOT NULL,                    -- 'fhir_bulk_export' | 'ndjson_upload'
    resource_types     TEXT,                                     -- JSON array of FHIR resource type names
    status             VARCHAR(20)  NOT NULL DEFAULT 'pending',  -- pending|downloading|ingesting|completed|failed
    total_resources    BIGINT       NOT NULL DEFAULT 0,
    ingested_resources BIGINT       NOT NULL DEFAULT 0,
    errors_count       BIGINT       NOT NULL DEFAULT 0,
    patient_count      BIGINT       NOT NULL DEFAULT 0,
    condition_count    BIGINT       NOT NULL DEFAULT 0,
    encounter_count    BIGINT       NOT NULL DEFAULT 0,
    observation_count  BIGINT       NOT NULL DEFAULT 0,
    errors_json        MEDIUMTEXT,                               -- truncated list of error strings
    submitted_by       INT,
    started_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at       DATETIME,
    INDEX idx_bulk_ingest_tenant  (tenant_id),
    INDEX idx_bulk_ingest_status  (status),
    INDEX idx_bulk_ingest_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
