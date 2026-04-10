-- Minimal OpenEMR schema for RAF Intelligence local development
CREATE DATABASE IF NOT EXISTS openemr;
USE openemr;

CREATE TABLE IF NOT EXISTS patient_data (
  pid bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  title varchar(255) DEFAULT '',
  fname varchar(255) DEFAULT '',
  lname varchar(255) DEFAULT '',
  mname varchar(255) DEFAULT '',
  DOB date DEFAULT NULL,
  sex varchar(25) DEFAULT '',
  street varchar(255) DEFAULT '',
  city varchar(255) DEFAULT '',
  state varchar(50) DEFAULT '',
  postal_code varchar(20) DEFAULT '',
  phone_home varchar(50) DEFAULT '',
  phone_cell varchar(50) DEFAULT '',
  email varchar(255) DEFAULT '',
  ss varchar(11) DEFAULT '',
  race varchar(255) DEFAULT '',
  ethnicity varchar(255) DEFAULT '',
  status varchar(20) DEFAULT 'active',
  providerID bigint DEFAULT NULL,
  date datetime DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  fname varchar(255) DEFAULT '',
  lname varchar(255) DEFAULT '',
  title varchar(255) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS form_encounter (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  pid bigint NOT NULL,
  encounter bigint NOT NULL,
  date datetime DEFAULT NULL,
  reason varchar(255) DEFAULT '',
  facility varchar(255) DEFAULT '',
  provider_id bigint DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS billing (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  pid bigint NOT NULL,
  encounter bigint NOT NULL,
  code_type varchar(50) DEFAULT '',
  code varchar(50) DEFAULT '',
  code_text varchar(255) DEFAULT '',
  activity tinyint DEFAULT 1,
  authorized tinyint DEFAULT 1
);

CREATE TABLE IF NOT EXISTS prescriptions (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  patient_id bigint NOT NULL,
  drug varchar(255) DEFAULT '',
  dosage varchar(100) DEFAULT '',
  route varchar(100) DEFAULT '',
  freq varchar(100) DEFAULT '',
  quantity varchar(50) DEFAULT '',
  size varchar(50) DEFAULT '',
  unit varchar(50) DEFAULT '',
  refills int DEFAULT 0,
  per_refill int DEFAULT 0,
  start_date date DEFAULT NULL,
  date_added date DEFAULT NULL,
  active tinyint DEFAULT 1,
  note text
);

CREATE TABLE IF NOT EXISTS form_soap (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  pid bigint NOT NULL,
  groupname varchar(100) DEFAULT '',
  activity tinyint DEFAULT 1,
  subjective text,
  objective text,
  assessment text,
  plan text
);

CREATE TABLE IF NOT EXISTS forms (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  date datetime DEFAULT NULL,
  encounter bigint NOT NULL,
  form_name varchar(255) DEFAULT '',
  form_id bigint NOT NULL,
  pid bigint NOT NULL,
  formdir varchar(100) DEFAULT '',
  deleted tinyint DEFAULT 0
);

CREATE TABLE IF NOT EXISTS form_vitals (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  pid bigint NOT NULL,
  encounter bigint DEFAULT NULL,
  date datetime DEFAULT NULL,
  weight_metric decimal(7,2) DEFAULT NULL,
  height_metric decimal(7,2) DEFAULT NULL,
  bpd decimal(5,2) DEFAULT NULL,
  bps decimal(5,2) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS form_clinical_notes (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  pid bigint NOT NULL,
  encounter bigint DEFAULT NULL,
  date datetime DEFAULT NULL,
  note_type varchar(100) DEFAULT '',
  note text
);

CREATE TABLE IF NOT EXISTS procedure_result (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  pid bigint DEFAULT NULL,
  encounter bigint DEFAULT NULL,
  date datetime DEFAULT NULL,
  result_text text
);

CREATE TABLE IF NOT EXISTS procedure_order (
  id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
  patient_id bigint DEFAULT NULL,
  encounter_id bigint DEFAULT NULL,
  date_ordered date DEFAULT NULL
);

-- Sample patients
INSERT INTO patient_data (pid, fname, lname, DOB, sex, city, state, phone_home) VALUES
(1, 'Robert', 'Johnson', '1948-03-15', 'Male', 'Boston', 'MA', '617-555-0101'),
(2, 'Mary', 'Williams', '1952-07-22', 'Female', 'Chicago', 'IL', '312-555-0102'),
(3, 'James', 'Brown', '1945-11-08', 'Male', 'Houston', 'TX', '713-555-0103'),
(4, 'Patricia', 'Davis', '1955-05-30', 'Female', 'Phoenix', 'AZ', '602-555-0104'),
(5, 'Michael', 'Miller', '1950-09-12', 'Male', 'Philadelphia', 'PA', '215-555-0105'),
(6, 'Linda', 'Wilson', '1943-01-25', 'Female', 'San Antonio', 'TX', '210-555-0106'),
(7, 'William', 'Moore', '1958-06-18', 'Male', 'San Diego', 'CA', '619-555-0107'),
(8, 'Barbara', 'Taylor', '1947-12-04', 'Female', 'Dallas', 'TX', '214-555-0108'),
(9, 'David', 'Anderson', '1953-04-27', 'Male', 'San Jose', 'CA', '408-555-0109'),
(10, 'Susan', 'Thomas', '1960-08-14', 'Female', 'Jacksonville', 'FL', '904-555-0110'),
(11, 'Richard', 'Jackson', '1942-02-09', 'Male', 'Indianapolis', 'IN', '317-555-0111'),
(12, 'Jessica', 'White', '1956-10-31', 'Female', 'Columbus', 'OH', '614-555-0112'),
(13, 'Charles', 'Harris', '1949-07-16', 'Male', 'Charlotte', 'NC', '704-555-0113'),
(14, 'Sarah', 'Martin', '1963-03-22', 'Female', 'Memphis', 'TN', '901-555-0114'),
(15, 'Thomas', 'Thompson', '1944-05-05', 'Male', 'Baltimore', 'MD', '410-555-0115');

INSERT INTO form_encounter (pid, encounter, date, reason, facility) VALUES
(1, 1001, '2025-10-15 09:00:00', 'Annual wellness visit', 'General Hospital'),
(1, 1002, '2026-01-20 14:00:00', 'Diabetes follow-up', 'General Hospital'),
(2, 1003, '2025-09-12 10:30:00', 'Hypertension management', 'City Clinic'),
(3, 1004, '2025-11-08 11:00:00', 'CHF management', 'Heart Center'),
(3, 1005, '2026-02-14 09:30:00', 'Cardiology follow-up', 'Heart Center'),
(4, 1006, '2025-12-01 15:00:00', 'COPD evaluation', 'Pulmonary Clinic'),
(5, 1007, '2026-01-10 08:00:00', 'CKD stage 3 follow-up', 'Nephrology Clinic'),
(6, 1008, '2025-10-22 13:00:00', 'Annual exam', 'Senior Care Center'),
(7, 1009, '2025-11-30 10:00:00', 'Diabetes and hypertension', 'Primary Care'),
(8, 1010, '2026-02-05 09:00:00', 'Atrial fibrillation follow-up', 'Cardiology'),
(9, 1011, '2025-12-15 11:00:00', 'CKD follow-up', 'Nephrology'),
(10, 1012, '2026-01-25 14:00:00', 'Diabetes management', 'Endocrinology'),
(11, 1013, '2025-10-30 09:30:00', 'COPD and CHF', 'Pulmonary'),
(12, 1014, '2026-02-10 10:00:00', 'Rheumatology follow-up', 'Rheumatology Clinic'),
(13, 1015, '2025-11-20 13:00:00', 'Annual wellness', 'Primary Care'),
(14, 1016, '2026-01-08 11:30:00', 'Diabetes follow-up', 'Endocrinology'),
(15, 1017, '2025-12-05 09:00:00', 'CHF management', 'Cardiology');

INSERT INTO billing (pid, encounter, code_type, code, code_text) VALUES
(1, 1001, 'ICD10', 'E11.9', 'Type 2 diabetes mellitus without complications'),
(1, 1001, 'ICD10', 'I10', 'Essential (primary) hypertension'),
(1, 1002, 'ICD10', 'E11.65', 'Type 2 diabetes with hyperglycemia'),
(2, 1003, 'ICD10', 'I10', 'Essential (primary) hypertension'),
(2, 1003, 'ICD10', 'I25.10', 'Atherosclerotic heart disease'),
(3, 1004, 'ICD10', 'I50.9', 'Heart failure, unspecified'),
(3, 1004, 'ICD10', 'I48.91', 'Unspecified atrial fibrillation'),
(3, 1005, 'ICD10', 'I50.32', 'Chronic diastolic heart failure'),
(4, 1006, 'ICD10', 'J44.1', 'COPD with acute exacerbation'),
(4, 1006, 'ICD10', 'J45.50', 'Severe persistent asthma'),
(5, 1007, 'ICD10', 'N18.3', 'CKD stage 3'),
(5, 1007, 'ICD10', 'E11.9', 'Type 2 diabetes mellitus'),
(6, 1008, 'ICD10', 'G30.9', 'Alzheimers disease unspecified'),
(7, 1009, 'ICD10', 'E11.9', 'Type 2 diabetes mellitus'),
(7, 1009, 'ICD10', 'I10', 'Essential hypertension'),
(7, 1009, 'ICD10', 'E78.5', 'Hyperlipidemia unspecified'),
(8, 1010, 'ICD10', 'I48.0', 'Paroxysmal atrial fibrillation'),
(8, 1010, 'ICD10', 'I50.9', 'Heart failure unspecified'),
(9, 1011, 'ICD10', 'N18.4', 'CKD stage 4'),
(9, 1011, 'ICD10', 'I10', 'Essential hypertension'),
(10, 1012, 'ICD10', 'E11.40', 'Type 2 diabetes with diabetic neuropathy'),
(11, 1013, 'ICD10', 'J44.1', 'COPD with acute exacerbation'),
(11, 1013, 'ICD10', 'I50.9', 'Heart failure unspecified'),
(12, 1014, 'ICD10', 'M05.79', 'Rheumatoid arthritis'),
(13, 1015, 'ICD10', 'E11.9', 'Type 2 diabetes mellitus'),
(14, 1016, 'ICD10', 'E10.9', 'Type 1 diabetes mellitus'),
(15, 1017, 'ICD10', 'I50.22', 'Chronic systolic heart failure');

INSERT INTO prescriptions (patient_id, drug, dosage, route, freq, start_date, active) VALUES
(1, 'Metformin', '1000mg', 'Oral', 'Twice daily', '2022-01-01', 1),
(1, 'Lisinopril', '10mg', 'Oral', 'Once daily', '2021-06-15', 1),
(2, 'Amlodipine', '5mg', 'Oral', 'Once daily', '2020-03-10', 1),
(2, 'Atorvastatin', '40mg', 'Oral', 'Once daily', '2020-03-10', 1),
(3, 'Furosemide', '40mg', 'Oral', 'Once daily', '2023-02-01', 1),
(3, 'Carvedilol', '25mg', 'Oral', 'Twice daily', '2023-02-01', 1),
(3, 'Warfarin', '5mg', 'Oral', 'Once daily', '2023-03-01', 1),
(4, 'Tiotropium', '18mcg', 'Inhaled', 'Once daily', '2021-09-15', 1),
(4, 'Fluticasone', '250mcg', 'Inhaled', 'Twice daily', '2021-09-15', 1),
(5, 'Losartan', '50mg', 'Oral', 'Once daily', '2022-05-20', 1),
(5, 'Insulin glargine', '20 units', 'Subcutaneous', 'Once daily', '2022-05-20', 1),
(6, 'Donepezil', '10mg', 'Oral', 'Once daily', '2023-07-01', 1),
(7, 'Insulin glargine', '20 units', 'Subcutaneous', 'Once daily', '2022-11-10', 1),
(7, 'Metformin', '500mg', 'Oral', 'Twice daily', '2022-11-10', 1),
(8, 'Warfarin', '5mg', 'Oral', 'Once daily', '2023-04-15', 1),
(8, 'Digoxin', '0.125mg', 'Oral', 'Once daily', '2023-04-15', 1);

INSERT INTO form_soap (pid, activity, subjective, objective, assessment, plan) VALUES
(1, 1, 'Patient reports fatigue and increased thirst. Monitoring blood sugar at home averaging 200-250.', 'BP 138/88, HR 76. BG 210 mg/dL fasting. HbA1c 8.2%.', 'Type 2 DM poorly controlled. Hypertension - monitor and treat. Patient compliant with medications.', 'Increase metformin to 1000mg BID. Recheck HbA1c in 3 months. Continue Lisinopril.'),
(2, 1, 'Patient here for blood pressure follow-up. Reports occasional headaches.', 'BP 158/96, HR 72. No edema. Heart sounds normal.', 'Hypertension inadequately controlled. Atherosclerotic heart disease - stable. Continue statin therapy.', 'Increase Amlodipine to 10mg. Follow up in 4 weeks.'),
(3, 1, 'Patient reports shortness of breath on exertion and bilateral leg swelling for 3 days.', 'BP 145/92, HR 88 irregular. Bibasilar crackles. 2+ pitting edema bilateral lower extremities.', 'Chronic diastolic heart failure with fluid overload. Atrial fibrillation - rate controlled on Warfarin. INR therapeutic.', 'Increase Furosemide to 80mg. Daily weights. Cardiology follow-up in 2 weeks. Restrict sodium.'),
(4, 1, 'Patient with increased dyspnea and productive cough for 5 days. Using rescue inhaler more frequently.', 'O2 sat 91% on RA, HR 98, RR 22. Diffuse expiratory wheezes. Decreased air entry bilateral bases.', 'COPD acute exacerbation. Severe persistent asthma. Evaluate and treat. Monitor O2 saturation.', 'Prednisone burst 40mg x 5 days. Increase bronchodilator frequency. Nebulizer treatment now.'),
(5, 1, 'Patient with known CKD stage 3. Fatigue and decreased appetite. Diabetes management ongoing.', 'BP 142/88, HR 74. Cr 2.1, eGFR 32. BG 180. Urine protein 2+.', 'CKD stage 3 progressing. Type 2 DM with nephropathy. Hypertension contributing to renal decline.', 'Continue Losartan. Nephrology referral. Restrict protein intake. Renal diet education.'),
(7, 1, 'Annual wellness visit. Patient managing diabetes and hypertension at home.', 'BP 134/82, HR 76. BG 165. HbA1c 7.4%. Lipids: LDL 95, HDL 42.', 'Type 2 DM reasonably controlled. Hypertension controlled. Hyperlipidemia on statin therapy.', 'Continue current regimen. Annual eye exam. Foot exam performed - no wounds. Follow up in 6 months.');

-- Performance indexes for RAF pipeline queries
ALTER TABLE form_encounter ADD INDEX IF NOT EXISTS idx_fe_pid (pid);
ALTER TABLE billing ADD INDEX IF NOT EXISTS idx_billing_pid (pid);
ALTER TABLE billing ADD INDEX IF NOT EXISTS idx_billing_pid_encounter (pid, encounter);
ALTER TABLE prescriptions ADD INDEX IF NOT EXISTS idx_prescriptions_patient_id (patient_id);
ALTER TABLE form_vitals ADD INDEX IF NOT EXISTS idx_vitals_pid (pid);
