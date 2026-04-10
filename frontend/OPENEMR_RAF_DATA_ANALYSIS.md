# OpenEMR Data Sources for RAF/HCC Scoring - Deep Analysis

**Date:** 2026-03-30
**Database:** 320 tables total in OpenEMR instance

---

## Executive Summary

Our current `openemr_connector.py` uses **8 tables**: `patient_data`, `form_encounter`, `billing`, `prescriptions`, `form_vitals`, `form_soap`, `form_clinical_notes`, `insurance_data` (+ joins to `users`, `forms`, `procedure_result`, `procedure_order`, `insurance_companies`).

There are **7 additional table groups** with untapped RAF/HCC-relevant data that could significantly improve scoring accuracy, suspect condition identification, and HEDIS compliance.

---

## Part 1: Currently Used Tables

### 1. `patient_data` - USED
- **Rows:** ~4,000+ patients
- **What we extract:** pid, name, DOB, sex, race, ethnicity, address, phone, email, providerID
- **RAF relevance:** Demographics drive age/sex coefficients. Race/ethnicity used for community score adjustments.
- **Gap:** We do NOT extract `language`, `status` (marital), `financial_review`, `deceased_date`, `deceased_reason` - these could flag institutional status or identify deceased members still in panels.

### 2. `form_encounter` - USED
- **Rows:** 46,546
- **What we extract:** encounter_id, pid, date, reason, facility, provider_id, billing_note, onset_date
- **RAF relevance:** Encounter dates determine recapture windows. Reason text feeds NLP for suspect conditions.
- **Gap:** We do NOT use `discharge_disposition`, `class_code`, `encounter_type_code`, `pos_code` (place of service). These are critical:
  - `discharge_disposition` can identify SNF/institutional status (affects RAF coefficients)
  - `pos_code` distinguishes inpatient vs outpatient (affects HCC hierarchy)
  - `class_code` identifies emergency visits (relevant for acuity)

### 3. `billing` - USED
- **Rows:** 2,446
- **What we extract:** ICD-10, ICD-9, SNOMED codes with dates, provider, fee
- **RAF relevance:** Primary source of HCC-mappable diagnosis codes.
- **Gap:** We filter to `code_type IN ('ICD10', 'ICD9', 'SNOMED')` but do NOT use CPT4 codes. CPT codes can:
  - Validate encounter type (AWV codes G0438/G0439 confirm annual wellness visits)
  - Identify procedures that support diagnoses (e.g., dialysis CPTs support ESRD HCC)
  - Track preventive services for HEDIS
  - `justify` column links CPT to ICD codes (diagnosis-procedure linkage)

### 4. `prescriptions` - USED
- **Rows:** 178,694
- **What we extract:** drug name, dosage, rxnorm_drugcode, route, active status, notes
- **RAF relevance:** Medication-to-condition inference (e.g., insulin -> diabetes, metoprolol -> CHF/HTN).
- **Gap:** We do NOT use `diagnosis` column (links Rx to diagnosis directly), `indication`, `usage_category`, `end_date` (to determine if still active). The `diagnosis` field could directly map medications to HCC conditions.

### 5. `form_vitals` - USED
- **Rows:** 8 (very sparse)
- **What we extract:** BP, weight, height, BMI, pulse, respiration, O2 sat, temperature
- **RAF relevance:** BMI supports obesity HCCs (HCC 48). BP supports hypertension. O2 sat supports respiratory HCCs.
- **Gap:** Minimal data currently populated. The clinical notes contain embedded vitals (e.g., "BP-Sitting Sys/Dia: 132/64") that are far richer than the structured vitals table.

### 6. `form_soap` - USED
- **Rows:** 0 (empty)
- **What we extract:** Subjective, Objective, Assessment, Plan text
- **RAF relevance:** NLP analysis of clinical text for suspect conditions.
- **Status:** No SOAP notes exist; all clinical documentation is in `form_clinical_notes`.

