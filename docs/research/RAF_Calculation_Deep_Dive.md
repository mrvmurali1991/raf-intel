# Risk Adjustment Factor (RAF) Score Calculation: Complete Technical Reference

**Last Updated:** April 2026  
**Scope:** Medicare Advantage, ACA Marketplace, PACE, ESRD, and related programs  
**Model Versions Covered:** V24, V28, V22, and blended transition calculations

---

## Table of Contents

1. [Core RAF Calculation Formula](#core-raf-calculation-formula)
2. [CMS-HCC Model Versions](#cms-hcc-model-versions)
3. [Demographic Factors](#demographic-factors)
4. [HCC Coefficients and Disease Interactions](#hcc-coefficients-and-disease-interactions)
5. [Patient vs Encounter vs Year-Level Calculations](#patient-vs-encounter-vs-year-level-calculations)
6. [Program-Specific Models](#program-specific-models)
7. [Normalization Factors](#normalization-factors)
8. [New vs Continuing Enrollee Models](#new-vs-continuing-enrollee-models)
9. [Community vs Institutional Models](#community-vs-institutional-models)
10. [V24 to V28 Transition Timeline](#v24-to-v28-transition-timeline)

---

## Core RAF Calculation Formula

### Basic Formula

```
Total RAF Score = Demographic Component + Σ(HCC Values) + Σ(Disease Interaction Terms) + Σ(HCC Count Modifiers)
```

### Normalized RAF Score (Applied to Payments)

```
Normalized RAF = Raw RAF Score / Normalization Factor
```

### Components Explained

1. **Demographic Component**: Base score derived from age, sex, Medicaid eligibility, disability status, institutional vs community living
2. **HCC Values**: Individual coefficients assigned to each documented Hierarchical Condition Category
3. **Disease Interaction Terms**: Additional additive factors when specific condition pairs exist simultaneously
4. **HCC Count Modifiers**: Bonus factors when 5 or more HCCs are documented

### Example Calculation (Illustrative)

For a patient with:
- Demographics: 72-year-old male with dual Medicaid eligibility = 0.626 base
- HCC 8 (Metastatic Cancer): 1.089
- HCC 85 (Chronic Systolic Heart Failure): 0.360
- Disease Interaction (Heart Failure + Kidney Disease): +0.112
- HCC Count Modifier (6+ HCCs): +0.050

**Raw RAF** = 0.626 + 1.089 + 0.360 + 0.112 + 0.050 = 2.237

If normalization factor is 1.045:
**Adjusted RAF** = 2.237 / 1.045 = 2.140

---

## CMS-HCC Model Versions

### V24 Model (2014-2023 Foundation)

- **HCC Categories**: 86 total HCCs
- **Valid ICD-10-CM Codes**: 9,797
- **Calibration Data**: Fee-for-service Medicare claims from 2011
- **Disease Groups**: 24 major condition groups
- **Disease Interactions**: 24 interaction terms

### V28 Model (2024-Present Updated Version)

- **HCC Categories**: 115 total HCCs (net +29 from V24)
- **Valid ICD-10-CM Codes**: 7,770 (net -2,027 codes removed, +209 new codes added)
- **Calibration Data**: More recent fee-for-service Medicare claims
- **Disease Groups**: Reorganized into more granular categories
- **Key Innovations**:
  - **Coefficient Constraining**: Related HCCs assigned same coefficients to prevent double-counting
  - **Payment HCC Count Modifier**: Bonus factors starting at 5 HCCs, capping at 10+
  - **Enhanced Disease Interactions**: 6 specific disease interaction combinations
  - **Removal of Interactions**: Immune disorders + cancer interaction eliminated

#### V28 Specific Coefficient Changes

| Condition | V24 Coefficient | V28 Coefficient | Change | Note |
|-----------|-----------------|-----------------|--------|------|
| Type 2 Diabetes (uncomplicated) | 0.105 | 0.166 | +57.6% | Constraining applied |
| Diabetes with complications | 0.312 | 0.166 | -46.8% | Constrained to same as uncomplicated |
| Chronic Systolic Heart Failure | 0.394 | 0.360 | -8.6% | Moderate decrease |
| Atrial Fibrillation | 0.298 | 0.299 | +0.3% | Minimal change |
| Metastatic Cancer | ~1.089 | Varies by type | - | Remains high severity |

#### V28 HCC Category Reorganization Examples

**Kidney Disease Group** (Contracted from 5 HCCs to 4):
- Removed: Dialysis status, acute renal failure (consolidated)
- Added: Split Stage 3 CKD into two categories
  - HCC 328: Stage 3B moderate CKD
  - HCC 329: Stage 3 (except 3B) moderate CKD

**Heart Failure HCCs** (Constrained):
- HCC 224, 225, 226 all assigned same coefficient
- Prevents additional payment for mild vs. severe CHF variance

---

## Demographic Factors

### Demographic Component Structure

The demographic score is calculated using multiple dimensions:

#### Age-Sex Variables

Base demographic coefficients vary by:
- **Age Bands**: 65-69, 70-74, 75-79, 80-84, 85+ (and under-65 groups)
- **Sex**: Male/Female
- **Eligibility Status**: Original Medicare, Disabled, etc.

#### Example Demographic Coefficients (Illustrative from V24/V28)

| Age Band | Male | Female |
|----------|------|--------|
| 65-69 | 0.408 | 0.289 |
| 70-74 | 0.527 | 0.523 |
| 75-79 | 0.688 | 0.650 |
| 80-84 | 0.815 | 0.774 |
| 85+ | 0.957 | 0.923 |

**Note**: Specific coefficients vary by payment year and model variant.

#### Medicaid Status Adjustment

- **Dual Eligible (Medicare + Medicaid)**: Additional adjustment factor applied (typically +0.06 to +0.10)
- **Non-Dual Eligible**: No Medicaid adjustment

#### Living Situation Adjustment

- **Community**: No adjustment
- **Institutional (SNF/Long-term care)**: Separate institutional model with adjusted coefficients
- **Other Residence Types**: Specific codes for nursing facilities, assisted living

#### Disability Status

- **Disabled (under 65)**: Different baseline than aged beneficiaries
- **End-Stage Renal Disease (ESRD)**: Separate model entirely

### Full Demographic Cell Calculation

```
Demographic RAF = Base(Age-Sex) + Medicaid_Adjustment + Institutional_Adjustment + Disability_Adjustments
```

---

## HCC Coefficients and Disease Interactions

### HCC Organization in V28

HCCs are organized into groups reflecting clinical relationships:

**Major Disease Groups (examples)**:
1. **Cancer-Related HCCs** (HCC 8-12): Multiple cancer types with interaction terms
2. **Diabetes HCCs** (HCC 19-21): Constrained to same coefficient (0.166)
3. **Heart Disease HCCs** (HCC 85-87): CHF variants, constrained
4. **Kidney Disease HCCs** (HCC 327-330): Stages and complications
5. **Neurological HCCs** (various): Dementia, Parkinson's, stroke history
6. **Psychiatric HCCs**: Mental health conditions

### Disease Interaction Terms (V28)

Disease interactions are **additive and applied independently of HCC hierarchy**, meaning:
- Even if one HCC in a pair is suppressed by hierarchy, the interaction still counts
- Interactions compound based on condition combinations

#### Known V28 Disease Interactions (with coefficients)

| Interaction Pair | Coefficient | Example |
|------------------|-------------|---------|
| Diabetes + Heart Failure | +0.112 | Multiplies risk for comorbid patients |
| Heart Failure + Chronic Kidney Disease | +0.189 | Higher interaction value |
| Heart Failure + Pulmonary Complications | +0.105 | Respiratory comorbidity |
| Cancer + Metastatic Conditions | Complex | Multiple interactions possible |
| Diabetes + Kidney Disease | +0.095 | Vascular/renal complications |
| Immune Disorders + Cancer | **REMOVED** | Eliminated in V28 (was 0.6-0.8) |

### HCC Count Modifier (Payment HCC Count - V28 New Feature)

**Structure**: Additive bonus when patient has 5+ documented HCCs

| Number of HCCs | Modifier Amount |
|----------------|-----------------|
| 0-4 | 0.000 |
| 5 | +0.050 (example) |
| 6 | +0.075 |
| 7 | +0.095 |
| 8 | +0.115 |
| 9 | +0.130 |
| 10+ | Cap (no additional) |

**Rationale**: Reflects complexity of care management for poly-morbid patients

---

## Patient vs Encounter vs Year-Level Calculations

### Calculation Levels

#### Patient-Level Calculation

- **Definition**: Combined risk score for a single patient across all encounters in a calendar year
- **Scope**: All diagnoses documented from January 1 to December 31
- **Used For**: Capitation payments, population health management
- **Duration**: One complete calendar year

**Example**:
```
Patient ID: 12345
Period: Jan 1 - Dec 31, 2025

All diagnoses from all visits in 2025 are:
- Visit 1 (Jan): E11.9 (Type 2 DM), I50.9 (Heart Failure)
- Visit 2 (Mar): E11.65 (DM with neuropathy)
- Visit 3 (May): N18.3 (CKD Stage 3)
- Visit 4 (Oct): No new diagnoses

Final RAF = Single score combining all 2025 documented conditions
```

#### Encounter-Level Data Capture

- **Definition**: Diagnoses documented within a single clinical encounter
- **Scope**: Individual office visit, hospitalization, ED visit
- **Purpose**: Feed into patient-level calculation
- **Rules**: 
  - Multiple conditions within same HCC count once per calendar year
  - Same diagnosis documented in multiple encounters in same year still counts once
  - Current year diagnoses only (must be re-documented annually for chronic conditions)

**Important Rule**: Current risk adjustment rules stipulate that an individual's HCCs are valid **only for the calendar year** in which the encounter is incurred.

#### Year-Level Reset

- **Annual Refresh**: RAF scores reset completely on January 1 each year
- **Chronic Condition Re-documentation**: Must be re-documented in current calendar year to retain credit
- **Payment Impact**: Failure to re-document chronic conditions results in lower RAF score
- **Data Collection Period**: Typically 12 months of Part B claims for continuing enrollees

---

## Program-Specific Models

### Medicare Advantage (MA) - Part C

**Current Model**: CMS-HCC V28 (transitioning from V24)

**Key Characteristics**:
- Uses 115 HCCs, 7,770 ICD-10-CM codes
- Divided into:
  - **Community-Dwelling**: Standard population
  - **Institutional**: Long-term care facilities
  - **ESRD**: Separate model
  - **Non-ESRD**: General MA population

**Payment Structure**:
- Risk scores drive capitation payments
- Payment rate = Benchmark * CMS Geographic Adjustment * RAF Score

---

### ACA Marketplace (Individual & Small Group)

**Model**: HHS-HCC (not CMS-HCC)

**Key Differences from Medicare Advantage**:

#### 1. **Timing Approach**
- **HHS-HCC**: Concurrent (uses current year codes for current year budget)
- **CMS-HCC**: Prospective (uses prior year codes to predict next year costs)

#### 2. **Population Calibration**
- **HHS-HCC**: Commercially insured (all ages), includes pediatric, obstetric, neonatal diagnoses
- **CMS-HCC**: Medicare aged (65+) and disabled (<65) populations only

#### 3. **Cost Coverage**
- **HHS-HCC**: Medical + pharmaceutical spending
- **CMS-HCC**: Medical spending only

#### 4. **HCC Categories**
- **HHS-HCC**: 127 HCC codes
- **CMS-HCC**: 115 HCCs (V28)
- **ICD-10 Codes**: 7,768 in HHS vs 7,770 in V28

#### 5. **Unique HCC Categories in HHS**
- Pregnancy and neonatal complications
- Pediatric-specific conditions
- Age 0-18 risk categories not in Medicare models

**Data Submission**: Concurrent data submitted during benefit year (uses RAPS-equivalent system)

---

### PACE (Programs of All-Inclusive Care for the Elderly)

**Current Status (as of 2026)**:

**Non-ESRD Model**: CMS-HCC **V22 (2017 model)** - Still using older model

**ESRD Model**: CMS-HCC **2019 ESRD model**

**Transition Timeline to V28**:
- **2026**: Blend 10% V28 + 90% V22
- **2027**: 20% V28 + 80% V22 (expected)
- **2028**: 50% V28 + 50% V22 (expected)
- **2029**: 100% V28 (expected) + Encounter data (instead of claims)

**Why Different Timeline**:
- PACE serves older, more vulnerable population (average age 83)
- Encounter-based data collection (different from claims-based)
- Longer implementation runway needed
- Shorter notice period for changes

---

### ESRD (End-Stage Renal Disease)

**Separate Risk Adjustment System**:

ESRD beneficiaries use a specialized model due to:
- Inevitable kidney failure (all qualify as sickest category)
- Different cost drivers than general Medicare population
- Four distinct subpopulations requiring separate models

#### ESRD Model Segments

| Segment | Definition | Model Type |
|---------|-----------|-----------|
| **Dialysis** | Currently on dialysis treatment | Separate coefficients |
| **Transplant (0-2 months)** | Recent transplant, immediate post-op period | Short-term model |
| **Functioning Graft 4-9 months** | Transplant graft functioning 4-9 months post-transplant | Mid-term model |
| **Functioning Graft 10+ months** | Transplant graft functioning 10+ months post-transplant | Long-term model |

#### ESRD-Specific HCC Restrictions

**HCCs That Are Zero-Weighted** (omitted from model):
- HCC for dialysis status (all ESRD patients already in dialysis)
- HCC for renal failure (implicit in all ESRD patients)
- HCC for nephritis/kidney disease (implicit in all ESRD patients)

**HCC That Gets Special Treatment**:
- HCC 174: Major Organ Transplant Status - **Estimated in model** (only ESRD HCC allowed unique coefficient)

**Other HCC Coefficients**:
- All non-kidney disease HCCs use **same coefficients as non-ESRD CMS-HCC model**
- Prevents double-counting of kidney-related conditions

#### ESRD Model Versions

- **Current**: CMS-HCC ESRD model since 2019
- **Used For**: Medicare Advantage ESRD beneficiaries, PACE ESRD beneficiaries
- **Calibration**: Based on ESRD-specific cost and claims data

---

## Normalization Factors

### Purpose of Normalization

Normalization factors adjust raw RAF scores to maintain an **average (mean) RAF of exactly 1.0** for the Fee-for-Service (FFS) baseline population in each year.

```
Normalized RAF = Raw RAF Score / Normalization Factor
```

### Why Normalization Is Needed

1. **Population Health Changes**: FFS Medicare population health status changes year-to-year
2. **Diagnostic Coding Intensity**: Increased coding (capture of diagnoses) raises average RAF
3. **Model Calibration**: Each new model version (V24 to V28) shifts average risk
4. **Price/Utilization Changes**: Healthcare cost patterns change annually

### Normalization Factor Values

#### Recent Years

| Payment Year | Normalization Factor | Notes |
|--------------|-------------------|-------|
| 2024 | 1.030 (approx.) | V24/V28 blend introduction |
| 2025 | 1.045 | Accounts for V24/V28 blend shift |
| 2026 | 1.05+ (projected) | Full V28 implementation |

**Interpretation**: A normalization factor of 1.045 means raw RAF scores are divided by 1.045 to adjust downward, ensuring the population average stays at 1.0.

### Methodology for Calculating Normalization

CMS uses **multiple linear regression** to:
1. Calculate average FFS risk score for denominator year (prior year)
2. Compare to payment year (current year) to determine drift
3. Account for:
   - COVID-19 pandemic impacts (handled separately in 2020-2023)
   - Aging of population
   - Increase in disability enrollment
   - Coding intensity improvements
4. Apply adjustment factor to maintain 1.0 average

### FFS Normalization Adjustments (2025)

CMS specifically noted that the normalization factor for 2025 incorporates:
- More sophisticated methodology addressing COVID-19 pandemic effects without deleting data
- Linear regression to predict FFS population changes
- Separate adjustments for demographic vs. diagnostic drift

---

## New vs Continuing Enrollee Models

### Continuing Enrollee Model

**Definition**: Beneficiary with **12 months of Part B claims data** in the data collection period

**RAF Components**:
- Demographic factors (age, sex, Medicaid, disability, institution)
- HCC disease factors (all available HCCs)
- Disease interaction terms
- HCC count modifiers

**Maximum Complexity**: Incorporates full diagnostic history

**Example Scenario**:
```
Beneficiary joined MA plan on Jan 1, 2025
Period: Full 12 months Part B data (Jan 1, 2024 - Dec 31, 2024)
Result: Continuing enrollee model applies in 2025
```

### New Enrollee Model

**Definition**: Beneficiary with **less than 12 months of Part B claims data**

**RAF Components**:
- Demographic factors ONLY
- **NO disease (HCC) factors**
- **NO interaction terms**
- **NO HCC count modifiers**

**Rationale**: 
- Insufficient diagnostic data to reliably predict
- Avoid penalizing plans for sicker new enrollees
- Uses only age, sex, Medicare status, Medicaid status, disability status

**Example New Enrollee RAF**:
```
65-year-old male, non-dual, community-dwelling
Demographic RAF = 0.408 (only)
No HCC factors added
```

### Enrollee Type Determination

| Situation | Classification |
|-----------|----------------|
| Joined MA plan mid-year with <12 mo data when calculated | New Enrollee |
| Joined MA plan but has 12+ months FFS data before joining | Continuing Enrollee |
| Switched between MA plans mid-year | Uses current enrollment status |
| Aged from disabled to aged (age 65+) | Transitions to aged rates |

### Model Variant Coefficients

Different coefficients exist for:
- New Enrollee (Aged)
- New Enrollee (Disabled)
- Continuing Enrollee (Aged)
- Continuing Enrollee (Disabled)

---

## Community vs Institutional Models

### Institutional vs Community Definition

#### Community-Dwelling (Standard Model)

**Definition**: Beneficiary NOT currently residing in a long-term care facility

**Population**: ~95% of Medicare Advantage beneficiaries

**Living Situations Included**:
- Private home/apartment
- Family home
- Supported living
- Independent senior housing
- Assisted living (day services only)

#### Institutional Living (Separate Model)

**Definition**: Beneficiary residing in a facility providing ongoing skilled nursing/personal care

**Population**: ~5% of Medicare Advantage beneficiaries

**Facility Types**:
- Skilled Nursing Facility (SNF)
- Nursing Home
- Long-term care facility
- Intermediate care facility

### Model Differences

#### Demographics Adjustment

**Institutional Demographic Multiplier**:
- Institutional models apply **higher base demographic coefficients** (reflecting higher care costs)
- Example: Age 75 male community = 0.688, institutional = ~0.85+ (20%+ premium)

#### HCC Coefficients

**Weighted Differently**:
- Some HCCs have **identical coefficients** in both models (e.g., cancer)
- Many HCCs have **higher coefficients in institutional** model (e.g., heart failure, dementia)
- A few HCCs have **lower coefficients** in institutional (competing risk/mortality)

**Rationale**: Institutional residents have:
- Higher baseline healthcare costs
- Different disease manifestations
- Higher mortality rates
- Different outcome trajectories

#### Disease Interactions

**Institutional-Specific Interactions**:
- Same interaction terms generally apply
- May have different coefficient values
- Recognize that institutional residents' conditions interact differently

### Calculation Rules

**Each patient classified as**:
- Community risk segment (default)
- Institutional risk segment (explicit indicator)

**Cannot blend models**: Use one model entirely, not hybrid

---

## V24 to V28 Transition Timeline

### Three-Year Phased Transition

#### Payment Year 2024

**Blend Calculation**:
```
PY2024 RAF = (67% × V24 Adjusted Score) + (33% × V28 Adjusted Score)
```

**Timeline**:
- Announced: April 2023
- Effective: January 1, 2024
- Diagnosis Collection: 2023 (1/1/2023 - 12/31/2023)
- Used For: 2024 payment rates

**Impact**: CMS projected -3.12% average MA risk score decrease ($11 billion savings)

#### Payment Year 2025

**Blend Calculation**:
```
PY2025 RAF = (33% × V24 Adjusted Score) + (67% × V28 Adjusted Score)
```

**Timeline**:
- Diagnosis Collection: 2024 (1/1/2024 - 12/31/2024)
- Used For: 2025 payment rates
- Normalization Factor: 1.045

**Impact**: CMS projected -2.45% average MA risk score decrease

#### Payment Year 2026 and Beyond

**Full V28 Implementation**:
```
PY2026+ RAF = 100% × V28 Adjusted Score
```

**Timeline**:
- Diagnosis Collection: 2025 (1/1/2025 - 12/31/2025)
- Used For: 2026 and subsequent years
- Ongoing adjustments: Normalization factors applied annually

### Why Three-Year Transition?

1. **Provider Preparation**: Time to update coding systems, train staff
2. **System Validation**: Identify and fix anomalies
3. **Beneficiary Protection**: Gradual payment changes reduce plan disruption
4. **Data Quality**: Ensure new codes/categories functioning correctly

### PACE Program Different Transition (Not Full V28 Until 2029)

PACE transition timeline differs due to encounter-based data system:
- 2026: 10% V28 + 90% V22
- 2027: 20% V28 + 80% V22
- 2028: 50% V28 + 50% V22
- 2029: 100% V28

---

## Key Regulatory and Compliance Notes

### RAF Score Audit Requirements

CMS conducts annual audits on:
- Coding accuracy (HCC validation)
- Completeness of diagnosis capture
- Demographic data accuracy
- Institutional status classifications

### Regulatory Oversight

**Office of Inspector General (OIG) Focus Areas**:
- "Upcoding" - assigning more severe diagnoses to inflate RAF
- Unsupported diagnoses - HCCs without corresponding clinical evidence
- Demographic misclassification
- Failure to re-document chronic conditions

### Data Submission Methods

| Program | Method | Frequency |
|---------|--------|-----------|
| Medicare Advantage | RAPS (Risk Adjustment Processing System) | Monthly/Annual |
| ACA Marketplace | RAPS / EDS (Enrollment Data System) | Concurrent |
| PACE | PACE-specific system (encounter data) | Ongoing (transitioning) |
| ESRD MA | Separate ESRD RAPS | Monthly/Annual |

---

## Technical Implementation Notes for SaaS Product

### Required Data Elements for RAF Calculation

#### Minimum Required Patient Data
1. **Demographics**
   - Age (exact date of birth)
   - Gender/Sex
   - Medicare eligibility category
   - Medicaid dual status
   - Institutional status code

2. **Diagnoses**
   - ICD-10-CM codes from encounters
   - Date of service
   - Encounter type (office, inpatient, outpatient)
   - Valid diagnosis indicator

3. **Program Information**
   - Plan type (MA, ACA, PACE, ESRD)
   - Enrollment start/end dates
   - Benefit year (calendar year for MA/PACE, benefit year for ACA)

#### Data Quality Validations
- ICD-10-CM codes must map to valid HCC
- Diagnosis code must have service date in applicable year
- Age calculation must use exact DOB
- Demographic fields must be present/valid
- Institutional status must be clearly documented

### Calculation Sequence

1. **Determine Model Parameters**
   - Program type (MA, ACA, PACE, ESRD)
   - Benefit year/payment year
   - Enrollee status (new vs. continuing)
   - Institutional vs. community

2. **Calculate Demographic Component**
   - Look up base coefficient (age-sex-status)
   - Apply Medicaid adjustment if applicable
   - Apply institutional adjustment if applicable

3. **Process Diagnoses**
   - Map ICD-10 to HCC
   - Apply HCC hierarchy rules
   - Sum valid HCC coefficients
   - Check for duplicate HCCs (count once per year)

4. **Calculate Interactions**
   - Identify HCC pairs present
   - Look up interaction coefficients
   - Apply additive interaction terms

5. **Calculate HCC Count Modifier**
   - Count valid HCCs
   - If 5+, apply count modifier

6. **Sum Components**
   - Demographic + HCCs + Interactions + Count Modifier = Raw RAF

7. **Apply Normalization**
   - Divide raw RAF by normalization factor
   - Result = Adjusted RAF (used for payment)

### System Architecture Considerations

**Necessary Components**:
- HCC mapping table (ICD-10 to HCC)
- HCC hierarchy rules engine
- Demographic coefficient lookup tables (varies by year)
- Interaction term lookup table
- Normalization factor table (by year/program)
- Blend calculation engine (for V24/V28 transition years)

**Data Refresh Requirements**:
- Annual coefficient updates (released by CMS ~April)
- Normalization factor updates
- New ICD-10 code mappings annually (October)

---

## References and Sources

The information in this document was compiled from the following authoritative sources:

- [Wolters Kluwer - CMS-HCC Version 28 Impact on RAF Scores](https://www.wolterskluwer.com/en/expert-insights/how-cms-hcc-version-28-will-impact-risk-adjustment-factor-raf-scores)
- [CMS Official - 2024 Advance Notice](https://www.cms.gov/files/document/2024-advance-notice-pdf.pdf)
- [AGS Health - Understanding CMS-HCC Model V28](https://www.agshealth.com/blog/understanding-the-changes-in-the-cms-hcc-model-v28/)
- [CSI Companies - Revolutionizing Risk Adjustment V28 Changes](https://csicompanies.com/revolutionizing-risk-adjustment-cms-hcc-version-28-changes/)
- [Foreseemed - Medicare Risk Adjustment Explained](https://www.foreseemed.com/medicare-risk-adjustment)
- [IMO Health - RAF Scores 101](https://www.imohealth.com/resources/raf-scores-101-understanding-risk-adjustment-coding/)
- [The Tuva Project - Risk Adjustment Knowledge Base](https://thetuvaproject.com/knowledge/advanced-topics/risk-adjustment)
- [CMS - 2023 ESRD Risk Adjustment Model Documentation](https://www.cms.gov/files/document/2023esrdmodelmorandmmrupdates508g.pdf)
- [Wakely - FFS Normalization Factor Deep Dive (2025)](https://www.wakely.com/wp-content/uploads/2024/04/deeper-look-cy2025-part-c-ffs-normalization-factor.pdf)
- [Doctutech - HCC V28 Series Parts 1-4](https://www.doctustech.com/part-1-hcc-v28-series/)
- [IntusCare - CMS HCC V28 Transition for PACE](https://intuscare.com/navigating-the-cms-hcc-v28-transition-in-pace/)
- [PMC - HHS-HCC Risk Adjustment Model for Individual Markets](https://pmc.ncbi.nlm.nih.gov/articles/PMC4214270/)
- [CMS - HHS Risk Adjustment Methodology PDF](https://www.cms.gov/cciio/resources/presentations/downloads/hie-risk-adjustment-methodology.pdf)
- [MedPAC - March 2024 Medicare Advantage Comments](https://www.medpac.gov/wp-content/uploads/2024/03/03012024_MA_PartD_CY2025_AdvanceNotice_MedPAC_COMMENT_SEC.pdf)
- [CMS - 2026 Medicare Advantage Rate Announcement](https://www.cms.gov/newsroom/fact-sheets/2026-medicare-advantage-part-d-rate-announcement)

---

**Document Version**: 1.0  
**Last Verified**: April 2026  
**Suitable For**: SaaS Product Development, Risk Adjustment Analytics, HCC Coding Systems
