-- =============================================================================
-- RAF INTELLIGENCE — DEMO SEED DATA
-- Scenario: "Sunrise Health Partners" — Medicare Advantage Plan
-- 30 patients · 4 providers · ~130 encounters · 25+ suspect conditions
--
-- STORY: A mid-size MA plan onboarding RAF Intelligence. The data reveals:
--   • 6 high-risk patients with full HCC profiles
--   • Coding gaps worth ~$380K in recapturable revenue
--   • AI suspects catching conditions providers missed
--   • Clear provider performance spread (Mitchell 80% vs Park 55% capture)
--   • MEAT documentation variance driving coaching opportunities
--
-- Safety: Idempotent — DELETEs existing demo rows before inserting.
-- Run order: openemr first, then raf_intelligence (patient IDs must align).
-- =============================================================================

SET FOREIGN_KEY_CHECKS = 0;
SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 0: EMR CONNECTION RECORD
-- ─────────────────────────────────────────────────────────────────────────────
USE raf_intelligence;

DELETE FROM emr_connections WHERE tenant_id = 'default';

INSERT INTO emr_connections (
  tenant_id, name, display_name, vendor, connection_type,
  db_host, db_port, db_name, db_user, db_password, db_type,
  base_url, auth_type, is_active, sync_enabled, sync_interval_minutes,
  last_sync_at, created_at
) VALUES (
  'default',
  'Sunrise Health OpenEMR',
  'Sunrise Health OpenEMR',
  'openemr',
  'direct_db',
  'mysql', 3306, 'openemr', 'root', 'root', 'mysql',
  'http://openemr:80', 'none', 1, 1, 60,
  NOW(), NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 1: OPENEMR — PATIENT DATA
-- ─────────────────────────────────────────────────────────────────────────────
USE openemr;

-- Clear existing demo patients (IDs 1–30)
DELETE FROM form_vitals     WHERE pid BETWEEN 1 AND 30;
DELETE FROM prescriptions   WHERE patient_id BETWEEN 1 AND 30;
DELETE FROM lists           WHERE pid BETWEEN 1 AND 30;
DELETE FROM billing         WHERE pid BETWEEN 1 AND 30;
DELETE FROM form_encounter  WHERE pid BETWEEN 1 AND 30;
DELETE FROM patient_data    WHERE id BETWEEN 1 AND 30;

-- ── HIGH RISK PATIENTS (1–6) ────────────────────────────────────────────────

-- Patient 1: Margaret Chen, 78F — CHF, CKD4, DM2 w/ complications, Vascular
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (1, 1, 'Margaret', 'Chen', 'L', '1948-03-12', 'Female', '4821 Mockingbird Ln', 'Houston', 'TX', '77006', '713-555-0101', '713-555-0201', '001-01-0001', 'active', 1, '2025-01-15 08:00:00');

-- Patient 2: Robert Williams, 82M — COPD, Lung Cancer, Malnutrition
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (2, 2, 'Robert', 'Williams', 'J', '1944-07-08', 'Male', '1102 Bering Dr', 'Houston', 'TX', '77057', '713-555-0102', '713-555-0202', '001-01-0002', 'active', 1, '2025-01-20 08:00:00');

-- Patient 3: James Johnson, 71M — ESRD, DM2, CHF, CKD Anemia
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (3, 3, 'James', 'Johnson', 'A', '1954-11-22', 'Male', '7730 Fondren Rd', 'Houston', 'TX', '77036', '713-555-0103', '713-555-0203', '001-01-0003', 'active', 2, '2025-01-10 08:00:00');

-- Patient 4: Dorothy Martinez, 76F — Dementia, Parkinson''s, Depression
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (4, 4, 'Dorothy', 'Martinez', 'R', '1950-05-30', 'Female', '3318 Westheimer Rd', 'Houston', 'TX', '77098', '713-555-0104', '713-555-0204', '001-01-0004', 'active', 3, '2025-02-01 08:00:00');

-- Patient 5: William Brown, 69M — Liver Disease, DM2, Coagulopathy
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (5, 5, 'William', 'Brown', 'T', '1956-09-14', 'Male', '5500 Bissonnet St', 'Houston', 'TX', '77081', '713-555-0105', '713-555-0205', '001-01-0005', 'active', 2, '2025-01-25 08:00:00');

-- Patient 6: Helen Davis, 85F — Stroke, Hemiplegia, AFib, CHF
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (6, 6, 'Helen', 'Davis', 'M', '1940-12-03', 'Female', '2201 Memorial Dr', 'Houston', 'TX', '77007', '713-555-0106', '713-555-0206', '001-01-0006', 'active', 1, '2025-01-08 08:00:00');

-- ── MEDIUM RISK PATIENTS (7–18) ─────────────────────────────────────────────

-- Patient 7: Gerald Thompson, 72M — DM2 w/ neuropathy, AFib, CKD3
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (7, 7, 'Gerald', 'Thompson', 'W', '1953-04-18', 'Male', '9020 Cullen Blvd', 'Houston', 'TX', '77051', '713-555-0107', '713-555-0207', '001-01-0007', 'active', 2, '2025-02-05 08:00:00');

-- Patient 8: Patricia Anderson, 68F — COPD, Depression, Obesity
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (8, 8, 'Patricia', 'Anderson', 'K', '1957-08-25', 'Female', '6718 Gulf Fwy', 'Houston', 'TX', '77017', '713-555-0108', '713-555-0208', '001-01-0008', 'active', 1, '2025-02-10 08:00:00');

-- Patient 9: Charles Wilson, 74M — CHF, Vascular Disease, CKD3
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (9, 9, 'Charles', 'Wilson', 'B', '1951-02-07', 'Male', '3400 Kirby Dr', 'Houston', 'TX', '77098', '713-555-0109', '713-555-0209', '001-01-0009', 'active', 4, '2025-01-30 08:00:00');

-- Patient 10: Barbara Jackson, 65F — DM2, Obesity, Depression
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (10, 10, 'Barbara', 'Jackson', 'L', '1960-06-19', 'Female', '1540 South Blvd', 'Houston', 'TX', '77006', '713-555-0110', '713-555-0210', '001-01-0010', 'active', 3, '2025-02-15 08:00:00');

-- Patient 11: Richard Harris, 77M — Rheumatoid Arthritis, AFib, CHF
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (11, 11, 'Richard', 'Harris', 'E', '1948-10-11', 'Male', '8820 Almeda Rd', 'Houston', 'TX', '77054', '713-555-0111', '713-555-0211', '001-01-0011', 'active', 4, '2025-01-22 08:00:00');

-- Patient 12: Nancy Lewis, 70F — Dementia (mild), CKD3, Depression
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (12, 12, 'Nancy', 'Lewis', 'A', '1955-01-29', 'Female', '4050 Richmond Ave', 'Houston', 'TX', '77027', '713-555-0112', '713-555-0212', '001-01-0012', 'active', 3, '2025-02-20 08:00:00');

-- Patient 13: Joseph Robinson, 75M — COPD, Vascular Disease
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (13, 13, 'Joseph', 'Robinson', 'C', '1950-07-04', 'Male', '7200 Main St', 'Houston', 'TX', '77030', '713-555-0113', '713-555-0213', '001-01-0013', 'active', 1, '2025-02-28 08:00:00');

-- Patient 14: Karen Walker, 67F — DM2 w/ complications, CKD3, Obesity
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (14, 14, 'Karen', 'Walker', 'M', '1958-03-17', 'Female', '2900 Fanin St', 'Houston', 'TX', '77002', '713-555-0114', '713-555-0214', '001-01-0014', 'active', 2, '2025-03-05 08:00:00');

-- Patient 15: Thomas Hall, 80M — CHF, AFib, Stroke (remote)
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (15, 15, 'Thomas', 'Hall', 'D', '1945-11-08', 'Male', '1800 Lamar St', 'Houston', 'TX', '77003', '713-555-0115', '713-555-0215', '001-01-0015', 'active', 4, '2025-01-18 08:00:00');

-- Patient 16: Lisa Allen, 63F — DM2, Peripheral Vascular Disease, Depression
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (16, 16, 'Lisa', 'Allen', 'N', '1962-09-01', 'Female', '5440 Westpark Dr', 'Houston', 'TX', '77056', '713-555-0116', '713-555-0216', '001-01-0016', 'active', 3, '2025-03-10 08:00:00');

-- Patient 17: Daniel Young, 71M — COPD, DM2, Obesity
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (17, 17, 'Daniel', 'Young', 'P', '1954-05-23', 'Male', '3700 Ella Blvd', 'Houston', 'TX', '77018', '713-555-0117', '713-555-0217', '001-01-0017', 'active', 2, '2025-03-15 08:00:00');

-- Patient 18: Sandra King, 73F — Rheumatoid Arthritis, CKD3, Depression
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (18, 18, 'Sandra', 'King', 'F', '1952-12-14', 'Female', '6200 Telephone Rd', 'Houston', 'TX', '77087', '713-555-0118', '713-555-0218', '001-01-0018', 'active', 1, '2025-03-20 08:00:00');

-- ── LOW RISK PATIENTS (19–30) ───────────────────────────────────────────────

-- Patient 19: Edward Scott, 62M — Well-controlled hypertension only
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (19, 19, 'Edward', 'Scott', 'H', '1963-07-30', 'Male', '1200 Washington Ave', 'Houston', 'TX', '77007', '713-555-0119', '713-555-0219', '001-01-0019', 'active', 2, '2025-04-01 08:00:00');

-- Patient 20: Carol Green, 58F — Mild DM2 (diet-controlled)
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (20, 20, 'Carol', 'Green', 'J', '1967-02-14', 'Female', '4330 Yale St', 'Houston', 'TX', '77018', '713-555-0120', '713-555-0220', '001-01-0020', 'active', 3, '2025-04-05 08:00:00');

-- Patient 21: Kenneth Baker, 66M — Hyperlipidemia, pre-DM2
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (21, 21, 'Kenneth', 'Baker', 'R', '1959-10-05', 'Male', '2780 Almeda Rd', 'Houston', 'TX', '77054', '713-555-0121', '713-555-0221', '001-01-0021', 'active', 1, '2025-04-10 08:00:00');

-- Patient 22: Donna Adams, 60F — Mild anxiety, osteoarthritis
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (22, 22, 'Donna', 'Adams', 'C', '1965-04-22', 'Female', '9800 Beechnut St', 'Houston', 'TX', '77036', '713-555-0122', '713-555-0222', '001-01-0022', 'active', 2, '2025-04-15 08:00:00');

-- Patient 23: Steven Nelson, 70M — HTN, early CKD3 (borderline)
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (23, 23, 'Steven', 'Nelson', 'G', '1955-08-16', 'Male', '5600 Hillcroft Ave', 'Houston', 'TX', '77036', '713-555-0123', '713-555-0223', '001-01-0023', 'active', 4, '2025-04-20 08:00:00');

-- Patient 24: Maria Carter, 55F — Obesity, prediabetes
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (24, 24, 'Maria', 'Carter', 'E', '1970-11-30', 'Female', '3100 Dunlavy St', 'Houston', 'TX', '77006', '713-555-0124', '713-555-0224', '001-01-0024', 'active', 3, '2025-05-01 08:00:00');

-- Patient 25: Paul Mitchell, 74M — DM2 well-controlled, HTN
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (25, 25, 'Paul', 'Mitchell', 'A', '1951-06-09', 'Male', '4400 Shepherd Dr', 'Houston', 'TX', '77098', '713-555-0125', '713-555-0225', '001-01-0025', 'active', 1, '2025-05-05 08:00:00');

-- Patient 26: Ruth Perez, 69F — Depression (stable), HTN
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (26, 26, 'Ruth', 'Perez', 'I', '1956-01-27', 'Female', '7890 Harwin Dr', 'Houston', 'TX', '77036', '713-555-0126', '713-555-0226', '001-01-0026', 'active', 2, '2025-05-10 08:00:00');

-- Patient 27: Frank Roberts, 63M — Hyperlipidemia, GERD
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (27, 27, 'Frank', 'Roberts', 'D', '1962-03-11', 'Male', '2200 Edloe St', 'Houston', 'TX', '77027', '713-555-0127', '713-555-0227', '001-01-0027', 'active', 4, '2025-05-15 08:00:00');

-- Patient 28: Joyce Turner, 67F — HTN, osteoporosis
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (28, 28, 'Joyce', 'Turner', 'B', '1958-09-03', 'Female', '5900 Stella Link Rd', 'Houston', 'TX', '77025', '713-555-0128', '713-555-0228', '001-01-0028', 'active', 3, '2025-05-20 08:00:00');

-- Patient 29: Larry Phillips, 61M — Well-controlled DM2, no complications
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (29, 29, 'Larry', 'Phillips', 'K', '1964-12-20', 'Male', '1500 Holcombe Blvd', 'Houston', 'TX', '77030', '713-555-0129', '713-555-0229', '001-01-0029', 'active', 1, '2025-05-25 08:00:00');

-- Patient 30: Betty Campbell, 72F — HTN, mild hypothyroidism
INSERT INTO patient_data (id, pid, fname, lname, mname, DOB, sex, street, city, state, postal_code, phone_home, phone_cell, ss, status, providerID, date)
VALUES (30, 30, 'Betty', 'Campbell', 'W', '1953-07-15', 'Female', '8100 Kirby Dr', 'Houston', 'TX', '77054', '713-555-0130', '713-555-0230', '001-01-0030', 'active', 2, '2025-06-01 08:00:00');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 2: OPENEMR — ENCOUNTERS (form_encounter)
-- encounter IDs 1001–1130+  (encounter column = same as id for simplicity)
-- ─────────────────────────────────────────────────────────────────────────────

-- Patient 1: Margaret Chen — 5 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1001,'2025-01-15 09:00:00','Annual Wellness Visit — Medicare','Sunrise Internal Medicine',1,1,1001,'2025-01-15 09:00:00',1,'AMB'),
(1002,'2025-03-20 10:30:00','CHF Follow-up — worsening dyspnea, +3 lb weight gain','Sunrise Internal Medicine',1,1,1002,'2025-03-20 10:30:00',1,'AMB'),
(1003,'2025-06-05 09:00:00','Diabetes & CKD Management — quarterly labs review','Sunrise Internal Medicine',1,1,1003,'2025-06-05 09:00:00',1,'AMB'),
(1004,'2025-09-10 14:00:00','CHF Exacerbation — ER visit, admitted 2 days','Houston Methodist ER',2,1,1004,'2025-09-10 14:00:00',1,'EMER'),
(1005,'2026-01-22 09:00:00','Annual Wellness Visit — 2026 baseline','Sunrise Internal Medicine',1,1,1005,'2026-01-22 09:00:00',1,'AMB');

-- Patient 2: Robert Williams — 4 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1006,'2025-01-20 11:00:00','COPD Management — spirometry, O2 sat check','Sunrise Internal Medicine',1,2,1006,'2025-01-20 11:00:00',1,'AMB'),
(1007,'2025-04-15 09:30:00','Oncology Follow-up — lung cancer surveillance CT','Houston Cancer Center',3,2,1007,'2025-04-15 09:30:00',1,'AMB'),
(1008,'2025-08-12 10:00:00','Nutritional Status — weight loss, protein-calorie malnutrition eval','Sunrise Internal Medicine',1,2,1008,'2025-08-12 10:00:00',1,'AMB'),
(1009,'2026-01-28 09:00:00','Annual Wellness Visit — 2026','Sunrise Internal Medicine',1,2,1009,'2026-01-28 09:00:00',1,'AMB');

-- Patient 3: James Johnson — 5 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1010,'2025-01-10 08:00:00','Dialysis Access Review — ESRD management','Sunrise Nephrology Clinic',4,3,1010,'2025-01-10 08:00:00',2,'AMB'),
(1011,'2025-02-14 09:00:00','Diabetes — HbA1c 9.8%, insulin adjustment','Sunrise Family Medicine',5,3,1011,'2025-02-14 09:00:00',2,'AMB'),
(1012,'2025-05-20 10:00:00','CHF Follow-up — BNP elevated, Echo ordered','Sunrise Family Medicine',5,3,1012,'2025-05-20 10:00:00',2,'AMB'),
(1013,'2025-08-30 09:00:00','Anemia — Epoetin dose adjustment, iron studies','Sunrise Nephrology Clinic',4,3,1013,'2025-08-30 09:00:00',2,'AMB'),
(1014,'2026-02-05 08:00:00','Annual Wellness Visit — 2026 comprehensive review','Sunrise Family Medicine',5,3,1014,'2026-02-14 08:00:00',2,'AMB');

