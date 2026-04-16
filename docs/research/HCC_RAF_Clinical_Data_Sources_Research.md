# Clinical Data Sources for HCC/RAF Scoring: Beyond Billing Codes
## Comprehensive Industry Research Report

**Last Updated:** March 2026
**Research Focus:** Clinical data sources, validation methodologies, and industry best practices for risk adjustment beyond ICD-10 billing codes

---

## Executive Summary

Healthcare organizations have evolved beyond relying solely on billing codes and clinical notes for HCC/RAF scoring. This research identifies **seven primary data source categories** that industry leaders use for comprehensive risk adjustment:

1. **Laboratory Values** - eGFR, bilirubin, AFP, BNP, HbA1c
2. **Vital Signs & Anthropometrics** - Blood pressure, BMI, weight, temperature
3. **Medication Reconciliation Data** - Active prescriptions revealing suspected conditions
4. **Problem Lists & Care Plans** - Clinical documentation from EHR systems
5. **Encounter Data** - Referral patterns, specialist visits, service utilization
6. **Social Determinants of Health (SDOH)** - Housing, food security, transportation
7. **Immunization Records & Quality Data** - HEDIS measures, preventive screening history

**Key Finding:** Industry leaders report that incorporating multi-source data validation reduces missed HCC captures by 30-50% and decreases retrospective coding needs.

---

## Part 1: Data Source Categories & HCC Applications

### 1. LABORATORY VALUES AS CLINICAL INDICATORS

#### eGFR (Estimated Glomerular Filtration Rate) - Chronic Kidney Disease
**HCC Codes Supported:** HCC 326-329 (CKD Stages 1-5)

**How It Works:**
- Specific eGFR values trigger CKD stage assignment
- Example: eGFR 28 = Stage 4 CKD (higher RAF weight than unspecified CKD)
- **Two separate eGFR measurements** required to change CKD stage classification
- Validates whether documentation of "Stage 4 CKD" actually exists in clinical reality

**Prospective vs. Retrospective:**
- **Prospective:** Pre-visit labs identify patients with unreported CKD stages
- **Retrospective:** Labs validate risk scores post-submission during RADV audits

**Clinical Indicator Status:**
Labs serve as objective clinical indicators that don't require coder interpretation—they're either present or not present in the medical record.

**Industry Best Practice:**
Organizations track lab result trending to identify patients progressing into higher CKD stages and proactively flag documentation needs during next encounter.

---

#### AFP (Alpha-Fetoprotein) - Hepatocellular Carcinoma (HCC Disease, not the coding model)

