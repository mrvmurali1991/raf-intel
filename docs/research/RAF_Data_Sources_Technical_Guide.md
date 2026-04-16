# Risk Adjustment Factor (RAF) Clinical Data Sources: Technical Integration Guide

**Research Date:** April 2026  
**Scope:** Comprehensive technical reference for building RAF data integration systems

---

## Executive Summary

RAF calculations depend on clinical data from multiple sources: claims (837P/837I/CMS-1500/UB-04), EHR/EMR systems (Epic, Cerner, Athenahealth, OpenEMR), pharmacy data, lab results, and medical records. CMS transitioned from RAPS to EDPS in 2022, requiring full encounter-level submission with diagnosis filtering applied by CMS. This guide covers the technical specifications for integrating these data sources into RAF calculation systems.

---

## 1. CLAIMS DATA SOURCES (837P, 837I, CMS-1500, UB-04)

### 1.1 Overview and Form Usage

- **CMS-1500 (Professional Claims)**: Used by individual healthcare providers (physicians, therapists, dietitians), ambulatory care
- **837P (Electronic equivalent of CMS-1500)**: HIPAA-compliant professional claim transaction format
- **UB-04 (Paper Institutional Claims)**: Used by institutional providers (hospitals, nursing facilities, rehabilitation centers)
- **837I (Electronic equivalent of UB-04)**: Institutional claim transaction format

### 1.2 Diagnosis Code Field Specifications

#### 837P Diagnosis Code Requirements (HI Segment)

**Segment Structure:**
- HI segment contains diagnosis codes for a specific claim (CLM in loop 2300)
- Diagnosis codes separated by tilde (~) segments
- Data elements within segments separated by asterisk (*)

**Qualifier Codes for Professional Claims:**
- **ABK**: Principal diagnosis code (primary reason for encounter)
- **ABF**: Additional diagnosis codes (up to 11 supplementary diagnoses per HI segment)
- Multiple HI segments can be submitted for claims with more than 12 diagnoses

**Technical Requirements:**
- ICD-10-CM codes only (no decimal points in submission; X12 compliance mandatory)
- Code to highest level of specificity available
- No leading zeros; formatted as numeric string
- Each diagnosis must be from an acceptable source (eligible CPT/HCPCS codes)

#### UB-04 Diagnosis Code Fields

**Form Locator 67 (Principal Diagnosis):**
- ICD-10-CM code for primary reason for admission/encounter
- Required on all institutional claims

**Form Locators 67A–67Q (Additional Diagnoses):**
- Up to 25 total diagnosis codes (FL 67 plus 24 additional)
- Each requires **POA (Present on Admission) indicator** (Y/N/U/W/X)
- POA indicators distinguish conditions present at admission from those acquired during stay

**HCC Relevance:**
- Not all diagnoses contribute to RAF
- Of ~72,748 ICD-10-CM codes, only ~9,700 are allowed for risk adjustment
- CMS applies filtering logic post-submission

### 1.3 Claims Data Elements Supporting HCC

**Critical fields for risk adjustment:**
- Service date (DOS) - determines eligible diagnosis sources
- Place of service code - determines claim type (office, hospital, ED, etc.)
- CPT/HCPCS codes - procedure codes filter eligible diagnosis sources
- Diagnosis codes - mapped to HCC categories
- Provider NPI - identifies rendering provider
- Claim type indicator (inpatient vs. outpatient)

**Data Quality Requirements:**
- Valid diagnosis codes active on date of service
- Diagnosis must link to eligible service (CPT/HCPCS code)
- No duplicate claims (MAO-001 validates this)
- Provider information aligned with CMS provider records

### 1.4 Diagnosis Validation in Claims

**Specificity Validation:**
- ICD-10-CM codes must be complete to highest digit level available
- 3-character codes accepted only if no further specificity exists
- Unspecified vs. specified codes: if eGFR = 28, must code N18.4 (Stage 4) not N18.9 (unspecified)
- Laterality requirements: bilateral codes preferred when applicable

**CPT/HCPCS Eligibility Filtering:**
- CMS maintains list of acceptable CPT/HCPCS codes for risk adjustment
- If at least one service line on encounter includes acceptable code, diagnoses from all service lines eligible
- Common eligible codes: E/M visits, procedures, evaluations, lab/pathology
- Excluded: some administrative-only codes

---

## 2. EHR/EMR DATA EXTRACTION

### 2.1 OpenEMR

**FHIR Compliance:**
- US Core 8.0 compliant
- FHIR R4 implementation
- SMART on FHIR v2.2.0 support
- ONC Cures Act information blocking requirements met

**Diagnosis Code Access Methods:**

**Method 1: FHIR Condition Resource (RESTful)**
```
GET /fhir/r4/Condition?patient={patientId}&clinical-status=active
```
- Returns FHIR Condition resources
- Maps local diagnosis codes to ICD-10-CM
- Supports filtering by status, encounter, date range

**Method 2: Bulk Data Export**
- FHIR Bulk Data Export specification compliance
- Large-scale data access for initial loads
- Preferred for batch diagnosis extraction
- Exports Condition resources with associated metadata

**Method 3: API Integration**
- RESTful endpoint access to condition/diagnosis data
- UDS (Uniform Data System) reporting integration
- Maps diagnosis data to reporting standards

**Data Elements Captured:**
- ICD-10-CM diagnosis code
- Problem description
- Date of diagnosis
- Status (active, resolved, inactive)
- Encounter reference
- Onset date

### 2.2 Epic EHR

**Integration Methods:**

**Primary: HL7 V2 ADT Messages (via Epic Bridges)**
- Most common production integration
- ADT^A01/A04 messages for admits, discharges, transfers
- HL7 segment structure:
  - MSH: Message header (sender, receiver, timestamp)
  - DG1: Diagnosis segment (ICD-10 code, description, type)
  - PR1: Procedure segment
  - OBX: Observation segment (lab results)