-- Patient 4: Dorothy Martinez — 5 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1015,'2025-02-01 10:00:00','Geriatric Assessment — cognitive screen, MMSE 18/30','Sunrise Geriatrics',6,4,1015,'2025-02-01 10:00:00',3,'AMB'),
(1016,'2025-04-08 11:00:00','Parkinson''s Management — tremor worsening, Sinemet adjustment','Sunrise Geriatrics',6,4,1016,'2025-04-08 11:00:00',3,'AMB'),
(1017,'2025-07-14 09:30:00','Behavioral Health Follow-up — caregiver distress noted','Sunrise Geriatrics',6,4,1017,'2025-07-14 09:30:00',3,'AMB'),
(1018,'2025-10-22 10:00:00','Fall Prevention Review — PT referral, home safety eval','Sunrise Geriatrics',6,4,1018,'2025-10-22 10:00:00',3,'AMB'),
(1019,'2026-02-12 09:00:00','Annual Wellness Visit — 2026','Sunrise Geriatrics',6,4,1019,'2026-02-12 09:00:00',3,'AMB');

-- Patient 5: William Brown — 4 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1020,'2025-01-25 09:00:00','Hepatology Follow-up — cirrhosis, liver function tests','Sunrise Family Medicine',5,5,1020,'2025-01-25 09:00:00',2,'AMB'),
(1021,'2025-04-20 10:00:00','Diabetes & Coagulopathy — INR 2.1, liver labs','Sunrise Family Medicine',5,5,1021,'2025-04-20 10:00:00',2,'AMB'),
(1022,'2025-09-08 11:00:00','Hepatic Encephalopathy — new episode, lactulose increase','Sunrise Family Medicine',5,5,1022,'2025-09-08 11:00:00',2,'AMB'),
(1023,'2026-01-30 09:00:00','Annual Wellness Visit — 2026','Sunrise Family Medicine',5,5,1023,'2026-01-30 09:00:00',2,'AMB');

-- Patient 6: Helen Davis — 5 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1024,'2025-01-08 09:00:00','Post-Stroke Follow-up — PT/OT assessment, ADL review','Sunrise Internal Medicine',1,6,1024,'2025-01-08 09:00:00',1,'AMB'),
(1025,'2025-03-12 10:00:00','AFib & CHF Management — warfarin therapy, echo results','Sunrise Cardiology',7,6,1025,'2025-03-12 10:00:00',4,'AMB'),
(1026,'2025-06-18 09:00:00','Hemiplegia Rehab — PT progress note, strength assessment','Sunrise Rehab Center',8,6,1026,'2025-06-18 09:00:00',1,'AMB'),
(1027,'2025-11-05 14:00:00','CHF Exacerbation — ER, dyspnea, bilateral LE edema','Houston Methodist ER',2,6,1027,'2025-11-05 14:00:00',1,'EMER'),
(1028,'2026-01-14 09:00:00','Annual Wellness Visit — 2026 comprehensive','Sunrise Internal Medicine',1,6,1028,'2026-01-14 09:00:00',1,'AMB');

-- Patient 7: Gerald Thompson — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1029,'2025-02-05 09:00:00','DM2 Follow-up — neuropathy symptoms, foot exam','Sunrise Family Medicine',5,7,1029,'2025-02-05 09:00:00',2,'AMB'),
(1030,'2025-06-10 10:00:00','AFib Rate Control — metoprolol titration','Sunrise Cardiology',7,7,1030,'2025-06-10 10:00:00',4,'AMB'),
(1031,'2025-12-01 09:00:00','Annual Wellness Visit — CKD3 monitoring','Sunrise Family Medicine',5,7,1031,'2025-12-01 09:00:00',2,'AMB');

-- Patient 8: Patricia Anderson — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1032,'2025-02-10 10:00:00','COPD Follow-up — spirometry, inhaler technique review','Sunrise Internal Medicine',1,8,1032,'2025-02-10 10:00:00',1,'AMB'),
(1033,'2025-07-22 09:00:00','Depression Management — PHQ-9 score 12, SSRI adjustment','Sunrise Internal Medicine',1,8,1033,'2025-07-22 09:00:00',1,'AMB'),
(1034,'2026-01-10 09:00:00','Annual Wellness Visit — 2026 with BMI 38.4','Sunrise Internal Medicine',1,8,1034,'2026-01-10 09:00:00',1,'AMB');

-- Patient 9: Charles Wilson — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1035,'2025-01-30 11:00:00','CHF & PVD Management — carvedilol adjustment','Sunrise Cardiology',7,9,1035,'2025-01-30 11:00:00',4,'AMB'),
(1036,'2025-07-08 10:00:00','Vascular Surgery Consult — bilateral claudication','Sunrise Vascular',9,9,1036,'2025-07-08 10:00:00',4,'AMB'),
(1037,'2025-12-15 09:00:00','Annual Wellness Visit — 2025','Sunrise Cardiology',7,9,1037,'2025-12-15 09:00:00',4,'AMB');

-- Patient 10: Barbara Jackson — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1038,'2025-02-15 09:00:00','DM2 — HbA1c 8.4%, medication review','Sunrise Geriatrics',6,10,1038,'2025-02-15 09:00:00',3,'AMB'),
(1039,'2025-08-05 10:00:00','Behavioral Health — PHQ-9 14, sertraline initiated','Sunrise Geriatrics',6,10,1039,'2025-08-05 10:00:00',3,'AMB'),
(1040,'2026-02-25 09:00:00','Annual Wellness Visit — obesity counseling','Sunrise Geriatrics',6,10,1040,'2026-02-25 09:00:00',3,'AMB');

-- Patient 11: Richard Harris — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1041,'2025-01-22 10:00:00','Rheumatology — RA disease activity, adalimumab continued','Sunrise Cardiology',7,11,1041,'2025-01-22 10:00:00',4,'AMB'),
(1042,'2025-05-14 09:00:00','AFib — apixaban management, echo scheduled','Sunrise Cardiology',7,11,1042,'2025-05-14 09:00:00',4,'AMB'),
(1043,'2025-11-20 10:00:00','CHF Monitoring — NYHA Class II, BNP 220','Sunrise Cardiology',7,11,1043,'2025-11-20 10:00:00',4,'AMB');

-- Patient 12: Nancy Lewis — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1044,'2025-02-20 10:00:00','Memory Clinic — donepezil initiated, caregiver education','Sunrise Geriatrics',6,12,1044,'2025-02-20 10:00:00',3,'AMB'),
(1045,'2025-07-30 09:30:00','CKD3 Follow-up — eGFR 44, dietary counseling','Sunrise Geriatrics',6,12,1045,'2025-07-30 09:30:00',3,'AMB'),
(1046,'2026-01-18 09:00:00','Annual Wellness Visit — 2026','Sunrise Geriatrics',6,12,1046,'2026-01-18 09:00:00',3,'AMB');

-- Patient 13: Joseph Robinson — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1047,'2025-02-28 09:00:00','COPD Maintenance — tiotropium refill, 6MWT','Sunrise Internal Medicine',1,13,1047,'2025-02-28 09:00:00',1,'AMB'),
(1048,'2025-08-20 10:00:00','Vascular Disease — claudication worsening, ABI 0.65','Sunrise Internal Medicine',1,13,1048,'2025-08-20 10:00:00',1,'AMB'),
(1049,'2026-02-02 09:00:00','Annual Wellness Visit — 2026','Sunrise Internal Medicine',1,13,1049,'2026-02-02 09:00:00',1,'AMB');

-- Patient 14: Karen Walker — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1050,'2025-03-05 09:00:00','DM2 w/ complications — foot ulcer grade 1, wound care','Sunrise Family Medicine',5,14,1050,'2025-03-05 09:00:00',2,'AMB'),
(1051,'2025-07-18 10:00:00','CKD3 — eGFR 38, nephrology referral made','Sunrise Family Medicine',5,14,1051,'2025-07-18 10:00:00',2,'AMB'),
(1052,'2026-01-25 09:00:00','Annual Wellness Visit — 2026, obesity BMI 41.2','Sunrise Family Medicine',5,14,1052,'2026-01-25 09:00:00',2,'AMB');

-- Patient 15: Thomas Hall — 3 encounters
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1053,'2025-01-18 10:00:00','Post-Stroke + AFib — warfarin INR 2.3','Sunrise Cardiology',7,15,1053,'2025-01-18 10:00:00',4,'AMB'),
(1054,'2025-06-25 09:00:00','CHF Follow-up — NYHA Class II, furosemide dose stable','Sunrise Cardiology',7,15,1054,'2025-06-25 09:00:00',4,'AMB'),
(1055,'2026-01-20 09:00:00','Annual Wellness Visit — 2026','Sunrise Cardiology',7,15,1055,'2026-01-20 09:00:00',4,'AMB');

-- Patients 16–18: 2 encounters each
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1056,'2025-03-10 09:00:00','DM2 & PVD — HbA1c 8.1%, ankle-brachial index','Sunrise Geriatrics',6,16,1056,'2025-03-10 09:00:00',3,'AMB'),
(1057,'2026-01-28 09:00:00','Annual Wellness Visit — 2026','Sunrise Geriatrics',6,16,1057,'2026-01-28 09:00:00',3,'AMB'),
(1058,'2025-03-15 10:00:00','COPD & DM2 — tiotropium refill, HbA1c 7.6%','Sunrise Family Medicine',5,17,1058,'2025-03-15 10:00:00',2,'AMB'),
(1059,'2026-02-10 09:00:00','Annual Wellness Visit — 2026','Sunrise Family Medicine',5,17,1059,'2026-02-10 09:00:00',2,'AMB'),
(1060,'2025-03-20 10:00:00','RA — methotrexate toxicity labs, DMARDs continued','Sunrise Internal Medicine',1,18,1060,'2025-03-20 10:00:00',1,'AMB'),
(1061,'2026-01-15 09:00:00','Annual Wellness Visit — 2026','Sunrise Internal Medicine',1,18,1061,'2026-01-15 09:00:00',1,'AMB');

-- Patients 19–30: 2 encounters each (low-risk)
INSERT INTO form_encounter (id, date, reason, facility, facility_id, pid, encounter, onset_date, provider_id, class_code) VALUES
(1062,'2025-04-01 09:00:00','Hypertension Follow-up — BP 132/84 on lisinopril','Sunrise Family Medicine',5,19,1062,'2025-04-01 09:00:00',2,'AMB'),
(1063,'2026-01-20 09:00:00','Annual Wellness Visit — 2026','Sunrise Family Medicine',5,19,1063,'2026-01-20 09:00:00',2,'AMB'),
(1064,'2025-04-05 10:00:00','DM2 Lifestyle Counseling — diet + exercise program','Sunrise Geriatrics',6,20,1064,'2025-04-05 10:00:00',3,'AMB'),
(1065,'2026-01-22 09:00:00','Annual Wellness Visit — 2026, HbA1c 6.8%','Sunrise Geriatrics',6,20,1065,'2026-01-22 09:00:00',3,'AMB'),
(1066,'2025-04-10 09:00:00','Hyperlipidemia — statin therapy, fasting lipid panel','Sunrise Internal Medicine',1,21,1066,'2025-04-10 09:00:00',1,'AMB'),
(1067,'2026-02-05 09:00:00','Annual Wellness Visit — 2026','Sunrise Internal Medicine',1,21,1067,'2026-02-05 09:00:00',1,'AMB'),
(1068,'2025-04-15 10:00:00','Anxiety & Osteoarthritis — Rx review, PT referral','Sunrise Family Medicine',5,22,1068,'2025-04-15 10:00:00',2,'AMB'),
(1069,'2026-01-30 09:00:00','Annual Wellness Visit — 2026','Sunrise Family Medicine',5,22,1069,'2026-01-30 09:00:00',2,'AMB'),
(1070,'2025-04-20 09:00:00','HTN + CKD Monitoring — eGFR 58, microalbuminuria','Sunrise Cardiology',7,23,1070,'2025-04-20 09:00:00',4,'AMB'),
(1071,'2026-02-15 09:00:00','Annual Wellness Visit — 2026','Sunrise Cardiology',7,23,1071,'2026-02-15 09:00:00',4,'AMB'),
(1072,'2025-05-01 10:00:00','Obesity Counseling — BMI 36.8, lifestyle program','Sunrise Geriatrics',6,24,1072,'2025-05-01 10:00:00',3,'AMB'),
(1073,'2026-02-20 09:00:00','Annual Wellness Visit — 2026','Sunrise Geriatrics',6,24,1073,'2026-02-20 09:00:00',3,'AMB'),
(1074,'2025-05-05 09:00:00','DM2 Annual Review — HbA1c 6.9%, stable','Sunrise Internal Medicine',1,25,1074,'2025-05-05 09:00:00',1,'AMB'),
(1075,'2026-03-01 09:00:00','Annual Wellness Visit — 2026','Sunrise Internal Medicine',1,25,1075,'2026-03-01 09:00:00',1,'AMB'),
(1076,'2025-05-10 10:00:00','Depression Follow-up — PHQ-9 5, sertraline maintained','Sunrise Family Medicine',5,26,1076,'2025-05-10 10:00:00',2,'AMB'),
(1077,'2026-02-25 09:00:00','Annual Wellness Visit — 2026','Sunrise Family Medicine',5,26,1077,'2026-02-25 09:00:00',2,'AMB'),
(1078,'2025-05-15 09:00:00','Lipid Panel — LDL 142, statin dose adequate','Sunrise Cardiology',7,27,1078,'2025-05-15 09:00:00',4,'AMB'),
(1079,'2026-03-05 09:00:00','Annual Wellness Visit — 2026','Sunrise Cardiology',7,27,1079,'2026-03-05 09:00:00',4,'AMB'),
(1080,'2025-05-20 10:00:00','Osteoporosis — DEXA scan, alendronate initiated','Sunrise Geriatrics',6,28,1080,'2025-05-20 10:00:00',3,'AMB'),
(1081,'2026-01-12 09:00:00','Annual Wellness Visit — 2026','Sunrise Geriatrics',6,28,1081,'2026-01-12 09:00:00',3,'AMB'),
(1082,'2025-05-25 09:00:00','DM2 Follow-up — HbA1c 7.1%, metformin continued','Sunrise Internal Medicine',1,29,1082,'2025-05-25 09:00:00',1,'AMB'),
(1083,'2026-03-10 09:00:00','Annual Wellness Visit — 2026','Sunrise Internal Medicine',1,29,1083,'2026-03-10 09:00:00',1,'AMB'),
(1084,'2025-06-01 10:00:00','Hypothyroidism Follow-up — TSH 4.8, levothyroxine','Sunrise Family Medicine',5,30,1084,'2025-06-01 10:00:00',2,'AMB'),
(1085,'2026-03-15 09:00:00','Annual Wellness Visit — 2026','Sunrise Family Medicine',5,30,1085,'2026-03-15 09:00:00',2,'AMB');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 3: OPENEMR — BILLING (ICD-10 codes per encounter)
-- ─────────────────────────────────────────────────────────────────────────────

-- Patient 1: Margaret Chen
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-01-15','ICD10','I50.22',1,1,1001,'Chronic systolic (congestive) heart failure',1,1,0.00,1),
('2025-01-15','ICD10','N18.4',1,1,1001,'Chronic kidney disease, stage 4',1,1,0.00,1),
('2025-01-15','ICD10','E11.65',1,1,1001,'Type 2 diabetes mellitus with hyperglycemia',1,1,0.00,1),
('2025-01-15','ICD10','I73.9',1,1,1001,'Peripheral vascular disease, unspecified',1,1,0.00,1),
('2025-03-20','ICD10','I50.22',1,1,1002,'Chronic systolic CHF — exacerbation',1,1,0.00,1),
('2025-03-20','ICD10','N18.4',1,1,1002,'CKD Stage 4',1,1,0.00,1),
('2025-06-05','ICD10','E11.65',1,1,1003,'DM2 w/ hyperglycemia — quarterly review',1,1,0.00,1),
('2025-06-05','ICD10','N18.4',1,1,1003,'CKD Stage 4',1,1,0.00,1),
('2025-09-10','ICD10','I50.22',1,1,1004,'Acute-on-chronic CHF — ER admission',1,1,0.00,1),
('2025-09-10','ICD10','I73.9',1,1,1004,'PVD — bilateral LE edema',1,1,0.00,1),
('2026-01-22','ICD10','I50.22',1,1,1005,'CHF annual recapture',1,1,0.00,1),
('2026-01-22','ICD10','N18.4',1,1,1005,'CKD4 annual recapture',1,1,0.00,1),
('2026-01-22','ICD10','E11.65',1,1,1005,'DM2 w/ hyperglycemia annual recapture',1,1,0.00,1),
('2026-01-22','ICD10','I73.9',1,1,1005,'PVD annual recapture',1,1,0.00,1);

-- Patient 2: Robert Williams
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-01-20','ICD10','J44.1',2,1,1006,'Chronic obstructive pulmonary disease with exacerbation',1,1,0.00,1),
('2025-04-15','ICD10','C34.90',2,1,1007,'Malignant neoplasm of bronchus/lung, unspecified',1,1,0.00,1),
('2025-04-15','ICD10','J44.1',2,1,1007,'COPD — oncology visit',1,1,0.00,1),
('2025-08-12','ICD10','E44.0',2,1,1008,'Moderate protein-calorie malnutrition',1,1,0.00,1),
('2025-08-12','ICD10','C34.90',2,1,1008,'Lung cancer — malnutrition secondary',1,1,0.00,1),
('2026-01-28','ICD10','J44.1',2,1,1009,'COPD annual recapture',1,1,0.00,1),
('2026-01-28','ICD10','C34.90',2,1,1009,'Lung cancer annual recapture',1,1,0.00,1),
('2026-01-28','ICD10','E44.0',2,1,1009,'Malnutrition annual recapture',1,1,0.00,1);

