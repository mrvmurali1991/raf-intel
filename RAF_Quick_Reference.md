# RAF Data Sources Quick Reference

## Critical Submission Deadlines

| Deadline Type | Timeline | Impact |
|---|---|---|
| Initial submission | ~Sept 30 | First chance to submit diagnoses |
| Mid-year submission | ~Jan 31 | Correction window |
| Final/Claims-runout deadline | ~April 30 | **FINAL** - after this, diagnoses excluded from RAF |

**ACTION:** Missing final deadline = permanent loss of HCC payment

---

## Data Source Priority Matrix

| Source | Quality | Completeness | Accessibility | Use Case |
|--------|---------|--------------|---|---|
| **837P/837I Claims** | High | High | High | Primary billing source; must use |
| **EHR (Epic, Cerner)** | High | Medium | Medium | Captures conditions not billed; supplement claims |
| **Lab Results** | Very High | Medium | Medium-High | Validates specificity (eGFR, HbA1c, BNP) |
| **Pharmacy** | Medium | Medium | High | Medication-to-diagnosis inference (with caution) |
| **Medical Records** | Very High | High | Low | RADV audit defense |

---

## HCC Validation Checklist

Before submitting any diagnosis code for RAF:

- [ ] ICD-10-CM code exists in active code set on DOS
- [ ] Code at highest specificity (no unspecified when specific exists)
- [ ] Encounter has at least one eligible CPT/HCPCS code
- [ ] Face-to-face encounter on claim/record
- [ ] MEAT criteria documented (Monitor, Evaluate, Assess, or Treat)
- [ ] Code not hierarchically excluded by another higher-severity code
- [ ] POA indicator present (if inpatient claim)
- [ ] Not prior-year diagnosis (must be current year)
- [ ] Code maps to HCC (only ~9,700 of 72K ICD-10 codes eligible)

**If ANY item fails: Do not submit diagnosis for RAF**

---

## Common RAF Integration Failure Points

### Claims Integration
| Issue | Detection | Resolution |
|-------|-----------|-----------|
| Duplicate encounters (MAO-001) | Error code "98325" | De-duplicate before final submission |
| Beneficiary not enrolled DOS | MAO-002 report | Verify enrollment on exact DOS |
| Invalid CPT code | MAO-002 report | Validate CPT active on DOS |
| Diagnosis not HCC-eligible | No HCC assigned | Check code against CMS allowed list |
| Unspecified diagnosis code | MAO-002 rejection | Code to highest specificity |

### EHR Integration
| Issue | Detection | Resolution |
|-------|-----------|-----------|
| FHIR API authentication fails | OAuth error | Check credentials, scopes |
| Bulk export timeout | No response after 2 hours | Check file size, retry with date filter |
| HL7 message parsing failure | Segment validation error | Check segment delimiters (^~\&) |
| Missing encounter linkage | Null encounter reference | Ensure Condition.encounter populated |
| Diagnosis code not ICD-10 | Code validation error | Verify EHR exporting ICD-10 (not ICD-9) |

### Lab Integration
| Issue | Detection | Resolution |
|-------|-----------|-----------|
| LOINC code unknown | No mapping to HCC indicator | Update LOINC database, check code validity |
| Missing units in result | Cannot validate threshold | Request lab to include units |
| Lab date outside 12-month window | Date validation failure | Diagnose must be within calendar year of lab |

### Pharmacy Integration
| Issue | Detection | Resolution |
|-------|-----------|-----------|
| NDC code invalid | FDA NDC lookup fails | Verify NDC format (11 digits), check source |
| Duplicate fill detected | Near-duplicate flagged | Remove, retain original only |
| Quantity/days supply inconsistent | Validation error | Audit pharmacy data for data entry errors |

---

## EDPS vs. RAPS Key Differences

**RAPS (Retired CY 2022):**
- Summary diagnosis submission only
- Minimal claim detail
- CMS applied all filtering

**EDPS (Current):**
- Full encounter-level detail (like FFS claims)
- All CPT/HCPCS codes required
- All diagnoses submitted (unfiltered)
- CMS applies filtering post-submission
- **Must submit valid 837P/837I format**

---

## Data Quality Thresholds