**DG1 Segment Structure (Diagnosis):**
```
DG1|1|ICD10|N18.4|Chronic Kidney Disease Stage 4|A|||[encounter-date]
```
- Field 1: Set ID
- Field 2: Diagnosis type (ICD10)
- Field 3: Diagnosis code
- Field 4: Diagnosis description
- Field 5: Diagnosis classification (A=Admission, W=Workup, etc.)

**Secondary: FHIR APIs (via App Orchard)**
- RESTful FHIR endpoint access
- Condition resource queries
- OAuth 2.0 authentication required
- Real-time API vs. batch HL7 options

**Diagnosis Data Access:**
- Problem list/condition queries
- Historical diagnosis tracking
- Active vs. resolved status differentiation
- Links to supporting evidence (encounters, labs, notes)

### 2.3 Cerner (Oracle Health)

**API Integration Methods:**

**FHIR R4 APIs (Ignite APIs - Recommended)**
- RESTful FHIR endpoints
- Condition resource for diagnoses
- MedicationRequest, DiagnosticReport, Observation resources
- OAuth 2.0 with JSON Web Key Set (JWKS) authentication

**HL7 V2 Messaging (Cerner Open Interface - COI)**
- DG1 segment for diagnoses
- ADT messaging for patient state updates
- Legacy but widely supported

**Millennium Platform APIs**
- Proprietary Cerner APIs
- Deeper EHR integration
- Requires Cerner developer credential registration

**Diagnosis Data Extraction:**
- Query FHIR Condition resource
- Retrieve problem list with ICD-10 codes
- Filter by status (active), date range, encounter
- Supports bulk export for large datasets

**Sample Query:**
```
GET /fhir/r4/Condition?patient=123&clinical-status=active
    &onset-date=ge2025-01-01
    &onset-date=le2025-12-31
```

### 2.4 Athenahealth

**API Architecture:**
- 800+ REST API endpoints
- FHIR Bulk Data Export (Cures Act compliant)
- Real-time synchronization (no delay vs. UI view)

**Data Export Methods:**

**Method 1: FHIR Bulk Data Export**
- Large-scale data extraction
- Patient, Condition, MedicationRequest, AllergyIntolerance, DiagnosticReport resources
- Recommended for initial loads and full syncs
- ND-JSON format delivery

**Method 2: REST API (athenaOne APIs)**
- Individual endpoint queries
- Real-time data access
- 800+ proprietary endpoints for administrative, clinical, financial functions
- Structured Electronic Health Information (EHI) export

**Method 3: Diagnosis Gap Identification**
- Real-time HCC-weighted chronic condition documentation
- Built-in alerts during clinician workflow
- Identifies open diagnosis gaps
- Supports HCC Assistant tool for real-time coding guidance

**Diagnosis Data Elements:**
- ICD-10-CM codes
- Problem descriptions
- Encounter associations
- Lab results supporting diagnoses
- Active/resolved status

---

## 3. FHIR & HL7 STANDARDS FOR DIAGNOSIS DATA EXCHANGE

### 3.1 FHIR R4 Condition Resource

**Structure:**
```json
{
  "resourceType": "Condition",
  "id": "condition-123",
  "clinicalStatus": {
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
      "code": "active"
    }]
  },
  "verificationStatus": {
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
      "code": "confirmed"
    }]
  },
  "code": {
    "coding": [{
      "system": "http://hl7.org/fhir/sid/icd-10-cm",
      "code": "N18.4",
      "display": "Chronic kidney disease, stage 4"
    }]
  },
  "subject": {
    "reference": "Patient/patient-123"
  },
  "encounter": {
    "reference": "Encounter/encounter-456"
  },
  "onsetDateTime": "2024-06-15",
  "recordedDate": "2024-06-15"
}
```

**Key Mappings for RAF:**
- `clinicalStatus`: Determines if condition is active (required for HCC)
- `code`: ICD-10-CM diagnosis code
- `subject`: Patient reference
- `encounter`: Links diagnosis to specific visit
- `onsetDate`: When condition started (context for hierarchical relationships)

### 3.2 HL7 V2 DG1 Segment (Legacy Standard)

**Segment Format:**
```
DG1|Set_ID|Coding_Method|Code|Description|Class|Code_Type|POA
```

**Example:**
```
DG1|1|ICD10|N18.4|Chronic Kidney Disease Stage 4|A|A|Y
```

**Field Definitions:**
- **Set ID**: Diagnosis sequence (1, 2, 3...)
- **Coding Method**: ICD10 (or other)
- **Code**: ICD-10-CM diagnosis code
- **Description**: Narrative diagnosis
- **Class**: Diagnosis type (A=Admission, W=Workup)
- **Code Type**: Type of code
- **POA**: Present on Admission (Y/N/U/W for inpatient)

### 3.3 HL7 V2 HI Segment (837P Equivalent)

**EDI Format in X12 837P Claims:**
```
HI*ABK:N18.4*ABF:E11.9*ABF:I10
```

**Element Definitions:**
- **ABK**: Principal diagnosis qualifier
- **ABF**: Additional diagnosis qualifier
- **Code**: ICD-10-CM code (no decimal)

### 3.4 Standards Adoption and Regulatory Requirements

**CMS/ONC Requirements (2020 Rules):**
- FHIR APIs required for patient data access
- FHIR APIs required for provider-to-payer data exchange
- Both CMS and ONC divisions mandate FHIR for interoperability

**Industry Transition Status:**
- Epic: Transitioning from HL7 V2 to FHIR, but V2 still dominant in production
- Cerner/Oracle Health: FHIR R4 APIs available alongside HL7 V2
- Athenahealth: FHIR-first approach for new integrations
- OpenEMR: Full FHIR R4 compliance and bulk export

---

## 4. CHART REVIEW AND MEDICAL RECORD ABSTRACTION

### 4.1 Workflow Overview