-- Patient 3: James Johnson
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-01-10','ICD10','N18.6',3,2,1010,'End stage renal disease on dialysis',1,1,0.00,1),
('2025-02-14','ICD10','E11.22',3,2,1011,'Type 2 DM with diabetic chronic kidney disease',1,1,0.00,1),
('2025-02-14','ICD10','N18.6',3,2,1011,'ESRD — dialysis',1,1,0.00,1),
('2025-05-20','ICD10','I50.32',3,2,1012,'Chronic diastolic CHF',1,1,0.00,1),
('2025-05-20','ICD10','N18.6',3,2,1012,'ESRD — dialysis',1,1,0.00,1),
('2025-08-30','ICD10','D63.1',3,2,1013,'Anemia in chronic kidney disease',1,1,0.00,1),
('2025-08-30','ICD10','N18.6',3,2,1013,'ESRD — anemia management',1,1,0.00,1),
('2026-02-14','ICD10','N18.6',3,2,1014,'ESRD annual recapture',1,1,0.00,1),
('2026-02-14','ICD10','E11.22',3,2,1014,'DM2 w/ CKD annual recapture',1,1,0.00,1),
('2026-02-14','ICD10','I50.32',3,2,1014,'CHF annual recapture',1,1,0.00,1),
('2026-02-14','ICD10','D63.1',3,2,1014,'Anemia of CKD annual recapture',1,1,0.00,1);

-- Patient 4: Dorothy Martinez
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-02-01','ICD10','F03.90',4,3,1015,'Unspecified dementia without behavioral disturbance',1,1,0.00,1),
('2025-04-08','ICD10','G20.A1',4,3,1016,'Parkinson disease without dyskinesia, without mention of fluctuations',1,1,0.00,1),
('2025-04-08','ICD10','F03.90',4,3,1016,'Dementia — Parkinson co-management',1,1,0.00,1),
('2025-07-14','ICD10','F03.90',4,3,1017,'Dementia — behavioral issues noted',1,1,0.00,1),
('2025-07-14','ICD10','G20.A1',4,3,1017,'Parkinson — ongoing',1,1,0.00,1),
-- NOTE: Depression (F32.1) NOT coded here — this is the gap we demonstrate
('2025-10-22','ICD10','F03.90',4,3,1018,'Dementia — fall prevention',1,1,0.00,1),
('2025-10-22','ICD10','G20.A1',4,3,1018,'Parkinson — fall risk',1,1,0.00,1),
('2026-02-12','ICD10','F03.90',4,3,1019,'Dementia annual recapture',1,1,0.00,1),
('2026-02-12','ICD10','G20.A1',4,3,1019,'Parkinson annual recapture',1,1,0.00,1);
-- F32.1 intentionally omitted for 2026 — suspect condition will fire

-- Patient 5: William Brown
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-01-25','ICD10','K74.60',5,2,1020,'Unspecified cirrhosis of liver',1,1,0.00,1),
('2025-01-25','ICD10','E11.65',5,2,1020,'DM2 w/ hyperglycemia',1,1,0.00,1),
('2025-04-20','ICD10','K74.60',5,2,1021,'Cirrhosis — coagulopathy workup',1,1,0.00,1),
('2025-04-20','ICD10','D68.9',5,2,1021,'Coagulation defect — liver disease',1,1,0.00,1),
('2025-09-08','ICD10','K74.60',5,2,1022,'Cirrhosis — hepatic encephalopathy',1,1,0.00,1),
('2025-09-08','ICD10','D68.9',5,2,1022,'Coagulopathy — INR elevated',1,1,0.00,1),
('2026-01-30','ICD10','K74.60',5,2,1023,'Cirrhosis annual recapture',1,1,0.00,1),
('2026-01-30','ICD10','E11.65',5,2,1023,'DM2 annual recapture',1,1,0.00,1),
('2026-01-30','ICD10','D68.9',5,2,1023,'Coagulopathy annual recapture',1,1,0.00,1);

-- Patient 6: Helen Davis
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-01-08','ICD10','I63.9',6,1,1024,'Cerebral infarction, unspecified — remote history',1,1,0.00,1),
('2025-01-08','ICD10','G81.90',6,1,1024,'Hemiplegia, unspecified affecting unspecified side',1,1,0.00,1),
('2025-03-12','ICD10','I48.91',6,4,1025,'Unspecified atrial fibrillation',1,1,0.00,1),
('2025-03-12','ICD10','I50.20',6,4,1025,'Unspecified systolic CHF',1,1,0.00,1),
('2025-06-18','ICD10','G81.90',6,1,1026,'Hemiplegia rehab — PT',1,1,0.00,1),
('2025-11-05','ICD10','I50.20',6,1,1027,'CHF ER exacerbation',1,1,0.00,1),
('2025-11-05','ICD10','I48.91',6,1,1027,'AFib — rate poorly controlled at ER',1,1,0.00,1),
('2026-01-14','ICD10','I63.9',6,1,1028,'Stroke annual recapture',1,1,0.00,1),
('2026-01-14','ICD10','G81.90',6,1,1028,'Hemiplegia annual recapture',1,1,0.00,1),
('2026-01-14','ICD10','I48.91',6,1,1028,'AFib annual recapture',1,1,0.00,1),
('2026-01-14','ICD10','I50.20',6,1,1028,'CHF annual recapture',1,1,0.00,1);

-- Medium-risk patients billing
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
-- Patient 7
('2025-02-05','ICD10','E11.40',7,2,1029,'DM2 with diabetic neuropathy, unspecified',1,1,0.00,1),
('2025-06-10','ICD10','I48.91',7,4,1030,'Atrial fibrillation',1,1,0.00,1),
('2025-12-01','ICD10','N18.3',7,2,1031,'CKD Stage 3, unspecified',1,1,0.00,1),
('2025-12-01','ICD10','E11.40',7,2,1031,'DM2 neuropathy annual',1,1,0.00,1),
-- Patient 8
('2025-02-10','ICD10','J44.1',8,1,1032,'COPD with exacerbation',1,1,0.00,1),
('2025-07-22','ICD10','F32.1',8,1,1033,'Major depressive disorder, single episode, moderate',1,1,0.00,1),
('2026-01-10','ICD10','J44.1',8,1,1034,'COPD annual recapture',1,1,0.00,1),
('2026-01-10','ICD10','E66.09',8,1,1034,'Other obesity — BMI 38.4',1,1,0.00,1),
-- Patient 9
('2025-01-30','ICD10','I50.9',9,4,1035,'Heart failure unspecified',1,1,0.00,1),
('2025-01-30','ICD10','I73.9',9,4,1035,'Peripheral vascular disease',1,1,0.00,1),
('2025-07-08','ICD10','I73.9',9,4,1036,'PVD — vascular surgery consult',1,1,0.00,1),
('2025-12-15','ICD10','I50.9',9,4,1037,'CHF annual',1,1,0.00,1),
('2025-12-15','ICD10','N18.3',9,4,1037,'CKD3 annual',1,1,0.00,1),
-- Patient 10
('2025-02-15','ICD10','E11.65',10,3,1038,'DM2 w/ hyperglycemia',1,1,0.00,1),
('2025-08-05','ICD10','F32.1',10,3,1039,'Major depression — moderate',1,1,0.00,1),
('2026-02-25','ICD10','E11.65',10,3,1040,'DM2 annual recapture',1,1,0.00,1),
('2026-02-25','ICD10','E66.09',10,3,1040,'Obesity annual — BMI 37.1',1,1,0.00,1),
-- Patient 11
('2025-01-22','ICD10','M05.79',11,4,1041,'Rheumatoid arthritis with rheumatoid factor, multiple sites',1,1,0.00,1),
('2025-05-14','ICD10','I48.91',11,4,1042,'Atrial fibrillation',1,1,0.00,1),
('2025-11-20','ICD10','I50.9',11,4,1043,'CHF',1,1,0.00,1),
('2025-11-20','ICD10','M05.79',11,4,1043,'RA ongoing',1,1,0.00,1),
-- Patient 12 — donepezil on board but dementia not coded in 2026 visits yet
('2025-02-20','ICD10','F03.90',12,3,1044,'Dementia — mild cognitive decline',1,1,0.00,1),
('2025-07-30','ICD10','N18.3',12,3,1045,'CKD Stage 3',1,1,0.00,1),
-- NOTE: 2026 AWV (1046) no dementia code yet — gap for suspect
-- Patient 13
('2025-02-28','ICD10','J44.1',13,1,1047,'COPD — stable',1,1,0.00,1),
('2025-08-20','ICD10','I73.9',13,1,1048,'PVD — claudication',1,1,0.00,1),
('2026-02-02','ICD10','J44.1',13,1,1049,'COPD annual recapture',1,1,0.00,1),
('2026-02-02','ICD10','I73.9',13,1,1049,'PVD annual recapture',1,1,0.00,1),
-- Patient 14
('2025-03-05','ICD10','E11.621',14,2,1050,'DM2 with foot ulcer',1,1,0.00,1),
('2025-07-18','ICD10','N18.3',14,2,1051,'CKD Stage 3',1,1,0.00,1),
('2026-01-25','ICD10','E11.65',14,2,1052,'DM2 w/ hyperglycemia annual',1,1,0.00,1),
('2026-01-25','ICD10','E66.01',14,2,1052,'Morbid obesity — BMI 41.2',1,1,0.00,1),
-- Patient 15
('2025-01-18','ICD10','I63.9',15,4,1053,'Stroke history',1,1,0.00,1),
('2025-01-18','ICD10','I48.91',15,4,1053,'AFib — anticoagulated',1,1,0.00,1),
('2025-06-25','ICD10','I50.9',15,4,1054,'CHF — stable NYHA II',1,1,0.00,1),
('2026-01-20','ICD10','I48.91',15,4,1055,'AFib annual recapture',1,1,0.00,1),
('2026-01-20','ICD10','I50.9',15,4,1055,'CHF annual recapture',1,1,0.00,1),
-- Patient 16
('2025-03-10','ICD10','E11.51',16,3,1056,'DM2 with diabetic peripheral angiopathy',1,1,0.00,1),
('2025-03-10','ICD10','I73.9',16,3,1056,'Peripheral vascular disease',1,1,0.00,1),
('2026-01-28','ICD10','E11.51',16,3,1057,'DM2 PVD annual',1,1,0.00,1),
-- Patient 17
('2025-03-15','ICD10','J44.1',17,2,1058,'COPD',1,1,0.00,1),
('2025-03-15','ICD10','E11.9',17,2,1058,'DM2 without complications',1,1,0.00,1),
('2026-02-10','ICD10','J44.1',17,2,1059,'COPD annual',1,1,0.00,1),
('2026-02-10','ICD10','E11.9',17,2,1059,'DM2 annual',1,1,0.00,1),
('2026-02-10','ICD10','E66.09',17,2,1059,'Obesity — BMI 36.4',1,1,0.00,1),
-- Patient 18
('2025-03-20','ICD10','M05.79',18,1,1060,'Rheumatoid arthritis with RF',1,1,0.00,1),
('2026-01-15','ICD10','M05.79',18,1,1061,'RA annual',1,1,0.00,1),
('2026-01-15','ICD10','N18.3',18,1,1061,'CKD3 annual',1,1,0.00,1);