**Clinical Indicator Thresholds:**
- **>200 ng/mL:** Near 100% predictive of HCC diagnosis in cirrhotic patients
- **>400 ng/mL:** Diagnostic with appropriate imaging confirmation
- Referenced in [Hepatocellular Carcinoma Workup Guide](https://emedicine.medscape.com/article/197319-workup)

**Multiple Lab Markers for HCC Suspicion:**
- Elevated AST, ALT, alkaline phosphatase, bilirubin
- Decreased albumin
- Prolonged PT/PTT, low platelet count
- Elevated red cell distribution width (RDW)

---

#### BNP (B-Type Natriuretic Peptide) - Heart Failure

**Application:**
- BNP elevation indicates heart failure presence/severity
- Used alongside clinical documentation of "CHF" to validate whether condition is actually present
- Helps distinguish between "history of heart failure" vs. active heart failure requiring HCC coding

**MEAT Criteria Link:**
Lab results fulfill "E" (Evaluate) in MEAT—they show objective assessment of condition status.

---

#### HbA1c Testing - Diabetes Management

**Standard Practice:**
- HbA1c tested at least twice per year per guidelines
- Validates active diabetes management
- When combined with CKD, requires specific documentation of diabetes type and CKD stage

---

#### Liver Function Panel - Multiple HCC Conditions

**Common Indicators:**
- Elevated bilirubin = cirrhosis progression
- Elevated transaminases (AST/ALT) = liver disease activity
- Decreased albumin = advanced liver disease/poor nutritional status

---

### 2. VITAL SIGNS & ANTHROPOMETRICS

#### Blood Pressure Documentation

**Critical Finding:** Simple hypertension (I10) does NOT affect RAF scores.

**What DOES Affect Risk Scores:**
- Hypertension WITH heart disease (HCC code required)
- Hypertension WITH kidney disease (HCC code required)
- Specific documentation of these combinations is essential

**Use Case:**
BP readings demonstrate "M" (Monitor) element of MEAT criteria—objective monitoring of hypertensive control supports active management documentation for HCC coding.

---

#### BMI & Morbid Obesity (HCC 48)

**Critical Requirements:**
- **Specific BMI value must be documented** (not a range)
- Coders CANNOT calculate BMI from height/weight
- Example: Patient with morbid obesity + BMI 42 = RAF 0.273 (significant reimbursement impact)

**RAF Score Impact:**
A single properly documented BMI value directly impacts reimbursement—this is why BMI documentation is a high-priority gap closure target.

**Clinical Indicator Use:**
- Auto-alert systems flag patients with high BMI without "morbid obesity" HCC coding
- Pre-visit review identifies documentation gaps for upcoming patient visits

---

#### Temperature, Pulse, Respiration, O2 Saturation

**MEAT Connection:**
These vitals fulfill "M" (Monitor) element—demonstrating ongoing clinical monitoring of chronic conditions.

---

### 3. MEDICATION RECONCILIATION DATA

#### Medication as Suspected Condition Indicator

**Inferential Coding Principle:**
Medications indicate likely diagnoses even when not explicitly documented.

**Examples:**
- **Insulin or Metformin** → Type 2 Diabetes (HCC 23)
- **ACE inhibitors/ARBs** → Hypertension + possible CKD/heart disease
- **Loop diuretics** → Heart failure (HCC 85/86)
- **Antidepressants + PHQ-9 score** → Depression (HCC 155)
- **COPD inhalers (albuterol, tiotropium)** → COPD (HCC 111)
- **Warfarin/DOACs** → Atrial fibrillation (HCC 96)

**Prospective Application:**
Pre-visit medication list review identifies patients on condition-specific medications without corresponding HCC diagnoses coded.

**RADV Audit Perspective:**
Auditors look at medication lists to validate whether documented diagnoses align with actual therapeutic management. A patient on insulin should have diabetes documentation.

**Industry Tools:**
- Medication reconciliation systems flag "orphaned" diagnoses (medications without diagnosis codes)
- NLP systems extract medication names from notes and cross-reference against diagnosis codes

---

### 4. PROBLEM LIST VS. BILLING CODES

#### The Critical Distinction

**CMS Requirement:**
"An acceptable problem list must be comprehensive, show evaluation and treatment for each condition related to an ICD-10-CM code on the date of service, and be signed and dated by the physician or extender." (RADV guidance)

**Important Finding:**
Simply selecting a diagnosis code from a problem list is NOT sufficient documentation. The diagnosis code alone doesn't provide specific clinical information about the patient's condition or management.

#### MEAT & TAMPER Criteria

**MEAT (Monitor, Evaluate, Assess/Address, Treat):**
- Industry standard for validating HCC diagnosis support
- Only ONE element needed, but more elements strengthen support
- Example: Diabetes HCC requires documentation showing physician is:
  - **M**onitoring - reviewing lab results, checking glucose log
  - **E**valuating - assessing medication effectiveness
  - **A**ssess/Address - ordering tests or adjusting regimen
  - **T**reating - prescribing/modifying medications

**TAMPER (Treatment, Assessment, Monitor, Plan, Evaluate, Referral):**
- Used for diagnoses listed without clear active management
- Helps distinguish "history of" from current active conditions
- Example: "History of MI" vs. "MI with ongoing cardiac rehab" get different coding treatment

**Problem List Best Practices:**
1. Problem lists should reflect **active conditions** being treated
2. Each problem should have supporting MEAT documentation in current encounter notes
3. Problem lists must be reconciled at every visit (added, resolved, or inactive)
4. CMS expects clean, maintained lists—not historical accumulations

---

### 5. ENCOUNTER DATA: REFERRALS & SPECIALIST VISITS

#### Specialist Visit Patterns as Data Sources

**Key Insight:** Organizations can identify potential HCC codes correlated with specialist referral patterns.

**Examples:**
- **Cardiology referral** → Likely heart disease, arrhythmia, or heart failure coding gaps
- **Nephrology referral** → CKD documentation gaps
- **Pulmonology referral** → COPD or respiratory condition documentation gaps
- **Endocrinology referral** → Diabetes complexity or thyroid disease gaps

**Prospective Coding Application:**
30-50% reduction in retrospective coding needs when organizations plan structured visits and assessments that surface conditions not appearing in routine encounters.

**Member Onboarding Strategy:**
Risk adjustment programs identify members with specialist visits already in the system and proactively ensure corresponding HCC documentation captures from those encounters.

---

#### Referral Data Elements to Track

- **Referral source** (PCP vs. system-initiated)
- **Specialty type** (cardiology, nephrology, psychiatry, etc.)
- **Frequency** of specialist visits
- **Time between referral and encounter**
- **Diagnoses from specialist documentation**

**Best Practice:** Ensure PCP captures key findings from specialist notes in the primary encounter documentation—don't rely on specialist notes alone for HCC coding.

---

### 6. SOCIAL DETERMINANTS OF HEALTH (SDOH)

#### Current State: Limited Direct HCC Impact

**Important Finding:** Most current HCC risk adjustment models do NOT include SDOH codes in RAF calculations.

**However:**
- SDOH influences patient outcomes and disease management ability
- Organizations capturing SDOH improve quality reporting and care coordination
- SDOH codes are billable Z-codes (Z55-Z65) but don't directly reimburse

**SDOH Code Examples:**
- Z59.0 - Homelessness
- Z59.1 - Inadequate housing
- Z59.4 - Food insecurity
- Z59.7 - Lack of adequate transportation
- Z57.0-Z57.9 - Occupational exposure

**Link to HCC Coding:**
SDOH data improves **quality of risk adjustment** by explaining why patients may be non-compliant with treatment (food insecurity affects medication access, housing instability affects treatment adherence).

**Future Direction:**
As healthcare payment models evolve, SDOH is being incorporated into alternative risk adjustment frameworks beyond traditional CMS-HCC.

**Capture Method:**
- Screening questions during visits (standardized screening tools)
- Member health risk assessments
- Care coordination program enrollments
- Community resource referrals documented in EHR

---

### 7. IMMUNIZATION RECORDS & QUALITY MEASURES

#### HEDIS Measures & Risk Adjustment Alignment

**HEDIS Overview:**
NCQA's Healthcare Effectiveness Data & Information Set (HEDIS) includes 90+ measures across six domains:
1. Effectiveness of Care
2. Access/Availability of Care
3. Experience of Care
4. Utilization
5. Health Plan Descriptive Information
6. **Risk Adjustment Utilization**

**Accuracy Validation:**
HEDIS immunization measures showed >90% accuracy when compared with CDC gold standard (range 94.3%-99.7%), though hepatitis B and pneumococcal conjugate showed lower accuracy.

**Connection to Risk Adjustment:**
- Quality gaps correlate with risk adjustment accuracy
- Organizations with strong HEDIS performance typically have better risk adjustment documentation
- Some risk-adjustable conditions (e.g., immunocompromised status) correlate with immunization patterns

**Data Collection Enhancement:**
"Plans are allowed to select a random sample of the population and supplement claims data with data from medical records. By doing so, plans may identify additional immunizations and report more favorable and accurate rates."

**Immunization as Clinical Indicator:**
- Lack of age-appropriate immunizations might indicate immunocompromised status (HCC codes available)
- Influenza/pneumococcal vaccine status documents chronic disease/age-related risk

---

## Part 2: RAPS vs. EDPS - System Architecture & Transition

### RAPS (Risk Adjustment Processing System)

**Timeline Status:** Retiring; transition accelerating through 2025-2026

**Data Submitted:**
- Minimal data beyond diagnosis itself
- Limited service detail (no CPT codes, modifiers, revenue codes)
- Simpler format requirements

**Validation Complexity:**
- Basic format, logic, and content checks
- Simple enrollment and duplicate verification
- Diagnosis code validity checks only

**Current Use:**
- Legacy pathway still active but declining
- Organizations maintain dual RAPS/EDPS submissions during transition period
- Risk of extrapolation penalties if RAPS overstates actual patient burden

---

### EDPS (Encounter Data Processing System)

**Timeline Status:** PRIMARY system; 100% migration target by 2025

**Data Required (X12 837 5010 format):**
- **Demographic data** - demographics, enrollment status
- **Service line detail** - CPT codes, modifiers, revenue codes, place of service
- **Diagnosis codes** - Full ICD-10-CM reporting with encounter-level linkage
- **Service dates** - Exact dates of service
- **Provider identifiers** - NPI, taxonomy codes, credentials

**Validation Complexity (Much Stricter):**
1. Format validation (X12 837 standard compliance)
2. Logic editing (procedure code consistency, provider credentials)
3. Content editing (diagnosis code validity, coverage rules)
4. Clinical consistency editing (e.g., infant diagnosis codes for pediatric patients)
5. CCI (Correct Coding Initiative) edits
6. Duplicate encounter detection (using service dates + provider + diagnosis)

**Risk Adjustment Filtering:**
- CMS applies filtering logic post-submission
- Determines which diagnoses are "risk adjustment eligible"
- Removes invalid encounters, duplicate services, non-covered services

**Reporting Feedback:**
- **MAO-001:** Duplicate encounter detection with detailed line items
- **MAO-002:** Encounter-level processing results with RA flags
- **MAO-003:** Reject details with correction requirements

---

### Migration Timeline & Financial Impact

**Historical Blend Ratios:**
- 2015: 90% RAPS / 10% EDPS
- 2017: 75% RAPS / 25% EDPS
- 2022: 0% RAPS / 100% EDPS (shift began)

**Current State (2025-2026):**
- 100% EDPS-based risk adjustment
- RAPS submissions accepted but not weighted in RAF calculations
- Dual submission still required during transition period

**Financial Implications:**
Organizations report revenue decreases: **1.8% to 27.6% per audit**, with **average 11.9% decrease**.

**Why the Variance?**
- Organizations with strong clinical documentation suffered less (already capturing conditions)
- Organizations with "add-only" retrospective programs faced larger clawbacks
- Stricter EDPS validation removes marginal/unsupported diagnoses

---

### CMS Requirements for Risk Adjustment Submission

**42 CFR Section 422.310 Requirements:**

1. **Report ALL items and services** provided to Medicare Advantage enrollees
2. **Characterize context and purpose** of each service
3. **Submit in X12 837 5010 format** (MA Encounter Data Records)
4. **Chart Review Records (CRRs)** for conditions identified in gap closures

**Data Elements Must Include:**
- Loops, segments, and data elements per X12 837 5010 TR3 specifications
- Supplemental CMS guidance for MA-specific requirements
- Chapter 3 of "MA Companion Guide for EDR and CRR Submissions"

**Timing Requirements:**
- Timely filing—typically within 60 days of service
- Annual submissions for calendar year services
- Corrections/updates per RADV notice deadlines

---

## Part 3: Chart Review Requirements & CMS V28 Changes

### CMS-HCC Model V28 Overview

**Implementation Timeline:**
- 2023 DOS: 33% V28 / 67% V24
- 2024 DOS: 67% V28 / 33% V24
- 2025+ DOS: **100% V28**

**Structural Changes:**
- HCC categories: 86 → 115 (29 new HCCs added)
- ICD-10-CM codes: 9,797 → 7,770
- Deleted codes: ~2,294
- Added codes: ~268

---

### V28 Documentation & Chart Review Requirements

**Key Mandate:**
"Accurate risk adjustment has always depended on the specificity of documentation and diagnostic coding, and HCC model V28 will require EVEN GREATER SPECIFICITY in documentation and code assignment."

**Specificity Examples:**
- **Diabetes:** Must specify Type 1 vs. Type 2 (V28 distinguishes differently)
- **Heart Failure:** Systolic vs. diastolic vs. combined; acute vs. chronic
- **CKD:** Must have specific stage (Stage 1 through Stage 5)
- **Cancer:** Must have anatomical site and behavior code
- **Depression:** New V28 HCC structure requires specific severity indicators

**Chart Review Burden:**
- V28 increases documentation requirements
- CMS audits will look more carefully at specificity
- Organizations need more rigorous QA processes
- Chart review teams must understand V28 mapping changes

---

### Chart Review vs. EHR Data Approaches

#### Prospective Chart Review (Pre-Visit Planning)

**Process:**
1. Certified coders review patient's chart 24-48 hours before encounter
2. Identify likely HCC conditions based on:
   - Historical diagnoses
   - Current medications
   - Recent lab results
   - Hospital records
   - Prior visits
3. Flag gaps and prepare provider for appointment
4. Provide list of diagnoses requiring documentation confirmation

**Benefits:**
- Real-time accuracy during encounter
- Provider has clinical context prepared
- 30-50% reduction in retrospective coding needs
- Immediate documentation feedback

**EHR Integration:**
Modern systems embed AI directly in EHR workflows at point of care, highlighting gaps as provider documents.

---

#### Retrospective Chart Review (Post-Claim)

**Timeline:**
- Occurs after claim submission
- Catches missed diagnoses weeks/months later
- Often combined with claims data analysis

**Efficiency Issues:**
- Provider memory fades
- Patient may have moved on from condition
- Higher documentation deficiency rates
- Provider frustration with delayed feedback

**RADV Audit Context:**
CMS conducts retrospective reviews to validate submitted diagnoses are actually documented in patient records with sufficient detail.

---

#### Concurrent/Point-of-Care Review

**Emerging Best Practice:**
Real-time review while patient is still receiving care—combines prospective and retrospective advantages.

**Process:**
1. Coder has remote EHR access during/immediately after visit
2. Reviews draft note for HCC documentation completeness
3. Alerts provider within 24-48 hours if gaps exist
4. Provider can address in follow-up without significant delay

**Outcomes:**
- Reduces administrative burden on provider at point of encounter
- Captures condition documentation accuracy while recent
- Decreases retrospective cleanup substantially

---

### Chart Review Requirements Under V28

**CMS Mandate Change:**
V28 requires both:
1. **Addition** of missed diagnoses (traditional gap closure)
2. **Removal** of unsupported diagnoses (new requirement emphasis)

**Significant Case Study:**
Aetna/CVS settled with DOJ for **$117.7 million** (March 2026) for maintaining an "add-only" retrospective program that submitted additional codes WITHOUT removing unsupported diagnoses—violating V28 compliance requirements.

**Implication:**
Organizations must implement:
- Bidirectional chart review (add AND remove)
- Quality validation processes
- Audit trails showing diagnostic support
- Provider feedback on removed codes (educational, not punitive)

---

## Part 4: Suspect Conditions & Gap Detection Methodologies

### Seven Primary Data Source Categories for Uncaptured Conditions

**Source Research:** [Milliman Risk Adjustment Methodologies](https://www.milliman.com/en/insight/risk-adjustment-methodologies-uncaptured-conditions)

#### 1. Rejected Claims
- Claims not processed due to technical errors
- Missing information flagging clinical content
- Pattern analysis reveals documentation gaps

#### 2. Denied Claims
- Coverage denials (prior auth missing)
- Payment denials (billing code issues)
- Indicate clinical services that may have unreported diagnoses

#### 3. Unqualified Claims
- Improper billing codes
- Procedure codes not qualifying for risk adjustment
- Service was provided but coded incorrectly

#### 4. Chronic Conditions Requiring Annual Recapture
- Diagnoses coded in prior year NOT recoded in current year
- V28 compliance requires annual re-documentation
- Biggest source of missed RAF points (patient still has condition)

#### 5. Related Diagnoses, Procedures, Drugs, Lab Results
- Medication-diagnosis correlation analysis
- Procedure-diagnosis correlation (e.g., cardiac catheterization → heart disease)
- Lab-diagnosis correlation (eGFR → CKD stage)
- Allows inference of suspected conditions

#### 6. Member Self-Reported Conditions
- Health risk assessments (HRAs)
- Member surveys and portals
- Care management program enrollments
- Preventive screening questionnaires

#### 7. Predictive Analytics & Episode Groupers
- Historical data analysis predicting progression
- Machine learning models identifying high-risk members
- Episode groupers clustering related conditions
- Cohort analysis (compare similar members)

---

### Clinical Indicator Examples by HCC

**Chronic Kidney Disease (HCC 326-329)**
- Clinical Indicator: eGFR lab result
- Specificity Required: Stage 1 (eGFR ≥90) through Stage 5 (eGFR <15)
- Additional Support: Urinalysis, creatinine trending, urology referral

**Type 2 Diabetes (HCC 23)**
- Clinical Indicators: HbA1c, fasting glucose, random glucose readings
- Medication Inference: Metformin, sulfonylureas, GLP-1 agonists
- Additional Support: Ophthalmology visit (retinopathy screening), podiatry referral

**Congestive Heart Failure (HCC 85/86)**
- Clinical Indicators: BNP elevation, echocardiogram findings, cardiac imaging
- Medication Inference: Loop diuretics, ACE inhibitors, beta-blockers, aldosterone antagonists
- Vital Signs: Monitoring for orthopnea, peripheral edema, weight gain
- Specialist Referral: Cardiology follow-up

**COPD (HCC 111)**
- Clinical Indicators: Spirometry results (FEV1), oxygen saturation on exertion
- Medication Inference: Bronchodilators (albuterol, tiotropium), corticosteroid inhalers
- Vital Signs: Respiratory rate monitoring, O2 saturation at rest/exertion
- Specialist Referral: Pulmonology consultation

**Depression (HCC 155)**
- Clinical Indicators: PHQ-9 score ≥10, PHQ-2 screening positive
- Medication Inference: SSRIs, SNRIs, tricyclic antidepressants
- Visit Type: Mental health specialist visits
- Assessment Documentation: Provider documented depression discussion

**Hepatocellular Carcinoma (Not HCC Code—the Disease)**
- Clinical Indicators: AFP >200 ng/mL, liver imaging (CT/MRI), biopsy results
- Lab Panel: Elevated bilirubin, elevated transaminases, low albumin
- Vital Signs: Jaundice, abdominal distension (ascites)
- History: Cirrhosis, chronic hepatitis B/C, alcohol use disorder

---

### NLP & Machine Learning Applications

#### How AI Systems Identify Suspect Conditions

**Text Mining Process:**
1. OCR (Optical Character Recognition) converts scanned documents to text
2. NLP extracts clinical terms from unstructured narratives
3. ML models learn patterns from coded/coded diagnoses
4. Algorithms surface mismatches between clinical language and codes

**Example Application:**
- EHR note contains: "patient with decreased renal function, eGFR now 35"
- NLP tags: kidney disease indicator, stage indicator
- System checks: Is CKD coded? Is stage documented?
- Flags: "Stage 3b CKD suspected but not coded"

**Detection Accuracy:**
Industry reports **up to 95% accuracy** for machine learning systems trained on large datasets, though human validation remains essential.

**Real-Time Clinical Decision Support:**
- Messages appear during or immediately after visit
- Shows suspected condition recommendation
- Displays rationale and evidence from chart
- Links back to supporting chart elements

---

### Prioritization Framework

**Scoring Approach:**
"Consider both the value of a condition in terms of revenue dollars and the likelihood that a patient actually has a suspected condition."

**Priority Index = (RAF Weight × Prevalence) + Audit Risk**

**High-Priority Gaps (Target First):**
1. High RAF weight + High prevalence + High audit risk
2. Example: Type 2 Diabetes (affects 15-20% of Medicare population, RAF ~0.3)
3. Example: Chronic Kidney Disease Stage 3+ (affects 10% of Medicare, RAF ~0.2-0.4)

**Medium-Priority Gaps:**
1. Moderate RAF weight + Moderate prevalence
2. Less audit scrutiny
3. Example: COPD (affects ~5% of Medicare, RAF ~0.3)

**Low-Priority Gaps:**
1. Very low prevalence OR very low RAF weight
2. High audit risk despite low prevalence (avoid overcoding)
3. Example: Rare cancer types

---

## Part 5: Industry Best Practices & Practical Recommendations

### 1. Data Integration Architecture

#### Recommended Multi-Source Integration Framework

**Data Layer (Collection):**
- EHR system (primary source)
- Claims data (secondary validation)
- Lab systems (objective indicators)
- Imaging/diagnostic systems
- External HIE systems
- Member self-reported data (surveys, portals)

**Processing Layer (Normalization):**
- Standardize date formats
- Normalize lab value units
- Map ICD-10 across systems
- Resolve patient identity (MPI)
- Flag data quality issues

**Intelligence Layer (Analysis):**
- Medication-diagnosis correlation
- Lab value anomaly detection
- Claim pattern analysis
- Predictive risk modeling
- Gap identification algorithms

**Action Layer (Deployment):**
- Pre-visit provider alerts
- Real-time point-of-care prompts
- Post-visit chart review tasks
- Member engagement communications
- Documentation improvement tools

---

### 2. Prospective vs. Retrospective Strategies

#### Optimal Hybrid Approach

**Phase 1: Pre-Encounter (Prospective)**
- 2-3 days before appointment: Identify likely HCCs
- Review medications, labs, prior diagnoses
- Prepare provider with gap list
- Embed prompts in EHR

**Phase 2: During Encounter (Concurrent)**
- Real-time documentation completeness checking
- Alert provider to MEAT criteria gaps
- Suggest specific documentation language
- Flag conditions requiring additional assessment

**Phase 3: Post-Encounter (Retrospective)**
- Chart validation within 24-48 hours
- Identify any remaining gaps
- Route to provider for immediate clarification
- Avoid weeks-delayed retrospective campaigns

**Outcome Target:**
"Organizations using hybrid models reduce retrospective coding needs by 30-50% while improving documentation quality."

---

### 3. Documentation Standards (MEAT Criteria Application)

#### MEAT Framework Implementation

**Monitor (M):** Objective tracking of condition status
- Vital signs readings
- Lab results
- Patient self-monitoring logs
- Disease-specific assessment scales (PHQ-9, STOP-BANG, etc.)

**Evaluate (E):** Assessment of test results and effectiveness
- "Labs reviewed—eGFR declined to 35, now Stage 3b CKD"
- "Patient tolerating current antihypertensive regimen well"
- "Repeat BNP elevated—CHF exacerbation risk"

**Assess/Address (A):** Clinical decision-making
- "Discussed findings with patient"
- "Ordered additional testing"
- "Adjusted medication regimen"
- "Referral made to specialist"

**Treat (T):** Active management documentation
- Medications prescribed/adjusted
- Behavioral counseling provided
- Therapy initiated
- Follow-up scheduled

**CMS Guidance:**
Only ONE MEAT element needed to support HCC coding, but multiple elements strengthen compliance.

---

### 4. Chart Review Quality Assurance (QA) Structure

#### Multi-Layer QA Process

**Layer 1: Coder-Level Validation**
- Individual coder reviews chart
- Applies MEAT criteria assessment
- Documents supporting evidence
- Flags ambiguous diagnoses

**Layer 2: Supervisor Review**
- 10-20% sample of all charts
- Validates MEAT criteria application
- Checks for missed conditions
- Verifies removal documentation

**Layer 3: Auditor Validation**
- 5-10% sample of supervised charts
- Independent verification
- Compliance assessment
- Identifies systemic issues

**Layer 4: Physician Oversight**
- Physician Medical Director review
- Quarterly compliance reports
- Provider feedback (educational)
- Trend analysis and optimization

---

### 5. RADV Audit Preparedness

#### CMS RADV Program Context (2025-2026)

**Expansion Significant:**
- Increased from 60 MA plans → **550+ plans audited**
- Coding teams expanded 40 → **2,000 reviewers**
- Record sample per contract: 35 → **200 records**

**Audit Methodology:**
- Random statistically valid sample
- Each HCC must be supported by documented evidence
- MEAT criteria strictly applied
- Bidirectional review (validate AND remove unsupported)

**Recent Enforcement:**
Aetna/CVS $117.7 million settlement (March 2026) demonstrates CMS enforcement of bidirectional requirements.

#### Preparation Checklist

**Documentation Readiness:**
- [ ] All current diagnoses have MEAT support
- [ ] Problem list cleaned (remove resolved/inactive conditions)
- [ ] Chart organization ensures reviewer can locate MEAT evidence
- [ ] Diagnosis-medication correlation documented
- [ ] Lab values referenced in provider notes
- [ ] Specialist referral findings captured in primary note

**Submission Accuracy:**
- [ ] EDPS validation rules applied pre-submission
- [ ] Duplicate encounter detection complete
- [ ] Provider credentials verified
- [ ] Diagnosis linkage to services verified
- [ ] CCI edits reviewed
- [ ] Risk adjustment flags verified

**Communication Structure:**
- [ ] Provider education on MEAT and V28 requirements
- [ ] Regular audit risk reports with trending
- [ ] Identified vulnerabilities communicated
- [ ] Corrective action plans documented
- [ ] Provider feedback mechanism established

---

### 6. Medication Reconciliation Integration

#### Process Integration

**Monthly Medication Review:**
- Extract active medication list from pharmacy
- Cross-reference against coded diagnoses
- Identify "orphaned" medications (medication without diagnosis)
- Flag for provider clarification

**Suspected Condition Flags:**
- Create rules-based system:
  - Insulin + no diabetes code → Flag for coding
  - Loop diuretic + no CHF code → Flag for coding
  - Antidepressant + no depression code → Flag for coding

**Provider Communication:**
- Monthly report: "Active medications without diagnosis codes"
- Educational tone (not accusatory)
- Easy correction mechanism
- Tracking and trending

---

### 7. SDOH Data Capture Strategy

#### Currently Non-Revenue Generating but Important

**Capture Methods:**
- Integrate into HRA (Health Risk Assessment) completion
- Standardized screening during visits (G0136 CPT code available)
- Care management program documentation
- Community resource referrals

**Application Beyond RAF:**
- Explains why patients may be non-compliant with treatment
- Informs care coordination intensity
- Identifies social work/community resource needs
- Improves quality measure outcomes

**Future Preparation:**
- Establish baseline SDOH data capture now
- Build reporting infrastructure
- As SDOH incorporation into risk adjustment occurs, organizations ready

---

### 8. Specialty Referral Data Management

#### Structured Capture Process

**At Referral Initiation:**
- Document clinical reason for specialist referral
- Link to specific HCC suspicion or gap closure goal
- Include clinical indicators (labs, vitals, symptoms)
- Set expectations for provider feedback

**Upon Specialist Encounter:**
- Capture specialist documentation in EHR
- Ensure relevant findings documented in PCP note
- Validate diagnoses from specialist
- Document agreed-upon management plan

**Post-Encounter Follow-Up:**
- Review specialist findings for new diagnoses
- Identify HCC codes from specialist documentation
- Update problem list with specialist-identified conditions
- Ensure continuity of care documentation

---

## Part 6: Competitor & Industry Implementation Examples

### Vendor Ecosystem

#### Categories of Solution Providers

**1. EHR-Integrated HCC Coding Platforms**
- Real-time point-of-care prompting
- Embedded within clinical workflows
- Examples: Innovaccer InNote, ForeSee Medical
- Strength: Providers get alerts during encounters
- Limitation: Requires EHR integration, workflow change

**2. Standalone HCC Coding Software**
- Desktop/web-based coder tools
- Examples: Optum HCC Coder, InferScience HCC Assistant
- Strength: Flexible deployment, familiar to coders
- Limitation: Post-encounter (not prospective)

**3. NLP/AI Discovery Platforms**
- Scan documentation for condition indicators
- Examples: Reveleer Risk NLP, Clinical Architecture
- Strength: Finds conditions coders might miss
- Limitation: Requires significant configuration

**4. Payer/Plan-Level Risk Adjustment Tools**
- Risk identification, gap closure workflows
- Examples: Optum Risk Identification, Navina
- Strength: Population-level analytics
- Limitation: Requires health plan data integration

**5. Advisory/Consulting Services**
- RADV audit preparation, documentation review
- Examples: 3Gen Consulting, ATTAC Consulting, FTI Consulting
- Strength: Expert guidance on compliance
- Limitation: Service-based (ongoing costs)

---

### Industry Leaders' Documented Approaches

#### Optum/UnitedHealth Group Strategy
- **Multi-source data integration:** Claims, EHR, labs, pharmacy
- **Risk identification platforms:** Identify members with uncaptured conditions
- **Prospective solutions:** Pre-visit alerts, provider education
- **Annual guidance:** 2025+ Risk Adjustment Coding and HCC Guide
- **V28 preparedness:** Detailed mapping and documentation requirements

#### Advocate Aurora / Large Health Systems
- **Problem list standardization:** Require specific format, annual attestation
- **HEDIS-Risk Alignment:** Bundle quality and risk adjustment initiatives
- **Specialty integration:** Cardiomyopathy referral → capture heart failure severity
- **Documentation education:** Ongoing provider training on MEAT + V28

#### Smaller Practices & Value-Based Care Organizations
- **Concurrent coding adoption:** Real-time feedback to providers
- **Automation focus:** Rules-based systems for medication-diagnosis correlation
- **Hybrid outsourcing:** Some functions externalized, high-risk retained internally

---

## Part 7: CMS & Regulatory Context

### Current Regulatory Environment (March 2026)

#### RADV Program Status
- **Expansion complete:** 550+ plans now audited vs. 60 previously
- **Annual requirement:** All MAO contracts audited annually
- **Increased scrutiny:** 200 records per contract (vs. 35 previously)
- **Enforcement active:** Ongoing settlements for non-compliant programs
- **Court challenge:** September 2025 RADV Rule vacated by federal court (process continues)

#### V28 Transition Complete
- **100% implementation:** All 2025+ dates of service use V28 model
- **Increased specificity:** 115 HCCs vs. 86 previously
- **Risk score impact:** -3.12% on CY 2024 (estimated $11 billion savings to Medicare)
- **Documentation burden:** Increased requirements for specificity

#### EDPS Migration Nearly Complete
- **100% primary:** All risk adjustment calculations use EDPS data
- **RAPS declining:** Legacy submission still accepted but not weighted
- **Dual submission:** Continue through transition period
- **Data validation:** Stricter validation rules than RAPS

---

### Future Regulatory Trends to Monitor

**Alternative Payment Models:**
- Accountable Care Organizations (ACO)
- Direct Contracting with CMS
- Managed Long-Term Services and Supports (LTSS)
- VBR (Value-Based Reimbursement) arrangements

**SDOH Integration:**
- CMS exploring SDOH inclusion in risk adjustment
- New Z-codes being monitored for RAF model incorporation
- Community benefit requirements for SDOH data capture

**Artificial Intelligence Oversight:**
- CMS developing AI validation standards for risk adjustment systems
- Transparency requirements for algorithmic decision-making
- Bias detection and mitigation requirements

---

## Summary Recommendations

### Immediate Actions (0-3 Months)

1. **Audit Current Data Governance**
   - Document all data sources currently used for HCC coding
   - Identify gaps in lab integration, medication reconciliation, vital signs
   - Map data quality issues and latency problems

2. **Implement EDPS Validation**
   - Ensure all encounter data submissions pass EDPS editing rules
   - Test X12 837 5010 compliance
   - Establish feedback loop for MAO-001 and MAO-002 reports

3. **Establish V28 Baseline**
   - Assess current documentation for V28 specificity requirements
   - Identify high-risk conditions (diabetes, CKD, CHF, COPD)
   - Plan remediation for documentation gaps

4. **Document Current State Metrics**
   - Establish baseline HCC capture rates by condition
   - Calculate current RAF scores vs. peer benchmarks
   - Identify top 20% of gaps driving revenue variance

---

### Medium-Term Projects (3-12 Months)

1. **Implement Multi-Source Data Integration**
   - Connect EHR lab system to HCC coding workflow
   - Integrate medication reconciliation system
   - Establish vital signs standardization
   - Connect specialist documentation feeds

2. **Deploy Prospective Coding Capability**
   - Implement pre-visit HCC gap identification
   - Establish provider alert mechanism (24-48 hours pre-visit)
   - Create documentation templates for high-risk conditions
   - Establish feedback loop for accuracy tracking

3. **Enhance Chart Review QA**
   - Implement tiered QA process (coder → supervisor → auditor → physician)
   - Establish MEAT criteria validation standards
   - Document audit trails for all HCC assignments
   - Create provider corrective action processes

4. **Build SDOH Capture Capability**
   - Establish standardized screening tools
   - Integrate into EHR workflow (visit template)
   - Establish reporting structure
   - Connect to care coordination/social work

5. **Advance NLP/AI Implementation**
   - Evaluate solution vendors (pilot 1-2 platforms)
   - Define suspect condition detection rules
   - Establish human validation workflows
   - Train staff on AI system outputs and limitations

---

### Strategic Initiatives (1-3 Years)

1. **Mature Hybrid Prospective/Retrospective Model**
   - Achieve 30-50% reduction in retrospective coding
   - Integrate concurrent (point-of-care) reviews
   - Establish real-time provider feedback capability
   - Track outcomes quarterly

2. **Establish Risk Adjustment Center of Excellence**
   - Cross-functional team (clinical, coding, IT, quality, compliance)
   - Regular benchmarking against industry peers
   - Annual risk adjustment strategy refresh
   - Provider education program (ongoing)

3. **Prepare for CMS Regulatory Changes**
   - Monitor SDOH model incorporation progress
   - Assess alternative payment model readiness
   - Establish AI governance framework
   - Plan for future risk model versions beyond V28

4. **Develop Specialty Integration Program**
   - Establish referral data standards
   - Create specialist-to-PCP documentation requirements
   - Build referral outcome tracking
   - Align incentives around HCC capture accuracy

---

## Data Source Reference Matrix

| Data Source | HCC Support | Prospective | Retrospective | Clinical Indicators | Industry Use |
|---|---|---|---|---|---|
| **Laboratory Values** | High (specific to condition stages) | Yes | Yes | eGFR, AFP, BNP, HbA1c | Universal |
| **Vital Signs** | Medium (supporting MEAT) | Yes | Yes | BP, BMI, O2 sat, RR | Universal |
| **Medications** | High (inferential) | Yes | Yes | Drug-disease correlation | 80%+ |
| **Problem List** | High (if current) | Yes | No | MEAT documentation | 90%+ |
| **Specialist Visits** | High (condition discovery) | Yes | Yes | Referral patterns | 70%+ |
| **SDOH Data** | Low (currently) | Yes | No | Screening responses | 40%+ |
| **Immunization Records** | Low (supportive) | Yes | Yes | Vaccination status | 50%+ |
| **Rejected/Denied Claims** | Medium (pattern analysis) | No | Yes | Claim disposition | 60%+ |
| **Predicted Risk Models** | High (population level) | Yes | No | Cohort comparison | 50%+ |
| **Member Self-Report** | Medium (HRA responses) | Yes | No | Survey responses | 70%+ |

---

## Bibliography & Sources

### Research Sources Consulted

- [HCC Coding 101 - IMO Health](https://www.imohealth.com/resources/hcc-101-what-you-need-to-know-about-hierarchical-condition-categories/)
- [RAPS vs. EDPS Guide - Mirra Healthcare](https://mirrahealthcare.com/insights/raps-vs-edps-a-simple-guide-to-cms-risk-adjustment-submissions-in-healthcare/)
- [Risk Adjustment Methodologies - Milliman](https://www.milliman.com/en/insight/risk-adjustment-methodologies-uncaptured-conditions)
- [HCC Suspecting Framework - The Tuva Project](https://thetuvaproject.com/data-marts/hcc-suspecting)
- [HEDIS Measures - NCQA](https://www.ncqa.org/hedis/)
- [CMS V28 Changes - AGS Health](https://www.agshealth.com/blog/understanding-the-changes-in-the-cms-hcc-model-v28/)
- [CMS Risk Adjustment Data Validation Program](https://www.cms.gov/data-research/monitoring-programs/medicare-risk-adjustment-data-validation-program)
- [Problem List vs. Billing Codes - AAPC Knowledge Center](https://www.aapc.com/blog/93645-what-does-the-problem-list-have-to-do-with-risk-adjustment/)
- [MEAT Criteria Documentation - AAPC](https://www.aapc.com/blog/41212-include-meat-in-your-risk-adjustment-documentation/)
- [Encounter Data Submission Guide - CMS](https://www.csscoperations.com/internet/csscw3_files.nsf/F2/ED_Submission_Processing_Guide_20221130_v5.2.0.pdf/$FILE/ED_Submission_Processing_Guide_20221130_v5.2.0.pdf)
- [SDOH in Risk Adjustment - Blue Cross NC](https://www.bluecrossnc.com/content/dam/bcbsnc/pdf/providers/network-programs/blue-medicare/hcc-risk-adjustment-coding/guidelines-for-coding-social-determinants-of-health.pdf)
- [Concurrent Coding Review - ForeSee Medical](https://www.foreseemed.com/blog/concurrent-coding)
- [Prospective Risk Adjustment - Zus Health](https://zushealth.com/the-end-of-retrospective-risk-adjustment-why-prospective-coding-is-the-new-standard/)

---

## Appendices

### Appendix A: Common HCC Codes & Clinical Indicators

**HCC 18 - Type 2 Diabetes without Complications**
- Labs: HbA1c, fasting glucose, random glucose
- Medications: Metformin, sulfonylureas, dipeptidyl peptidase-4 (DPP-4) inhibitors
- Vital Signs: Weight monitoring, BP
- Documentation: DM Type 2 specifically documented

**HCC 23 - Type 2 Diabetes with Complications**
- Labs: HbA1c + evidence of complication (retinopathy, neuropathy, nephropathy)
- Medications: Multiple agents for complex diabetes
- Specialists: Ophthalmology, podiatry, nephrology
- Documentation: Specific complication type documented

**HCC 48 - Morbid Obesity**
- Vital Signs: **Specific BMI value** (not calculated by coder)
- Labs: Weight trending
- Medications: Obesity-specific agents (GLP-1 agonists, orlistat)
- Documentation: "Morbid obesity" documented + BMI value

**HCC 85 - Congestive Heart Failure**
- Labs: BNP elevation, echocardiogram (EF percentage)
- Medications: ACE inhibitors, beta-blockers, loop diuretics
- Vital Signs: Weight gain, orthopnea, edema documentation
- Specialist: Cardiology consultation/ongoing care
- Documentation: Systolic vs. diastolic; acute vs. chronic

**HCC 111 - Chronic Obstructive Pulmonary Disease**
- Labs: Spirometry (FEV1 value if documented), ABG if severe exacerbation
- Medications: Bronchodilators, corticosteroid inhalers
- Vital Signs: Respiratory rate, O2 saturation at rest and exertion
- Specialist: Pulmonology consultation
- Documentation: COPD severity (mild, moderate, severe) if documented

**HCC 155 - Depression**
- Labs: PHQ-9 score (≥10 indicates moderate depression), PHQ-2 screening
- Medications: SSRIs, SNRIs, tricyclic antidepressants, MAOIs
- Mental Health Visits: Psychology/psychiatry encounters
- Documentation: Depression diagnosis, severity if available, treatment plan

**HCC 326-329 - Chronic Kidney Disease (Stages 1-5)**
- Labs: **eGFR value** (must be specific stage, not just "CKD")
- Medications: ACE inhibitors, ARBs (for kidney protection)
- Specialist: Nephrology referral/ongoing care
- Additional: Urinalysis results, creatinine trending
- Documentation: Specific stage (Stage 3a, 3b, 4, or 5) required per CMS guidance

---

### Appendix B: Data Element Checklist for EDPS Submission

**Required Data Elements Per X12 837 5010:**

**Administrative:**
- [ ] Member ID (health plan assigned)
- [ ] Member name, DOB, gender
- [ ] Enrollment status and coverage dates
- [ ] Payer ID (health plan identifier)

**Service Information:**
- [ ] Provider NPI and taxonomy code
- [ ] Place of service code
- [ ] Dates of service (from and to)
- [ ] Service type code
- [ ] Units of service
- [ ] Revenue code (if applicable)

**Clinical:**
- [ ] ICD-10-CM diagnosis codes (all documented)
- [ ] Procedure codes (CPT/HCPCS)
- [ ] Modifiers (if applicable)
- [ ] Quantity (services rendered)
- [ ] Charge amount

**Validation:**
- [ ] No duplicate encounters (service date + provider + diagnosis)
- [ ] Diagnosis codes valid per current ICD-10-CM
- [ ] CPT codes valid per current code sets
- [ ] Provider credentials valid
- [ ] Enrollment verification passes
- [ ] Service dates within coverage period
- [ ] Clinical consistency checks pass (e.g., pediatric diagnosis for adult)
- [ ] CCI edit requirements met

---

### Appendix C: MEAT Documentation Examples

**Example 1: COPD Documented Properly (All MEAT Elements)**

*Provider Note:*
"Patient with COPD presents with cough × 2 weeks. Spirometry performed today shows FEV1 of 58% predicted, consistent with moderate airway obstruction. We reviewed results—patient's obstruction has worsened compared to last year's FEV1 of 68%. Discussed with patient regarding progression. Assessed current regimen of tiotropium and albuterol. Adjusted therapy—increased albuterol frequency to 4× daily and added fluticasone/salmeterol inhaler. Patient educated on inhaler technique. Referred to pulmonology for further optimization."

**MEAT Elements Present:**
- **M** (Monitor): Spirometry performed and reviewed
- **E** (Evaluate): Results assessed, compared to prior year
- **A** (Assess): Discussed with patient, therapy adjustment made
- **T** (Treat): Medications adjusted, additional therapy initiated
- **Result:** Meets full MEAT documentation; HCC 111 coding supported

---

**Example 2: Diabetes Documented Inadequately (Only History)**

*Provider Note:*
"Patient has history of diabetes. Continue current medications."

**Analysis:**
- No MEAT elements present
- No evidence of monitoring, evaluation, assessment, or treatment
- Diagnosis simply carried forward from problem list
- **Result:** Does NOT meet MEAT criteria; HCC coding is at audit risk

---

**Example 3: Heart Failure Documented Acceptably (Meets MEAT with Lab)**

*Provider Note:*
"CHF follow-up visit. Patient reports increased shortness of breath with exertion × 1 week. Examined today—no peripheral edema noted, lungs clear. BNP level from clinic today is 450 (elevated from last month: 285). Given progression of BNP and patient symptoms, increased lisinopril from 10 mg to 20 mg daily. Discussed fluid restriction and daily weights at home. Patient to follow up in 2 weeks."

**MEAT Elements Present:**
- **M** (Monitor): BNP trending (285→450), symptoms monitored
- **E** (Evaluate): BNP reviewed, clinical assessment performed
- **A** (Assess): Medication adjustment decision based on findings
- **T** (Treat): Lisinopril increased, patient counseling provided
- **Result:** Meets MEAT documentation; HCC coding well-supported

---

### Appendix D: Medication-to-Condition Correlation Rules

| Medication Class | Specific Agents | Suspected Condition | HCC Code |
|---|---|---|---|
| GLP-1 Agonists | Semaglutide, dulaglutide, liraglutide | Type 2 Diabetes | HCC 23+ |
| Insulin | Any type | Type 1 or Type 2 Diabetes | HCC 18 or 23+ |
| ACE Inhibitors/ARBs | Lisinopril, losartan, valsartan | Hypertension + CKD or CHF | HCC variants |
| Beta Blockers (cardiac) | Metoprolol, carvedilol, bisoprolol | CHF or hypertension | HCC 85/86 or variant |
| Loop Diuretics | Furosemide, bumetanide, torsemide | CHF or advanced renal disease | HCC 85/86 or HCC 326+ |
| Bronchodilators | Albuterol, tiotropium, formoterol | COPD or asthma | HCC 111 |
| Corticosteroid Inhalers | Fluticasone, budesonide, mometasone | COPD or asthma | HCC 111 |
| SSRIs/SNRIs | Sertraline, escitalopram, venlafaxine | Depression | HCC 155 |
| Antipsychotics | Aripiprazole, olanzapine, risperidone | Schizophrenia/bipolar | HCC 157 |
| Statins | Atorvastatin, simvastatin | CHD risk, CAD | HCC 18+, 86+ |
| Anticoagulants | Warfarin, apixaban, rivaroxaban | Atrial fibrillation | HCC 96 |
| Opioids | Morphine, oxycodone, hydromorphone | Cancer, severe pain condition | HCC 8+ |

**How to Use:**
- Patient on three different antidepressants but no depression HCC coded?
- Patient on loop diuretics but only hypertension coded (not CHF)?
- Patient on insulin but diabetes not documented?
- These patterns trigger review for documentation gaps

---

## Conclusion

Clinical data sources beyond billing codes provide objective, verifiable foundations for HCC/RAF scoring. The evolution toward **multi-source data integration, prospective coding, and concurrent review** represents a fundamental shift in how organizations optimize risk adjustment while ensuring compliance with increasingly stringent CMS requirements.

Organizations successfully implementing these practices report:
- 30-50% reduction in retrospective coding needs
- 95% accuracy in machine learning-assisted gap detection
- 40%+ revenue protection vs. organizations relying on billing codes alone
- Significantly improved RADV audit outcomes

The transition to EDPS, implementation of V28, and expansion of RADV audits create both risks and opportunities. Organizations proactively building multi-source data capabilities while establishing bidirectional chart review processes position themselves to thrive in this increasingly complex regulatory environment.

---

**Document Version:** 1.0
**Last Updated:** March 30, 2026
**Recommended Review Cycle:** Quarterly (due to rapid CMS regulatory changes)