### 7. `form_clinical_notes` - USED
- **Rows:** 96
- **What we extract:** description, codetext, clinical_notes_type
- **RAF relevance:** PRIMARY source of clinical documentation. These are extremely rich Annual Wellness Visit notes containing:
  - Complete problem lists with ICD codes
  - Lab values (HbA1c, LDL, eGFR, Hemoglobin) embedded in text
  - HEDIS compliance data (screening dates, vaccination status)
  - Functional assessments, depression screening (GDS scores)
  - Medication adherence (PDC measures)
  - SDOH data (transportation, housing, social support)
- **Gap:** We pass this text to Gemini for NLP but do NOT do structured extraction of the embedded lab values, screening dates, or HEDIS measures. Parsing these systematically could yield far more suspect conditions.

### 8. `insurance_data` + `insurance_companies` - USED
- **Rows:** 12,200
- **What we extract:** Plan name, group name, company name for dual-eligibility and OREC derivation
- **RAF relevance:** Dual status affects RAF coefficients significantly (+60-159% for full dual).
- **Gap:** `policy_type`, `copay`, `date`/`date_end` fields not used. Policy type could better classify Medicare Advantage vs FFS. Date ranges identify coverage gaps.

---

## Part 2: NOT Currently Used - High Priority

### 9. `lists` (medical_problem subtype) - NOT USED
- **Rows:** 990,615 total (includes medical_problem + allergy types)
- **Columns:** title, diagnosis (ICD code), begdate, enddate, activity, verification, severity, outcome, comments
- **RAF Value: CRITICAL - HIGH PRIORITY**
- This is the **problem list** - a persistent record of all conditions across encounters. Unlike `billing` (which only captures what was billed per visit), `lists` contains the complete longitudinal problem list.
- **Key fields:**
  - `diagnosis`: Contains ICD-10 codes (e.g., "ICD10:H18.603") - directly HCC-mappable
  - `begdate`/`enddate`: Tracks condition duration - identifies chronic conditions needing annual recapture
  - `activity`: Active vs resolved conditions
  - `verification`: "confirmed" vs unconfirmed - quality filter for RAF submissions
  - `outcome`: Tracks condition resolution
- **Use cases:**
  1. **Recapture gap analysis**: Active problems not billed in current year = recapture opportunities
  2. **Suspect condition validation**: Cross-reference NLP suspects against known problem list
  3. **Historical HCC tracking**: Problems with `enddate` null = chronic conditions needing annual coding
- **Sample query:**
```sql
-- Find active problems with HCC-mappable ICD codes not billed this year
SELECT l.pid, l.title, l.diagnosis, l.begdate, l.verification
FROM lists l
WHERE l.type = 'medical_problem'
  AND l.activity = 1
  AND l.diagnosis LIKE 'ICD10:%'
  AND l.pid NOT IN (
    SELECT b.pid FROM billing b
    WHERE b.code = REPLACE(l.diagnosis, 'ICD10:', '')
      AND b.date >= '2026-01-01'
      AND b.activity = 1
  )
ORDER BY l.pid;
```

### 10. `issue_encounter` - NOT USED
- **Rows:** 1 (newly started)
- **Columns:** pid, list_id, encounter, resolved
- **RAF Value: MEDIUM**
- Links problem list items (`lists`) to specific encounters. Essential for determining WHICH encounter addressed WHICH condition - needed for recapture tracking and ensuring each HCC is tied to a valid face-to-face encounter.

### 11. `history_data` - NOT USED
- **Rows:** 28
- **Columns:** Family history (mother/father/siblings conditions), surgical history, social history (tobacco, alcohol, drugs), screening dates
- **RAF Value: MEDIUM**
- **Use cases:**
  - `relatives_diabetes`, `relatives_heart_problems`, `relatives_cancer` etc. = risk stratification for suspect conditions
  - `tobacco`, `alcohol` = substance use HCCs (HCC 55/56)
  - Surgical history fields (`heart_surgery`, `hip_replacement`, `knee_replacement`) = historical procedure validation
  - Screening dates (`last_mammogram`, `last_colonoscopy`, `last_retinal`) = HEDIS gap tracking