**HCC Capture Process:**
1. Patient chart review by certified coders
2. Identification of HCC-relevant conditions
3. Extraction of supporting documentation
4. Validation against MEAT criteria
5. Code assignment with date/evidence linkage

### 4.2 MEAT Validation Framework

**Definition:** Four evidence types required to validate HCC diagnoses

- **M - Monitor**: Signs and symptoms documented in provider notes
- **E - Evaluate**: Test results, lab values supporting diagnosis
- **A - Assess/Address**: Provider assessment or acknowledgment of condition
- **T - Treat**: Active management or treatment plan for condition

**Example (Chronic Kidney Disease Stage 4):**
- M: "Patient reports fatigue, decreased urine output"
- E: "eGFR = 28 mL/min/1.73m² (Lab date: 2025-06-15)"
- A: "CKD stage 4 noted in assessment"
- T: "Referred to nephrology; ACE inhibitor prescribed"

**Validation Requirements:**
- At least ONE MEAT element required per HCC
- Evidence must link to face-to-face encounter in payment year
- Maximum 2 medical records per audited HCC (only 1 needed for payment validity)
- All supporting documentation must be from current calendar year

### 4.3 Face-to-Face Encounter Requirements

**Regulatory Requirements:**
- Diagnosis must be documented within 12 months of the service date
- Provider must have face-to-face contact with patient for diagnosis to be valid
- Telehealth visits qualify as face-to-face
- Documentation must show clinical evaluation supporting HCC

**Encounter Types Supporting HCC:**
- Office visits (E/M codes)
- Hospital visits (inpatient, observation, ED)
- Telehealth/virtual visits
- Behavioral health visits
- Home health visits

### 4.4 Chart Review Tools and Workflows

**Automated HCC Identification:**
- NLP-based keyword scanning for suspect HCCs
- Problem list mining
- Lab value thresholds triggering HCC queries
- Medication-to-HCC mapping

**Example Tool Features:**
- Real-time alerts during provider documentation
- Coder workbench organized by suspected HCC
- Direct linking from condition to supporting evidence
- Hierarchical relationship enforcement (exclusions based on more severe codes)

**Quality Assurance in Abstraction:**
- Secondary review by lead coder
- Periodic external audit validation
- CMS RADV audit preparation (25 weeks for medical record assembly)

---

## 5. LAB RESULTS AND HCC SUPPORT

### 5.1 Lab Value Thresholds and HCC Mapping

**Chronic Kidney Disease (CKD):**
- eGFR < 45: Triggers CKD coding requirement
- eGFR 30-44: Stage 4 (HCC 137)
- eGFR 15-29: Stage 5 (HCC 136)
- **Red Flag:** CKD coded without creatinine/eGFR in chart → RADV audit failure
- **Hierarchy:** More specific stage trumps unspecified coding

**Diabetes Complications:**
- Glycemic control (HbA1c values)
- Lab evidence of complications (kidney, eye, neurological)
- Separate HCCs for controlled vs. uncontrolled conditions

**Heart Failure:**
- BNP/NT-proBNP levels
- Ejection fraction from imaging
- Distinguishes severity levels (HCC 224/225/226 constrained to same weight in V28)

**Anemia:**
- Hemoglobin levels
- Type of anemia (iron deficiency vs. chronic disease)
- Treatment status

### 5.2 Lab Data Standards in RAF Calculations

**Supported Lab Value Types:**
- Chemistry panels (creatinine, eGFR, electrolytes)
- Hematology (hemoglobin, hematocrit, WBC)
- Lipids and glucose
- Specialized markers (BNP, troponin, PSA)

**Data Elements Required:**
- Lab code (LOINC preferred)
- Lab value and units
- Reference range
- Date of test
- Performing lab/facility

**Integration Points:**
- EHR-embedded lab queries
- HL7 ORU (Observation Result) messages
- FHIR DiagnosticReport and Observation resources
- Claims-based lab results (procedural codes with results)

### 5.3 Lab Documentation Best Practices for HCC Validation

**MEAT Compliance:**
- Laboratory results satisfy **E (Evaluate)** element
- Frequency: Most labs valid for HCC support if within 12 months
- Trending: Serial labs more convincing than single values

**Critical Gaps:**
- CKD Stage 4 without eGFR documentation
- Diabetes without HbA1c
- Heart failure without ejection fraction or BNP
- Anemia without hemoglobin value

---

## 6. PHARMACY DATA AND MEDICATION-DIAGNOSIS INFERENCE

### 6.1 National Drug Code (NDC) Structure

**Format:** 11-digit code (5-4-2 segments)
- **Segment 1 (5 digits)**: Manufacturer/labeler code
- **Segment 2 (4 digits)**: Drug ingredient, strength, dosage form, route
- **Segment 3 (2 digits)**: Packaging

**Example:** 00378-0750-05 (Amoxicillin)

**Data Elements in Pharmacy Claims:**
- NDC code
- Quantity dispensed
- Days supply
- Dose
- Date of dispensing
- Pharmacy identifier
- Prescriber NPI

### 6.2 Medication-to-Diagnosis Inference Rules

**Limitations:** Not all medications reliably infer diagnoses

**Valid Inferences (Strong Association):**
- Insulin → Diabetes (HCC 36/37/38)
- ACE inhibitor → Hypertension or Heart Failure
- Immunosuppressants → Transplant recipient
- Antiretrovirals → HIV/AIDS

**Invalid Inferences (Weak/Ambiguous):**
- Metformin → Pre-diabetes only (not reliable for diabetes HCC) - excluded from RXC 7
- NSAIDs → Could indicate pain management (not diagnostic)
- Antibiotics → Acute infection (transient, not chronic HCC)

### 6.3 RXC (Pharmacy-Based Risk Condition) Program

**Overview:**
- Parallel to HCC for pharmacy data
- Analyzes dispensed medications as disease proxies
- More conservative than HCC to prevent over-coding