**Acceptable Performance:**
- Claim acceptance rate: >92%
- Diagnosis code validity rate: >95%
- HCC capture rate within 5% of CMS average
- Timeliness: >95% by final deadline

**Red Flags (Audit Risk):**
- Acceptance rate <85% → systemic validation issues
- Unspecified diagnoses >15% → specificity problem
- HCC capture >20% above norm → over-coding risk
- High concentration of uncommon HCCs → RADV target

---

## Hierarchical Condition Categories (V28) Key Constraints

| Disease Class | Constrained HCCs | Shared Weight | Impact |
|---|---|---|---|
| Diabetes | 36, 37, 38 | 0.166 | All diabetes variants = same RAF |
| Heart Failure | 224, 225, 226 | 0.36 | Severity irrelevant to payment |
| Dementia | 125, 126, 127 | 0.341 | Type doesn't affect score |
| CKD | 136, 137, 138 | Varies | Stage 5 > Stage 4 > Unspecified |
| Cancer | 8-34 (various) | Varies | Specific cancer type matters |

**Implications:** Coding more severe HCC won't increase payment if constrained → focus on accuracy, not upcoding

---

## MEAT Documentation Shortcuts

### CKD Stage 4 (N18.4)
```
M: "Fatigue, decreased urine output"
E: "eGFR = 28" [from lab]
A: "CKD stage 4"
T: "Referred to nephrology"
```

### Type 2 Diabetes (E11.9)
```
M: "Polyuria, polydipsia"
E: "HbA1c = 9.2%" [from lab]
A: "Diabetes type 2, uncontrolled"
T: "Metformin increased to 2000mg daily"
```

### Heart Failure (I50.9)
```
M: "Dyspnea on exertion, edema"
E: "BNP = 450 pg/mL, EF = 35%"
A: "Heart failure, systolic"
T: "Started lisinopril and furosemide"
```

---

## 837P Diagnosis Code Field Reference

**HI Segment Format:**
```
HI*ABK:N18.4*ABF:E11.9*ABF:I10
   │      │      │      │      │
   │      │      │      │      └─ Diagnosis code (no decimal)
   │      │      │      └─ Additional diagnosis qualifier
   │      │      └─ Additional diagnosis code
   │      └─ Principal diagnosis code
   └─ Segment ID
```

**Maximum:** 12+ diagnosis codes per claim (HI segment can repeat)

**Validation:**
- No decimal points in code
- Codes separated by segment/field markers
- ABK (principal) should appear once
- ABF (additional) for up to 11 more

---

## CMS Filtering Logic Summary

```
Encounter meets criteria IF:
├─ Beneficiary enrolled on DOS
├─ Claim type acceptable (outpatient, inpatient, etc.)
└─ At least one CPT/HCPCS code in eligible list
    └─ IF TRUE: All diagnoses on encounter eligible
    └─ IF FALSE: No diagnoses eligible
```

**Eligible CPT Ranges:**
- E/M codes: 99201-99499
- Surgery: 10000-69999
- Pathology/Lab: 80000-89999
- Radiology: 70000-79999
- Preventive: 99381-99429
- Many others (check CMS list for updates)

---

## RADV Audit Timeline

| Phase | Timeline | Action |
|---|---|---|
| Selection | Spring-Summer | CMS selects high-risk beneficiaries |
| Notification | July-Aug | Health plan receives audit notice |
| Record Gathering | Aug-Sept | Health plan retrieves medical records (25 weeks allowed) |
| Submission | Sept-Oct | Submit records to CMS |
| CMS Review | Oct-Dec | CMS reviews and finds improper payments |
| Appeals | Jan-Feb | Health plan can appeal findings |
| Recovery | Mar-Apr | CMS recovers overpayment |

**Critical:** Worst-case recovery can be months of accumulated overpayment + interest

---

## Red Flag Diagnoses (High RADV Audit Risk)

| Diagnosis | Issue | How to Support |
|---|---|---|
| CKD Stage 4 (N18.4) | No lab values | MUST have eGFR 30-44 |
| Diabetes unspecified (E11.9) | No HbA1c | Need recent HbA1c or glucose trend |
| Heart failure unspecified (I50.9) | No EF/BNP | Need echo with EF or BNP result |
| Anemia (D50.9 or D63.1) | No hemoglobin | Must show Hgb <12 |
| Pulmonary HTN | No right heart cath | Need imaging evidence |
| Cancer (site-specific) | No diagnosis date | Document date of diagnosis |