- **Sample query:**
```sql
SELECT pid, tobacco, alcohol, recreational_drugs,
       relatives_diabetes, relatives_heart_problems, relatives_stroke,
       last_retinal, last_ldl, last_hemoglobin
FROM history_data
WHERE pid > 0;
```

### 12. `immunizations` - NOT USED
- **Rows:** 2,122
- **Columns:** patient_id, administered_date, cvx_code, manufacturer, lot_number, route
- **RAF Value: LOW for RAF, HIGH for HEDIS/Stars**
- Not directly HCC-relevant but critical for HEDIS measures:
  - Flu vaccination rates (Medicare Stars)
  - Pneumonia vaccination (PCV20/PPV23)
  - COVID-19 vaccination tracking
- **Sample query:**
```sql
SELECT patient_id, administered_date, cvx_code, manufacturer, note
FROM immunizations
WHERE administered_date >= '2025-01-01'
ORDER BY patient_id, administered_date;
```

---

## Part 3: NOT Currently Used - Medium Priority

### 13. `form_history_sdoh` - NOT USED
- **Rows:** Unknown (table exists, likely sparse)
- **Columns:** food_insecurity, housing_instability, transportation_insecurity, financial_strain, social_isolation, employment_status, disability_status, etc.
- **RAF Value: MEDIUM (growing importance)**
- CMS is increasingly incorporating SDOH Z-codes into risk adjustment. These map to ICD-10 Z55-Z65 codes:
  - Food insecurity -> Z59.48
  - Housing instability -> Z59.819
  - Transportation -> Z59.82
- Also affects Stars ratings and quality measures.

### 14. `form_observation` - NOT USED
- **Rows:** 0 currently
- **Columns:** code, observation, ob_value, ob_unit, ob_type, ob_status
- **RAF Value: MEDIUM (when populated)**
- Structured clinical observations (PHQ-9 depression scores, fall risk assessments, etc.)
- Could validate mental health HCCs and functional status

### 15. `form_functional_cognitive_status` - NOT USED
- **Rows:** 0 currently
- **Columns:** code, codetext, description
- **RAF Value: MEDIUM (when populated)**
- Functional limitations map to HCC 161 (Chronic Ulcers) indirectly and support institutional status determination

### 16. `form_care_plan` - NOT USED
- **Rows:** 0 currently
- **Columns:** code, codetext, description, care_plan_type, plan_status
- **RAF Value: LOW-MEDIUM**
- Active care plans can validate chronic condition management and support HEDIS care plan measures

### 17. `transactions` + `lbt_data` - NOT USED
- **Rows:** 13 transactions, 98 lbt_data
- **Content:** Calling notes (appointment scheduling, reminders)
- **RAF Value: LOW for scoring, MEDIUM for operations**
- Outreach tracking for recapture visit scheduling

### 18. `documents` - NOT USED
- **Rows:** 509
- **RAF Value: MEDIUM-HIGH (if contains scanned records, lab reports, referral letters)**
- Could contain uploaded lab results, specialist referral notes, or scanned documents with additional diagnosis information
- Would require document/OCR processing pipeline

---

## Part 4: Untapped Data WITHIN Currently Used Tables

### A. CPT Codes in `billing` (Currently Filtered Out)
We only pull ICD codes but CPT4 codes exist:
```sql
SELECT code, code_text, COUNT(*) as cnt
FROM billing
WHERE code_type = 'CPT4' AND activity = 1
GROUP BY code, code_text
ORDER BY cnt DESC LIMIT 20;
```
**Value:** Validates encounter types, supports procedure-based HCC evidence, tracks AWV completion.