**Scoring Formula:**
- When both HCC (diagnosis) and RXC (medication) present: Lower enrollee score
- Rationale: Incentivizes reporting both diagnosis and medication utilization
- If HCC only OR RXC only: Single risk adjustment applied

**Common RXC Categories:**
- RXC 1: Diabetes medications
- RXC 2: Heart failure medications
- RXC 7: Diabetes/metabolic (but excludes metformin alone)

### 6.4 Pharmacy Data in RAF Integration

**Data Sources:**
- Outpatient pharmacy claims (837P with NDC)
- Inpatient pharmacy records
- Medication reconciliation from EHR
- DME pharmacy claims

**Validation Rules:**
- NDC must be valid on date of dispensing
- Quantity and days supply must be consistent
- Refills tracked to detect duplicate submissions
- Drug knowledge base mapping for medication families

---

## 7. HEDIS AND QUALITY MEASURE DATA OVERLAP

### 7.1 HEDIS Measure Overview

**Definition:** Healthcare Effectiveness Data and Information Set (NCQA)
- Standardized performance measures for health plans
- ~90 measures across clinical quality, member satisfaction, access/timeliness
- Annual measurement and reporting

**Data Collection Methods:**
- Administrative claims data
- Medical record review
- NCQA-certified EHR reporting
- Hybrid approaches (claims + chart review)

### 7.2 Diagnosis Code Overlap Between HEDIS and Risk Adjustment

**Overlapping Data Elements:**

| Measure | HCC Relevance | Data Source | Shared Codes |
|---------|---------------|-------------|--------------|
| Controlling High Blood Pressure | Hypertension HCC | Claims/EHR | ICD-10 I10-I16 |
| Comprehensive Diabetes Care | Diabetes HCC 36/37/38 | Claims/Lab/EHR | ICD-10 E10-E14 |
| Appropriate Medication Use | Drug HCC/RXC | Pharmacy claims | NDC codes |
| Kidney Health Evaluation | CKD HCC 137/138 | Lab/EHR | eGFR, ICD-10 N18.x |
| Cardiovascular Condition | Heart failure HCC 224-226 | EHR/Claims | ICD-10 I50.x |
| Care for Older Adults (Medication) | Multiple HCCs | EHR/Pharmacy | Beers Criteria drugs |

### 7.3 Documentation Alignment Strategy

**Single Documentation Benefits:**
- One clinical encounter document supports both HEDIS and HCC
- Risk adjustment coding triggers quality measure documentation
- HCC-specific diagnosis codes enable HEDIS numerator inclusion

**Example:** Chronic Kidney Disease
- Supports HEDIS measure: "Kidney Health Evaluation" (labs, imaging screening)
- Supports HCC coding: CKD Stage 4 (N18.4) → HCC 137
- Combined documentation improves both metric rates

**Risk:** Over-documentation
- Coding clinically valid diagnoses for payment may inflate quality metrics artificially
- CMS monitors for suspicious clustering of HCC codes

### 7.4 Risk Adjustment Utilization (RAU) Tables

**NCQA Tools:** Risk Adjustment Utilization tables
- Predict measure-specific outcomes
- Account for patient age, gender, comorbidities
- Risk-adjusted denominators for HEDIS measures

---

## 8. RAPS vs. EDPS: SUBMISSION SYSTEMS

### 8.1 RAPS (Risk Adjustment Processing System)

**Historical Context:**
- CMS's original risk adjustment submission method (pre-2022)
- Minimal data beyond diagnosis codes
- Effective through CY 2021; no longer used for RAF calculations as of CY 2022

**Data Submitted:**
- Beneficiary ID
- HCC diagnosis codes (summary only)
- Service dates
- Provider information (minimal)

**Limitations:**
- No service-level detail
- No procedure codes for context
- No lab or medication linkage
- CMS applied filtering logic internally

### 8.2 EDPS (Encounter Data Processing System)

**Current Standard (CY 2022 Forward):**
- Encounter-level submission (similar to traditional FFS Medicare claims)
- Complete service detail with diagnosis codes for each service
- CMS applies filtering logic post-submission

**Data Required per Encounter:**
- Beneficiary ID and demographics
- Service date and place of service
- Type of service (inpatient, outpatient, ED, etc.)
- All procedure codes (CPT/HCPCS)
- All diagnosis codes (unfiltered)
- Provider NPIs
- Units, charges, claims amounts
- Modifier information

**Submission Format:**
- 837P (professional) or 837I (institutional)
- Standard HIPAA EDI compliance
- Same edits as fee-for-service Medicare

### 8.3 Key Differences: RAPS vs. EDPS

| Aspect | RAPS | EDPS |
|--------|------|------|
| Data Scope | Diagnosis codes only | Full encounter detail |
| Service Detail | None | All CPT/HCPCS codes |
| Filtering | CMS-applied | CMS-applied |
| Claims Format | Custom format | Standard 837P/837I |
| Frequency | Annual submission | Multiple deadlines (initial, mid-year, final) |
| Effective | Through CY 2021 | CY 2022 forward |

### 8.4 Transition Impact on Data Integration

**System Changes Required:**
1. Switch from summary diagnosis submission to full encounter submission
2. Implement CPT/HCPCS code validation for eligibility filtering
3. Add EDI claim validation (HIPAA compliance)
4. Implement duplicate detection logic
5. Add comprehensive audit trail for CMS MAO reports

---

## 9. ENCOUNTER DATA SUBMISSION TO CMS (EDPS PROCESS)

### 9.1 MAO-004 Report Structure

**Purpose:** Final stage of EDPS processing; provides payment reconciliation and encounter validation summary

**Content:**
- Payment adjustments for accepted diagnoses
- Summary counts of submitted vs. accepted encounters
- Diagnosis code rollup by HCC
- Error counts and categories
- RAF score impact summary

**Timing:**
- Generated after all editing and processing complete
- Provides final payment calculation
- Used for financial reconciliation

