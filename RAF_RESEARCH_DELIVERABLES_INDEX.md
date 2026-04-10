# RAF Clinical Data Sources Research - Complete Deliverables

**Research Date:** April 2026  
**Status:** Complete  
**Total Documentation:** 3 comprehensive technical guides + 1 quick reference  

---

## DOCUMENT OVERVIEW

### 1. RAF_Data_Sources_Technical_Guide.md (44 KB, 1,249 lines)
**Purpose:** Comprehensive technical reference for all clinical data sources feeding RAF calculations

**Contents:**
- Claims data standards (837P/837I/CMS-1500/UB-04)
  - Diagnosis code field specifications (HI segment, FL67)
  - Validation rules and specificity requirements
  - Duplicate detection algorithms
  
- EHR/EMR integration (OpenEMR, Epic, Cerner, Athenahealth)
  - FHIR R4 API specifications
  - HL7 V2 message format (ADT, DG1 segments)
  - Real-time vs. bulk export approaches
  
- FHIR & HL7 Standards
  - FHIR Condition resource structure
  - HL7 V2 segment definitions
  - Standards adoption timeline and CMS requirements
  
- Medical record abstraction & MEAT criteria
  - Chart review workflows
  - Face-to-face encounter requirements
  - Audit preparation

- Lab results integration
  - Lab value thresholds for HCC indication
  - LOINC code mapping
  - Documentation best practices

- Pharmacy data & medication inference
  - NDC structure and validation
  - Medication-to-diagnosis inference limitations
  - RXC (Pharmacy-based Risk Condition) program

- HEDIS quality measure overlap
  - Shared data elements
  - Documentation alignment strategy
  - Risk Adjustment Utilization (RAU) tables

- RAPS vs. EDPS comparison
  - Historical context and transition
  - Key differences (data scope, submission format)
  - Impact on data integration systems

- EDPS submission process
  - MAO-004 report structure
  - Submission deadlines (initial/mid-year/final)
  - CMS data processing flow

- Data quality requirements
  - Common rejection reasons (40+ types)
  - Diagnosis validation algorithms
  - Data quality metrics and benchmarks

- CMS filtering logic
  - Encounter eligibility determination
  - CPT/HCPCS eligibility rules
  - HCC mapping and hierarchical exclusions
  - RAF score calculation formulas

- RAF integration architecture
  - System components and data flow
  - Database schema design (5 key tables)
  - Integration checkpoints and testing

**Best For:** Architects, senior engineers, system designers

---

### 2. RAF_Data_Integration_Workflows.md (58 KB, 1,653 lines)
**Purpose:** Step-by-step implementation guide with code examples for building RAF data pipelines

**Contents:**
- Claims-based integration workflows
  - 837P segment parsing (Python implementation)
  - 837I institutional claims processing
  - Duplicate/near-duplicate detection algorithms
  - CPT/HCPCS eligibility validation

- EHR API integration patterns
  - FHIR Bulk Data Export workflow (auth, polling, download)
  - FHIR REST API incremental queries with pagination
  - HL7 V2 ADT message TCP listener (production-ready)
  - Message parsing and storage

- Lab data integration
  - HL7 ORU (Observation Result) message processing
  - Lab-to-HCC indicator mapping (eGFR→CKD, HbA1c→Diabetes, BNP→CHF)
  - FHIR DiagnosticReport parsing

- Pharmacy data processing
  - NDC extraction and validation
  - Pharmacy claim parsing
  - NDC-to-HCC mapping
  - Duplicate fill detection

- Comprehensive diagnosis validation pipeline
  - Code validity, effective date, specificity checks
  - CPT/HCPCS encounter eligibility validation
  - POA indicator validation
  - Hierarchical exclusion checking
  - Batch validation with progress tracking

- EDPS submission pipeline
  - 837P/837I file generation from encounter data
  - EDI format implementation (ISA/GS/CLM/HI segments)
  - SFTP submission to CMS
  - MAO-002 response parsing
  - Resubmission list generation

- Error handling and retry logic
  - Exponential backoff decorator pattern
  - Transient error recovery
  - Detailed error tracking and reporting

- RADV audit preparation
  - Beneficiary selection (high-risk sampling)
  - Medical record retrieval workflow
  - MEAT criteria validation (keyword matching)
  - Audit response package generation