### B. `form_encounter` Additional Fields
```sql
SELECT discharge_disposition, pos_code, class_code, encounter_type_code,
       COUNT(*) as cnt
FROM form_encounter
WHERE discharge_disposition IS NOT NULL OR pos_code IS NOT NULL
GROUP BY discharge_disposition, pos_code, class_code, encounter_type_code;
```
**Value:** `discharge_disposition` = institutional flag. `pos_code` = place of service for claim validation.

### C. `prescriptions.diagnosis` Field
```sql
SELECT drug, diagnosis, COUNT(*) as cnt
FROM prescriptions
WHERE diagnosis IS NOT NULL AND diagnosis != ''
GROUP BY drug, diagnosis
ORDER BY cnt DESC LIMIT 20;
```
**Value:** Direct drug-to-diagnosis mapping without needing inference.

---

## Part 5: Clinical Notes as a Goldmine

The `form_clinical_notes.description` field contains structured AWV documentation that embeds:

| Data Element | Example | RAF/HEDIS Use |
|---|---|---|
| HbA1c values | "HbA1C: 7.8 %" | Diabetes HCC severity, HEDIS CDC |
| LDL values | "LDL: 121 mg/dl" | Cardiovascular HCC support, HEDIS |
| eGFR values | "eGFR: 61 ml/min" | CKD staging -> HCC 138/139 |
| Hemoglobin | "Hgb: 10.6 g/dL" | Anemia HCC support |
| BMI | "BMI: 29.7" | Obesity HCC 48 |
| BP readings | "132/64 mm/Hg" | Hypertension control, HEDIS CBP |
| GDS score | "2/15 GDS" | Depression screening, HEDIS |
| CDT score | "5/5 CDT" | Cognitive assessment |
| PHQ-9/GAD-7 | Within screening section | Mental health HCCs |
| Vaccination dates | "Flu Vaccine - 10/16/24" | HEDIS immunization measures |
| Fall risk | "Risk for Falls - Low" | HCC functional status |
| Medication adherence PDC | "Med.Adherence Diabetes (PDC) - Yes" | Stars D-measures |
| Colonoscopy dates | In preventive section | HEDIS COL measure |
| Retinal exam dates | "Retinal eye exam - Yes" | HEDIS EED measure |
| Mammogram dates | In female section | HEDIS BCS measure |
| Bone density | "Bone Density Test - Yes" | Osteoporosis HCC |
| Filament test | "Sensation in Foot by Filament Test" | Diabetic neuropathy HCC |

**Recommendation:** Build a structured parser for clinical notes that extracts these values into a normalized format, rather than relying solely on LLM analysis.

---

## Priority Ranking for Integration

| Priority | Table/Feature | Effort | Impact | Description |
|---|---|---|---|---|
| **P0** | `lists` (problem list) | Low | Very High | 990K rows of diagnoses with ICD codes. Immediate recapture gap detection. |
| **P0** | CPT codes from `billing` | Trivial | High | Just remove the code_type filter. AWV tracking, procedure validation. |
| **P1** | `form_encounter` extra fields | Low | High | discharge_disposition, pos_code for institutional/POS determination. |
| **P1** | `prescriptions.diagnosis` | Trivial | Medium | Direct Rx-to-ICD mapping. |
| **P1** | Clinical notes structured parser | Medium | Very High | Extract lab values, screening dates, HEDIS data from note text. |
| **P2** | `history_data` | Low | Medium | Family history for risk stratification, surgical history, screening dates. |
| **P2** | `immunizations` | Low | Medium | HEDIS/Stars vaccination measures. |
| **P2** | `issue_encounter` | Low | Medium | Problem-to-encounter linkage for recapture validation. |
| **P3** | `form_history_sdoh` | Low | Low-Medium | SDOH Z-codes, growing CMS importance. |
| **P3** | `documents` | High | Medium | Would require OCR/document processing pipeline. |
| **P3** | `form_observation` | Low | Low | Currently empty; future value when populated. |

---

## Recommended New Connector Functions