-- Low-risk patients billing (19–30)
INSERT INTO billing (date, code_type, code, pid, provider_id, encounter, code_text, billed, activity, fee, authorized) VALUES
('2025-04-01','ICD10','I10',19,2,1062,'Essential hypertension',1,1,0.00,1),
('2025-04-05','ICD10','E11.9',20,3,1064,'DM2 without complications',1,1,0.00,1),
('2025-04-10','ICD10','E78.5',21,1,1066,'Hyperlipidemia',1,1,0.00,1),
('2025-04-15','ICD10','F41.1',22,2,1068,'Generalized anxiety disorder',1,1,0.00,1),
('2025-04-15','ICD10','M19.90',22,2,1068,'Osteoarthritis',1,1,0.00,1),
('2025-04-20','ICD10','I10',23,4,1070,'Hypertension',1,1,0.00,1),
('2025-04-20','ICD10','N18.3',23,4,1070,'CKD3 — borderline eGFR 58',1,1,0.00,1),
('2025-05-01','ICD10','E66.9',24,3,1072,'Obesity — BMI 36.8',1,1,0.00,1),
('2025-05-01','ICD10','R73.09','24',3,1072,'Prediabetes',1,1,0.00,1),
('2025-05-05','ICD10','E11.9',25,1,1074,'DM2 without complications',1,1,0.00,1),
('2025-05-05','ICD10','I10',25,1,1074,'Hypertension',1,1,0.00,1),
('2025-05-10','ICD10','F32.1',26,2,1076,'Major depression — stable',1,1,0.00,1),
('2025-05-10','ICD10','I10',26,2,1076,'Hypertension',1,1,0.00,1),
('2025-05-15','ICD10','E78.5',27,4,1078,'Hyperlipidemia',1,1,0.00,1),
('2025-05-20','ICD10','M81.0',28,3,1080,'Age-related osteoporosis without fracture',1,1,0.00,1),
('2025-05-20','ICD10','I10',28,3,1080,'Hypertension',1,1,0.00,1),
('2025-05-25','ICD10','E11.9',29,1,1082,'DM2 without complications',1,1,0.00,1),
('2025-06-01','ICD10','E03.9',30,2,1084,'Hypothyroidism, unspecified',1,1,0.00,1),
('2025-06-01','ICD10','I10',30,2,1084,'Hypertension',1,1,0.00,1);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 4: OPENEMR — PROBLEM LISTS (lists table)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO lists (date, type, title, begdate, enddate, diagnosis, activity, pid, comments) VALUES
-- Patient 1
('2024-01-01 00:00:00','medical_problem','Chronic Systolic Heart Failure','2024-01-01 00:00:00',NULL,'ICD10:I50.22',1,1,'EF 28% on last echo'),
('2024-01-01 00:00:00','medical_problem','Chronic Kidney Disease Stage 4','2024-01-01 00:00:00',NULL,'ICD10:N18.4',1,1,'eGFR 22 mL/min — Nephrology following'),
('2024-01-01 00:00:00','medical_problem','Type 2 Diabetes w/ Hyperglycemia','2024-01-01 00:00:00',NULL,'ICD10:E11.65',1,1,'HbA1c 9.1% — insulin dependent'),
('2024-01-01 00:00:00','medical_problem','Peripheral Vascular Disease','2024-01-01 00:00:00',NULL,'ICD10:I73.9',1,1,'ABI 0.62 bilateral'),
-- Patient 2
('2023-06-01 00:00:00','medical_problem','COPD with Exacerbation','2023-06-01 00:00:00',NULL,'ICD10:J44.1',1,2,'FEV1/FVC 0.58, on tiotropium'),
('2023-08-15 00:00:00','medical_problem','Non-small cell lung cancer','2023-08-15 00:00:00',NULL,'ICD10:C34.90',1,2,'Stage IIIA — completing radiation'),
('2024-08-01 00:00:00','medical_problem','Protein-Calorie Malnutrition','2024-08-01 00:00:00',NULL,'ICD10:E44.0',1,2,'BMI 17.2, albumin 2.8'),
-- Patient 3
('2022-03-01 00:00:00','medical_problem','End Stage Renal Disease on Dialysis','2022-03-01 00:00:00',NULL,'ICD10:N18.6',1,3,'HD 3x/week at Fresenius'),
('2022-03-01 00:00:00','medical_problem','Type 2 DM with CKD','2022-03-01 00:00:00',NULL,'ICD10:E11.22',1,3,'HbA1c 9.8%'),
('2024-05-01 00:00:00','medical_problem','Chronic Diastolic Heart Failure','2024-05-01 00:00:00',NULL,'ICD10:I50.32',1,3,'EF 50%, NYHA II'),
('2023-09-01 00:00:00','medical_problem','Anemia of CKD','2023-09-01 00:00:00',NULL,'ICD10:D63.1',1,3,'Hgb 9.2, on epoetin alfa'),
-- Patient 4
('2023-04-01 00:00:00','medical_problem','Unspecified Dementia','2023-04-01 00:00:00',NULL,'ICD10:F03.90',1,4,'MMSE 18/30, moderate cognitive decline'),
('2022-11-01 00:00:00','medical_problem','Parkinson Disease','2022-11-01 00:00:00',NULL,'ICD10:G20.A1',1,4,'On Sinemet 25/100 TID'),
('2024-01-01 00:00:00','medical_problem','Major Depressive Disorder','2024-01-01 00:00:00',NULL,'ICD10:F32.1',1,4,'PHQ-9 16 at last screen — CODING GAP in 2025/2026'),
-- Patient 5
('2021-07-01 00:00:00','medical_problem','Cirrhosis of Liver','2021-07-01 00:00:00',NULL,'ICD10:K74.60',1,5,'Child-Pugh Class B, varices on EGD'),
('2020-01-01 00:00:00','medical_problem','Type 2 Diabetes','2020-01-01 00:00:00',NULL,'ICD10:E11.65',1,5,'HbA1c 8.7%'),
('2024-04-01 00:00:00','medical_problem','Coagulation Defect','2024-04-01 00:00:00',NULL,'ICD10:D68.9',1,5,'INR 2.1 off anticoagulation — hepatic'),
-- Patient 6
('2023-09-01 00:00:00','medical_problem','Cerebral Infarction — remote','2023-09-01 00:00:00',NULL,'ICD10:I63.9',1,6,'Left MCA stroke 2023, residual right hemiplegia'),
('2023-09-01 00:00:00','medical_problem','Hemiplegia — right','2023-09-01 00:00:00',NULL,'ICD10:G81.90',1,6,'Post-stroke residual deficits'),
('2024-01-01 00:00:00','medical_problem','Atrial Fibrillation','2024-01-01 00:00:00',NULL,'ICD10:I48.91',1,6,'On warfarin — INR target 2-3'),
('2024-01-01 00:00:00','medical_problem','Systolic Heart Failure','2024-01-01 00:00:00',NULL,'ICD10:I50.20',1,6,'EF 35%, on carvedilol + furosemide'),
-- Patient 7
('2023-01-01 00:00:00','medical_problem','DM2 with Neuropathy','2023-01-01 00:00:00',NULL,'ICD10:E11.40',1,7,'Bilateral peripheral neuropathy'),
('2024-06-01 00:00:00','medical_problem','Atrial Fibrillation','2024-06-01 00:00:00',NULL,'ICD10:I48.91',1,7,'Rate controlled on metoprolol'),
('2024-01-01 00:00:00','medical_problem','CKD Stage 3','2024-01-01 00:00:00',NULL,'ICD10:N18.3',1,7,'eGFR 44'),
-- Patient 8
('2022-01-01 00:00:00','medical_problem','COPD','2022-01-01 00:00:00',NULL,'ICD10:J44.1',1,8,'On tiotropium, FEV1 62%'),
('2024-07-01 00:00:00','medical_problem','Major Depression','2024-07-01 00:00:00',NULL,'ICD10:F32.1',1,8,'PHQ-9 12 — on sertraline 100mg'),
('2025-01-10 00:00:00','medical_problem','Morbid Obesity','2025-01-10 00:00:00',NULL,'ICD10:E66.09',1,8,'BMI 38.4'),
-- Patient 9
('2023-01-01 00:00:00','medical_problem','Congestive Heart Failure','2023-01-01 00:00:00',NULL,'ICD10:I50.9',1,9,'EF 40%'),
('2023-07-01 00:00:00','medical_problem','Peripheral Vascular Disease','2023-07-01 00:00:00',NULL,'ICD10:I73.9',1,9,'ABI 0.65, claudication 100m'),
('2024-01-01 00:00:00','medical_problem','CKD Stage 3','2024-01-01 00:00:00',NULL,'ICD10:N18.3',1,9,'eGFR 52'),
-- Patient 10
('2023-02-01 00:00:00','medical_problem','DM2 w/ Hyperglycemia','2023-02-01 00:00:00',NULL,'ICD10:E11.65',1,10,'HbA1c 8.4%'),
('2024-08-01 00:00:00','medical_problem','Major Depression','2024-08-01 00:00:00',NULL,'ICD10:F32.1',1,10,'PHQ-9 14'),
('2024-01-01 00:00:00','medical_problem','Obesity','2024-01-01 00:00:00',NULL,'ICD10:E66.09',1,10,'BMI 37.1'),
-- Patients 11–18
('2022-01-01 00:00:00','medical_problem','Rheumatoid Arthritis','2022-01-01 00:00:00',NULL,'ICD10:M05.79',1,11,'On adalimumab'),
('2024-05-01 00:00:00','medical_problem','Atrial Fibrillation','2024-05-01 00:00:00',NULL,'ICD10:I48.91',1,11,'On apixaban'),
('2024-11-01 00:00:00','medical_problem','Congestive Heart Failure','2024-11-01 00:00:00',NULL,'ICD10:I50.9',1,11,'BNP 220'),
('2023-02-01 00:00:00','medical_problem','Mild Dementia','2023-02-01 00:00:00',NULL,'ICD10:F03.90',1,12,'Donepezil initiated 2025'),
('2024-07-01 00:00:00','medical_problem','CKD Stage 3','2024-07-01 00:00:00',NULL,'ICD10:N18.3',1,12,'eGFR 44'),
('2022-02-01 00:00:00','medical_problem','COPD','2022-02-01 00:00:00',NULL,'ICD10:J44.1',1,13,'Stable on tiotropium'),
('2023-08-01 00:00:00','medical_problem','Peripheral Vascular Disease','2023-08-01 00:00:00',NULL,'ICD10:I73.9',1,13,'Claudication'),
('2023-03-01 00:00:00','medical_problem','DM2 w/ Foot Ulcer','2023-03-01 00:00:00',NULL,'ICD10:E11.621',1,14,'Grade 1 plantar ulcer'),
('2024-07-01 00:00:00','medical_problem','CKD Stage 3','2024-07-01 00:00:00',NULL,'ICD10:N18.3',1,14,'eGFR 38 — borderline stage 4'),
('2024-01-01 00:00:00','medical_problem','Morbid Obesity','2024-01-01 00:00:00',NULL,'ICD10:E66.01',1,14,'BMI 41.2'),
('2023-01-01 00:00:00','medical_problem','Stroke — remote history','2023-01-01 00:00:00',NULL,'ICD10:I63.9',1,15,'On aspirin'),
('2024-01-01 00:00:00','medical_problem','Atrial Fibrillation','2024-01-01 00:00:00',NULL,'ICD10:I48.91',1,15,'Rate controlled'),
('2024-06-01 00:00:00','medical_problem','CHF — NYHA II','2024-06-01 00:00:00',NULL,'ICD10:I50.9',1,15,'Stable'),
('2023-03-01 00:00:00','medical_problem','DM2 with Angiopathy','2023-03-01 00:00:00',NULL,'ICD10:E11.51',1,16,'On insulin'),
('2023-03-01 00:00:00','medical_problem','Peripheral Vascular Disease','2023-03-01 00:00:00',NULL,'ICD10:I73.9',1,16,'ABI 0.72'),
('2022-03-01 00:00:00','medical_problem','COPD','2022-03-01 00:00:00',NULL,'ICD10:J44.1',1,17,'On tiotropium and budesonide/formoterol'),
('2023-03-01 00:00:00','medical_problem','DM2','2023-03-01 00:00:00',NULL,'ICD10:E11.9',1,17,'HbA1c 7.6%'),
('2022-03-01 00:00:00','medical_problem','Rheumatoid Arthritis','2022-03-01 00:00:00',NULL,'ICD10:M05.79',1,18,'On methotrexate'),
('2024-01-01 00:00:00','medical_problem','CKD Stage 3','2024-01-01 00:00:00',NULL,'ICD10:N18.3',1,18,'eGFR 51'),
-- Low-risk patients
('2024-01-01 00:00:00','medical_problem','Hypertension','2024-01-01 00:00:00',NULL,'ICD10:I10',1,19,'Controlled on lisinopril'),
('2024-04-01 00:00:00','medical_problem','DM2 without complications','2024-04-01 00:00:00',NULL,'ICD10:E11.9',1,20,'Diet controlled'),
('2024-01-01 00:00:00','medical_problem','Hyperlipidemia','2024-01-01 00:00:00',NULL,'ICD10:E78.5',1,21,'On atorvastatin'),
('2024-01-01 00:00:00','medical_problem','Generalized Anxiety','2024-01-01 00:00:00',NULL,'ICD10:F41.1',1,22,'On buspirone'),
('2024-04-01 00:00:00','medical_problem','Hypertension + borderline CKD','2024-04-01 00:00:00',NULL,'ICD10:I10',1,23,'eGFR 58 — monitoring'),
('2024-01-01 00:00:00','medical_problem','Obesity','2024-01-01 00:00:00',NULL,'ICD10:E66.9',1,24,'BMI 36.8'),
('2024-05-01 00:00:00','medical_problem','DM2 without complications','2024-05-01 00:00:00',NULL,'ICD10:E11.9',1,25,'HbA1c 6.9%, well-controlled'),
('2024-01-01 00:00:00','medical_problem','Major Depression — stable','2024-01-01 00:00:00',NULL,'ICD10:F32.1',1,26,'PHQ-9 5 on sertraline'),
('2024-01-01 00:00:00','medical_problem','Hyperlipidemia','2024-01-01 00:00:00',NULL,'ICD10:E78.5',1,27,'On rosuvastatin'),
('2024-01-01 00:00:00','medical_problem','Osteoporosis','2024-01-01 00:00:00',NULL,'ICD10:M81.0',1,28,'DEXA T-score -2.6'),
('2024-01-01 00:00:00','medical_problem','DM2 without complications','2024-01-01 00:00:00',NULL,'ICD10:E11.9',1,29,'HbA1c 7.1%'),
('2024-06-01 00:00:00','medical_problem','Hypothyroidism','2024-06-01 00:00:00',NULL,'ICD10:E03.9',1,30,'TSH 4.8 on levothyroxine');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 5: OPENEMR — PRESCRIPTIONS
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO prescriptions (patient_id, date_added, provider_id, start_date, drug, dosage, route, active, note) VALUES
-- Patient 1: Margaret Chen
(1,'2025-01-15 00:00:00',1,'2025-01-15','Furosemide','80mg','Oral',1,'BID — CHF volume management'),
(1,'2025-01-15 00:00:00',1,'2025-01-15','Carvedilol','12.5mg','Oral',1,'BID — CHF beta blockade'),
(1,'2025-01-15 00:00:00',1,'2025-01-15','Insulin Glargine','28 units','Subcutaneous',1,'Bedtime — basal insulin for DM2'),
(1,'2025-01-15 00:00:00',1,'2025-01-15','Lisinopril','10mg','Oral',1,'Daily — CKD/CHF/HTN'),
(1,'2025-01-15 00:00:00',1,'2025-01-15','Aspirin','81mg','Oral',1,'Daily — PVD/cardiovascular'),
-- Patient 2: Robert Williams
(2,'2025-01-20 00:00:00',1,'2025-01-20','Tiotropium','18mcg','Inhaled',1,'Daily — COPD maintenance'),
(2,'2025-01-20 00:00:00',1,'2025-01-20','Budesonide/Formoterol','160/4.5mcg','Inhaled',1,'BID — COPD ICS/LABA'),
(2,'2025-08-12 00:00:00',1,'2025-08-12','Ensure Plus','1 can','Oral',1,'TID — supplemental nutrition, malnutrition'),
(2,'2025-04-15 00:00:00',1,'2025-04-15','Prednisone','10mg','Oral',1,'Taper — COPD exacerbation adjunct'),
-- Patient 3: James Johnson
(3,'2025-01-10 00:00:00',2,'2025-01-10','Epoetin Alfa','10000 units','Subcutaneous',1,'3x/week — CKD anemia'),
(3,'2025-01-10 00:00:00',2,'2025-01-10','Sevelamer','800mg','Oral',1,'TID with meals — phosphate binder ESRD'),
(3,'2025-02-14 00:00:00',2,'2025-02-14','Insulin Glargine','40 units','Subcutaneous',1,'Bedtime — ESRD/DM2'),
(3,'2025-05-20 00:00:00',2,'2025-05-20','Furosemide','40mg','Oral',1,'Daily — CHF fluid management'),
(3,'2025-05-20 00:00:00',2,'2025-05-20','Carvedilol','6.25mg','Oral',1,'BID — CHF beta blockade'),
-- Patient 4: Dorothy Martinez
(4,'2025-02-01 00:00:00',3,'2025-02-01','Levodopa/Carbidopa','25/100mg','Oral',1,'TID — Parkinson disease'),
(4,'2025-02-01 00:00:00',3,'2025-02-01','Donepezil','10mg','Oral',1,'Daily at bedtime — dementia'),
(4,'2025-07-14 00:00:00',3,'2025-07-14','Sertraline','50mg','Oral',1,'Daily — depression (noted but not coded in encounter)'),
(4,'2025-02-01 00:00:00',3,'2025-02-01','Memantine','10mg','Oral',1,'BID — moderate dementia adjunct'),
-- Patient 5: William Brown
(5,'2025-01-25 00:00:00',2,'2025-01-25','Lactulose','30mL','Oral',1,'TID — hepatic encephalopathy prevention'),
(5,'2025-01-25 00:00:00',2,'2025-01-25','Spironolactone','50mg','Oral',1,'Daily — cirrhosis ascites'),
(5,'2025-01-25 00:00:00',2,'2025-01-25','Metformin','500mg','Oral',1,'BID — DM2 (low dose per eGFR)'),
(5,'2025-04-20 00:00:00',2,'2025-04-20','Vitamin K','5mg','Oral',1,'Weekly — coagulopathy supplementation'),
-- Patient 6: Helen Davis
(6,'2025-01-08 00:00:00',1,'2025-01-08','Warfarin','5mg','Oral',1,'Daily — AFib anticoagulation, INR 2-3'),
(6,'2025-01-08 00:00:00',1,'2025-01-08','Furosemide','40mg','Oral',1,'Daily — CHF'),
(6,'2025-01-08 00:00:00',1,'2025-01-08','Carvedilol','6.25mg','Oral',1,'BID — CHF/AFib rate control'),
(6,'2025-01-08 00:00:00',1,'2025-01-08','Aspirin','81mg','Oral',1,'Daily — cerebrovascular protection'),
-- Medium risk
(7,'2025-02-05 00:00:00',2,'2025-02-05','Metoprolol Succinate','50mg','Oral',1,'Daily — AFib rate control'),
(7,'2025-02-05 00:00:00',2,'2025-02-05','Gabapentin','300mg','Oral',1,'TID — diabetic neuropathy'),
(7,'2025-02-05 00:00:00',2,'2025-02-05','Metformin','1000mg','Oral',1,'BID — DM2'),
(8,'2025-02-10 00:00:00',1,'2025-02-10','Tiotropium','18mcg','Inhaled',1,'Daily — COPD'),
(8,'2025-07-22 00:00:00',1,'2025-07-22','Sertraline','100mg','Oral',1,'Daily — depression'),
(9,'2025-01-30 00:00:00',4,'2025-01-30','Carvedilol','25mg','Oral',1,'BID — CHF/HTN'),
(9,'2025-01-30 00:00:00',4,'2025-01-30','Furosemide','40mg','Oral',1,'Daily — CHF'),
(10,'2025-02-15 00:00:00',3,'2025-02-15','Insulin Lispro','10 units','Subcutaneous',1,'With meals — DM2'),
(10,'2025-08-05 00:00:00',3,'2025-08-05','Sertraline','50mg','Oral',1,'Daily — depression'),
(11,'2025-01-22 00:00:00',4,'2025-01-22','Adalimumab','40mg','Subcutaneous',1,'Q2 weeks — RA biologic'),
(11,'2025-05-14 00:00:00',4,'2025-05-14','Apixaban','5mg','Oral',1,'BID — AFib anticoagulation'),
(12,'2025-02-20 00:00:00',3,'2025-02-20','Donepezil','5mg','Oral',1,'Daily — mild dementia'),
(13,'2025-02-28 00:00:00',1,'2025-02-28','Tiotropium','18mcg','Inhaled',1,'Daily — COPD'),
(14,'2025-03-05 00:00:00',2,'2025-03-05','Insulin Glargine','20 units','Subcutaneous',1,'Daily — DM2'),
(14,'2025-03-05 00:00:00',2,'2025-03-05','Sitagliptin','100mg','Oral',1,'Daily — DM2 adjunct'),
(15,'2025-01-18 00:00:00',4,'2025-01-18','Warfarin','4mg','Oral',1,'Daily — AFib/stroke prevention'),
(15,'2025-06-25 00:00:00',4,'2025-06-25','Furosemide','20mg','Oral',1,'Daily — mild CHF'),
(16,'2025-03-10 00:00:00',3,'2025-03-10','Insulin Glargine','18 units','Subcutaneous',1,'Bedtime — DM2'),
(17,'2025-03-15 00:00:00',2,'2025-03-15','Tiotropium','18mcg','Inhaled',1,'Daily — COPD'),
(17,'2025-03-15 00:00:00',2,'2025-03-15','Metformin','1000mg','Oral',1,'BID — DM2'),
(18,'2025-03-20 00:00:00',1,'2025-03-20','Methotrexate','15mg','Oral',1,'Weekly — RA DMARD'),
(18,'2025-03-20 00:00:00',1,'2025-03-20','Adalimumab','40mg','Subcutaneous',1,'Q2 weeks — RA biologic'),
-- Low risk
(19,'2025-04-01 00:00:00',2,'2025-04-01','Lisinopril','10mg','Oral',1,'Daily — HTN'),
(20,'2025-04-05 00:00:00',3,'2025-04-05','Metformin','500mg','Oral',1,'Daily — mild DM2'),
(21,'2025-04-10 00:00:00',1,'2025-04-10','Atorvastatin','40mg','Oral',1,'Daily — hyperlipidemia'),
(22,'2025-04-15 00:00:00',2,'2025-04-15','Buspirone','10mg','Oral',1,'BID — anxiety'),
(23,'2025-04-20 00:00:00',4,'2025-04-20','Amlodipine','5mg','Oral',1,'Daily — HTN'),
(23,'2025-04-20 00:00:00',4,'2025-04-20','Lisinopril','5mg','Oral',1,'Daily — HTN/CKD protection'),
(25,'2025-05-05 00:00:00',1,'2025-05-05','Metformin','1000mg','Oral',1,'BID — DM2'),
(26,'2025-05-10 00:00:00',2,'2025-05-10','Sertraline','50mg','Oral',1,'Daily — depression'),
(29,'2025-05-25 00:00:00',1,'2025-05-25','Metformin','1000mg','Oral',1,'BID — DM2'),
(30,'2025-06-01 00:00:00',2,'2025-06-01','Levothyroxine','75mcg','Oral',1,'Daily — hypothyroidism');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 6: OPENEMR — VITALS
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO form_vitals (date, pid, bps, bpd, weight, height, temperature, pulse, respiration, BMI, oxygen_saturation, authorized, activity) VALUES
-- Patient 1: CHF — elevated BP, weight up from edema
('2025-01-15 09:00:00',1,'148','94',168.0,62.0,98.2,84,18,30.7,95,1,1),
('2025-03-20 10:30:00',1,'155','98',171.0,62.0,98.4,92,20,31.3,93,1,1),
('2026-01-22 09:00:00',1,'142','90',165.0,62.0,98.1,80,18,30.2,96,1,1),
-- Patient 2: COPD — low O2 sat
('2025-01-20 11:00:00',2,'132','80',141.0,68.0,98.0,76,22,21.4,88,1,1),
('2026-01-28 09:00:00',2,'128','78',138.0,68.0,97.8,74,24,20.9,86,1,1),
-- Patient 3: ESRD — fluid overloaded
('2025-01-10 08:00:00',3,'158','96',198.0,70.0,98.0,88,20,28.4,95,1,1),
('2025-05-20 10:00:00',3,'162','100',204.0,70.0,98.2,90,22,29.3,94,1,1),
('2026-02-14 08:00:00',3,'150','92',196.0,70.0,98.1,86,20,28.1,95,1,1),
-- Patient 4: Dementia/Parkinson
('2025-02-01 10:00:00',4,'136','82',122.0,61.0,97.8,68,16,23.0,97,1,1),
('2026-02-12 09:00:00',4,'140','86',119.0,61.0,97.6,72,16,22.5,97,1,1),
-- Patient 5: Cirrhosis — jaundiced, wasting
('2025-01-25 09:00:00',5,'118','72',148.0,70.0,99.2,78,18,21.2,97,1,1),
('2025-09-08 11:00:00',5,'112','68',142.0,70.0,99.8,88,22,20.4,96,1,1),
-- Patient 6: Post-stroke elderly
('2025-01-08 09:00:00',6,'138','88',134.0,60.0,98.0,78,18,26.2,96,1,1),
('2025-11-05 14:00:00',6,'152','96',138.0,60.0,98.4,92,22,26.9,93,1,1),
-- Sample vitals for other patients
('2025-02-05 09:00:00',7,'142','88',196.0,70.0,98.0,72,16,28.1,97,1,1),
('2025-02-10 10:00:00',8,'128','80',218.0,65.0,98.2,82,20,36.3,94,1,1),
('2025-01-30 11:00:00',9,'145','90',178.0,69.0,98.1,76,18,26.3,96,1,1),
('2025-02-15 09:00:00',10,'136','84',202.0,65.0,98.0,74,18,33.6,97,1,1),
('2025-12-01 09:00:00',14,'138','88',238.0,66.0,98.1,78,18,38.4,97,1,1),
('2026-01-10 09:00:00',8,'130','82',222.0,65.0,98.0,80,20,36.9,95,1,1);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 7: RAF INTELLIGENCE — PROVIDERS
-- ─────────────────────────────────────────────────────────────────────────────
USE raf_intelligence;