### 9.2 Submission Deadlines (Payment Year Cycle)

**Three Submission Windows per Payment Year:**

1. **Initial Submission Deadline** (Example: Sept 30 for PY 2026 diagnoses)
   - First opportunity to submit diagnosis codes
   - CMS provides preliminary MAO-001 and MAO-002 reports

2. **Mid-Year Submission Deadline** (Example: Jan 31)
   - Opportunity to correct, add diagnoses
   - New encounters and late-arriving claims
   - CMS reprocesses with updated data

3. **Final/Claims-Runout Deadline** (Example: April 30)
   - Absolute final deadline for diagnosis code inclusion
   - Diagnoses submitted after this date excluded from RAF calculation
   - Claims incurred but not submitted forfeit risk adjustment dollars

**Impact:** Missing final deadline = permanent loss of HCC-associated risk adjustment payment

### 9.3 EDPS Data Processing Flow

```
1. MAO Submits Encounter Data (837P/837I)
   ↓
2. CMS EDPS Validation Edits
   ├─ Enrollment validation (beneficiary eligible on DOS)
   ├─ Provider validation (NPI alignment with CMS records)
   ├─ Duplicate detection (MAO-001 report)
   ├─ CPT/HCPCS code validation
   ├─ Diagnosis code validity (ICD-10 active on DOS)
   └─ CCI edit compliance
   ↓
3. CMS Applies Filtering Logic
   ├─ Identify eligible encounters (CPT/HCPCS code presence)
   ├─ Extract diagnosis codes from eligible encounters
   └─ Match to HCC crosswalk
   ↓
4. CMS Processes HCC Hierarchies
   ├─ Group diagnoses by HCC
   ├─ Apply hierarchical exclusions
   ├─ Calculate RAF factors by HCC
   └─ Sum to patient-level RAF score
   ↓
5. CMS Issues Validation Reports
   ├─ MAO-002: Processing status and errors
   ├─ MAO-004: Final payment and reconciliation
   └─ MAO-001: Duplicate encounter summary
```

### 9.4 MAO-002 Processing Status Report

**Purpose:** Provides line-level encounter and error tracking

**Key Sections:**
- '000' header line: Overall encounter acceptance/rejection status
- Individual service line statuses (accepted/rejected)
- Diagnosis code processing results per line
- Error codes for rejected records (98325 = duplicates, invalid codes, etc.)
- Encounter counts (submitted vs. processed)

**Error Processing:**
- If '000' header rejected: Entire encounter rejected, must resubmit
- If specific diagnosis rejected: Diagnosis excluded from HCC, encounter may partially process
- Common rejection codes:
  - "Invalid diagnosis code on this DOS"
  - "Diagnosis code not HCC-eligible"
  - "Duplicate encounter submitted"
  - "Beneficiary not enrolled on DOS"

---

## 10. DATA QUALITY REQUIREMENTS AND REJECTION REASONS

### 10.1 Common EDPS Rejection Reasons

**Enrollment/Eligibility Errors (40-50% of rejections):**
- Beneficiary not enrolled in plan on date of service
- Beneficiary disenrolled before claim submission
- Medical Assistance status mismatch
- Enrollment termination before visit date

**Provider Information Errors (20-30%):**
- Provider NPI not aligned with CMS database
- Invalid/inactive provider NPI
- Specialty code mismatch
- Missing provider taxonomy code

**Diagnosis Code Errors (15-20%):**
- Invalid ICD-10-CM code (not in active code set)
- Code inactive on date of service
- Code too non-specific (unspecified codes when specific available)
- Code not in acceptable list for service type

**Service Validation Errors (10-15%):**
- Invalid CPT/HCPCS code
- Code/modifier combination not allowed (CCI edits)
- Place of service not valid for service code
- Unit values inconsistent with code

**Duplicate/Data Quality (5-10%):**
- Exact duplicate of previously submitted encounter (MAO-001)
- Near-duplicate detection (same patient, same DOS, similar charges)
- Claim already processed and adjusted
- Submission out of sequence

**Pharmacy-Specific Errors:**
- Beneficiary not enrolled in pharmacy benefit
- NDC code inactive on DOS
- Dispensing date not in pharmacy benefit
- Quantity/days supply inconsistent

### 10.2 Diagnosis Code Validation Algorithm

**Specificity Validation:**
```
IF code_length < 3:
    REJECT: "Insufficient specificity"
ELSE IF code_length = 3:
    IF 4-character alternative exists:
        REJECT: "More specific code available"
    ELSE:
        ACCEPT
ELSE IF code_length = 4:
    IF 5-character alternative exists:
        REJECT: "More specific code available"
    ELSE:
        ACCEPT
ELSE IF code_length = 5 OR 6:
    ACCEPT
```

**Laterality Validation:**
- If code supports bilateral: Unilateral codes rejected
- If bilateral applies: Left+Right codes rejected
- If unspecified allowed: Accept unspecified
- Example: N18.31 (CKD Stage 3a) valid; N18.30 only valid if 3a not applicable

**Exclusionary Hierarchy:**
- Applied post-submission by CMS
- More severe HCC excludes less severe (e.g., CKD Stage 5 excludes Stage 4)
- Multiple diabetes complications: More specific diagnosis preferred

### 10.3 Data Quality Metrics

**Plans Should Monitor:**
- Claim acceptance rate (% submitted that process)
- Diagnosis code rejection rate (% diagnoses rejected)
- HCC capture rate (% HCCs submitted vs. CMS-calculated average)
- Duplicate encounter rate (% duplicates detected and rejected)
- Timeliness metrics (% submitted by deadline)

**Industry Benchmarks:**
- Acceptance rate: 92-98% (depends on data integration maturity)
- Diagnosis rejection: 2-8%
- Timeliness: >95% by final deadline

### 10.4 Validation Best Practices for Integration Systems

