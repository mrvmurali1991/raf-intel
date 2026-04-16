# RAF Intelligence - End-to-End Demo Documentation

## Product Overview

**RAF Intelligence** is an AI-powered Risk Adjustment Factor (RAF) optimization platform that automatically ingests patient data from Electronic Medical Records (EMRs), analyzes clinical encounters using Google Gemini AI, calculates CMS-HCC risk scores, and identifies missed diagnoses for revenue optimization.

---

## Demo Flow Summary

This document demonstrates the complete end-to-end flow:

1. **OpenEMR** (Source EHR) -- Patient data lives here
2. **FHIR R4 Sync** -- Automated data extraction via HL7 FHIR standard
3. **RAF Intelligence** -- AI analysis, RAF scoring, suspect detection

---

## STEP 1: OpenEMR Login

We begin at the external OpenEMR instance (`openemr.ehrservicedesk.com`), which serves as the source Electronic Health Record system.

**Screenshot:** `01_openemr_login_page.png`
- Standard OpenEMR 7.0.2 login interface
- Secure HTTPS connection with Cloudflare protection

**Screenshot:** `02_openemr_login_filled.png`
- Admin credentials entered
- Multi-facility, multi-provider setup

**Screenshot:** `03_openemr_dashboard.png`
- OpenEMR calendar dashboard after login
- Shows multiple providers and facilities (WC Wellness Center, Blue Ridge Medical Center, Blue Ridge Diagnostic Lab, etc.)
- 14+ patients in the system

---

## STEP 2: Create New Patient in OpenEMR

We create a new patient to demonstrate the full data flow from EHR to RAF Intelligence.

**Screenshot:** `04_openemr_new_patient_form.png`
- OpenEMR's comprehensive patient registration form
- Sections: Who, Contact, Choices, Employer, Stats, Misc, Related, Insurance

**Screenshot:** `05_openemr_patient_demographics.png`
- Patient: **Maria Elena Rodriguez**
- DOB: March 15, 1958 (68 years old - Medicare eligible)
- Sex: Female
- SSN: 999-88-7777
- External ID: RAF-DEMO-2026

**Screenshot:** `06_openemr_patient_contact.png`
- Address: 4521 Palm Beach Blvd, Miami, FL 33137
- Phone: (305) 555-0142
- Email: maria.rodriguez@example.com

**Screenshot:** `07_openemr_patient_created.png`
- Patient successfully created in OpenEMR
- Assigned to the system and ready for clinical encounters

---

## STEP 3: Existing Patient Data in OpenEMR

The OpenEMR instance already contains 14 patients with rich clinical data including diagnoses, encounters, medications, and lab results.

**Screenshot:** `08_openemr_patient_summary_abeyta.png`
- Example patient: Ronald Abeyta (DOB: Sep 16, 1943, 82 years old)
- Multiple active medical problems with ICD-10 codes
- Encounter history spanning 2024-2026

---

## STEP 4: RAF Intelligence Login

Now we switch to the RAF Intelligence platform to see how this data is ingested and analyzed.

**Screenshot:** `09_raf_login_page.png`
- Professional login interface for RAF Intelligence
- Branded as "TMIAB RAF - Clinical Intelligence"

**Screenshot:** `10_raf_login_filled.png`
- Admin login credentials

**Screenshot:** `11_raf_after_login.png`
- Successfully authenticated

---

## STEP 5: Patient Population Dashboard

The heart of RAF Intelligence - the patient population view showing all synced patients with their risk profiles.

**Screenshot:** `14_raf_patients_list.png`

**Key Metrics Visible:**
| Metric | Value |
|--------|-------|
| Total Patients | 13 |
| High Risk (RAF >= 2.00) | 0 |
| Medium Risk (1.00 - 1.99) | 5 |
| Average RAF Score | 0.92 |
| Total HCCs | 34 |
| Scored Rate | 85% |

**Patient List (sample):**
| Patient | Risk Level | RAF Score | HCCs | Status |
|---------|-----------|-----------|------|--------|
| ABEYTA, RONALD (82M) | Medium | 1.07 | 3 | Analyzed |
| Henderson, Lisa M (65F) | Medium | 1.37 | 5 | Analyzed |
| Garcia, Maria (67F) | Medium | 1.05 | 4 | Analyzed |
| Chen, Sarah (54F) | Low | 0.12 | 1 | Analyzed |
| Adams, Terry (19F) | Unscored | - | 0 | Pending |

---