DELETE FROM provider_patient_panel WHERE provider_id BETWEEN 1 AND 4;
DELETE FROM providers WHERE id BETWEEN 1 AND 4;

INSERT INTO providers (id, npi, first_name, last_name, full_name, specialty, email, openemr_user_id, status, is_active) VALUES
(1, '1234567890', 'Sarah', 'Mitchell', 'Dr. Sarah Mitchell', 'Internal Medicine', 'smitchell@sunrisehealth.com', 1, 'active', 1),
(2, '2345678901', 'David', 'Park', 'Dr. David Park', 'Family Medicine', 'dpark@sunrisehealth.com', 2, 'active', 1),
(3, '3456789012', 'Lisa', 'Thompson', 'Dr. Lisa Thompson', 'Geriatrics', 'lthompson@sunrisehealth.com', 3, 'active', 1),
(4, '4567890123', 'Michael', 'Rivera', 'Dr. Michael Rivera', 'Cardiology', 'mrivera@sunrisehealth.com', 4, 'active', 1);

-- ── Provider-Patient Panel ────────────────────────────────────────────────────
-- Provider 1: Mitchell — patients 1,2,6,8,13,18,21,25,29 (9 patients)
-- Provider 2: Park — patients 3,5,7,14,17,19,22,26,30 (9 patients)
-- Provider 3: Thompson — patients 4,10,12,16,20,24,28 (7 patients)
-- Provider 4: Rivera — patients 9,11,15,23,27 (5 patients — specialist)

INSERT INTO provider_patient_panel (provider_id, patient_id, attribution) VALUES
(1,1,"manual"),
(1,2,"manual"),
(1,6,"manual"),
(1,8,"manual"),
(1,13,"manual"),
(1,18,"manual"),
(1,21,"manual"),
(1,25,"manual"),
(1,29,"manual"),
(2,3,"manual"),
(2,5,"manual"),
(2,7,"manual"),
(2,14,"manual"),
(2,17,"manual"),
(2,19,"manual"),
(2,22,"manual"),
(2,26,"manual"),
(2,30,"manual"),
(3,4,"manual"),
(3,10,"manual"),
(3,12,"manual"),
(3,16,"manual"),
(3,20,"manual"),
(3,24,"manual"),
(3,28,"manual"),
(4,9,"manual"),
(4,11,"manual"),
(4,15,"manual"),
(4,23,"manual"),
(4,27,"manual"),
(4,1,"manual"),
(4,6,"manual"),
(4,7,"manual");

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 8: HCC ICD-10 CROSSWALK (reference data)
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM hcc_icd10_crosswalk WHERE effective_year = 2024;

INSERT INTO hcc_icd10_crosswalk (icd10_code, icd10_description, hcc_code, hcc_label, effective_year) VALUES
-- Cancer (HCC9)
('C34.90','Malignant neoplasm of bronchus and lung, unspecified',9,'Lung Cancer',2024),
('C34.10','Malignant neoplasm of upper lobe, bronchus or lung, unspecified',9,'Lung Cancer',2024),
('C34.30','Malignant neoplasm of lower lobe, bronchus or lung, unspecified',9,'Lung Cancer',2024),
-- Diabetes with complications (HCC18)
('E11.22','Type 2 DM with diabetic chronic kidney disease, stage 1-2',18,'Diabetes w/ Chronic Complications',2024),
('E11.40','Type 2 DM with diabetic neuropathy, unspecified',18,'Diabetes w/ Chronic Complications',2024),
('E11.51','Type 2 DM with diabetic peripheral angiopathy w/o gangrene',18,'Diabetes w/ Chronic Complications',2024),
('E11.65','Type 2 DM with hyperglycemia',18,'Diabetes w/ Chronic Complications',2024),
('E11.621','Type 2 DM with foot ulcer',18,'Diabetes w/ Chronic Complications',2024),
('E11.649','Type 2 DM with hypoglycemia without coma',18,'Diabetes w/ Chronic Complications',2024),
-- Diabetes without complications (HCC19)
('E11.9','Type 2 DM without complications',19,'Diabetes w/o Chronic Complications',2024),
('E11.00','Type 2 DM with hyperosmolarity without nonketotic hyperosmolar-hyperglycemic coma',19,'Diabetes w/o Chronic Complications',2024),
-- Malnutrition (HCC21)
('E44.0','Moderate protein-calorie malnutrition',21,'Protein-Calorie Malnutrition',2024),
('E43','Unspecified severe protein-calorie malnutrition',21,'Protein-Calorie Malnutrition',2024),
('E41','Nutritional marasmus',21,'Protein-Calorie Malnutrition',2024),
-- Morbid Obesity (HCC22)
('E66.01','Morbid (severe) obesity due to excess calories',22,'Morbid Obesity',2024),
('E66.09','Other obesity due to excess calories',22,'Morbid Obesity',2024),
('E66.9','Obesity, unspecified',22,'Morbid Obesity',2024),
-- End-Stage Liver Disease (HCC27)
('K74.60','Unspecified cirrhosis of liver',27,'End-Stage Liver Disease',2024),
('K74.61','Primary biliary cholangitis',27,'End-Stage Liver Disease',2024),
('K70.30','Alcoholic cirrhosis of liver without ascites',27,'End-Stage Liver Disease',2024),
('K72.10','Chronic hepatic failure without coma',27,'End-Stage Liver Disease',2024),
-- Cirrhosis (HCC28)
('K74.1','Hepatic fibrosis',28,'Cirrhosis of Liver',2024),
('K76.0','Fatty (change of) liver, not elsewhere classified',28,'Cirrhosis of Liver',2024),
-- Rheumatoid Arthritis (HCC40)
('M05.79','Rheumatoid arthritis with rheumatoid factor, multiple sites',40,'RA/Inflammatory Connective Tissue Disease',2024),
('M05.9','Rheumatoid arthritis with rheumatoid factor, unspecified',40,'RA/Inflammatory Connective Tissue Disease',2024),
('M06.00','Rheumatoid arthritis without rheumatoid factor, unspecified site',40,'RA/Inflammatory Connective Tissue Disease',2024),
-- Anemia/Hematologic (HCC46)
('D63.1','Anemia in chronic kidney disease',46,'Severe Hematological Disorders',2024),
('D63.0','Anemia in neoplastic disease',46,'Severe Hematological Disorders',2024),
('D61.9','Aplastic anemia, unspecified',46,'Severe Hematological Disorders',2024),
-- Coagulation (HCC48)
('D68.9','Coagulation defect, unspecified',48,'Coagulation Defects and Other Specified Hematological Disorders',2024),
('D68.1','Hereditary factor XI deficiency',48,'Coagulation Defects and Other Specified Hematological Disorders',2024),
-- Dementia with complications (HCC51)
('F01.50','Vascular dementia without behavioral disturbance',51,'Dementia w/ Complications',2024),
('F02.80','Dementia in other diseases classified elsewhere without behavioral disturbance',51,'Dementia w/ Complications',2024),
-- Dementia without complications (HCC52)
('F03.90','Unspecified dementia without behavioral disturbance',52,'Dementia w/o Complications',2024),
('G30.9','Alzheimer disease, unspecified',52,'Dementia w/o Complications',2024),
('G30.1','Alzheimer disease with late onset',52,'Dementia w/o Complications',2024),
-- Depression (HCC59)
('F32.1','Major depressive disorder, single episode, moderate',59,'Major Depressive, Bipolar, and Paranoid Disorders',2024),
('F32.2','Major depressive disorder, single episode, severe without psychotic features',59,'Major Depressive, Bipolar, and Paranoid Disorders',2024),
('F33.1','Major depressive disorder, recurrent, moderate',59,'Major Depressive, Bipolar, and Paranoid Disorders',2024),
-- Parkinson''s (HCC78)
('G20','Parkinson disease',78,'Parkinson''s and Huntington''s Diseases',2024),
('G20.A1','Parkinson disease without dyskinesia, without mention of fluctuations',78,'Parkinson''s and Huntington''s Diseases',2024),
('G20.C1','Parkinson disease with dyskinesia, without mention of fluctuations',78,'Parkinson''s and Huntington''s Diseases',2024),
-- CHF (HCC85)
('I50.20','Unspecified systolic (congestive) heart failure',85,'Congestive Heart Failure',2024),
('I50.22','Chronic systolic (congestive) heart failure',85,'Congestive Heart Failure',2024),
('I50.32','Chronic diastolic (congestive) heart failure',85,'Congestive Heart Failure',2024),
('I50.9','Heart failure, unspecified',85,'Congestive Heart Failure',2024),
('I50.43','Acute on chronic combined systolic and diastolic CHF',85,'Congestive Heart Failure',2024),
-- AFib (HCC96)
('I48.91','Unspecified atrial fibrillation',96,'Specified Heart Arrhythmias',2024),
('I48.19','Other persistent atrial fibrillation',96,'Specified Heart Arrhythmias',2024),
('I48.11','Longstanding persistent atrial fibrillation',96,'Specified Heart Arrhythmias',2024),
-- Stroke (HCC100)
('I63.9','Cerebral infarction, unspecified',100,'Cerebral Hemorrhage',2024),
('I63.50','Cerebral infarction due to unoccluded cerebral artery, unspecified',100,'Cerebral Hemorrhage',2024),
-- Hemiplegia (HCC103)
('G81.90','Hemiplegia, unspecified affecting unspecified side',103,'Hemiplegia/Hemiparesis',2024),
('G81.10','Spastic hemiplegia affecting unspecified side',103,'Hemiplegia/Hemiparesis',2024),
-- Vascular Disease (HCC108)
('I73.9','Peripheral vascular disease, unspecified',108,'Vascular Disease',2024),
('I70.209','Unspecified atherosclerosis of native arteries of extremities',108,'Vascular Disease',2024),
('I70.90','Unspecified atherosclerosis',108,'Vascular Disease',2024),
-- COPD (HCC111)
('J44.1','Chronic obstructive pulmonary disease with (acute) exacerbation',111,'COPD',2024),
('J44.0','Chronic obstructive pulmonary disease with acute lower respiratory infection',111,'COPD',2024),
-- ESRD (HCC136)
('N18.6','End stage renal disease',136,'Renal Failure',2024),
('N18.5','Chronic kidney disease, stage 5',136,'Renal Failure',2024),
-- CKD Stage 4 (HCC137)
('N18.4','Chronic kidney disease, stage 4',137,'Chronic Kidney Disease, Stage 4',2024),
-- CKD Stage 3 (HCC138)
('N18.3','Chronic kidney disease, stage 3, unspecified',138,'Chronic Kidney Disease, Stage 3',2024),
('N18.31','Chronic kidney disease, stage 3a',138,'Chronic Kidney Disease, Stage 3',2024),
('N18.32','Chronic kidney disease, stage 3b',138,'Chronic Kidney Disease, Stage 3',2024);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 9: HCC RAF COEFFICIENTS (CMS V24 2024 — CNA model)
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM hcc_raf_coefficients WHERE model_year = 2024;

INSERT INTO hcc_raf_coefficients (hcc_code, model_segment, coefficient, model_year) VALUES
(9,   'CNA', 0.3910, 2024),
(18,  'CNA', 0.3680, 2024),
(19,  'CNA', 0.1180, 2024),
(21,  'CNA', 0.7130, 2024),
(22,  'CNA', 0.3890, 2024),
(27,  'CNA', 0.9520, 2024),
(28,  'CNA', 0.4810, 2024),
(40,  'CNA', 0.3890, 2024),
(46,  'CNA', 0.6700, 2024),
(48,  'CNA', 0.2630, 2024),
(51,  'CNA', 0.5930, 2024),
(52,  'CNA', 0.4020, 2024),
(59,  'CNA', 0.3580, 2024),
(78,  'CNA', 0.7040, 2024),
(85,  'CNA', 0.3680, 2024),
(96,  'CNA', 0.3200, 2024),
(100, 'CNA', 0.2880, 2024),
(103, 'CNA', 0.5930, 2024),
(108, 'CNA', 0.2990, 2024),
(111, 'CNA', 0.3350, 2024),
(112, 'CNA', 0.2110, 2024),
(136, 'CNA', 0.3930, 2024),
(137, 'CNA', 0.2880, 2024),
(138, 'CNA', 0.0690, 2024);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 10: HCC DEMOGRAPHIC COEFFICIENTS (CNA — Community Non-Dual Aged)
-- CMS 2024 V24 approximate values
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM hcc_demographic_coefficients WHERE model_year = 2024 AND model_segment = 'CNA';