**Pre-Submission Validation:**
1. Enrollment verification (verify beneficiary enrolled DOS)
2. Provider validation (NPI active, aligned)
3. Code validity checks (ICD-10 active, code exists)
4. Specificity checks (highest digit level coded)
5. Duplicate detection (flag exact/near-duplicates)
6. CCI edit compliance (check CPT code combinations)
7. Service-to-diagnosis linking (ensure eligible encounter)

**Post-Submission Tracking:**
1. MAO-002 review for rejection patterns
2. Error code trending
3. Corrective action for systemic issues
4. Re-submission of corrected records before deadline

---

## 11. CMS FILTERING LOGIC AND HCC MAPPING

### 11.1 CMS Encounter Filtering Process

**Step 1: Determine Encounter Eligibility**
- Service date must fall within plan enrollment period
- Encounter type must have associated diagnosis codes (professional, institutional, lab)
- Exclude administrative-only visits (registration, authorization)

**Step 2: CPT/HCPCS Code Filtering**
- CMS maintains official list of acceptable CPT/HCPCS codes for risk adjustment
- If ANY service line on encounter includes acceptable code → diagnoses from all service lines eligible
- Common eligible codes:
  - Evaluation & Management (99201-99499 series)
  - Surgery and procedures (99000-99607 plus CPT surgical range)
  - Laboratory and pathology (80000-89999)
  - Radiology (70000-79999)
  - Preventive visits (99381-99429)

**Step 3: Diagnosis Code Validation**
- Diagnosis code must be valid ICD-10-CM code
- Code must be active on date of service
- Code must not be excluded from HCC model
- ~9,700 of 72,748 ICD-10-CM codes are allowable

**Step 4: HCC Mapping**
- Valid diagnosis code mapped to condition category (CC)
- CC grouped into HCC (hierarchical rule application)
- HCC assigned RAF weight factor

### 11.2 Hierarchical Condition Categories (V28)

**Current CMS Model:** Version 28 (effective Jan 1, 2026)

**Structure Changes from V24:**
- HCC categories increased from 86 to 115
- Valid diagnosis codes reduced from 9,797 to 7,770
- Recoded all ICD-10 mappings for alignment with V28 HCC structure
- Projected impact: -3.12% average RAF score reduction

**Constrained Weighting (V28 Changes):**
Certain disease severity levels assigned same coefficient:

```
Diabetes Conditions (HCC 36, 37, 38):
  All assigned: 0.166 RAF factor
  Rationale: Uncomplicated vs. complicated have similar treatment cost

Heart Failure (HCC 224, 225, 226):
  All assigned: 0.36 RAF factor
  Eliminates incentive to up-code severity

Dementia (HCC 125, 126, 127):
  All assigned: 0.341 RAF factor
```

### 11.3 HCC-to-Diagnosis Code Mapping Example

```
ICD-10 Code → Condition Category → HCC → RAF Factor

N18.4 (CKD Stage 4) → CC145 → HCC137 → 0.327
N18.5 (CKD Stage 5) → CC146 → HCC136 → 0.419
N18.9 (CKD unspecified) → CC147 → HCC138 → 0.197

E11.9 (Type 2 Diabetes w/o complications) → CC17 → HCC36 → 0.166
E11.22 (Type 2 Diabetes w/ diabetic chronic kidney disease) → CC18 → HCC37 → 0.166
E11.65 (Type 2 Diabetes w/ hyperglycemia) → CC19 → HCC36 → 0.166
```

**Hierarchical Exclusions:**
- Patient with both N18.4 (CKD Stage 4) and N18.5 (CKD Stage 5): Only N18.5 + HCC136 counted
- Patient with E11.9 and E11.22: Higher severity HCC37 applies, lower HCC36 excluded

### 11.4 RAF Score Baseline and Weighting

**Baseline:** RAF = 1.0
- Represents average Medicare beneficiary
- Associated annual medical spend: ~$10,402.34

**Calculation Formula:**
```
Patient RAF = Demographic Base + Sum(HCC Weights) + Interactions
  - Demographic Base: Age, gender, Medicaid status components
  - HCC Weights: Factor for each applicable HCC
  - Interactions: Multi-morbidity adjustment factors
```

**Example RAF Calculation:**
```
Patient: 74-year-old male, non-Medicaid

Demographic Base:         1.029
HCC137 (CKD Stage 4):    +0.327
HCC38 (Diabetes w/comp): +0.166
HCC227 (Hypertension):   +0.075
Interaction factors:     +0.032
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total RAF:               1.629

CMS Payment = 1.629 × Base Rate
```

---

## 12. TECHNICAL ARCHITECTURE FOR RAF DATA INTEGRATION

### 12.1 System Components

```
┌─────────────────────────────────────────────────────────┐
│                    EHR/Billing Systems                  │
│  (Epic, Cerner, Athenahealth, OpenEMR, Claims Scrubs)   │
└──────┬──────────────────────────────────────────────────┘
       │
       ├─ HL7 V2 Messages (ADT, DG1 segments)
       ├─ FHIR REST APIs (Condition, Medication resources)
       ├─ 837P/837I Claims (EDI format)
       └─ Bulk Data Exports (NDJSON files)
       │
┌──────v──────────────────────────────────────────────────┐
│           Data Integration Layer                         │
│  - Message parsing (HL7, EDI, JSON)                     │
│  - Duplicate detection                                  │
│  - Enrollment validation                                │
│  - NDC/code lookups                                     │
└──────┬──────────────────────────────────────────────────┘
       │
┌──────v──────────────────────────────────────────────────┐
│          Diagnosis Code Validation                       │
│  - ICD-10 code validity (active on DOS)                 │
│  - Specificity checking                                 │
│  - CPT/HCPCS eligibility filtering                      │
│  - Laterality validation                                │
│  - Duplicate diagnosis detection                        │
└──────┬──────────────────────────────────────────────────┘
       │
┌──────v──────────────────────────────────────────────────┐
│          HCC Mapping and Hierarchy                       │
│  - Map diagnosis to HCC (using V28 crosswalk)          │
│  - Apply hierarchical exclusions                        │
│  - Handle constrained weightings                        │
│  - Medication-to-RXC mapping                            │
└──────┬──────────────────────────────────────────────────┘
       │
┌──────v──────────────────────────────────────────────────┐
│          RAF Score Calculation                          │
│  - Compile HCC list per beneficiary                    │
│  - Apply demographic factors                           │
│  - Sum RAF weights                                     │
│  - Apply interaction factors                           │
└──────┬──────────────────────────────────────────────────┘
       │
┌──────v──────────────────────────────────────────────────┐
│          Submission & Reporting                         │
│  - Generate 837P/837I files                            │
│  - CMS EDPS submission                                  │
│  - MAO-001/002/004 report processing                   │
│  - RADV audit preparation                               │
└──────────────────────────────────────────────────────────┘
```

