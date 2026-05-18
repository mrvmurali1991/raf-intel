# HEDIS NCQA Spec Self-Validation

**Status:** Self-validated against publicly available NCQA specification summaries.
Pending external NCQA certification.

**Last Updated:** 2026-05-17
**Measures Covered:** BCS, CCS, HBD, CBP, FUM (NCQA HEDIS MY2026)

---

## 1. Purpose

Enterprise payers require that HEDIS measure calculators used in quality reporting
conform to NCQA technical specifications.  While Kriya RAF Intelligence cannot yet
hold official NCQA certification (which requires an annual NCQA license and a formal
third-party audit), we have implemented a self-validation framework that:

- Encodes the publicly documented NCQA HEDIS MY2026 spec criteria for each measure
- Compares implementation logic against those criteria automatically
- Documents all known gaps between the MVP implementation and the full spec
- Exposes a dedicated API endpoint for enterprise security reviewers to inspect

This document summarizes the methodology, per-measure findings, and the path to
official certification.

---

## 2. Measures Covered

| Measure | Full Name | NCQA Reference |
|---------|-----------|----------------|
| BCS | Breast Cancer Screening | NCQA HEDIS MY2026 Vol 2, "BCS-E" |
| CCS | Cervical Cancer Screening | NCQA HEDIS MY2026 Vol 2, "CCS" |
| HBD | Hemoglobin A1c Control for Patients With Diabetes | NCQA HEDIS MY2026 Vol 2, "HBD" |
| CBP | Controlling High Blood Pressure | NCQA HEDIS MY2026 Vol 2, "CBP" |
| FUM | Follow-Up After ED Visit for Mental Illness | NCQA HEDIS MY2026 Vol 2, "FUM" |

All references are to publicly available NCQA specification summaries and CMS Star
Ratings technical notes.  No copyrighted NCQA technical specification text is
reproduced in this codebase.

---

## 3. Self-Validation Methodology

### 3.1 Spec Validators

Each measure has a corresponding validator module at:

```
backend/app/services/hedis/spec_validators/{measure}.py
```

Each validator implements `validate_measure_spec(measurement_year: int) -> dict`
which returns a structured report containing:

- Denominator criteria (age range, sex, diagnosis codes, enrollment requirements)
- Numerator criteria (event type, look-back window, code sets, thresholds)
- Exclusion criteria (ICD-10 codes, value-set OIDs)
- VSAC value-set OIDs referenced
- Explicit list of discrepancies (logic errors vs. known MVP gaps)
- `self_validation_score` (0.0 to 1.0)
- `certification_status` (always states "self-validated; pending external NCQA certification")

### 3.2 Synthetic Patient Test Fixtures

Synthetic patient profiles covering denominator-in/out, numerator-met/unmet, and
exclusion-yes/no scenarios are defined in:

```
backend/tests/fixtures/hedis_validation/{measure}_patients.json
```

Each fixture includes the expected NCQA-spec answer and a rationale string citing
the specific spec criterion being tested.

### 3.3 Automated Tests

The test suite at `backend/tests/test_hedis_ncqa_validation.py` verifies:

1. Spec validator returns all required fields
2. Age/sex boundaries in our calculator match the NCQA-documented spec
3. HbA1c threshold (8.0%), BP threshold (140/90 mmHg), and look-back windows
   are correctly set
4. No logic errors — only known MVP gaps — appear in validator output
5. Certification status language never claims certification we do not hold
6. All 5 validators register in the VALIDATORS registry

Tests that cover MVP known gaps (exclusion logic not yet implemented) are
explicitly marked and skipped rather than failed.

### 3.4 API Endpoint

Enterprise reviewers can fetch live validator output at:

```
GET /api/hedis/spec-validation?year=2026
```

Access requires admin or manager role.  The response includes per-measure
validation reports and an overall self-validation score.

---

## 4. Spec Conformance Findings

### 4.1 What Matches the NCQA Spec

The following criteria are correctly implemented and match the NCQA public spec:

| Criterion | BCS | CCS | HBD | CBP | FUM |
|-----------|-----|-----|-----|-----|-----|
| Age minimum | 50 | 21 | 18 | 18 | 6 |
| Age maximum | 74 | 64 | 75 | 85 | None (no upper bound) |
| Sex restriction | Female | Female | None | None | None |
| Primary threshold | — | — | HbA1c < 8.0% | BP < 140/90 | 7d / 30d |
| VSAC OIDs documented | Yes | Yes | Yes | Yes | Yes |

### 4.2 Known Discrepancies (MVP Gaps)

All discrepancies are MVP implementation gaps, not spec interpretation errors.
No age/sex/threshold logic errors were detected.

**BCS — Breast Cancer Screening**
1. EHR query: CPT 77065/77066/77067 and HCPCS G0202/G0204/G0206 not yet queried
   within the 27-month window; deterministic fallback used.