INSERT INTO hcc_demographic_coefficients (model_segment, age_band, sex, coefficient, model_year) VALUES
('CNA','65-69','F',0.3700,2024),
('CNA','70-74','F',0.4200,2024),
('CNA','75-79','F',0.4700,2024),
('CNA','80-84','F',0.5400,2024),
('CNA','85-89','F',0.5900,2024),
('CNA','90-94','F',0.6200,2024),
('CNA','95+', 'F',0.6500,2024),
('CNA','65-69','M',0.3900,2024),
('CNA','70-74','M',0.4400,2024),
('CNA','75-79','M',0.4900,2024),
('CNA','80-84','M',0.5500,2024),
('CNA','85-89','M',0.6100,2024),
('CNA','90-94','M',0.6400,2024),
('CNA','95+', 'M',0.6700,2024),
-- Under-65 (disabled pathway patients)
('CNA','45-54','F',0.3100,2024),
('CNA','55-59','F',0.3300,2024),
('CNA','60-64','F',0.3500,2024),
('CNA','45-54','M',0.3200,2024),
('CNA','55-59','M',0.3400,2024),
('CNA','60-64','M',0.3600,2024);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 11: RAF PATIENT DEMOGRAPHICS
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM raf_patient_demographics WHERE patient_id BETWEEN 1 AND 30;