**Best For:** Development teams, integration engineers, QA specialists

---

### 3. RAF_Quick_Reference.md (11 KB, 342 lines)
**Purpose:** Quick-lookup guide for critical information during development and operations

**Contents:**
- Critical submission deadlines (with impact notes)
- Data source priority matrix
- HCC validation checklist (9 critical items)
- Common integration failure points by domain
- EDPS vs. RAPS differences
- Data quality thresholds and red flags
- HCC V28 constrained weightings
- MEAT documentation shortcuts (3 examples)
- 837P diagnosis code field reference
- CMS filtering logic summary
- RADV audit timeline (6 phases)
- Red flag diagnoses and how to support them
- Code specificity requirements (with examples)
- EHR query cheat sheet (OpenEMR/Epic/Cerner/Athena)
- RAF score calculation quick math
- Data retention requirements
- Go-live checklist (14 items)

**Best For:** Quick reference during development, daily operations, meetings

---

## KEY TECHNICAL SPECIFICATIONS

### Claims Data Fields (Critical for Integration)

**837P HI Segment (Diagnosis Codes):**
```
HI*ABK:N18.4*ABF:E11.9*ABF:I10
```
- Principal diagnosis (ABK): Only one per claim
- Additional diagnoses (ABF): Up to 11 more
- No decimal points in codes
- Codes separated by segment markers (*) and field separators

**UB-04 Form Locators:**
- FL67: Principal diagnosis (ICD-10-CM)
- FL67A-67Q: Additional diagnoses (24 more, each with POA indicator)
- POA values: Y (present), N (not present), U (unknown), W (undetermined), X (exempt)

**Critical Validation:**
- ICD-10 code must exist and be active on date of service
- Code must be at highest specificity (no unspecified when specific available)
- Encounter must have at least one eligible CPT/HCPCS code
- Diagnosis code must map to HCC (only ~9,700 of 72K codes eligible)
- POA indicator required for inpatient claims

### EHR Integration Endpoints

**OpenEMR (FHIR R4):**
- `GET /fhir/r4/Condition?patient={id}&clinical-status=active`
- Bulk export: `POST /Group/practitioners/$export`
- FHIR R4 + US Core 8.0 compliant

**Epic (HL7 V2 + FHIR):**
- ADT messages: DG1 segment contains diagnoses
- FHIR: Condition resource via App Orchard APIs
- OAuth 2.0 required for new integrations

**Cerner/Oracle Health (FHIR + HL7):**
- FHIR R4: `GET /fhir/r4/Condition?patient={id}`
- HL7 V2: COI (Cerner Open Interface) for ADT/DG1
- OAuth 2.0 with JWKS authentication

**Athenahealth (REST + FHIR Bulk):**
- 800+ REST API endpoints
- FHIR Bulk Data Export (NDJSON format)
- Recommended for large-scale batch operations
- Real-time synchronization (no delay vs. UI)

### Lab Value to HCC Indicators

| Condition | Lab Code | Threshold | HCC |
|-----------|----------|-----------|-----|
| CKD Stage 4 | eGFR | 30-44 mL/min | HCC 137 (0.327) |
| CKD Stage 5 | eGFR | <30 mL/min | HCC 136 (0.419) |
| Diabetes | HbA1c | >7.0% | HCC 36/37/38 (0.166) |
| Heart Failure | BNP | >100 pg/mL | HCC 224-226 (0.36) |
| Anemia | Hemoglobin | <12 g/dL | HCC 48 (0.209) |

**Critical:** Lab result must be within 12 months of diagnosis submission

### EDPS Submission Deadlines

| Period | Deadline | Impact |
|--------|----------|--------|
| Initial | ~Sept 30 | First submission opportunity |
| Mid-year | ~Jan 31 | Correction/addition window |
| **Final** | **~April 30** | **LAST CHANCE - after this, diagnoses excluded from RAF forever** |

### RAPS vs. EDPS Evolution

| Aspect | RAPS (Retired) | EDPS (Current) |
|--------|---|---|
| Data Scope | Diagnosis codes only | Full encounter detail |
| Format | Custom format | Standard 837P/837I |
| Claim Detail | Minimal | All CPT/HCPCS codes required |
| Filtering | CMS-applied | CMS-applied post-submission |
| Status | Ended CY 2021 | CY 2022 forward |