## STEP 6: Patient Detail - Ronald Abeyta (RAF 1.069)

Clicking into a patient reveals comprehensive clinical intelligence.

**Screenshot:** `27_raf_patient_detail_abeyta.png`

**Patient Header:**
- Name: RONALD ABEYTA
- PID: 855 | Age: 82 | Sex: M | DOB: Sep 16, 1943
- RAF Score (2026): **1.069**
- Model Segment: CNA (Community, Non-Dual, Aged)
- HCC Count: **3 conditions**
- MEAT Compliance: Pending
- Data Quality: 50%

**Action Buttons:** Analyze All Encounters | Calculate RAF | Generate Audit | Print

**Active Problems (8 conditions with ICD-10 codes):**
| Condition | ICD-10 | Onset |
|-----------|--------|-------|
| Type 2 diabetes mellitus without complications | E11.9 | Jan 15, 2025 |
| COPD with acute exacerbation | J44.1 | Jan 15, 2025 |
| Chronic kidney disease, stage 3 | N18.3 | Jan 15, 2025 |
| Hypothyroidism, unspecified | E03.9 | Jun 1, 2024 |
| Hyperlipidemia, unspecified | E78.5 | Jun 1, 2024 |
| Essential (primary) hypertension | I10 | Jun 1, 2024 |
| Atherosclerotic heart disease | I25.18 | Jun 1, 2024 |
| Primary osteoarthritis, right knee | M17.11 | Jun 1, 2024 |

**Screenshot:** `28_raf_patient_abeyta_conditions.png`

**Recent Encounters (4):**
- Encounter for check up (procedure) - Mar 20, 2026
- Follow-up Visit - Mar 10, 2026
- Annual Wellness Visit - Jan 10, 2026
- Chronic Care Management - Sep 20, 2025

Each encounter has an **"Analyze"** button for AI-powered clinical analysis.

**Data Completeness:**
- Encounters: Available
- Clinical Notes: Available
- Problems: Available
- Medications: Available
- Vitals: Missing
- Labs: Missing
- Billing: Missing
- Insurance: Available

---

## STEP 7: Patient Detail - Lisa Henderson (RAF 1.374)

**Screenshot:** `30_raf_patient_detail_henderson.png`

Another high-value patient with 5 HCC conditions and RAF score of 1.37, demonstrating the platform's ability to track multiple complex patients.

---

## STEP 8: Search - Maria Elena Rodriguez (Newly Created)

**Screenshot:** `15_raf_search_rodriguez.png`

Our newly created patient from OpenEMR is now visible in RAF Intelligence:
- **Rodriguez, Maria Elena** - Age 68, PID 2433
- Risk Level: Low
- RAF Score: **0.37** (demographic score only - no conditions yet)
- Status: **Analyzed**
- Demo 0.370

This confirms the complete data flow: patient created in OpenEMR --> FHIR sync --> appears in RAF Intelligence with calculated demographic RAF score.

---

## STEP 9: EMR Configuration

**Screenshot:** `25_raf_emr_connected.png`

The EMR Configuration page shows:

**Summary Cards:**
| Metric | Value |
|--------|-------|
| Total Connections | 2 |
| Active | 1 (1 inactive) |
| Last Sync | 19h ago |
| Errors | 0 - All connections healthy |

**AI Analysis Pipeline:**
- Toggle: **AUTO AI ON** (green)
- Description: "Gemini AI runs automatically on every EMR sync (8-phase pipeline)"
- Pipeline Phases: EMR Sync --> Normalize --> **AI Analysis** --> RAF Calc --> HCC Hierarchy --> Suspects --> Gap Generation --> Webhooks

**Connections:**
1. **EHR ServiceDesk (FHIR)** - Active, FHIR R4 protocol, with Authorize/Test/Sync/Edit controls
2. **Local OpenEMR** - Inactive, Direct DB (Legacy)

---

## STEP 10: Suspect Conditions

**Screenshot:** `18_raf_suspects.png`

The Suspect Conditions page shows the AI-driven suspect detection engine:

**Columns:** Patient | Suspected Condition | Evidence | Confidence | RAF Lift

**Filters:**
- Status: Open, Accepted, Dismissed, Coded
- Sources: All Sources, Lab, Medication, Imaging, Referral, Historical
- Confidence: High >85%, Med 65-85%, Low <65%

*Currently showing 0 suspects because the full AI analysis pipeline has not yet completed for all encounters. Once encounters are analyzed by Gemini AI, suspects will be populated automatically.*