```python
# P0: Problem list extraction
def get_problem_list(pid: int) -> list[dict]:
    """Return active medical problems with ICD codes from lists table."""
    sql = """
        SELECT id, title, diagnosis, begdate, enddate, activity,
               verification, outcome, comments, modifydate
        FROM lists
        WHERE pid = %s AND type = 'medical_problem'
        ORDER BY begdate DESC
    """

# P0: Recapture gap detection
def get_recapture_gaps(pid: int, year: int = 2026) -> list[dict]:
    """Find active problems not billed in the current year."""
    sql = """
        SELECT l.title, l.diagnosis,
               MAX(b.date) as last_billed
        FROM lists l
        LEFT JOIN billing b ON b.pid = l.pid
            AND b.code = REPLACE(REPLACE(l.diagnosis, 'ICD10:', ''), 'ICD9:', '')
            AND b.activity = 1
            AND YEAR(b.date) = %s
        WHERE l.pid = %s
          AND l.type = 'medical_problem'
          AND l.activity = 1
          AND l.diagnosis LIKE 'ICD10:%%'
        GROUP BY l.id
        HAVING last_billed IS NULL
    """

# P0: CPT code extraction
def get_cpt_codes(pid: int) -> list[dict]:
    """Return CPT billing codes for encounter type validation."""
    sql = """
        SELECT code, code_text, date, encounter, fee
        FROM billing
        WHERE pid = %s AND code_type = 'CPT4' AND activity = 1
        ORDER BY date DESC
    """

# P1: Encounter details with POS/disposition
def get_encounter_details(encounter_id: int) -> dict:
    """Return encounter with discharge disposition and POS code."""
    sql = """
        SELECT encounter, pid, date, reason, discharge_disposition,
               pos_code, class_code, encounter_type_code
        FROM form_encounter
        WHERE encounter = %s
    """

# P2: Allergies
def get_allergies(pid: int) -> list[dict]:
    """Return allergies - relevant for drug interaction HCC analysis."""
    sql = """
        SELECT title, diagnosis, reaction, severity_al, begdate
        FROM lists
        WHERE pid = %s AND type = 'allergy' AND activity = 1
    """

# P2: Immunizations for HEDIS
def get_immunizations(pid: int) -> list[dict]:
    """Return immunization history for HEDIS measure tracking."""
    sql = """
        SELECT administered_date, cvx_code, manufacturer, note
        FROM immunizations
        WHERE patient_id = %s
        ORDER BY administered_date DESC
    """

# P2: Family/social history
def get_history(pid: int) -> dict:
    """Return social and family history for risk stratification."""
    sql = """
        SELECT tobacco, alcohol, recreational_drugs,
               relatives_diabetes, relatives_heart_problems,
               relatives_stroke, relatives_cancer,
               last_retinal, last_ldl, last_hemoglobin,
               last_mammogram, last_sigmoidoscopy_colonoscopy
        FROM history_data
        WHERE pid = %s
        ORDER BY date DESC LIMIT 1
    """
```

---

## Key Findings Summary

1. **`lists` table is the single biggest missed opportunity** - 990K rows of diagnosed conditions with ICD codes that we completely ignore. This is the problem list, distinct from billing, and contains the longitudinal view of all patient conditions.

2. **CPT codes are trivially available** but filtered out. Adding CPT extraction requires a one-line change.

3. **Clinical notes contain structured lab/HEDIS data** embedded in text that we send to Gemini but do not systematically parse. A regex-based extractor for HbA1c, LDL, eGFR, BP, GDS, and screening dates would dramatically improve HEDIS gap detection.

4. **`form_encounter` discharge_disposition and pos_code** are needed for institutional status determination (currently hardcoded to `False`).

5. **The `prescriptions.diagnosis` field** provides direct medication-to-condition mapping that we currently infer indirectly.

6. **SDOH data** exists in a dedicated table (`form_history_sdoh`) and is increasingly relevant as CMS expands Z-code risk adjustment.