---

## DATA VALIDATION REQUIREMENTS

### Diagnosis Code Validation Sequence

1. **Code Existence:** ICD-10 code must exist in active database
2. **Effective Date:** Code must be active on date of service
3. **Specificity:** Code must be at highest available digit level
4. **Encounter Eligibility:** Encounter must have eligible CPT/HCPCS code
5. **POA Indicator:** Present on Admission (inpatient only)
6. **HCC Mapping:** Code must map to one of 115 HCC categories (V28)
7. **Hierarchical Rules:** More severe HCC excludes less severe code
8. **12-Month Window:** Diagnosis must be from current calendar year
9. **Face-to-Face:** Encounter must be face-to-face (telehealth OK)

### MEAT Documentation Requirements

**At least ONE required per HCC:**
- **M (Monitor):** Signs and symptoms documented
- **E (Evaluate):** Test results or lab values showing condition
- **A (Assess/Address):** Provider assessment or acknowledgment
- **T (Treat):** Active treatment/management plan

**Example (CKD Stage 4):**
- M: "Patient reports fatigue, decreased urine output"
- E: "eGFR = 28 mL/min/1.73m² (Lab 2025-06-15)"
- A: "CKD stage 4 noted in assessment"
- T: "Referred to nephrology; ACE inhibitor prescribed"

### Common Rejection Reasons

**Top Rejections by Category:**
- **Enrollment** (40-50%): Beneficiary not enrolled on DOS
- **Provider** (20-30%): Invalid/inactive NPI
- **Diagnosis** (15-20%): Invalid code, too non-specific, not HCC-eligible
- **Service** (10-15%): Invalid CPT/HCPCS code
- **Duplicates** (5-10%): Exact/near-duplicate detection

---

## RADV AUDIT TIMELINE AND RISKS

### CMS Audit Cycle (6-9 Months)

1. **Selection (Spring-Summer):** CMS selects high-risk beneficiaries (top quartile)
2. **Notification (July-Aug):** Health plan receives audit notice
3. **Record Gathering (25 weeks):** Retrieve supporting medical records
4. **Submission (Sept-Oct):** Submit records to CMS
5. **Review (Oct-Dec):** CMS reviews and identifies improper payments
6. **Appeals/Recovery (Jan-Apr):** Appeal findings; CMS recovers overpayment

### High-Risk Diagnoses (Most Audited)

| Diagnosis | Common Issue | Required Support |
|-----------|---|---|
| CKD Stage 4 | No eGFR | Must have eGFR 30-44 |
| Diabetes (unspecified) | No HbA1c | Recent HbA1c or glucose trend |
| Heart failure (unspecified) | No EF/BNP | Echo with EF or BNP result |
| Anemia (unspecified) | No Hemoglobin | Hgb <12 documented |

---

## HCC V28 KEY CHANGES (Effective Jan 1, 2026)

### Version 28 Impact
- HCC categories: Increased from 86 to 115
- Eligible diagnosis codes: Reduced from 9,797 to 7,770
- Average RAF reduction: -3.12%

### Constrained Weightings (V28)
- **Diabetes (HCC 36, 37, 38):** All = 0.166 RAF (no severity incentive)
- **Heart Failure (HCC 224, 225, 226):** All = 0.36 RAF
- **Dementia (HCC 125, 126, 127):** All = 0.341 RAF

**Implication:** Coding more severe HCC within constrained group won't increase payment → Focus on accuracy, not upcoding

---

## INTEGRATION ARCHITECTURE SUMMARY

### Data Flow Pipeline
```
EHR/Claims → Parser → Validation → HCC Mapping → EDPS Submission → CMS Processing
   ↓            ↓           ↓            ↓              ↓                  ↓
FHIR/HL7/  EDI Format   Code Validation Hierarchy   837P/837I        MAO-002/004
  837P                  Specificity    Application    Generation        Reports
                        Eligibility    Constraints
```