---

## STEP 11: Recapture Gaps

**Screenshot:** `19_raf_recapture_gaps.png` / `33_raf_recapture_gaps_detail.png`

The Recapture Gaps module identifies conditions from prior years that need to be re-documented in the current measurement year to maintain RAF scores.

---

## STEP 12: Data Uploads

**Screenshot:** `32_raf_data_uploads.png`

The Data Uploads page allows manual document upload (PDF, images) for Gemini Vision AI analysis. Documents are analyzed to extract:
- ICD-10 diagnosis codes
- HCC mappings
- Medications
- Lab results
- MEAT compliance evidence

---

## Technical Architecture

```
OpenEMR (EHR)                    RAF Intelligence
+------------------+            +---------------------------+
| Patients         |  FHIR R4   | Patient Demographics      |
| Conditions       | ---------> | HCC Conditions (ICD-10)   |
| Encounters       |  OAuth2    | RAF Scores (V24/V28)      |
| Medications      |  Sync      | AI Analysis (Gemini)      |
| Observations     |            | Suspect Conditions        |
| Immunizations    |            | Care Gaps                 |
| Allergies        |            | Provider Worklists        |
| Documents        |            | Webhooks                  |
+------------------+            +---------------------------+
```

**FHIR Resources Synced (9 types):**
1. Patient --> Demographics + RAF demographic scoring
2. Condition --> ICD-10 codes --> HCC crosswalk --> RAF calculation
3. Encounter --> Clinical analysis by Gemini AI
4. MedicationRequest --> Medication-based suspect detection
5. Observation --> Lab-based suspect detection
6. DiagnosticReport --> NLP analysis
7. Immunization --> HEDIS measures
8. AllergyIntolerance --> Safety alerts
9. DocumentReference --> Gemini Vision document analysis

**8-Phase Automated Pipeline:**
1. EMR Sync (FHIR R4 data ingestion)
2. Normalization (standardize codes, names, dates)
3. AI Analysis (Gemini 2.5 Pro per encounter)
4. RAF Calculation (CMS-HCC V24/V28 blended scoring)
5. HCC Hierarchy (trumping/interaction logic)
6. Suspect Detection (4 engines: lab, medication, history, NLP)
7. Gap Generation (care gaps + chart chase)
8. Webhooks (notifications + completion events)

---

## Key Takeaways

1. **Seamless EHR Integration**: Patient data flows automatically from OpenEMR via FHIR R4 with OAuth2 security
2. **AI-Powered Analysis**: Google Gemini 2.5 Pro analyzes every clinical encounter for missed diagnoses
3. **Accurate RAF Scoring**: CMS-HCC V24/V28 blended model with demographic + disease + interaction scoring
4. **Comprehensive Patient View**: All clinical data, conditions, encounters, medications, labs in one view
5. **Actionable Intelligence**: Suspect conditions, care gaps, and provider worklists drive revenue optimization
6. **Enterprise Ready**: Multi-tenant, HIPAA-compliant, with audit logging and role-based access

---

## Screenshots Reference

| # | Screenshot | Description |
|---|-----------|-------------|
| 01 | openemr_login_page | OpenEMR login screen |
| 02 | openemr_login_filled | Credentials entered |
| 03 | openemr_dashboard | OpenEMR calendar dashboard |
| 04 | openemr_new_patient_form | New patient registration form |
| 05 | openemr_patient_demographics | Patient demographics filled |
| 06 | openemr_patient_contact | Contact information filled |
| 07 | openemr_patient_created | Patient creation confirmed |
| 08 | openemr_patient_summary_abeyta | Existing patient summary |
| 09 | raf_login_page | RAF Intelligence login |
| 10 | raf_login_filled | RAF login credentials |
| 14 | raf_patients_list | Full patient population view |
| 15 | raf_search_rodriguez | Searching for newly created patient |
| 18 | raf_suspects | Suspect conditions dashboard |
| 19 | raf_recapture_gaps | Recapture gaps view |
| 25 | raf_emr_connected | EMR configuration with AI pipeline |
| 27 | raf_patient_detail_abeyta | Patient detail - RAF score, conditions |
| 28 | raf_patient_abeyta_conditions | Encounters, care gaps, data quality |
| 30 | raf_patient_detail_henderson | Another patient detail view |
| 32 | raf_data_uploads | Document upload interface |

---

*Document generated: April 16, 2026*
*RAF Intelligence v2.0*