---

## Code Specificity Requirements by Example

| DON'T Code | DO Code | Reason |
|---|---|---|
| E11.9 (Type 2 DM, unspecified) | E11.22 (Type 2 DM with CKD) | When CKD present, specify |
| N18.9 (CKD, unspecified) | N18.4 (CKD Stage 4) | When eGFR available, specify stage |
| I50.9 (HF, unspecified) | I50.22 (Systolic HF, with reduced EF) | When EF known, specify |
| I10 (Hypertension, unspecified) | I11.9 (Hypertensive chronic kidney disease) | When kidney disease present |
| M79.1 (Myalgia, unspecified) | M79.11 (Myalgia, right leg) | When laterality known, specify |

---

## EHR Query Cheat Sheet

### OpenEMR FHIR
```
GET /fhir/r4/Condition?patient=PT-123&clinical-status=active
Response: Condition resources with ICD-10 codes
```

### Epic HL7 ADT
```
Inbound ADT^A01 message → Extract DG1 segments → Parse diagnosis codes
```

### Cerner FHIR
```
GET /fhir/r4/Condition?patient=PT-456&onset-date=ge2025-01-01
Response: Condition resources with active diagnoses in 2025
```

### Athenahealth Bulk Export
```
POST /export → Wait for NDJSON files → Parse Condition resources
Preferred for large-scale batch operations
```

---

## RAF Score Calculation Quick Math

```
RAF = Demographic Base + Σ(HCC Weights) + Interactions

Example:
74-year-old male, non-Medicaid

Demographic Base:          1.029  ← Age/gender factor
  + HCC137 (CKD Stg 4):   +0.327  ← Each HCC adds to score
  + HCC38 (Diabetes):     +0.166  ← Constrained weight in V28
  + HCC227 (HTN):         +0.075  ← Smaller HCCs lower impact
  + Interaction:          +0.032  ← Multi-morbidity bonus
────────────────────────────────
  Total RAF:              1.629

Payment = 1.629 × CMS Base Rate (~$10,402)
        = ~$16,945 annual capitation
```

---

## Data Retention Requirements

| Data Type | Minimum Retention | Reason |
|---|---|---|
| Claims/837 files | 10 years | Medicare audit requirements |
| Medical records (RADV-related) | 6 years | RADV cycle + buffer |
| EHR diagnosis extracts | 6 years | Supporting audit defense |
| Pharmacy claims | 10 years | CMS audit |
| RAF calculation audit trail | 7 years | Payment integrity |
| Submission records (MAO-002/004) | 7 years | Proof of submission |

---

## Go-Live Checklist

- [ ] Claim parsing working (837P/837I)
- [ ] EHR integration tested (FHIR or HL7 working)
- [ ] Diagnosis code validation functional
- [ ] HCC mapping integrated
- [ ] Duplicate detection implemented
- [ ] CMS filtering logic replicated
- [ ] EDI generation tested
- [ ] SFTP submission working
- [ ] MAO-002/004 parsing working
- [ ] Error handling/retry logic in place
- [ ] Monitoring/alerting configured
- [ ] RADV audit trail logging enabled
- [ ] Data governance policies signed
- [ ] Performance baseline established

---

## Key Contacts & Resources

**CMS:**
- Risk Adjustment: https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment
- RADV Program: https://www.cms.gov/data-research/monitoring-programs/medicare-risk-adjustment-data-validation-program
- DIY Software: https://www.cms.gov/files/document/cy2023-diy-instructions-08222023.pdf

**Standards:**
- FHIR: https://www.hl7.org/fhir/
- HL7 V2: https://www.hl7.org/standards/
- X12 837: ASC X12N/005010X222A1

**Industry Resources:**
- HCC Coding: https://www.hccinstitute.org/
- AAFP HCC Guide: https://www.aafp.org/
- NCQA HEDIS: https://www.ncqa.org/hedis/

---

**Last Updated:** April 2026  
**Version:** 1.0  
**Keep Handy:** Use during development, integration testing, and go-live