### 12.2 Data Source Integration Specifics

**Claims Integration (837P/837I):**
- Parse EDI format (X12 standard)
- Extract HI segments (diagnosis codes)
- Validate against CMS CLM (claim detail)
- Link diagnoses to CPT/HCPCS for eligibility filtering

**EHR FHIR Integration:**
- OAuth 2.0 authentication setup
- FHIR Condition resource queries
- Bulk export scheduling (daily/weekly batches)
- Parse NDJSON response format
- Map FHIR codes to ICD-10-CM

**HL7 V2 Message Integration:**
- Inbound listener for ADT/DG1 messages
- Segment parser for MSH (header), DG1 (diagnosis), PR1 (procedure)
- Validation of required fields
- Store with timestamp for audit trail

**Pharmacy Claims:**
- NDC code validation against FDA database
- Medication to HCC/RXC mapping
- Quantity/days supply consistency
- Refill detection to prevent duplicates

### 12.3 Database Schema for RAF Integration

**Key Tables:**

**1. Beneficiary Table**
```sql
CREATE TABLE beneficiary (
  beneficiary_id VARCHAR(50),
  member_id VARCHAR(50),
  date_of_birth DATE,
  gender CHAR(1),
  medicaid_status VARCHAR(10),
  enrollment_start DATE,
  enrollment_end DATE,
  PRIMARY KEY (beneficiary_id)
);
```

**2. Diagnosis Table**
```sql
CREATE TABLE diagnosis_record (
  diagnosis_id BIGINT,
  beneficiary_id VARCHAR(50),
  icd10_code VARCHAR(7),
  encounter_date DATE,
  encounter_id VARCHAR(50),
  encounter_type VARCHAR(20),  -- 'office', 'inpatient', 'ed'
  provider_npi VARCHAR(10),
  source_system VARCHAR(20),  -- 'epic', 'claims', 'cerner'
  submitted_to_cms BOOLEAN,
  submission_date DATE,
  payment_year INT,
  validation_status VARCHAR(20),  -- 'valid', 'rejected', 'pending'
  rejection_reason VARCHAR(255),
  PRIMARY KEY (diagnosis_id),
  FOREIGN KEY (beneficiary_id) REFERENCES beneficiary(beneficiary_id)
);
```

**3. HCC Mapping Table**
```sql
CREATE TABLE hcc_mapping (
  icd10_code VARCHAR(7),
  model_version VARCHAR(10),  -- 'v24', 'v28'
  condition_category INT,
  hcc_code INT,
  raf_factor DECIMAL(6,4),
  hierarchical_exclusion VARCHAR(255),
  effective_date DATE,
  PRIMARY KEY (icd10_code, model_version)
);
```

**4. Encounter Table**
```sql
CREATE TABLE encounter (
  encounter_id VARCHAR(50),
  beneficiary_id VARCHAR(50),
  dos DATE,
  place_of_service VARCHAR(20),
  encounter_type VARCHAR(20),
  primary_procedure_code VARCHAR(10),
  submitted_to_cms BOOLEAN,
  cms_status VARCHAR(20),  -- 'accepted', 'rejected'
  cms_error_code VARCHAR(50),
  PRIMARY KEY (encounter_id),
  FOREIGN KEY (beneficiary_id) REFERENCES beneficiary(beneficiary_id)
);
```

**5. RAF Score Table**
```sql
CREATE TABLE raf_score (
  raf_record_id BIGINT,
  beneficiary_id VARCHAR(50),
  payment_year INT,
  demographic_factor DECIMAL(6,4),
  hcc_sum DECIMAL(8,4),
  interaction_factor DECIMAL(6,4),
  total_raf DECIMAL(8,4),
  calculation_date DATETIME,
  submission_date DATE,
  cms_validated BOOLEAN,
  cms_final_raf DECIMAL(8,4),
  PRIMARY KEY (raf_record_id),
  FOREIGN KEY (beneficiary_id) REFERENCES beneficiary(beneficiary_id)
);
```

### 12.4 Integration Implementation Considerations

**Data Quality Checkpoints:**

1. **Ingestion Phase:**
   - Validate source message format
   - Check required fields present
   - Reject malformed records
   - Log validation errors

2. **Enrichment Phase:**
   - Look up ICD-10 code validity
   - Cross-reference CPT codes for eligibility
   - Verify beneficiary enrollment status
   - Check for duplicates (within source, across sources)

3. **Mapping Phase:**
   - Apply HCC crosswalk (with version matching)
   - Enforce hierarchical rules
   - Calculate RAF factor
   - Track audit trail (source, timestamp, approver)

4. **Submission Phase:**
   - Format encounters for 837P/837I
   - Apply CMS edit rules pre-submission
   - Generate audit report
   - Track submission deadlines

**Testing Requirements:**
- Unit tests: Code validation, hierarchy logic, RAF calculation
- Integration tests: End-to-end diagnosis submission
- EDPS response testing: Parse MAO-002/004 reports
- Performance testing: Batch processing at scale (millions of diagnoses)
- RADV readiness: Test medical record assembly and audit trail