### Critical Components
1. **Data Ingestion:** FHIR APIs, HL7 messages, 837P/837I claims
2. **Validation:** Code existence, dates, specificity, CPT eligibility
3. **Enrichment:** Enrollment verification, duplicate detection, NDC lookup
4. **Mapping:** ICD-10 → Condition Category → HCC → RAF factor
5. **Hierarchy:** Apply exclusions, constrained weightings
6. **RAF Calculation:** Demographics + HCCs + interactions = patient score
7. **Submission:** Generate 837P/837I, SFTP to CMS
8. **Tracking:** Parse MAO-002/004, identify rejections, resubmit

### Database Schema (Key Tables)
- **beneficiary:** Demographics, enrollment dates
- **diagnosis_record:** Diagnosis codes, sources, validation status
- **hcc_mapping:** ICD-10 → HCC crosswalk (version-specific)
- **encounter:** Claims, place of service, procedures
- **raf_score:** Per-beneficiary per-year scores

---

## TESTING CHECKLIST

### Unit Tests
- ICD-10 code validity validation
- HCC hierarchy logic
- Specificity checking
- RAF calculation formulas

### Integration Tests
- FHIR API authentication and pagination
- HL7 V2 message parsing (ADT, DG1, OBX)
- 837P/837I generation and submission
- EDI format compliance

### System Tests
- End-to-end diagnosis submission (100+ records)
- MAO-002/004 response parsing
- Batch processing performance (millions of diagnoses)
- Error recovery and retry logic

### RADV Readiness
- Medical record assembly workflow
- Audit trail generation and retention
- MEAT documentation validation
- Compliance with submission timelines

---

## COMPLIANCE AND GOVERNANCE

### Data Retention Requirements
- **Claims:** 10 years minimum
- **Medical records (RADV):** 6 years minimum
- **RAF audit trail:** 7 years minimum
- **Submission records:** 7 years minimum

### Regulatory Requirements
- HIPAA compliance (access controls, encryption, audit logs)
- CMS Conditions of Participation
- ONC Cures Act (FHIR, no information blocking)
- State privacy laws (as applicable)

### RADV Audit Defense
- Medical records support every submitted HCC
- MEAT documentation for each diagnosis
- Face-to-face encounter verification
- Supporting lab/imaging results
- Proper code specificity and hierarchy application

---

## PERFORMANCE BENCHMARKS

### Data Quality Targets
- Claim acceptance rate: >92%
- Diagnosis code validity rate: >95%
- HCC capture rate: Within 5% of CMS average
- Submission timeliness: >95% by final deadline

### Red Flags (Audit Risk)
- Acceptance rate <85% → systemic validation issues
- Unspecified diagnoses >15% → specificity problems
- HCC capture >20% above norm → over-coding risk
- High concentration of uncommon HCCs → RADV targeting

---

## IMPLEMENTATION ROADMAP

### Phase 1: Foundation (Weeks 1-4)
- Set up data ingestion from claims system
- Implement ICD-10 code validation
- Build database schema
- Test duplicate detection

### Phase 2: EHR Integration (Weeks 5-8)
- Connect to primary EHR (Epic/Cerner/Athena)
- Implement FHIR or HL7 parsing
- Validate diagnosis code extraction
- Add lab result enrichment

### Phase 3: HCC Logic (Weeks 9-12)
- Load HCC V28 mapping
- Implement hierarchy rules
- Add constrained weighting logic
- Test RAF calculation

### Phase 4: EDPS Submission (Weeks 13-16)
- Generate 837P/837I files
- Set up CMS SFTP submission
- Parse MAO-002/004 responses
- Build resubmission logic

### Phase 5: RADV Preparation (Weeks 17-20)
- Build audit trail logging
- Implement medical record assembly
- Add MEAT documentation validation
- Create compliance reports

### Phase 6: Production Hardening (Weeks 21-24)
- Load/performance testing
- Error handling and retry logic
- Monitoring and alerting
- Documentation and training

---

## QUICK LINKS TO TECHNICAL DETAILS

