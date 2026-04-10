# RAF_Patient_Import_Template.xlsx — Contract

This document is the fixed contract for the RAF Intelligence patient import
workbook. The importer and the template generator MUST agree on these names
and enum values. Do not rename or reorder columns.

File path (shipped with backend): `backend/app/data/RAF_Patient_Import_Template.xlsx`

Workbook builder: `/tmp/build_raf_template.py` (local, not committed).

## Sheets (exact names, in order)

1. `Patients`
2. `HCC_Conditions`
3. `MEAT_Evidence`
4. `Suspect_Conditions`
5. `Reference_Codes`
6. `Instructions`

MRN is the stable join key across sheets 1–4.

---

## Sheet 1 — `Patients` (10 data rows)

Column order:

1. `mrn` (string, unique, required) — e.g. `MRN-2001`
2. `first_name` (string, required)
3. `middle_name` (string, optional)
4. `last_name` (string, required)
5. `dob` (ISO date `YYYY-MM-DD`, required)
6. `sex` (enum, required) — `Male` | `Female`
7. `birth_sex` (enum) — `Male` | `Female`
8. `gender_identity` (USCDI code) — `identifies-as-male` | `identifies-as-female` | `transgender-male` | `transgender-female` | `non-binary` | `other` | `not-disclosed`
9. `pronouns` — `he/him` | `she/her` | `they/them`
10. `race` (USCDI code) — `2106-3` | `2054-5` | `2028-9` | `1002-5` | `2076-8`
11. `ethnicity` (USCDI code) — `2135-2` | `2186-5`
12. `preferred_language` — `en` | `es` | `zh` | `fr` | `vi` | `ko` | `ar`
13. `phone` (string)
14. `email` (string)
15. `address` (string)
16. `city` (string)
17. `state` (2-letter US state)
18. `zip` (string)
19. `ssn` (string, masked)
20. `mbi` (string, optional) — format `XAXX-XXX-XXXX`
21. `insurance_type` (enum) — `Medicare` | `Medicare Advantage` | `Medicaid` | `Commercial`
22. `emergency_contact_name` (string)
23. `emergency_contact_phone` (string)
24. `pcp_provider` (string)
25. `measurement_year` (int) — `2026` for this template

Row count: **10**

---

## Sheet 2 — `HCC_Conditions` (51 data rows)

Column order:

1. `mrn` (FK → Patients.mrn, required)
2. `measurement_year` (int, required) — `2026`
3. `hcc_code` (int, required) — CMS-HCC V28 code
4. `icd10_code` (string, required)
5. `diagnosis_description` (string)
6. `raf_coefficient` (decimal, required) — V28 community coefficient, 0.10–0.50 range
7. `meat_status` (enum, required) — `complete` | `partial` | `missing`

HCC codes used in this template and their RAF coefficients:

| HCC | ICD-10 | Description | RAF |
|-----|--------|-------------|-----|
| 17  | E11.22  | Diabetes with chronic kidney disease | 0.302 |
| 18  | E11.65  | Diabetes with chronic complications | 0.302 |
| 19  | E11.9   | Diabetes without complications | 0.105 |
| 22  | E66.01  | Morbid obesity (BMI >= 40) | 0.250 |
| 23  | E03.9   | Other significant endocrine/metabolic | 0.223 |
| 51  | F03.90  | Dementia without behavioral disturbance | 0.346 |
| 52  | F03.91  | Dementia with behavioral disturbance | 0.478 |
| 59  | F33.1   | Major depressive disorder, recurrent | 0.309 |
| 85  | I50.32  | Heart failure | 0.331 |
| 96  | I48.91  | Specified heart arrhythmias (AFib) | 0.268 |
| 108 | I70.231 | Atherosclerosis w/ complication | 0.379 |
| 111 | J44.9   | COPD | 0.335 |
| 136 | N18.4   | CKD stage 4 | 0.289 |
| 137 | N18.5   | CKD stage 5 | 0.421 |
| 138 | I73.9   | Vascular disease | 0.288 |
| 221 | G47.33  | Obstructive sleep apnea | 0.196 |

Row count: **51**

---

## Sheet 3 — `MEAT_Evidence` (50 data rows)

One row per (patient, HCC) pair where the HCC's `meat_status` is
`complete` or `partial` (missing MEAT = no row).

Column order:

1. `mrn` (FK → Patients.mrn, required)
2. `hcc_code` (int, FK → HCC_Conditions.hcc_code, required)
3. `encounter_date` (ISO date `YYYY-MM-DD`, required)
4. `meat_m` (string) — Monitor
5. `meat_e` (string) — Evaluate
6. `meat_a` (string) — Assess
7. `meat_t` (string) — Treat (blank when `meat_status = partial`)
8. `raw_note_excerpt` (string) — 2–3 sentence progress note excerpt

Row count: **50**

---

## Sheet 4 — `Suspect_Conditions` (15 data rows)

Column order:

1. `mrn` (FK → Patients.mrn, required)
2. `measurement_year` (int, required) — `2026`
3. `suspect_hcc` (int, required) — CMS-HCC V28 code
4. `suspect_icd10` (string, required)
5. `evidence_type` (enum, required) — `medication` | `lab` | `imaging` | `referral` | `historical`
6. `evidence_detail` (string)
7. `confidence_score` (decimal 0.0000–1.0000)
8. `rationale` (string)

Row count: **15**

---

## Sheet 5 — `Reference_Codes` (40 data rows)

Column order: `Field`, `Code`, `Description`.

Fields covered: `race`, `ethnicity`, `sex`, `birth_sex`, `gender_identity`,
`pronouns`, `preferred_language`, `insurance_type`, `meat_status`,
`evidence_type`.

Row count: **40**

---

## Sheet 6 — `Instructions`

Human-facing onboarding guide. Not consumed by the importer.

---

## Enum reference (authoritative)

| Field | Values |
|-------|--------|
| `sex`, `birth_sex` | `Male`, `Female` |
| `gender_identity` | `identifies-as-male`, `identifies-as-female`, `transgender-male`, `transgender-female`, `non-binary`, `other`, `not-disclosed` |
| `pronouns` | `he/him`, `she/her`, `they/them` |
| `race` | `2106-3`, `2054-5`, `2028-9`, `1002-5`, `2076-8` |
| `ethnicity` | `2135-2`, `2186-5` |
| `preferred_language` | `en`, `es`, `zh`, `fr`, `vi`, `ko`, `ar` |
| `insurance_type` | `Medicare`, `Medicare Advantage`, `Medicaid`, `Commercial` |
| `meat_status` | `complete`, `partial`, `missing` |
| `evidence_type` | `medication`, `lab`, `imaging`, `referral`, `historical` |

## Cohort RAF totals (HCC contribution only)

| MRN | Name | HCC Total RAF |
|-----|------|---------------|
| MRN-2001 | Margaret Williams | 1.478 |
| MRN-2002 | Carlos Rivera | 1.234 |
| MRN-2003 | Dorothy Chen | 1.028 |
| MRN-2004 | James Patterson | 1.388 |
| MRN-2005 | Priya Sharma | 0.860 |
| MRN-2006 | William Jackson | 2.236 |
| MRN-2007 | Elena Vasquez | 1.499 |
| MRN-2008 | Raymond Nguyen | 1.524 |
| MRN-2009 | Susan O'Brien | 0.860 |
| MRN-2010 | Harold Washington | 2.802 |

Range: **0.86 – 2.80** (HCC coefficients only; demographic factors add ~0.3–0.5 on top at runtime).
