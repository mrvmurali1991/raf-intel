-- 032_patients_view_mbi.sql
--
-- Adds a synthetic `mbi` column (Medicare Beneficiary Identifier) to the
-- raf_intelligence.patients VIEW that bridges to openemr.patient_data.
--
-- Root cause:
--   openemr_connector.get_patient() SELECT-list includes `mbi` (line 251),
--   but the VIEW created during the OpenEMR integration omitted that column.
--   Result: every call to GET /api/patients/{id} and GET /api/suspects/{id}
--   raised "Unknown column 'mbi' in 'field list'" → HTTP 500, and the patient
--   detail page name remained stuck at "Loading…".
--
-- Fix:
--   OpenEMR's patient_data table has no native mbi column.  The production
--   MBI source is claims-derived data loaded via the upload pipeline.  For
--   the demo environment, CAST(NULL AS CHAR(20)) is correct and patient_service
--   handles NULL gracefully (displays "N/A" in the audit PDF cover sheet).
--
-- Backward compatibility:
--   Every column that existed in the original VIEW is preserved with identical
--   alias names so that /api/dashboard/stats, /api/patients, and all other
--   callers that read from `patients` continue to work without modification.
--
-- Idempotency:
--   DROP VIEW IF EXISTS + CREATE VIEW is the MySQL 8 idempotent pattern for
--   views (no stored-procedure wrapper required — DDL on views is always safe
--   to re-run because the view has no persistent row data).
--
-- Apply:
--   docker exec -i raf-mysql mysql -uroot -proot raf_intelligence \
--       < database/migrations/032_patients_view_mbi.sql

DROP VIEW IF EXISTS patients;

CREATE VIEW patients AS
SELECT
    openemr.patient_data.pid                              AS id,
    CAST(openemr.patient_data.pid AS CHAR(20))            AS emr_pid,
    openemr.patient_data.fname                            AS first_name,
    openemr.patient_data.lname                            AS last_name,
    openemr.patient_data.mname                            AS middle_name,
    openemr.patient_data.DOB                              AS dob,
    openemr.patient_data.sex                              AS sex,
    openemr.patient_data.pubpid                           AS mrn,
    openemr.patient_data.race                             AS race,
    openemr.patient_data.ethnicity                        AS ethnicity,
    openemr.patient_data.language                         AS preferred_language,
    openemr.patient_data.street                           AS address,
    openemr.patient_data.street                           AS street,
    openemr.patient_data.city                             AS city,
    openemr.patient_data.state                            AS state,
    openemr.patient_data.postal_code                      AS zip,
    openemr.patient_data.postal_code                      AS postal_code,
    openemr.patient_data.phone_cell                       AS phone,
    openemr.patient_data.phone_home                       AS phone_home,
    openemr.patient_data.phone_cell                       AS phone_cell,
    openemr.patient_data.email                            AS email,
    CAST(NULL AS CHAR(20))                                AS mbi,
    CAST(NULL AS CHAR(50))                                AS insurance_type,
    openemr.patient_data.providerID                       AS provider_id,
    'emr'                                                 AS data_source,
    1                                                     AS is_active,
    CAST(1 AS CHAR(64))                                   AS tenant_id,
    openemr.patient_data.date                             AS created_at
FROM openemr.patient_data;