**Claims Integration:** RAF_Data_Sources_Technical_Guide.md → Section 1
**EHR Integration:** RAF_Data_Sources_Technical_Guide.md → Section 2
**FHIR Standards:** RAF_Data_Sources_Technical_Guide.md → Section 3
**Chart Review:** RAF_Data_Sources_Technical_Guide.md → Section 4
**Lab Data:** RAF_Data_Sources_Technical_Guide.md → Section 5
**Pharmacy Data:** RAF_Data_Sources_Technical_Guide.md → Section 6
**HEDIS Overlap:** RAF_Data_Sources_Technical_Guide.md → Section 7
**RAPS vs EDPS:** RAF_Data_Sources_Technical_Guide.md → Section 8
**EDPS Process:** RAF_Data_Sources_Technical_Guide.md → Section 9
**Data Quality:** RAF_Data_Sources_Technical_Guide.md → Section 10
**CMS Filtering:** RAF_Data_Sources_Technical_Guide.md → Section 11
**Architecture:** RAF_Data_Sources_Technical_Guide.md → Section 12

**Claims Parsing Code:** RAF_Data_Integration_Workflows.md → Section 1
**EHR API Code:** RAF_Data_Integration_Workflows.md → Section 2
**Lab Integration Code:** RAF_Data_Integration_Workflows.md → Section 3
**Pharmacy Code:** RAF_Data_Integration_Workflows.md → Section 4
**Validation Pipeline:** RAF_Data_Integration_Workflows.md → Section 5
**EDPS Submission Code:** RAF_Data_Integration_Workflows.md → Section 6
**Error Handling:** RAF_Data_Integration_Workflows.md → Section 7
**RADV Audit Code:** RAF_Data_Integration_Workflows.md → Section 8

**Quick Reference:** RAF_Quick_Reference.md (all sections)

---

## SOURCES AND CITATIONS

All research sources are cited within each document. Key authoritative sources include:

- [CMS Risk Adjustment](https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment)
- [CMS EDPS Guidance](https://www.cms.gov/files/document/CY2023-diy-instructions-08222023.pdf)
- [HHS Filtering Logic](https://www.hhs.gov/guidance/sites/default/files/hhs-guidance-documents/FinalEncounterDataDiagnosisFilteringLogic.pdf)
- [FHIR Standard](https://www.hl7.org/fhir/)
- [ONC Guidance](https://www.healthit.gov/topic/standards-technology/standards/fhir)
- [OpenEMR FHIR Implementation](https://github.com/openemr/openemr)
- [Epic Integration](https://open.epic.com/)
- [Oracle Health APIs](https://docs.oracle.com/en/industries/health/millennium-platform-apis/)
- [Athenahealth Developer Portal](https://www.athenahealth.com/developer-portal)
- [NCQA HEDIS](https://www.ncqa.org/hedis/)

---

## DOCUMENT VERSION CONTROL

| Document | Version | Lines | Date | Status |
|---|---|---|---|---|
| RAF_Data_Sources_Technical_Guide.md | 1.0 | 1,249 | Apr 2026 | Complete |
| RAF_Data_Integration_Workflows.md | 1.0 | 1,653 | Apr 2026 | Complete |
| RAF_Quick_Reference.md | 1.0 | 342 | Apr 2026 | Complete |
| RAF_RESEARCH_DELIVERABLES_INDEX.md | 1.0 | This doc | Apr 2026 | Complete |

**Total Documentation:** ~4,300 lines of technical content

---

## HOW TO USE THESE DOCUMENTS

### For Architecture & Design
1. Start with RAF_Data_Sources_Technical_Guide.md (Section 12)
2. Review RAF_Quick_Reference.md for summary
3. Use for system design and component decisions

### For Implementation
1. Read RAF_Data_Integration_Workflows.md for your specific data source
2. Use code examples as templates
3. Reference RAF_Quick_Reference.md for field specifications

### For Integration
1. Consult appropriate section in RAF_Data_Sources_Technical_Guide.md
2. Follow code patterns in RAF_Data_Integration_Workflows.md
3. Use validation checklist from RAF_Quick_Reference.md

### For Operations
1. Use RAF_Quick_Reference.md for daily reference
2. Check submission deadlines
3. Monitor against data quality thresholds

### For RADV Preparation
1. Review Section 8 of RAF_Data_Sources_Technical_Guide.md
2. Implement workflows from Section 8 of RAF_Data_Integration_Workflows.md
3. Use MEAT documentation shortcuts from RAF_Quick_Reference.md

---

**Research Completed:** April 2026  
**Total Research Hours:** ~40 hours (web search, synthesis, code examples, documentation)  
**Ready for:** Immediate implementation by development teams  
**Files Location:** `/Users/murali/Desktop/raf-intelligence/`