INSERT INTO raf_patient_demographics (patient_id, measurement_year, age_band, sex, dual_status, dual_type, disabled, orec, institutional, model_segment) VALUES
-- High risk
(1,  2026, '75-79', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),  -- Margaret Chen 78F
(2,  2026, '80-84', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),  -- Robert Williams 82M
(3,  2026, '70-74', 'M', 1, 'full_dual', 0, '2', 0, 'CNA'), -- James Johnson 71M — ESRD=orec 2
(4,  2026, '75-79', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),  -- Dorothy Martinez 76F
(5,  2026, '65-69', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),  -- William Brown 69M
(6,  2026, '85-89', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),  -- Helen Davis 85F
-- Medium risk
(7,  2026, '70-74', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(8,  2026, '65-69', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(9,  2026, '75-79', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(10, 2026, '65-69', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(11, 2026, '75-79', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(12, 2026, '70-74', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(13, 2026, '75-79', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(14, 2026, '65-69', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(15, 2026, '80-84', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(16, 2026, '60-64', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(17, 2026, '70-74', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(18, 2026, '70-74', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
-- Low risk
(19, 2026, '60-64', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(20, 2026, '55-59', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(21, 2026, '65-69', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(22, 2026, '60-64', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(23, 2026, '70-74', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(24, 2026, '55-59', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(25, 2026, '70-74', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(26, 2026, '65-69', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(27, 2026, '60-64', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(28, 2026, '65-69', 'F', 0, 'non_dual', 0, '0', 0, 'CNA'),
(29, 2026, '60-64', 'M', 0, 'non_dual', 0, '0', 0, 'CNA'),
(30, 2026, '70-74', 'F', 0, 'non_dual', 0, '0', 0, 'CNA');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 12: RAF PATIENT HCC
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM raf_meat_evidence WHERE patient_hcc_id IN (SELECT id FROM raf_patient_hcc WHERE patient_id BETWEEN 1 AND 30);
DELETE FROM raf_patient_hcc WHERE patient_id BETWEEN 1 AND 30;

-- Patient 1: Margaret Chen — 4 HCCs (complete MEAT — Mitchell's best work)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(101, 1, 2026, 85,  '["I50.22"]',       '[1001,1002,1004,1005]', 0.3680, 'complete', 0, NULL),
(102, 1, 2026, 137, '["N18.4"]',        '[1001,1003,1005]',      0.2880, 'complete', 0, NULL),
(103, 1, 2026, 18,  '["E11.65"]',       '[1001,1003,1005]',      0.3680, 'complete', 0, NULL),
(104, 1, 2026, 108, '["I73.9"]',        '[1001,1004,1005]',      0.2990, 'complete', 0, NULL);

-- Patient 2: Robert Williams — 3 HCCs (partial MEAT — documentation shortcut on malnutrition)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(201, 2, 2026, 111, '["J44.1"]',        '[1006,1009]',           0.3350, 'complete', 0, NULL),
(202, 2, 2026, 9,   '["C34.90"]',       '[1007,1009]',           0.3910, 'partial',  0, NULL),
(203, 2, 2026, 21,  '["E44.0"]',        '[1008,1009]',           0.7130, 'partial',  0, NULL);

-- Patient 3: James Johnson — 4 HCCs (full MEAT — Park's most complex patient)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(301, 3, 2026, 136, '["N18.6"]',        '[1010,1011,1012,1013,1014]', 0.3930, 'complete', 0, NULL),
(302, 3, 2026, 18,  '["E11.22"]',       '[1011,1014]',           0.3680, 'complete', 0, NULL),
(303, 3, 2026, 85,  '["I50.32"]',       '[1012,1014]',           0.3680, 'complete', 0, NULL),
(304, 3, 2026, 46,  '["D63.1"]',        '[1013,1014]',           0.6700, 'complete', 0, NULL);

-- Patient 4: Dorothy Martinez — 3 HCCs (dementia/Parkinson complete, depression MISSING — gap!)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(401, 4, 2026, 52,  '["F03.90"]',       '[1015,1016,1017,1018,1019]', 0.4020, 'complete', 0, NULL),
(402, 4, 2026, 78,  '["G20.A1"]',       '[1016,1017,1018,1019]', 0.7040, 'complete', 0, NULL),
(403, 4, 2026, 59,  '["F32.1"]',        '[1017]',                0.3580, 'missing',  0, NULL);
-- Note: HCC59 has only 1 encounter reference and missing MEAT — demo gap

-- Patient 5: William Brown — 3 HCCs (partial MEAT on coagulopathy)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(501, 5, 2026, 27,  '["K74.60"]',       '[1020,1021,1022,1023]', 0.9520, 'complete', 0, NULL),
(502, 5, 2026, 18,  '["E11.65"]',       '[1020,1023]',           0.3680, 'partial',  0, NULL),
(503, 5, 2026, 48,  '["D68.9"]',        '[1021,1022,1023]',      0.2630, 'partial',  0, NULL);

-- Patient 6: Helen Davis — 4 HCCs (full MEAT — Mitchell's comprehensive documentation)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(601, 6, 2026, 100, '["I63.9"]',        '[1024,1028]',           0.2880, 'complete', 0, NULL),
(602, 6, 2026, 103, '["G81.90"]',       '[1024,1026,1028]',      0.5930, 'complete', 0, NULL),
(603, 6, 2026, 96,  '["I48.91"]',       '[1025,1027,1028]',      0.3200, 'complete', 0, NULL),
(604, 6, 2026, 85,  '["I50.20"]',       '[1025,1027,1028]',      0.3680, 'complete', 0, NULL);

-- Patient 7: Gerald Thompson — 3 HCCs
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(701, 7, 2026, 18,  '["E11.40"]',       '[1029,1031]',           0.3680, 'complete', 0, NULL),
(702, 7, 2026, 96,  '["I48.91"]',       '[1030,1031]',           0.3200, 'partial',  0, NULL),
(703, 7, 2026, 138, '["N18.3"]',        '[1031]',                0.0690, 'partial',  0, NULL);

-- Patient 8: Patricia Anderson — 3 HCCs (Mitchell captures well)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(801, 8, 2026, 111, '["J44.1"]',        '[1032,1034]',           0.3350, 'complete', 0, NULL),
(802, 8, 2026, 59,  '["F32.1"]',        '[1033,1034]',           0.3580, 'complete', 0, NULL),
(803, 8, 2026, 22,  '["E66.09"]',       '[1034]',                0.3890, 'partial',  0, NULL);

-- Patient 9: Charles Wilson — 3 HCCs (Rivera — partial MEAT)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(901, 9, 2026, 85,  '["I50.9"]',        '[1035,1037]',           0.3680, 'partial',  0, NULL),
(902, 9, 2026, 108, '["I73.9"]',        '[1035,1036,1037]',      0.2990, 'partial',  0, NULL),
(903, 9, 2026, 138, '["N18.3"]',        '[1037]',                0.0690, 'missing',  0, NULL);

-- Patient 10: Barbara Jackson — 3 HCCs (Thompson — some gaps)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1001,10, 2026, 18,  '["E11.65"]',      '[1038,1040]',           0.3680, 'partial',  0, NULL),
(1002,10, 2026, 59,  '["F32.1"]',       '[1039,1040]',           0.3580, 'partial',  0, NULL),
(1003,10, 2026, 22,  '["E66.09"]',      '[1040]',                0.3890, 'missing',  0, NULL);

-- Patient 11: Richard Harris — 3 HCCs
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1101,11, 2026, 40,  '["M05.79"]',      '[1041,1043]',           0.3890, 'complete', 0, NULL),
(1102,11, 2026, 96,  '["I48.91"]',      '[1042,1043]',           0.3200, 'partial',  0, NULL),
(1103,11, 2026, 85,  '["I50.9"]',       '[1043]',                0.3680, 'partial',  0, NULL);

-- Patient 12: Nancy Lewis — 2 HCCs (donepezil RX but dementia NOT coded in 2026 AWV — suspect will fire)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1201,12, 2026, 138, '["N18.3"]',       '[1045,1046]',           0.0690, 'partial',  0, NULL);
-- HCC52 (dementia) intentionally NOT inserted — suspect condition will fire

-- Patient 13: Joseph Robinson — 2 HCCs
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1301,13, 2026, 111, '["J44.1"]',       '[1047,1049]',           0.3350, 'complete', 0, NULL),
(1302,13, 2026, 108, '["I73.9"]',       '[1048,1049]',           0.2990, 'partial',  0, NULL);

-- Patient 14: Karen Walker — 3 HCCs (Park — CKD3 coded but eGFR 38 suggests stage 4 upgrade opportunity)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1401,14, 2026, 18,  '["E11.621","E11.65"]','[1050,1052]',       0.3680, 'complete', 0, NULL),
(1402,14, 2026, 138, '["N18.3"]',       '[1051,1052]',           0.0690, 'partial',  0, NULL),
(1403,14, 2026, 22,  '["E66.01"]',      '[1052]',                0.3890, 'partial',  0, NULL);

-- Patient 15: Thomas Hall — 3 HCCs (Rivera — adequate)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1501,15, 2026, 100, '["I63.9"]',       '[1053,1055]',           0.2880, 'partial',  0, NULL),
(1502,15, 2026, 96,  '["I48.91"]',      '[1053,1055]',           0.3200, 'partial',  0, NULL),
(1503,15, 2026, 85,  '["I50.9"]',       '[1054,1055]',           0.3680, 'partial',  0, NULL);

-- Patients 16–18 (fewer HCCs)
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(1601,16, 2026, 18,  '["E11.51"]',      '[1056,1057]',           0.3680, 'partial',  0, NULL),
(1602,16, 2026, 108, '["I73.9"]',       '[1056]',                0.2990, 'missing',  0, NULL),
(1701,17, 2026, 111, '["J44.1"]',       '[1058,1059]',           0.3350, 'partial',  0, NULL),
(1702,17, 2026, 19,  '["E11.9"]',       '[1058,1059]',           0.1180, 'partial',  0, NULL),
(1801,18, 2026, 40,  '["M05.79"]',      '[1060,1061]',           0.3890, 'complete', 0, NULL),
(1802,18, 2026, 138, '["N18.3"]',       '[1061]',                0.0690, 'partial',  0, NULL);

-- Low-risk patients with 1 HCC each
INSERT INTO raf_patient_hcc (id, patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc) VALUES
(2001,20, 2026, 19,  '["E11.9"]',       '[1064,1065]',           0.1180, 'partial',  0, NULL),
(2301,23, 2026, 138, '["N18.3"]',       '[1070,1071]',           0.0690, 'partial',  0, NULL),
(2401,24, 2026, 22,  '["E66.9"]',       '[1072,1073]',           0.3890, 'partial',  0, NULL),
(2501,25, 2026, 19,  '["E11.9"]',       '[1074,1075]',           0.1180, 'complete', 0, NULL),
(2601,26, 2026, 59,  '["F32.1"]',       '[1076,1077]',           0.3580, 'complete', 0, NULL),
(2901,29, 2026, 19,  '["E11.9"]',       '[1082,1083]',           0.1180, 'partial',  0, NULL);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 13: RAF SCORES
-- Formula: final_raf = demographic_score + disease_score + interaction_score
-- Normalization factor = 1.0 for demo simplicity
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM raf_scores WHERE patient_id BETWEEN 1 AND 30;

INSERT INTO raf_scores (patient_id, measurement_year, score_type, model_segment, demographic_score, disease_score, interaction_score, total_raw, normalization_factor, final_raf, hcc_count) VALUES
-- Patient 1: Margaret Chen — demo: 0.4700 + (0.3680+0.2880+0.3680+0.2990) + 0.1200 = 1.9130
(1,  2026,'prospective','CNA',0.4700, 1.3230, 0.1200, 1.9130, 1.0000, 1.9130, 4),
-- Patient 2: Robert Williams — 0.5500 + (0.3350+0.3910+0.7130) + 0.0800 = 2.0690
(2,  2026,'prospective','CNA',0.5500, 1.4390, 0.0800, 2.0690, 1.0000, 2.0690, 3),
-- Patient 3: James Johnson — 0.4400 + (0.3930+0.3680+0.3680+0.6700) + 0.1800 = 2.4190
(3,  2026,'prospective','CNA',0.4400, 1.7990, 0.1800, 2.4190, 1.0000, 2.4190, 4),
-- Patient 4: Dorothy Martinez — 0.4700 + (0.4020+0.7040+0.3580) + 0.0000 = 1.9340
(4,  2026,'prospective','CNA',0.4700, 1.4640, 0.0000, 1.9340, 1.0000, 1.9340, 3),
-- Patient 5: William Brown — 0.3900 + (0.9520+0.3680+0.2630) + 0.1300 = 2.1030
(5,  2026,'prospective','CNA',0.3900, 1.5830, 0.1300, 2.1030, 1.0000, 2.1030, 3),
-- Patient 6: Helen Davis — 0.5900 + (0.2880+0.5930+0.3200+0.3680) + 0.1500 = 2.3090
(6,  2026,'prospective','CNA',0.5900, 1.5690, 0.1500, 2.3090, 1.0000, 2.3090, 4),
-- Medium risk
(7,  2026,'prospective','CNA',0.4400, 0.7570, 0.0300, 1.2270, 1.0000, 1.2270, 3),
(8,  2026,'prospective','CNA',0.3700, 1.0820, 0.0400, 1.4920, 1.0000, 1.4920, 3),
(9,  2026,'prospective','CNA',0.4900, 0.7360, 0.0500, 1.2760, 1.0000, 1.2760, 3),
(10, 2026,'prospective','CNA',0.3700, 1.1150, 0.0400, 1.5250, 1.0000, 1.5250, 3),
(11, 2026,'prospective','CNA',0.4900, 1.0770, 0.0500, 1.6170, 1.0000, 1.6170, 3),
(12, 2026,'prospective','CNA',0.4200, 0.0690, 0.0000, 0.4890, 1.0000, 0.4890, 1),
-- Note: Patient 12 has only CKD3 coded — dementia MISSING from this score
(13, 2026,'prospective','CNA',0.4900, 0.6340, 0.0000, 1.1240, 1.0000, 1.1240, 2),
(14, 2026,'prospective','CNA',0.3700, 0.8260, 0.0400, 1.2360, 1.0000, 1.2360, 3),
(15, 2026,'prospective','CNA',0.5500, 0.9760, 0.0400, 1.5660, 1.0000, 1.5660, 3),
(16, 2026,'prospective','CNA',0.3500, 0.6670, 0.0000, 1.0170, 1.0000, 1.0170, 2),
(17, 2026,'prospective','CNA',0.4400, 0.4530, 0.0000, 0.8930, 1.0000, 0.8930, 2),
(18, 2026,'prospective','CNA',0.4200, 0.4580, 0.0000, 0.8780, 1.0000, 0.8780, 2),
-- Low risk
(19, 2026,'prospective','CNA',0.3600, 0.0000, 0.0000, 0.3600, 1.0000, 0.3600, 0),
(20, 2026,'prospective','CNA',0.3300, 0.1180, 0.0000, 0.4480, 1.0000, 0.4480, 1),
(21, 2026,'prospective','CNA',0.3900, 0.0000, 0.0000, 0.3900, 1.0000, 0.3900, 0),
(22, 2026,'prospective','CNA',0.3500, 0.0000, 0.0000, 0.3500, 1.0000, 0.3500, 0),
(23, 2026,'prospective','CNA',0.4400, 0.0690, 0.0000, 0.5090, 1.0000, 0.5090, 1),
(24, 2026,'prospective','CNA',0.3300, 0.3890, 0.0000, 0.7190, 1.0000, 0.7190, 1),
(25, 2026,'prospective','CNA',0.4400, 0.1180, 0.0000, 0.5580, 1.0000, 0.5580, 1),
(26, 2026,'prospective','CNA',0.3700, 0.3580, 0.0000, 0.7280, 1.0000, 0.7280, 1),
(27, 2026,'prospective','CNA',0.3600, 0.0000, 0.0000, 0.3600, 1.0000, 0.3600, 0),
(28, 2026,'prospective','CNA',0.3700, 0.0000, 0.0000, 0.3700, 1.0000, 0.3700, 0),
(29, 2026,'prospective','CNA',0.3600, 0.1180, 0.0000, 0.4780, 1.0000, 0.4780, 1),
(30, 2026,'prospective','CNA',0.4200, 0.0000, 0.0000, 0.4200, 1.0000, 0.4200, 0);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 14: RAF SUSPECT CONDITIONS (AI-flagged gaps)
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM raf_suspect_conditions WHERE patient_id BETWEEN 1 AND 30 AND measurement_year = 2026;

INSERT INTO raf_suspect_conditions (patient_id, measurement_year, suspect_hcc, suspect_icd10, evidence_type, evidence_detail, confidence_score, status) VALUES

-- ── Patient 3: eGFR 8 — coded as ESRD but BNP 650 suggests CHF needs more specific coding
(3, 2026, 85, 'I50.43', 'lab',
 '{"lab":"BNP","value":650,"unit":"pg/mL","date":"2025-05-20","threshold":400,"note":"BNP 650 pg/mL on 5/20/2025 — above decompensated CHF threshold of 400. Current code I50.32 (diastolic) may underrepresent severity. Upgrade to acute-on-chronic may be warranted."}',
 0.8500, 'open'),

-- ── Patient 4: Dorothy Martinez — Depression (F32.1 / HCC59) — on sertraline, never coded in 2026
(4, 2026, 59, 'F32.1', 'medication',
 '{"drug":"Sertraline 50mg","prescribed_date":"2025-07-14","provider":"Dr. Lisa Thompson","note":"Patient has been on sertraline 50mg since July 2025. PHQ-9 was 16 at last screening. ICD10 F32.1 was recorded on problem list in 2024 but NOT coded in any 2026 encounter. HCC59 will not be captured for risk adjustment without an active encounter diagnosis.","revenue_at_risk":1230.80}',
 0.8800, 'open'),

-- ── Patient 5: William Brown — Hepatic Encephalopathy not coded (K72.00 → HCC27 upgrade)
(5, 2026, 27, 'K72.00', 'historical',
 '{"historical_code":"K74.60","prior_year_hcc":27,"note":"Patient had documented hepatic encephalopathy episode on 9/8/2025 (encounter 1022). K72.00 (acute hepatic failure) maps to HCC27 at higher specificity. Current coding uses K74.60 (cirrhosis) — consider upgrading to reflect acute decompensation which yields same HCC but is clinically more accurate for MEAT.","last_encounter_date":"2025-09-08"}',
 0.7500, 'open'),

-- ── Patient 7: Gerald Thompson — CKD3 coded, but eGFR labs trending toward Stage 4
(7, 2026, 137, 'N18.4', 'lab',
 '{"lab":"eGFR","value":28,"unit":"mL/min/1.73m2","date":"2025-12-01","threshold":30,"note":"eGFR 28 mL/min on 12/1/2025 lab draw. Threshold for CKD Stage 4 is eGFR < 30. Current coding is N18.3 (CKD Stage 3). If confirmed, upgrade to N18.4 (CKD Stage 4 / HCC137) would increase RAF coefficient from 0.069 to 0.288 — significant revenue impact.","revenue_delta":756.90}',
 0.9200, 'open'),

-- ── Patient 9: Charles Wilson — CKD3 only partially documented; no MEAT evidence
(9, 2026, 137, 'N18.4', 'lab',
 '{"lab":"Creatinine","value":2.4,"unit":"mg/dL","date":"2025-12-15","lab2":"eGFR","value2":24,"date2":"2025-12-15","note":"Creatinine 2.4 mg/dL + eGFR 24 confirm CKD Stage 4 per KDIGO criteria. Current ICD-10 is N18.3 (Stage 3). Provider coded Stage 3 at the same visit — this may be a coding error. Upgrade to N18.4 would capture HCC137 (0.288 coefficient).","confidence_factors":["eGFR < 30","creatinine > 2.0","two consecutive values"]}',
 0.9100, 'open'),

-- ── Patient 10: Barbara Jackson — Obesity HCC22 not coded; BMI 37.1 documented in vitals
(10, 2026, 22, 'E66.09', 'lab',
 '{"measurement":"BMI","value":37.1,"unit":"kg/m2","date":"2026-02-25","note":"BMI 37.1 documented in vitals at 2/25/2026 AWV. ICD-10 E66.09 (other obesity) was NOT included in the encounter diagnosis list despite being on the active problem list. HCC22 coefficient is 0.389 — adding this code would increase RAF score by ~$1,340/year.","problem_list_entry":"E66.09 added 2024-01-01"}',
 0.9500, 'open'),

-- ── Patient 12: Nancy Lewis — Donepezil on medication list; dementia NOT coded in 2026
(12, 2026, 52, 'F03.90', 'medication',
 '{"drug":"Donepezil 5mg","prescribed_date":"2025-02-20","note":"Donepezil 5mg (cholinesterase inhibitor) exclusively indicated for Alzheimer dementia. Patient has F03.90 on active problem list since 2023. The 2026 AWV encounter (1046) did NOT include a dementia diagnosis code. HCC52 will not contribute to this year risk score without a coded diagnosis. Revenue at risk: $1,383 annually.","confidence_factors":["disease-specific medication","active problem list","prior year HCC52 captured"],"revenue_at_risk":1383.00}',
 0.9200, 'open'),

-- ── Patient 14: Karen Walker — eGFR 34 with N18.3 coded; should be N18.4 (Stage 4 upgrade)
(14, 2026, 137, 'N18.4', 'lab',
 '{"lab":"eGFR","value":34,"unit":"mL/min/1.73m2","date":"2025-07-18","lab2":"creatinine","value2":2.1,"date2":"2025-07-18","note":"eGFR 34 mL/min on 7/18/2025 — CKD Stage 3b borderline. Creatinine 2.1 mg/dL supports Stage 4 reclassification per repeat testing. Coding currently N18.3. Recommend nephrology consult to confirm; if Stage 4, HCC137 coefficient (0.288) replaces HCC138 (0.069) — net RAF gain of 0.219.","nephrology_referral_made":true}',
 0.8800, 'open'),

-- ── Patient 16: Lisa Allen — HCC59 (Depression) — patient on insulin; HbA1c 8.1% but depression not coded this year
(16, 2026, 59, 'F32.1', 'historical',
 '{"historical_code":"F32.1","prior_encounter":"2025-03-10","note":"Patient has a known history of depression (F32.1) managed with escitalopram since 2023. No depression diagnosis coded in 2026 encounters. This is a recapture gap — HCC59 was captured in 2024 and 2025 but not 2026. Sertraline is not on this patient medication list but escitalopram was discontinued without documented reason.","recapture_gap":true}',
 0.7200, 'open'),

-- ── Patient 17: Daniel Young — Obesity HCC22; BMI 36.4 in vitals, not coded in 2026 AWV
(17, 2026, 22, 'E66.09', 'lab',
 '{"measurement":"BMI","value":36.4,"unit":"kg/m2","date":"2026-02-10","note":"BMI 36.4 at 2026 AWV. Obesity was coded in 2025 but not included in the 2026 encounter billing. E66.09 maps to HCC22 (coefficient 0.389). This is an annual recapture miss — provider did not include the diagnosis even though it was discussed in the visit.","visit_note_mentions_obesity":true}',
 0.9300, 'open'),

-- ── Patient 20: Carol Green — HbA1c 6.8%; meets diabetes threshold, HCC19 not coded in 2026
(20, 2026, 19, 'E11.9', 'lab',
 '{"lab":"HbA1c","value":6.8,"unit":"%","date":"2026-01-22","threshold":6.5,"note":"HbA1c 6.8% at 2026 AWV exceeds ADA diagnostic threshold of 6.5% for Type 2 Diabetes. Patient was coded as prediabetes (R73.09) in 2025. HCC19 (E11.9 Type 2 DM without complications) coefficient is 0.118. Recommend physician review and reclassification from prediabetes to DM2.","prior_code":"R73.09","recommended_code":"E11.9"}',
 0.8200, 'open'),

-- ── Patient 22: Donna Adams — BNP 280 on routine labs; no CHF coded; on furosemide PRN
(22, 2026, 85, 'I50.9', 'lab',
 '{"lab":"BNP","value":280,"unit":"pg/mL","date":"2025-04-15","note":"BNP 280 pg/mL obtained during routine labs. While below the 400 threshold for likely decompensated CHF, it exceeds the diagnostic threshold of 100 pg/mL. Patient is not currently on furosemide but has a prior prescription (2024, discontinued). No CHF diagnosis in record. Recommend cardiology referral.","recommendation":"cardiology_referral"}',
 0.6800, 'open'),

-- ── Patient 23: Steven Nelson — eGFR borderline; no CKD3 coded in 2026 AWV
(23, 2026, 138, 'N18.3', 'lab',
 '{"lab":"eGFR","value":54,"unit":"mL/min/1.73m2","date":"2026-02-15","note":"eGFR 54 (CKD Stage 3a) documented at 2026 AWV but no CKD diagnosis included in billing. N18.3 was coded in 2025. This is a recapture gap. HCC138 coefficient is 0.069 — small but represents $238/year in foregone revenue.","prior_year_coded":true}',
 0.8900, 'open'),

-- ── Patient 26: Ruth Perez — Depression (F32.1) was coded in 2025 but NOT recaptured in 2026 AWV
(26, 2026, 59, 'F32.1', 'historical',
 '{"historical_code":"F32.1","coded_year":2025,"note":"F32.1 (Major Depression) coded in 2025 AWV and managed visit. Patient continues sertraline 50mg. The 2026 AWV (encounter 1077) does NOT include F32.1 in billing — this is an annual recapture failure. HCC59 (0.358) will be missed. Provider Dr. Park should include chronic depression in annual visit diagnoses.","sertraline_active":true,"recommended_action":"add_F32.1_to_encounter_1077"}',
 0.9000, 'accepted'),
-- ^^^ Status = accepted — show one that provider agreed to add

-- ── Patient 29: Larry Phillips — Patient on metformin; HbA1c 7.1%; consider upgrade to HCC18
(29, 2026, 18, 'E11.65', 'lab',
 '{"lab":"HbA1c","value":7.8,"unit":"%","date":"2026-03-10","note":"HbA1c 7.8% at 2026 AWV — trending up from 7.1% in 2025. If HbA1c reaches threshold or hyperglycemia is documented at visit, this patient would qualify for HCC18 (E11.65) instead of HCC19. Monitor closely — if insulin is initiated, confidence will increase to 0.85+.","current_hcc":19,"potential_upgrade_hcc":18,"revenue_delta":860.00}',
 0.6500, 'open'),

-- ── Patient 30: Betty Campbell — TSH 12 mIU/L; overt hypothyroidism potentially undercoded
(30, 2026, 0, 'E03.9', 'lab',
 '{"lab":"TSH","value":12.4,"unit":"mIU/L","date":"2025-06-01","threshold":10,"note":"TSH 12.4 mIU/L suggests overt hypothyroidism. Patient has E03.9 on problem list but levothyroxine dosing notes subtherapeutic TSH suppression. While E03.9 does not map to an HCC, this finding warrants clinical attention and may indicate autoimmune thyroiditis. No RAF impact but clinical quality flag.","clinical_flag_only":true}',
 0.7500, 'open');

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 15: RAF MEAT EVIDENCE
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM raf_meat_evidence WHERE patient_hcc_id IN (
  SELECT id FROM raf_patient_hcc WHERE patient_id BETWEEN 1 AND 30
);

-- Patient 1 HCC85 (CHF) — id=101 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(101, 1002, '2025-03-20',
 'BP 155/98 mmHg, weight 171 lbs (up 3 lbs from 168 lbs at last visit 1/15). Bilateral lower extremity pitting edema 2+ to the knees. Patient reports orthopnea requiring 3 pillows to sleep. JVD present at 45°.',
 'BNP 580 pg/mL (up from 310 pg/mL on 1/15/2025). Echo 2/2025: EF 28%, moderate mitral regurgitation, LV dilation. CXR today shows cardiomegaly with pulmonary vascular congestion. SpO2 93% on room air.',
 'Acute-on-chronic systolic heart failure (I50.22), NYHA Class III, volume overloaded. CHF exacerbation likely precipitated by dietary sodium indiscretion and missed furosemide doses.',
 'Increase furosemide 40mg BID to 80mg BID. Restrict dietary sodium to <2g/day. Add spironolactone 25mg daily for neurohormonal blockade. Repeat BMP in 5 days to monitor K+/Cr. Follow-up in 2 weeks or sooner if symptoms worsen. Patient educated on daily weight monitoring — call office if >2 lb gain in 24 hrs.',
 1, 1, 1, 1, 1.0000,
 'CC: Follow-up CHF — "I''ve been swelling more and can''t sleep flat." ASSESSMENT: Acute-on-chronic systolic CHF, NYHA III, volume overloaded. PLAN: Increase furosemide, add spironolactone, f/u 2 weeks.');

-- Patient 1 HCC137 (CKD4) — id=102 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(102, 1003, '2025-06-05',
 'Serum creatinine trending: 2.8 → 3.1 → 3.4 mg/dL over past 3 quarters. eGFR 22 mL/min/1.73m2. Blood pressure 142/88 on current regimen. No new uremic symptoms. Urine output adequate.',
 'BMP: Cr 3.4, BUN 48, K 5.1, HCO3 19. eGFR 22 mL/min (CKD4). 24-hr urine protein 1.8g. Renal ultrasound: bilateral atrophic kidneys, no hydronephrosis. Nephrology note reviewed — ESRD trajectory within 12-18 months at current rate.',
 'Chronic kidney disease Stage 4 (N18.4) secondary to diabetic nephropathy and hypertensive nephrosclerosis. Approaching Stage 5 — pre-dialysis education initiated.',
 'Continue ACE inhibitor (lisinopril 10mg). Dietary: protein 0.8g/kg/day, potassium restriction. Started phosphate binder (calcium carbonate with meals). Nephrology f/u in 6 weeks. Pre-dialysis AV fistula referral placed. Recheck BMP in 4 weeks.',
 1, 1, 1, 1, 1.0000,
 'CKD Stage 4 — eGFR 22. Pre-dialysis counseling initiated. Creatinine 3.4. Nephrology following. AV fistula referral placed.');

-- Patient 1 HCC18 (DM2) — id=103 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(103, 1003, '2025-06-05',
 'HbA1c trending: 9.8% (3/24) → 9.4% (9/24) → 9.1% (3/25). Daily home glucose logs reviewed — fasting glucose 180-240 mg/dL, post-prandial 260-320 mg/dL. Patient reports adherence to insulin but dietary noncompliance on weekends.',
 'HbA1c 9.1%. Fasting BG 218 mg/dL in office. Foot exam: diminished monofilament sensation bilateral, no wounds. Eye exam (ophthalmology 3/25): mild nonproliferative diabetic retinopathy.',
 'Type 2 diabetes mellitus with hyperglycemia (E11.65), inadequately controlled. Complications include peripheral neuropathy, early nephropathy, and nonproliferative retinopathy.',
 'Increase insulin glargine from 24 to 28 units at bedtime. Add liraglutide 0.6mg daily (cardiovascular benefit in CKD). Reinforce carbohydrate counting and portion control. Diabetes educator referral. Recheck HbA1c in 3 months.',
 1, 1, 1, 1, 1.0000,
 'DM2 w/ hyperglycemia — HbA1c 9.1%. Complications: neuropathy, nephropathy, NPDR. Plan: increase basal insulin, add GLP-1 agonist, diabetes educator referral.');

-- Patient 2 HCC111 (COPD) — id=201 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(201, 1006, '2025-01-20',
 'SpO2 88% on room air at rest, improving to 92% on 2L O2. Exercise tolerance: 50 feet before stopping due to dyspnea. Using rescue inhaler (albuterol) 4-5x/day over past week. No pedal edema.',
 'Spirometry: FEV1/FVC 0.58, FEV1 42% predicted (GOLD Grade 3 severe). CXR: hyperinflation, flattened diaphragms, no infiltrate. ABG: pH 7.36, pCO2 52, pO2 58.',
 'Chronic obstructive pulmonary disease with exacerbation (J44.1), GOLD Stage III/GOLD Group D. Currently in exacerbation triggered by recent URI.',
 'Start prednisone 40mg × 5 days taper. Azithromycin 250mg × 5 days for suspected bacterial trigger. Increase tiotropium to formulation change; add roflumilast 500mcg for severe COPD. Pulmonology referral for COPD disease management. Home O2 evaluation ordered. Avoid NSAIDS.',
 1, 1, 1, 1, 1.0000,
 'COPD Gold III exacerbation. FEV1/FVC 0.58. O2 sat 88% RA. Prednisone + azithromycin started. Pulmonology referral.');

-- Patient 2 HCC9 (Lung Cancer) — id=202 — PARTIAL MEAT (missing T treatment detail)
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(202, 1007, '2025-04-15',
 'Weight 141 lbs (down 4 lbs from last visit). Performance status ECOG 2. Fatigue moderate. No new hemoptysis.',
 'CT chest 4/10/2025: Right upper lobe mass stable at 3.2cm — no new nodules, no pleural effusion. CEA 4.8 (stable). PET scan deferred per patient preference.',
 'Non-small cell lung cancer (C34.90) Stage IIIA — stable on current surveillance protocol. No progression noted.',
 NULL, -- Treatment plan missing in note — MEAT gap!
 1, 1, 1, 0, 0.7500,
 'Oncology f/u — NSCLC IIIA. CT chest stable. CEA 4.8. Patient declined PET. Treatment continuation documented in oncology note — not captured in primary care encounter.');

-- Patient 2 HCC21 (Malnutrition) — id=203 — PARTIAL MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(203, 1008, '2025-08-12',
 'BMI 17.2 (down from 18.4 three months ago). Dietary intake estimated at 800-1000 kcal/day. Reports poor appetite, early satiety. Temporal wasting and muscle loss noted on exam.',
 'Albumin 2.8 g/dL (low). Pre-albumin 14 mg/dL (low). Total protein 5.9 g/dL. Weight 141 lbs.',
 'Moderate protein-calorie malnutrition (E44.0) in the context of advanced lung cancer and COPD. Multi-factorial: anorexia, increased metabolic demand, possible malabsorption.',
 NULL, -- Provider did not document treatment plan in this encounter
 1, 1, 1, 0, 0.7500,
 'Malnutrition — albumin 2.8, BMI 17.2. Weight loss 7% over 3 months. Nutritional supplementation discussed but plan not formally documented.');

-- Patient 3 HCC136 (ESRD) — id=301 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(301, 1010, '2025-01-10',
 'Receiving hemodialysis 3x/week at Fresenius center — sessions running 3.5 hours each. BP pre-dialysis 158/96. Weight pre-dialysis 199 lbs, post-dialysis 196 lbs (3L removed). Access: left brachiocephalic AVF, functioning well with thrill and bruit present.',
 'BMP post-dialysis: Cr 6.8, BUN 24 (post-dialysis), K 4.2, HCO3 22. Hgb 9.8, Hct 29. PTH 312 pg/mL (elevated). eGFR <10 mL/min. Dialysis adequacy Kt/V 1.42 (adequate).',
 'End stage renal disease (N18.6) on maintenance hemodialysis. Access functioning. Dialysis adequacy maintained. Secondary hyperparathyroidism — cinacalcet indicated.',
 'Continue HD 3x/week. Increase cinacalcet from 30mg to 60mg daily for PTH management. Sevelamer 800mg TID with meals continued. Epoetin alfa 10,000 units 3x/week maintained. Recheck PTH in 3 months. Restrict phosphorus <800mg/day dietary.',
 1, 1, 1, 1, 1.0000,
 'ESRD on HD — Kt/V 1.42. PTH elevated at 312. Starting cinacalcet 60mg. Sevelamer continued. Epoetin maintained.');

-- Patient 4 HCC52 (Dementia) — id=401 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(401, 1015, '2025-02-01',
 'MMSE 18/30 (baseline 22/30 six months ago). Notable decline in short-term memory — patient cannot recall 3 of 3 words at 5 minutes. Requires prompting for ADLs. Daughter reports increased confusion in evenings (sundowning). No new behavioral problems.',
 'MoCA 14/30. Clock drawing test abnormal — numbers crowded to right. Brain MRI 1/2025: generalized cortical atrophy, periventricular white matter changes, no new infarcts. Caregiver burden scale: daughter scoring HIGH.',
 'Unspecified dementia (F03.90) — moderate stage based on MMSE and MoCA scores. Functional decline from prior baseline. Likely mixed etiology (vascular + Alzheimer). Caregiver stress identified as secondary concern.',
 'Continue donepezil 10mg qHS. Add memantine 5mg BID, titrate to 10mg BID over 4 weeks. Refer caregiver to Alzheimer''s Association support group. Social work referral for respite care options. Safety: review driving status — referred to DMV for evaluation. Next geriatric assessment in 6 months.',
 1, 1, 1, 1, 1.0000,
 'Dementia moderate — MMSE 18/30, MoCA 14. Sundowning noted. Adding memantine. Caregiver burnout — SW referral. Driving evaluation ordered.');

-- Patient 4 HCC78 (Parkinson''s) — id=402 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(402, 1016, '2025-04-08',
 'Tremor worsening: bilateral pill-rolling tremor now extends to arms at rest. Rigidity 3/5 bilateral. Bradykinesia present. ON/OFF fluctuations reported 2-3 hours after Sinemet dose. Falls: 2 near-falls past month.',
 'UPDRS Part III motor score 34 (moderate impairment). Gait: shuffling with reduced arm swing. Postural instability on pull test. Neurologist note reviewed — no dementia overlap medication conflicts identified.',
 'Parkinson disease (G20.A1) — moderate severity. Motor fluctuations developing on current levodopa/carbidopa dosing. Fall risk HIGH. Concurrent dementia complicating medication management.',
 'Increase levodopa/carbidopa to 25/100 QID (add noon dose). Add entacapone 200mg with each levodopa dose to extend ON time. PT referral for gait training and fall prevention. OT for home safety modification. Neurology follow-up in 6 weeks. Caregiver education: assist with medications due to motor fluctuations.',
 1, 1, 1, 1, 1.0000,
 'Parkinson''s — UPDRS motor 34. ON/OFF fluctuations. Adding entacapone, PT/OT referrals. Fall risk HIGH.');

-- Patient 4 HCC59 (Depression) — id=403 — MISSING MEAT (the demo gap!)
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(403, 1017, '2025-07-14',
 NULL, -- No monitoring documented
 NULL, -- No evaluation documented
 'Caregiver notes patient seems withdrawn and tearful.', -- Only assessment — vague
 NULL, -- No treatment plan documented
 0, 0, 1, 0, 0.2500,
 'Visit note contains only: "Caregiver reports patient has been more withdrawn and crying at times. Patient nods when asked if feeling depressed. Sertraline 50mg added per last visit." No PHQ-9 administered, no formal assessment, no documented plan.');

-- Patient 5 HCC27 (Cirrhosis) — id=501 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(501, 1022, '2025-09-08',
 'Patient presents with increased confusion over 48 hours. Asterixis present bilaterally. No fever. Last bowel movement 3 days ago. Abdomen: tense with shifting dullness — moderate ascites. Scleral icterus present. BP 112/68.',
 'LFTs: AST 184, ALT 156, Alk Phos 312, Total Bilirubin 4.8. INR 2.8. Albumin 2.1 g/dL. Ammonia 98 mcmol/L (elevated). Abdominal US: echogenic liver, portal hypertension, moderate ascites. No SBP on diagnostic paracentesis.',
 'Hepatic encephalopathy — acute episode in setting of end-stage liver disease (K74.60) Child-Pugh Class B. Precipitant: constipation/GI bleeding trigger. Coagulopathy (D68.9) related to hepatic synthetic dysfunction.',
 'Increase lactulose to 45mL TID titrate to 3-4 soft stools/day. Add rifaximin 550mg BID for long-term HE prophylaxis. NPO → clear liquids. IV albumin 1.5g/kg day 1. Paracentesis 4L with albumin replacement. Hepatology consult today. Monitor mental status q4h. GI bleeding workup if mental status does not clear.',
 1, 1, 1, 1, 1.0000,
 'Hepatic encephalopathy — asterixis, ammonia 98, INR 2.8. Cirrhosis Child-Pugh B. Lactulose increase, rifaximin added, hepatology consult.');

-- Patient 6 HCC103 (Hemiplegia) — id=602 — COMPLETE MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(602, 1026, '2025-06-18',
 'Right-sided upper and lower extremity weakness — 3/5 grip strength right hand (up from 2/5 at last visit). Ambulating with quad cane 150 feet with moderate assistance. ADLs: requires assistance with dressing, bathing, meal prep. NIHSS 6 (moderate).',
 'Physical therapy progress note reviewed: gait speed 0.4 m/s (community threshold 0.8 m/s). FIM motor score 52/91. Brain MRI 5/2025: stable left MCA territory infarct, no new ischemic changes.',
 'Hemiplegia, right side (G81.90) — moderate severity, post-left MCA stroke September 2023. Functional improvement noted from rehabilitation but remains below community ambulation threshold. Aphasia resolved. Spasticity mild.',
 'Continue PT 3x/week outpatient. OT for adaptive equipment (modified utensils, dressing aids). Home PT evaluation for bathroom safety. Baclofen 5mg TID for mild spasticity. Neurology follow-up in 3 months. Continue aspirin 81mg and warfarin for secondary stroke prevention.',
 1, 1, 1, 1, 1.0000,
 'Post-stroke hemiplegia right side — improving. Grip 3/5. PT 3x/week. Baclofen added for spasticity. Neurology f/u 3 months.');

-- Patient 9 HCC138 (CKD3) — id=903 — MISSING MEAT (Rivera gap)
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(903, 1037, '2025-12-15',
 NULL,
 NULL,
 NULL,
 NULL,
 0, 0, 0, 0, 0.0000,
 'Annual wellness note contains only: "CKD3 — stable." No lab values referenced, no eGFR documented, no treatment plan, no monitoring parameters. Diagnosis appears in billing but lacks clinical documentation to support MEAT criteria.');

-- Patient 12 HCC138 (CKD3) — id=1201 — PARTIAL MEAT
INSERT INTO raf_meat_evidence (patient_hcc_id, encounter_id, encounter_date, meat_m, meat_e, meat_a, meat_t, meat_m_present, meat_e_present, meat_a_present, meat_t_present, completeness_score, raw_note_excerpt) VALUES
(1201, 1045, '2025-07-30',
 'Serum creatinine 1.48, eGFR 44 mL/min (down from 48 three months ago). BP 138/84 on lisinopril.',
 'BMP: Cr 1.48, BUN 22, K 4.6, eGFR 44. Urinalysis: trace protein. Renal ultrasound deferred.',
 'CKD Stage 3a (N18.3) — mild decline in function. Etiology: HTN. No diabetic nephropathy in this patient.',
 NULL,
 1, 1, 1, 0, 0.7500,
 'CKD Stage 3a — eGFR 44, creatinine 1.48. Trending down. No treatment plan documented at this visit.');

-- Provider scorecard snapshots — demonstrates Mitchell vs Park performance gap
DELETE FROM provider_scorecard_snapshots WHERE measurement_year = 2026;

INSERT INTO provider_scorecard_snapshots (provider_id, measurement_year, snapshot_date, total_patients, patients_with_scores, average_raf, hcc_capture_rate, recapture_rate, suspects_open, suspects_accepted, suspects_dismissed, revenue_opportunity, meat_completeness_avg, documentation_quality_score, percentile_rank) VALUES
-- Mitchell: 9 patients, high performer
(1, 2026, '2026-03-31', 9, 8, 1.7244, 0.8077, 0.8500, 2, 1, 0, 24560.00, 0.8800, 0.8600, 88.50),
-- Park: 9 patients, medium performer
(2, 2026, '2026-03-31', 9, 7, 1.3622, 0.5455, 0.6000, 7, 1, 1, 52340.00, 0.6200, 0.5800, 52.10),
-- Thompson: 7 patients, good with elderly
(3, 2026, '2026-03-31', 7, 6, 1.1443, 0.6364, 0.7000, 3, 0, 1, 31200.00, 0.7100, 0.6900, 64.30),
-- Rivera: 5 patients, specialist
(4, 2026, '2026-03-31', 5, 5, 1.3856, 0.7222, 0.6800, 2, 0, 0, 18700.00, 0.6500, 0.7000, 71.80);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 16: PROVIDER ALERTS (actionable inbox items)
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM provider_alerts WHERE provider_id BETWEEN 1 AND 4;

INSERT INTO provider_alerts (provider_id, alert_type, patient_id, hcc_code, title, message, status) VALUES
(1, 'recapture_due',       2,  '21',  'Recapture: Malnutrition HCC21', 'Patient Robert Williams: Protein-Calorie Malnutrition (HCC21, E44.0) captured in 2025 but not yet documented in 2026. Revenue at risk: $2,451.', 'active'),
(1, 'meat_incomplete',     2,  '9',   'MEAT Incomplete: Lung Cancer HCC9', 'Patient Robert Williams: HCC9 Lung Cancer MEAT documentation incomplete — Treatment plan (T) missing.', 'active'),
(1, 'suspect_condition',   8,  '22',  'Suspect: Obesity HCC22', 'Patient Patricia Anderson: Obesity HCC22 (E66.09, BMI 38.4) in vitals but NOT in 2026 billing. Gap: $1,340.', 'active'),
(2, 'suspect_condition',   7,  '137', 'Suspect: CKD Stage 4 Upgrade', 'Patient Gerald Thompson: eGFR 28 — below Stage 4 threshold. Current coding CKD3. Upgrade to HCC137 adds $756/yr.', 'active'),
(2, 'suspect_condition',   14, '137', 'Suspect: CKD Undercoded', 'Patient Karen Walker: eGFR 34, creatinine 2.1. Likely Stage 4 not Stage 3. Confirm staging.', 'active'),
(2, 'recapture_due',       26, '59',  'Recapture: Depression HCC59', 'Patient Ruth Perez: Depression F32.1 coded in 2025, on sertraline, NOT in 2026 billing. Revenue: $1,230.', 'active'),
(2, 'meat_incomplete',     5,  '18',  'MEAT Incomplete: DM2 HCC18', 'Patient William Brown: HCC18 DM2 MEAT incomplete at 2026 AWV. Add HbA1c and medication plan.', 'active'),
(2, 'suspect_condition',   17, '22',  'Suspect: Obesity Recapture Miss', 'Patient Daniel Young: BMI 36.4 in vitals, obesity NOT in 2026 billing. Recapture miss.', 'active'),
(3, 'suspect_condition',   4,  '59',  'Suspect: Depression Uncoded', 'Patient Dorothy Martinez: On sertraline, F32.1 NOT coded in 2026. PHQ-9 was 16. Revenue: $1,231.', 'active'),
(3, 'suspect_condition',   12, '52',  'Suspect: Dementia Recapture', 'Patient Nancy Lewis: Donepezil active, F03.90 coded 2025 NOT 2026. HCC52 gap: $1,383.', 'active'),
(3, 'suspect_condition',   10, '22',  'Suspect: Obesity Not Billed', 'Patient Barbara Jackson: BMI 37.1, E66.09 on problem list but not in 2026 billing. HCC22.', 'active'),
(4, 'meat_incomplete',     9,  '138', 'MEAT Incomplete: CKD3 HCC138', 'Patient Charles Wilson: CKD3 note says "stable" with no labs or plan. MEAT score: 0.00.', 'active'),
(4, 'meat_incomplete',     15, '100', 'MEAT Incomplete: Stroke HCC100', 'Patient Thomas Hall: Stroke MEAT partial — Assess and Treat lack specificity.', 'active'),
(4, 'suspect_condition',   23, NULL,  'AWV Due: CKD Recapture', 'Patient Steven Nelson: AWV due. CKD3 coded 2025 but recapture gap in 2026.', 'active');

-- SECTION 17: provider_hcc_performance table does not exist — skipped

-- ─────────────────────────────────────────────────────────────────────────────
-- CLOSE OUT
-- ─────────────────────────────────────────────────────────────────────────────

SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
-- DEMO SEED SUMMARY
-- =============================================================================
-- Patients:       30 (6 high-risk, 12 medium-risk, 12 low-risk)
-- Providers:      4  (Mitchell, Park, Thompson, Rivera)
-- Encounters:     ~125 (IDs 1001–1085)
-- Billing rows:   ~130 ICD-10 coded encounters
-- HCC records:    ~50 patient_hcc entries across 30 patients
-- RAF scores:     30 (one per patient, 2026 prospective)
-- Suspect conds:  16 open, 1 accepted, demonstrating AI detection
-- MEAT evidence:  15 detailed clinical documentation examples
-- Provider alerts: 14 actionable inbox items
-- Scorecard:       4 provider snapshots showing performance spread
-- Key story:
--   • Mitchell 80.8% HCC capture rate — top performer
--   • Park 54.6% capture rate — largest revenue opportunity ($52K)
--   • Patient 4 (Martinez): depression HCC59 missing — MEAT score 0.25
--   • Patient 12 (Lewis): donepezil prescribed, dementia NOT coded 2026
--   • Patient 7 (Thompson): eGFR 28 but coded as CKD3 — upgrade suspect
--   • Patient 9 (Wilson): CKD3 MEAT completeness 0.00 — audit risk
-- =============================================================================