---

## 13. SUMMARY TABLE: DATA SOURCE SPECIFICATIONS

| Source | Format | Diagnosis Data | Key Fields | Frequency | Validation Rules |
|--------|--------|---|---|---|---|
| **837P Claims** | EDI X12 | HI segment (ABK/ABF) | NPI, DOS, CPT, ICD10 | Per claim | Specificity, active code, eligible CPT |
| **837I Claims** | EDI X12 | UB-04 FL67+67A-67Q | Facility, DOS, Type-of-bill | Per claim | POA, specificity, active code |
| **OpenEMR** | FHIR R4 | Condition resource | code.coding, clinicalStatus, encounter | Real-time/bulk | Active status, date range |
| **Epic** | HL7 V2 ADT | DG1 segment | Code, type, POA, DOS | Real-time | Code validity, active on DOS |
| **Cerner/Oracle** | FHIR R4 or HL7 V2 | Condition/DG1 | code, status, encounter | Real-time/bulk | Active status, face-to-face |
| **Athenahealth** | REST API/FHIR | Problem list/Condition | ICD10, status, encounter | Real-time/bulk | Clinical status, date range |
| **Lab Results** | HL7 ORU or FHIR DiagnosticReport | Referenced in Condition | LOINC, value, date | Per result | Date within 12 mo, proper units |
| **Pharmacy Claims** | 837P with NDC | Implicit (medication-to-diagnosis) | NDC, DOS, quantity, days supply | Per fill | NDC valid, quantity consistent, no duplicates |

---

## 14. REGULATORY AND COMPLIANCE CONSIDERATIONS

### 14.1 RADV Audit Risk Mitigation

**Audit Timeline (Payment Year Cycle):**
- CMS selects samples of beneficiaries (top quartile risk scores)
- Health plans have ~25 weeks to gather medical records
- Medical record submission window: April 13 - August 28 (typical for PY 2020)
- CMS conducts reviews and issues findings

**Documentation Requirements for HCC Support:**
- Every submitted HCC must have supporting medical record
- MEAT documentation (Monitor, Evaluate, Assess, Treat) required
- Face-to-face encounter mandatory
- Lab/procedure results must support diagnosis specificity
- Billing codes must match documented conditions

**High-Risk HCC Codes (Frequent Audit Targets):**
- Unspecified CKD (N18.9) without eGFR → audit failure 90% of time
- Diabetes without HbA1c or glucose documentation
- Heart failure without ejection fraction
- Anemia without hemoglobin
- Pulmonary hypertension without right heart catheterization findings

### 14.2 Data Governance and Privacy

**HIPAA Compliance:**
- De-identification for testing/analytics
- Access controls by role (clinician vs. coder vs. analyst)
- Audit logs for all data access
- Encryption in transit and at rest

**Interoperability Regulations:**
- ONC Cures Act compliance (FHIR, no information blocking)
- CMS Conditions of Participation for data exchange
- State privacy laws (e.g., California CCPA considerations)

### 14.3 Data Retention Requirements

**Recommended Retention:**
- Claims/encounter records: 10 years
- Medical records supporting HCC: Minimum 6 years (RADV cycle + 2 years buffer)
- RAF calculation audit trail: 7 years minimum
- EDPS submission records: 7 years

---

## REFERENCES AND AUTHORITATIVE SOURCES

**CMS Official Documentation:**
- [CMS Risk Adjustment](https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment)
- [CMS DIY Risk Adjustment Software](https://www.cms.gov/files/document/cy2023-diy-instructions-08222023.pdf)
- [HHS Encounter Data Diagnosis Filtering Logic](https://www.hhs.gov/guidance/sites/default/files/hhs-guidance-documents/FinalEncounterDataDiagnosisFilteringLogic.pdf)
- [CMS Medical Record Reviewer Guidance](https://www.cms.gov/research-statistics-data-and-systems/monitoring-programs/medicare-risk-adjustment-data-validation-program/other-content-types/radv-docs/medical-record-reviewer-guidance.pdf)

**Standards and Interoperability:**
- [HL7 FHIR Overview](https://www.hl7.org/fhir/overview.html)
- [ONC FHIR Information](https://www.healthit.gov/topic/standards-technology/standards/fhir)
- [Office of the National Coordinator (ONC)](https://www.healthit.gov/)

**EHR Integration Guides:**
- [OpenEMR FHIR Implementation](https://github.com/openemr/openemr)
- [Epic Open Health](https://open.epic.com/)
- [Oracle Health Millennium APIs](https://docs.oracle.com/en/industries/health/millennium-platform-apis/)
- [Athenahealth Developer Portal](https://www.athenahealth.com/developer-portal)

**Clinical Coding and Risk Adjustment:**
- [American Academy of Family Physicians (AAFP) - HCC Coding](https://www.aafp.org/family-physician/practice-and-career/getting-paid/coding/hierarchical-condition-category.html)
- [NCQA HEDIS Measures](https://www.ncqa.org/hedis/measures/)
- [HCC Intelligence - RAF and HCC Coding Guide](https://www.hccinstitute.org/)
- [Inferscience - HCC Coding and RAF Analysis](https://www.inferscience.com/)

**Audit and Validation:**
- [CMS RADV Program](https://www.cms.gov/data-research/monitoring-programs/medicare-risk-adjustment-data-validation-program)
- [Medicare Advantage Risk Adjustment Data Validation Final Rule](https://www.cms.gov/newsroom/fact-sheets/medicare-advantage-risk-adjustment-data-validation-final-rule-cms-4185-f2-fact-sheet)

---

**Document Version:** 1.0  
**Last Updated:** April 2026  
**Classification:** Technical Reference  
**Intended Audience:** Data architects, integration engineers, healthcare IT professionals