2. Exclusion logic: Bilateral mastectomy (Z90.13, Z90.11 + Z90.12) not implemented.
3. Enrollment: Continuous enrollment (11/12 months, 45-day gap tolerance) not enforced.

**CCS — Cervical Cancer Screening**
1. EHR query: Pap CPT codes (88141-88175) and HPV CPT 87624/87625 not queried;
   deterministic fallback used.
2. Three-path numerator (cytology-only, co-test, HPV-only) not differentiated.
3. Exclusion: Hysterectomy (Z90.710, Z90.712) not enforced.
4. Enrollment: Continuous enrollment not enforced.

**HBD — Hemoglobin A1c Control for Patients With Diabetes**
1. EHR query: LOINC codes 4548-4/4549-2/17856-6 not queried for most-recent HbA1c;
   deterministic fallback used.
2. Denominator: Diabetes identification uses random score instead of E10/E11/E13
   on two distinct visit dates or antidiabetic pharmacy claim.
3. Exclusion: Pregnancy, ESRD, palliative care, frailty not implemented.

**CBP — Controlling High Blood Pressure**
1. EHR query: Most-recent BP vital-sign query not implemented against structured
   encounter data; deterministic fallback used.
2. Denominator: HTN diagnosis on two distinct dates not verified.
3. Exclusion: Pregnancy, ESRD, dialysis, renal transplant, frailty not implemented.

**FUM — Follow-Up After ED Visit for Mental Illness**
1. EHR query: ED visit with mental-illness principal Dx not queried (CPT 99281-99285
   + VSAC 2.16.840.1.113883.3.464.1004.1183); ~8% deterministic prevalence used.
2. Follow-up detection: Mental health outpatient CPT codes (90785-90876, 99201-99215)
   not queried for 7-day and 30-day windows.
3. Index exclusions: Same-day inpatient admission and last-30-days-of-year exclusions
   not implemented.
4. Exclusion: Hospice, SUD-only principal Dx not implemented.

---

## 5. Planned Remediation

| Priority | Work Item | Target Milestone |
|----------|-----------|-----------------|
| P1 | Implement LOINC HbA1c query (VSAC 2.16.840.1.113883.3.464.1004.1093) for HBD | Q3 2026 |
| P1 | Implement BP vital-sign structured query for CBP | Q3 2026 |
| P2 | Implement mammography CPT/HCPCS query in 27-month window for BCS | Q3 2026 |
| P2 | Implement Pap/HPV CPT query with 3/5-year windows for CCS | Q3 2026 |
| P2 | Implement ED visit + mental-illness Dx + follow-up query for FUM | Q3 2026 |
| P3 | Add bilateral mastectomy exclusion (BCS) and hysterectomy exclusion (CCS) | Q4 2026 |
| P3 | Add pregnancy, ESRD, frailty exclusions across HBD/CBP | Q4 2026 |
| P3 | Implement continuous enrollment enforcement (11/12 months) | Q4 2026 |
| P4 | NCQA license acquisition and formal HEDIS audit engagement | Q1 2027 |

---

## 6. Path to Official NCQA Certification

Official NCQA HEDIS certification requires:

1. **License the NCQA HEDIS Technical Specifications** — Annual subscription
   available at https://www.ncqa.org/hedis/measures/. Required before production
   rate submission to payers.

2. **Implement complete VSAC value-set lookups** — Replace deterministic fallbacks
   with live queries using the VSAC OIDs documented in each spec validator. CMS
   provides VSAC access at https://vsac.nlm.nih.gov/.

3. **Engage an NCQA-certified HEDIS auditor** — Third-party validation of
   denominator, numerator, and exclusion logic against NCQA-provided test scenarios.

4. **Submit via NCQA IDSS** — Certified rates are submitted to the NCQA Interactive
   Data Submission System. Payers accept IDSS-certified rates for Star quality
   reporting.

Until certification is obtained, rates produced by this system are labeled
"self-validated, for internal analytics only" in all customer-facing outputs.

---

## 7. Artifact Locations

| Artifact | Path |
|----------|------|
| Spec validators | `backend/app/services/hedis/spec_validators/` |
| Synthetic fixtures | `backend/tests/fixtures/hedis_validation/` |
| Test suite | `backend/tests/test_hedis_ncqa_validation.py` |
| API endpoint | `GET /api/hedis/spec-validation?year={year}` |
| This document | `docs/enterprise/HEDIS_NCQA_VALIDATION.md` |

---

## 8. Disclaimer

This document and the associated software are not affiliated with or endorsed by
the National Committee for Quality Assurance (NCQA).  HEDIS is a registered
trademark of NCQA.  Production HEDIS rate submission to Medicare Advantage plans
or CMS Star programs requires an NCQA license and certified vendor rates.
