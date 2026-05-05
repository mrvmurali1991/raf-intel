-- ===========================================================================
-- patients compatibility VIEW
-- ===========================================================================
-- Several services in app/services/* (patient_service, awv_prioritization,
-- hcc_removal_engine, etc.) query a `patients` table in raf_intelligence with
-- columns inherited from an earlier schema. The current production schema
-- keeps demographic data in OpenEMR's patient_data table and tenant scoping
-- in raf_patient_demographics.
--
-- This VIEW bridges the two so legacy callers keep working. It is read-only
-- (writes via patients table are not used by the services that hit this view).
--
-- Columns are mapped to match what app/services/patient_service.py SELECTs.
-- Apply once per environment:
--     mysql ... raf_intelligence < add_patients_compat_view.sql
-- ===========================================================================

CREATE OR REPLACE VIEW patients AS
SELECT
    pd.pid                                AS id,
    pd.fname                              AS first_name,
    pd.lname                              AS last_name,
    pd.mname                              AS middle_name,
    pd.DOB                                AS dob,
    pd.DOB                                AS date_of_birth,
    pd.sex                                AS sex,
    pd.race                               AS race,
    pd.ethnicity                          AS ethnicity,
    pd.language                           AS preferred_language,
    pd.street                             AS address,
    pd.city                               AS city,
    pd.state                              AS state,
    pd.postal_code                        AS zip,
    pd.phone_cell                         AS phone,
    pd.phone_home                         AS phone_home,
    pd.email                              AS email,
    pd.pubpid                             AS mrn,
    NULL                                  AS insurance_type,
    'openemr'                             AS data_source,
    pd.pid                                AS emr_pid,
    1                                     AS emr_connection_id,
    1                                     AS is_active,
    COALESCE(rpd.tenant_id, '1')          AS tenant_id,
    pd.date                               AS created_at,
    pd.date                               AS updated_at
FROM openemr.patient_data pd
LEFT JOIN (
    SELECT patient_id, MAX(tenant_id) AS tenant_id
    FROM raf_patient_demographics
    GROUP BY patient_id
) rpd ON rpd.patient_id = pd.pid;
