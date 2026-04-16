# Risk Adjustment Beyond Medicare Advantage: Comprehensive Research Guide

## Executive Summary

Risk adjustment systems in US healthcare extend far beyond Medicare Advantage. This research covers ACA/Marketplace plans, Medicaid managed care, specialized programs (PACE, ESRD), dual-eligible plans, and commercial health plans. Each system uses different models, methodologies, and transfer mechanisms. SaaS solutions supporting these programs must accommodate multiple models with distinct coding rules, hierarchies, coefficients, and validation requirements.

---

## 1. ACA/HHS Risk Adjustment Model vs. CMS-HCC

### 1.1 HHS-HCC Overview (Individual and Small Group Markets)

The **HHS-HCC model** is CMS's risk adjustment tool for ACA marketplace plans in 36 states and regional small group markets.

**Key Characteristics:**
- **Prediction Timeframe**: Uses current-year diagnoses and demographics to predict current-year spending (concurrent prediction)
- **Cost Basis**: Includes both medical AND drug spending (unlike CMS-HCC which traditionally excluded pharmacy)
- **Population Origin**: Developed using commercially-insured population data (not Medicare)
- **Total HCC Count**: 127 HCCs (vs. CMS-HCC's 86-115 categories depending on version)
- **Special Focus**: Includes 656 pregnancy codes mapping to six HCC categories—critical for marketplace plans serving reproductive-age populations

**Sources:**
- [The HHS-HCC Risk Adjustment Model for Individual and Small Group Markets - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4214270/)
- [How do CMS-HCC and HHS-HCC models compare in 2025? | IMO Health](https://www.imohealth.com/resources/hcc-101-cms-vs-hhs-hierarchical-condition-categories/)

### 1.2 CMS-HCC Model Evolution

**Model Versions and Timeline:**
- **V22 (Legacy)**: Previously used for Medicare Advantage; being phased out
- **V24**: Standard through 2023; uses 86 HCC categories with 9,797 valid ICD-10-CM codes
- **V28 (Current)**: Effective 2024+; 115 HCC categories with 7,770 valid codes (net reduction of 2,027 codes)

**V24 to V28 Transition Details:**
- **Population Data Source**: Medicare aged (≥65) and disabled (<65) beneficiaries
- **Constraining Feature**: V28 introduces HCC constraining—related HCCs assigned same coefficient to prevent double-counting clinically related conditions
  - Example: Diabetes with complications no longer receives separate additive HCC values
- **RAF Weight Changes**: 
  - Cirrhosis of liver: 0.363 (V24) → 0.447 (V28)
  - Morbid obesity: 0.250 (V24) → 0.186 (V28)
- **Phased Implementation Schedule for Medicare Advantage**:
  - PY 2024: 33% V28, 67% V24
  - PY 2025: 67% V28, 33% V24
  - PY 2026: 100% V28
  - By 2028-2029: Complete transition with encounter data

**Sources:**
- [CMS-HCC Model V28: Full List - RAAPID](https://www.raapidinc.com/blogs/cms-hcc-model-v28/)
- [A primer on the CMS-HCC transition from V24 to V28 | IMO Health](https://www.imohealth.com/resources/a-primer-on-the-cms-hcc-transition-from-v24-to-v28/)
- [Understanding HCC v28: What Changed, What It Means - Keebler Health](https://keebler.health/understanding-hcc-v28/)

### 1.3 HHS-HCC vs. CMS-HCC Fundamental Differences

| Dimension | HHS-HCC (ACA) | CMS-HCC (Medicare) |
|-----------|---------------|-------------------|
| **Use Case** | Individual/Small Group ACA Marketplace | Medicare Advantage, PACE |
| **Population Designed For** | Commercial (non-elderly) | Elderly/Disabled Medicare |
| **Time Orientation** | Concurrent (current year predicts current) | Prospective (prior year predicts next) |
| **Cost Categories** | Medical + Drug | Medical only (except Part D) |
| **Total HCC Count** | 127 | 86-115 (varies by version) |
| **Special Populations** | Pregnancy/neonatal (656 codes) | ESRD, Dialysis status |
| **Coding Resistance** | Generally less resistant to gaming | Designed resistant to upcoding |

**Sources:**
- [Affordable Care Act Risk Adjustment: Overview, Context, and Challenges - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4214269/)
- [CMS-HCC vs HHS-HCC: Key Differences - MEDCODE](https://medcodeservices.com/blog/cms-hcc-vs-hhs-hcc-key-differences-in-risk-adjustment-explained/)

---

## 2. EDGE Server Submissions for ACA Plans

### 2.1 EDGE Server Overview

**EDGE** = Encounter Data, Group, and Enrollment system. All ACA issuers must submit enrollment and claims data on a predefined annual schedule.

**Annual Submission Timeline:**
- **October 1 - April 30**: Data submission window (benefit year claims/enrollment)
- **Fall/Winter**: Initial submissions open
- **Late April**: Final data submission deadline
- **May-June**: CMS performs risk adjustment calculations
- **August**: Risk adjustment transfers processed

### 2.2 Data Requirements and Quality

**What Must Be Submitted:**
1. **Enrollment Data**: Member demographics, coverage effective/termination dates, plan selection
2. **Claim Data**: Medical and pharmacy claims with diagnosis codes, procedure codes, dates of service
3. **Business Rules**: Plan design (deductibles, copays, out-of-pocket maximums)
4. **Service Area**: Rating area information and geographic data
5. **Rate Data**: Plan premium rates and actuarial value information

**Critical Quality Requirements:**
- Each issuer is responsible for "completeness and accuracy of benefit year data submitted"
- Default risk adjustment charge = PMPM × enrollment if data quality issues exist
- Missing information, EDGE errors, and misspecifications affect risk adjustment transfers "either now or in future audits"
- These issues create "double jeopardy": less favorable results for compliant plans, more favorable for non-compliant

**Sources:**
- [EDGE 2024_QQ Guidance - CMS](https://www.cms.gov/files/document/edge-2024qq-guidance508-compliant.pdf)
- [ACA risk adjustment management: Higher EDGE-ucation | Milliman](https://www.milliman.com/en/insight/aca-risk-adjustment-management-higher-edge-ucation)
- [Best practices for navigating annual EDGE server submissions | Milliman](https://us.milliman.com/en/insight/in-it-for-the-long-haul-best-practices-for-edge-server-submissions)

### 2.3 Risk Adjustment Process Flow

```
1. RBIS Submission (Fall)
   ↓ Plan/benefit data, rates, service areas
2. Senior Officer Attestation
   ↓ Plans approved for EDGE submission
3. EDGE Data Submission (Oct-April)
   ↓ Claims and enrollment data
4. CMS Validation & MAO-004 Report
   ↓ Accepted ICD-10/HCC assignments
5. Risk Score Calculation
   ↓ HHS-HCC applied to diagnoses
6. Transfer Formula Applied
   ↓ Plan-level charges/receipts determined
7. Transfer Settlement (August)
   ↓ Funds move between plans
```

---

## 3. ACA Risk Adjustment Transfer Formula

### 3.1 Transfer Formula Components and Purpose

**Purpose**: Reduce impact of risk selection on premiums by redistributing funds from low-risk to high-risk plans on budget-neutral basis.

**Key Formula Components:**
1. **Plan Risk Score**: HHS-HCC derived from submitted diagnoses
2. **Plan Rating Factor**: Age, tobacco, family composition adjustments
3. **Actuarial Value Factor**: Plan's cost-sharing level (60%, 70%, 80%, 90%)
4. **Induced Demand Factor**: Behavioral cost impact of plan design
5. **Geographic Cost Factor**: Regional cost variations
6. **Statewide Average Premium**: Scaling factor for all calculations

### 3.2 Transfer Formula Mechanics

**Formula Overview:**
```
Transfer = (Plan Required Revenue / Statewide Avg Required Revenue) 
         - (Plan Allowable Premium / Statewide Avg Allowable Premium)
         × Statewide Enrollment-Weighted Market Average Premium

If positive = Plan RECEIVES funds (high risk pool subsidy)
If negative = Plan PAYS INTO pool (low risk pool contribution)
```

**Statewide Average Premium Calculation:**
- Calculated separately for each rating area
- Standardized to remove age rating by dividing by plan rating factors
- For 2022 BY: Reduced by 14% to account for administrative costs not varying with claims
- Enrollment-weighted across all plans in the market

**Budget Neutrality Constraint:**
- Sum of all transfers must equal zero within each state
- Premium contributions match premium receipts exactly
- No external subsidies to/from CMS

### 3.3 Transfer Magnitude (2014 Example)

- **Individual Market**: ~10% of premiums transferred (~$3.5 billion nationwide)
- **Small Group Market**: ~6% of premiums transferred (~$1.1 billion nationwide)
- **Total**: $4.6 billion transferred in 2014

**Transfer Concerns:**
- Formula penalizes plans with lower premiums relative to statewide average
- Disadvantages newer plans and smaller plans with different risk profiles
- Creates incentives for lower actuarial value and higher cost-sharing

**Sources:**
- [Risk Transfer Formula for Individual and Small Group Markets - CMS](https://www.cms.gov/mmrr/Articles/A2014/MMRR2014_004_03_a04.html)
- [Risk Transfer Formula - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4209298/)
- [CMS White Paper: ACA Risk Adjustment Methodology - Health Affairs Forefront](https://www.healthaffairs.org/content/forefront/cms-white-paper-examines-aca-risk-adjustment-methodology-update)

---

## 4. Medicaid Managed Care Risk Adjustment Models by State

### 4.1 Overall State Usage

**Prevalence of Risk Adjustment:**
- **38 Medicaid programs** use risk-adjusted capitation for MCO payments
- **33 of 38** (~87%) use CDPS as their primary model
- **5 remaining** use alternatives (Ingenix Symmetry, ACG, DxCG, CRxG, or proprietary state models)

**Multi-Model Approach:**
- Single states often use different models for different populations
- Example: State might use CDPS for TANF recipients, different model for elderly/disabled

**Update Cycle for CDPS:**
- 2017-2019 data from 8 states: Florida, Illinois, Kansas, Kentucky, Louisiana, Michigan, New Jersey, Washington
- Covered ~17 million person-years of Medicaid MCO claims

**Sources:**
- [Medicaid Risk Adjustment - Medicaid Innovation](https://medicaidinnovation.org/wp-content/uploads/2023/04/CDPS_April_Fact-Sheet_FINAL.pdf)
- [Medicaid and CHIP Managed Care Payment Methods and Spending in 20 States - ASPE](https://aspe.hhs.gov/reports/medicaid-chip-managed-care-payment-methods-spending-20-states-0)

### 4.2 State-Specific Examples

#### Arizona
- Uses **competitive bidding** for capitation rate-setting
- Longer history of encounter data usage compared to claims
- Risk adjustment integrated with actuarial rate setting

#### California
- Uses **pharmacy utilization data** prominently (more complete than encounter data)
- Only **20% of capitation rate** determined by risk adjustment (phased approach)
- Recent expansion of Medicaid dollars for social determinants (housing, meals, transportation)

#### New York
- Implemented risk-adjusted rates in **2008**
- Replaced 10 rate cells (age/sex/geography/eligibility) with **3 rate cells** (age/eligibility)
- Covers HCBS (home and community-based services) through D-SNP integration

**Sources:**
- [Medicaid and CHIP Managed Care Payment Methods - Urban Institute](https://www.urban.org/sites/default/files/publication/24051/412925-medicaid-and-chip-managed-care-payment-methods-and-spending-in-states.pdf)

---

## 5. CDPS (Chronic Illness and Disability Payment System)

### 5.1 CDPS Core Methodology

**Purpose**: Diagnose-based risk adjustment specifically designed for Medicaid populations (low-income, disabled, pregnant women, children).

**Key Characteristics:**
- **Diagnostic Classification**: Uses ICD codes (ICD-9 historically, now ICD-10)
- **Major Categories**: 19 major body system/disease categories
- **Specific Categories**: 52 CDPS-specific categories within the major groups
- **Hierarchy Approach**: Within each category, clinical severity and expected cost impact establish hierarchy
- **Sample-Resistant Design**: Originally designed with fewer categories (58 vs. 76-127 in competing models) to resist gaming and overcoding
- **Medicaid-Specific**: Conditions common in Medicaid populations (e.g., complications of disabilities, maternal/neonatal conditions)

**Recent Updates (2022):**
- Data: 2017-2019 from 3 national MCOs across 8 states
- Revision Coverage: 17 million person-year observations
- **Six Categories Substantially Revised**:
  1. Psychiatric/behavioral
  2. Pulmonary/respiratory
  3. Renal/kidney
  4. Cancer
  5. Infectious disease
  6. Hematological conditions

### 5.2 CDPS Variants and Related Models

**CDPS+Rx (Current Version 7.0+)**
- Incorporates pharmacy/drug utilization data
- Improves predictive accuracy for pharmaceutical cost management
- Version 7.1 update reviewed November 2024

**Related Medicaid Models:**
- **Ingenix Symmetry**: Episode-based grouper; alternative to CDPS
- **CRxG** (Clinical Pharmaceutical Groups): Combines diagnoses and pharmacy
- **ACG** (Adjusted Clinical Groups): Johns Hopkins system; focuses on multimorbidity
- **DxCG**: Originally CMS development; robust for general populations
- **State-Proprietary Models**: Some states develop custom models (e.g., California)

### 5.3 CDPS vs. CMS-HCC Comparison

| Aspect | CDPS (Medicaid) | CMS-HCC (Medicare) |
|--------|-----------------|-------------------|
| **Population** | Low-income, disabled, pregnant, children | Elderly, disabled beneficiaries |
| **Design Approach** | Fewer categories; gaming-resistant | Comprehensive; granular |
| **Data Origin** | Medicaid MCO claims (diverse populations) | Medicare claims (elderly-dominated) |
| **Cost Prediction** | Medicaid-typical spending | Medicare-typical spending |
| **Disability Focus** | High (disability complications included) | Lower (fewer disability-specific) |
| **Categories** | 52 specific (19 major) | 115 (V28) or 86 (V24) |
| **Pharmacy Integration** | CDPS+Rx explicit | Separate Part D analysis |

### 5.4 Social Determinants Finding

**Important Limitation**: Analysis of updated CDPS found **no consistent relationship between area-level deprivation and healthcare spending** within Medicaid populations, suggesting risk adjustment alone may not effectively address health disparities. Additional SDH interventions needed.

**Sources:**
- [Updating the Chronic Illness and Disability Payment System - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10871574/)
- [CDPS Methodology - UCSD](http://cdps.ucsd.edu/)
- [Improving Health-Based Payment for Medicaid - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4194678/)

---

## 6. Dual-Eligible Special Needs Plans (D-SNP) Risk Adjustment

### 6.1 D-SNP Overview

**Target Population**: Beneficiaries entitled to both:
- **Medicare** (Title XVIII) - aged or disabled
- **Medicaid** (Title XIX) - state coverage

**Plan Structure**:
- Medicare Advantage plans specializing in dual-eligible populations
- Capitation payment from CMS for Medicare benefits
- Separate Medicaid capitation from state (or integrated through FIDE SNP)

### 6.2 D-SNP Risk Adjustment Methodology

**Payment Basis**:
- D-SNPs paid using **same risk adjustment method as other MA plans** (CMS-HCC based)
- Capitation payments adjusted for:
  - Beneficiary health conditions
  - Demographic characteristics (dual status, disability status, institutional status)
  - Dual-eligible indicator (higher average costs)

**Higher Risk Adjustment Factors**:
- CMS per-enrollee payments to D-SNPs "generally higher than other MA plans in same area"
- This reflects specialization in high-cost population, NOT SNP status advantage
- Results from HCC concentration in chronically ill, disabled population

### 6.3 FIDE SNP Frailty Adjustment

**FIDE SNP** (Fully Integrated Dual Eligible) = Enhanced integration of Medicare + Medicaid through single MCO.

**Frailty Adjustment Calculation**:
```
Frailty Score = 33% × V24 Frailty Factor + 67% × V28 Frailty Factor (CY 2025)
Blended toward 50-50 by 2028
100% V28 by 2029
```

**Frailty Basis**:
- Activities of Daily Living (ADL) limitations from Medicare HOS (Health Outcomes Survey)
- HOS-M (Modified) = shorter version with 6 ADL core items
- Data collected from previous year; applied in current payment year
- Separate frailty calculations for:
  - Non-ESRD community-residing enrollees age 55+
  - LTI (Long-term institutional) populations
  - ESRD populations (separate calculation)

**Application**:
- Frailty score added to risk score only if plan's frailty meets/exceeds PACE minimum threshold
- PACE minimum (PY 2023): 0.129

**Sources:**
- [Dual Eligible Special Needs Plans - CMS](https://www.cms.gov/medicare/enrollment-renewal/special-needs-plans/dual-eligible)
- [2023 Frailty Scores - CMS](https://www.cms.gov/files/document/2023frailtyscoreshpmsmemo582023508g.pdf)
- [Dual Eligible SNPs & MACPAC](https://www.macpac.gov/subtopic/medicare-advantage-dual-eligible-special-needs-plans-aligned-with-medicaid-managed-long-term-services-and-supports/)

---

## 7. PACE (Programs of All-Inclusive Care for the Elderly) Risk Adjustment

### 7.1 PACE Payment Structure

**PACE Target**: Frail elderly (75+ typically) in community settings; alternative to institutionalization.

**Payment Mechanism**:
- **Capitated PMPM** from Medicare + Medicaid
- **CMS-HCC Risk Adjustment**: Core payment adjustment
- **Frailty Adjustment**: Organizational-level addition based on participant survey data

### 7.2 Risk Adjustment Components

**Calculation Formula**:
```
PACE Payment = Base Rate 
             × [(Organizational-Specific Frailty Score) + (Participant-Level HCC Risk Score)]
```

**Participant-Level Risk Score**:
- Uses CMS-HCC model (currently transitioning from V22 to V28)
- Similar to Medicare Advantage scoring

**Organizational-Level Frailty Score**:
- Calculated from **HOS-Modified (HOS-M)** survey responses
- Completed annually by PACE participants
- Reflects limitations in activities of daily living (ADLs)
- Compared to PACE minimum threshold (e.g., 0.129 in PY 2023)

### 7.3 V22 to V28 Transition Timeline (2026-2029)

**Progressive Blending Schedule**:
- **2026**: 10% V28 + 90% V22 blend
- **2027**: (Interim year)
- **2028**: 50% V28 + 50% V22 blend
- **2029**: 100% V28 + encounter data (final state)

**Rationale**: Gradual transition allows system adjustments; encounter data implementation phased in final year.

### 7.4 Special Populations in PACE

**Separate Risk Adjustment Factors**:
- **Long-Term Institutional (LTI)**: Different frailty and HCC factors
- **ESRD**: Separate HCC model (omits dialysis/renal failure HCCs since all have ESRD)

**Sources:**
- [Understanding PACE Capitation and Funding - Health Dimensions Group](https://healthdimensionsgroup.com/insights/blog/pace-funding/)
- [PACE Medicare Risk Adjustment - LeadingAge NY](https://www.leadingageny.org/providers/managed-long-term-care/pace-and-map/pace-medicare-risk-adjustment/)
- [PACE providers gearing up for new risk calculation model in 2026 - McKnights](https://www.mcknightshomecare.com/news/pace-providers-gearing-up-for-new-risk-calculation-model-in-2026/)

---

## 8. ESRD (End-Stage Renal Disease) Model Specifics

### 8.1 ESRD Risk Adjustment Overview

**ESRD Definition**: Patients with kidney failure requiring dialysis or transplant; Medicare-eligible regardless of age.

**Payment Framework**:
- ESRD beneficiaries eligible for Medicare regardless of age
- Approximately 780,000 US ESRD patients
- Significant cost concentration (15-20% of Medicare spending with 1% of beneficiaries)

### 8.2 CMS-HCC ESRD Risk Adjustment Model

**Key Distinctions**:
- **HCC Omissions**: All kidney-disease-related HCCs removed
  - Dialysis status HCC omitted (all have ESRD)
  - Renal failure HCC omitted
  - Nephritis HCC omitted
- **Reason**: Since ALL ESRD patients already in most severe kidney category, these HCCs create artificial variation
- **Focus Shift**: Payment adjusts for **treatment modality and comorbidities** instead

**Model Calibration**:
- Updated to use more recent data (recent revision)
- Improves on prior version by better capturing treatment status differences
- Accounts for hemodialysis vs. peritoneal dialysis vs. transplant variations

### 8.3 ESRD Treatment Choices (ETC) Model

**Alternative Specialized Model**:
- Mandatory model designed to incentivize home dialysis and kidney transplants
- Goal: Improve quality while reducing costs
- **Status as of November 2025**: CMS finalized end of ETC Model effective CY 2026
- ETC represented CMS innovation in payment models focused on modality selection

**ESRD Prospective Payment System (PPS)**:
- Separate bundled payment for dialysis services under Outpatient Prospective Payment System
- Includes drugs, supplies, and dialysis labor
- Different from capitated MA/PACE ESRD payments

### 8.4 ESRD in PACE and D-SNP

**PACE ESRD Participants**:
- Separate frailty and risk adjustment calculation
- HOS-M survey still administered
- Different HCC model applied
- Can be institutional or community

**D-SNP/FIDE SNP ESRD Participants**:
- Separate frailty calculation (not eligible for standard frailty adjustment)
- CMS-HCC applied with ESRD-specific factors
- Consideration for transplant status and dialysis modality

**Sources:**
- [2023 CMS-HCC ESRD Risk Adjustment Model - CMS](https://www.cms.gov/files/document/2023esrdmodelmorandmmrupdates508g.pdf)
- [Risk-Adjustment System for Medicare Capitated ESRD - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4194965/)
- [ESRD Treatment Choices Model - CMS](https://www.cms.gov/priorities/innovation/innovation-models/esrd-treatment-choices-model)
- [Early Findings from Medicare's ESRD Treatment Choices Model - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10133989/)

---

## 9. Commercial Risk Adjustment Models

### 9.1 Model Landscape

**Major Commercial Models** (Non-Government Payers):
1. Johns Hopkins ACG (Adjusted Clinical Groups)
2. Optum DxCG (originally CMS-developed)
3. Optum Impact Pro
4. Ingenix Symmetry (episode-based)
5. Proprietary models (various vendors)

### 9.2 Johns Hopkins ACG System

**Overview**:
- Developed by Johns Hopkins clinicians/researchers
- 30+ years operational
- Used across commercial, government, health systems, large employers
- Billions of dollars in capitation facilitation

**Core Methodology**:
- **Whole-Person Approach**: Patterns of disease vs. single conditions
- **Resource Prediction**: Classifies individuals by expected healthcare resource use
- **Concurrent & Prospective**: Can apply both current and future risk
- **ACG Cells**: 102 actuarial cells with national or localized weights

**ACG Risk Stratification**:
- Diagnostic codes map to ADGs (Ambulatory Diagnostic Groups)
- Multiple ADGs aggregate into ACGs
- Each cell has relative risk index for capitation
- Multimorbidity handling: Accounts for compounding complexity of multiple conditions

**Applications**:
- Capitation rate-setting
- Quality benchmarking
- Utilization prediction
- Care management targeting
- Private exchanges and employer plans

**Sources:**
- [Johns Hopkins ACG System Overview](https://www.hopkinsacg.org/about-the-acg-system/)
- [The Johns Hopkins ACG System Technical Reference](https://www.healthpartners.com/content/dam/brand-identity/pdfs/care/acg-technical-guide.pdf)

### 9.3 DxCG Model (Optum)

**History & Development**:
- Originally developed in partnership with CMS
- Foundation for CMS-HCC model still used today
- Became standard for commercial risk adjustment
- Continuous recalibration (every 2-3 years)

**Methodology**:
- Diagnostic and cost group assignment
- Includes pharmacy data integration
- Robust cost prediction across diverse populations
- Hierarchical condition classification

**Comparative Performance**:
- Studies show DxCG prospective risk scores similar to CMS V21
- DxCG with pharmacy data offers improved fit over V21 alone
- Particularly strong with pharmacy/drug cost prediction

**Sources:**
- [The evolution of DxCG - Cotiviti](https://resources.cotiviti.com/risk-adjustment/cotiviti-whitepaper-evolutionofdxcg)
- [Risk Adjustment Tools Comparison: DxCG and CMS-HCC V21 - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5034200/)

### 9.4 Optum Impact Pro

**Focus**: Avoidable costs and high-risk case management candidates.

**Methodology**:
- Episode-based predictive modeling (ETG™ methodology)
- Combines administrative claims with clinical data
- **Morbidity-based**, not service utilization based
- Prospective, retrospective, and actuarial configurations available

**Key Features**:
- 600+ clinical measures for gap identification
- Predicts healthcare usage and costs
- Targets high-benefit-from-case-management patients
- Flexible implementation timeframes
- Recalibration frequency: Every 2-3 years

**Best Use**: When focus is avoidable admission reduction and case management ROI identification

**Sources:**
- [Impact Pro for Care Management - Optum](https://www.optum.com.br/content/dam/optum/resources/productSheets/Impact_Pro_for_Care_Management_ps_06_2012.pdf)
- [Predictive Models: Current and Future - EHCCA](https://www.ehcca.com/presentations/predmodel5/wickstrom_2.pdf)

### 9.5 Risk Adjustment Model Comparison

| Model | Population | Strength | Best For |
|-------|-----------|----------|----------|
| **ACG** | Commercial/All | Multimorbidity handling | Employer/exchange plans |
| **DxCG** | General population | Pharmacy integration | Cost prediction accuracy |
| **Impact Pro** | High-cost subset | Avoidable costs | Case management targeting |
| **CDPS** | Medicaid | Medicaid-specific conditions | Medicaid MCO capitation |
| **CMS-HCC** | Medicare | Regulatory compliance | MA/PACE/ESRD |
| **HHS-HCC** | ACA marketplace | Pregnancy/neonatal | ACA plan payment |

**Sources:**
- [Understanding the Differences Between Risk Adjustment Programs - Edifecs](https://www.edifecs.com/blog/understanding-the-differences-between-risk-adjustment-programs/)
- [HDG #021: The many predictive risk models in healthcare - Stefany Goradia](https://stefanygoradia.com/newsletter/hdg-021-the-many-predictive-risk-models-in-healthcare)

---

## 10. SaaS Architecture for Multi-Model Risk Adjustment

### 10.1 Core Architecture Components

A healthcare SaaS platform supporting multiple risk adjustment models must accommodate:

**1. Data Integration Layer**
- **Multi-source ingestion**: EHRs, claims systems, pharmacy, labs, patient-generated data
- **ETL pipelines**: Extract, transform, load with validation checkpoints
- **Data standardization**: Normalize codes (ICD-10, CPT, NDC) across sources
- **HIPAA compliance**: Encryption at rest/transit, audit logging, access controls

**2. Diagnostic Code Management**
- **Version control**: Maintain ICD-10-CM mappings for all models
- **Model-specific mappings**:
  - HHS-HCC: 127 HCCs from 9,797+ codes
  - CMS-HCC V24: 86 HCCs from 9,797 codes
  - CMS-HCC V28: 115 HCCs from 7,770 codes
  - CDPS: 52 categories from variable code set
  - ACG: ADG-to-ACG mapping structure
  - DxCG: Alternative diagnostic grouping
- **ICD-10-to-ICD-9 mapping** (legacy support)
- **Code validation**: Reject invalid codes before scoring

**3. Multi-Model Risk Score Calculation Engine**

```
Architecture Pattern:
┌─────────────────────────────────────┐
│   Diagnosis Code Input              │
│   (ICD-10 + supporting data)        │
└──────────┬──────────────────────────┘
           │
      ┌────┴─────┬──────────┬────────┬──────────┐
      │           │          │        │          │
   ┌──▼──┐    ┌──▼──┐    ┌──▼──┐ ┌──▼──┐   ┌──▼──┐
   │HHS  │    │CMS  │    │CDPS │ │ACG  │   │DxCG │
   │HCC  │    │HCC  │    │     │ │     │   │     │
   │V127 │    │V28  │    │     │ │     │   │     │
   └──┬──┘    └──┬──┘    └──┬──┘ └──┬──┘   └──┬──┘
      │           │          │        │          │
      └───────────┴──────────┴────────┴──────────┘
                  │
         ┌────────▼─────────┐
         │ Risk Score Array │
         │ [HHS, CMS, CDPS, │
         │  ACG, DxCG, ...]│
         └──────────────────┘
              │
         ┌────▼──────────┐
         │ Regulatory    │
         │ Compliance    │
         │ & Audit Trail │
         └───────────────┘
```

**Implementation Patterns**:
- **Parallel processing**: Calculate all model scores for single member simultaneously
- **Version management**: Support multiple CMS-HCC versions (V22, V24, V28 blend)
- **Hierarchical application**: Enforce HCC hierarchies (parent-child relationships)
- **Constraining logic**: V28 constraining rules to prevent double-counting

**4. Pharmacy Data Integration**
- NDC-to-therapeutic category mapping
- Pharmacy claims vs. medical claims reconciliation
- Inclusion in models using pharmacy (CDPS+Rx, DxCG, etc.)
- Exclude from models not using (traditional CMS-HCC)

**5. Special Population Handling**
- **Frailty calculations** (PACE, D-SNP): ADL score application
- **ESRD determination**: Dialysis status, transplant status, treatment modality
- **Pregnancy status**: For HHS-HCC (656 pregnancy codes)
- **Institutional status**: LTI vs. community-dwelling for frailty calculations

**6. Validation and Compliance Layer**

**Input Validation**:
- Diagnosis code format/validity (must exist in ICD-10-CM)
- Date range checks (service date within benefit year)
- Member eligibility checks (alive, covered on service date)
- Code source validation (only accepted encounter sources)

**Output Validation**:
- Risk score reasonableness checks (flagging outliers)
- HCC assignment audit trails (member diagnosis → HCC mapping)
- MEAT criteria validation (Monitoring/Evaluating/Assessing/Treating rule)
- Reconciliation with government reports (MAO-004 for ACA)

**Audit Logging**:
- Every score calculation logged with timestamp, user, model version
- Diagnosis code changes tracked (added/removed/corrected)
- Score recalculation history maintained
- Export capabilities for CMS audits

**7. Data Pipeline Architecture for Batch Processing**

```
Claims/Enrollment Batch
        │
        ▼
┌──────────────────┐
│ Input Validation │ ← Reject invalid claims
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Code Normalization│ ← ICD-10 validation
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Member Dedup     │ ← Multiple claims per member
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Risk Calculation │ ← All models in parallel
│ (Parallelized)   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Hierarchy Apply  │ ← Resolve HCC conflicts
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Output Validation│ ← Score reasonableness
└────────┬─────────┘
         │
         ▼
Risk Score Report
(HHS, CMS, CDPS, ACG, etc.)
```

**8. Transfer Formula & Payment Calculations**

For ACA plans:
- Implement transfer formula components (statewide average premium, rating factors, etc.)
- State-level aggregations
- Budget neutrality calculations
- Transfer amount determination

For Medicaid/PACE/ESRD:
- Per-member capitation calculations
- Frailty adjustments where applicable
- State-specific rate cells
- MCO/health plan level grouping

### 10.2 Multi-Tenant Architecture Considerations

**Security & Isolation**:
- Separate schemas per tenant (or row-level security)
- Encrypted data segregation
- Per-tenant encryption keys
- Audit logs capturing tenant access
- HIPAA Business Associate Agreements (BAAs)

**Cost Efficiency**:
- Shared infrastructure across tenants: 40-60% cost reduction vs. single-tenant
- Database pooling and query optimization
- Batch processing efficiency
- Per-tenant resource limits and metering

**Performance**:
- Caching layer for code mappings (ICD-10 to HCC)
- Parallel calculation engines
- Batch processing for large member populations
- Real-time scoring for enrollment/claims submissions

### 10.3 Data Quality & Governance

**Coding Accuracy**:
- Modern systems achieve 98%+ coding accuracy
- Chart review time: <10 minutes with AI assistance
- NLP for diagnosis extraction from unstructured clinical notes
- MEAT criteria validation (clinical documentation validation)

**Pattern Monitoring**:
- Continuous coding pattern analysis
- Flagging unusual HCC concentrations
- Provider comparison (specialty-adjusted)
- Benchmarking against regional/national norms

**CMS Integration Points**:
- **EDGE server validation**: Confirm submitted codes appear in MAO-004
- **MAO-004 reconciliation**: Match CMS-accepted diagnoses to internal records
- **RADV audit preparation**: Maintain linkage between submitted codes and source documents
- **Payment reconciliation**: Track permanent vs. advance payments

### 10.4 Regulatory Compliance Requirements

**Model-Specific Compliance**:
- **ACA/HHS-HCC**: EDGE submission requirements, transfer formula calculations
- **Medicare/CMS-HCC**: V28 transition, PACE frailty integration, ESRD special rules
- **Medicaid/CDPS**: State-specific model versions, encounter data timing
- **RADV Audit**: Documentation retention, code supporting evidence

**Documentation Requirements**:
- ICD-10 code to source documentation linkage
- HCC assignment justification (condition hierarchy)
- Frailty calculation details (HOS-M responses)
- Transfer formula component tracking

**Error Recovery**:
- Code correction workflows (diagnosis added/removed)
- Score recalculation and reconciliation
- CMS resubmission handling
- Audit defense documentation

### 10.5 Recommended Architecture Pattern

```
┌─────────────────────────────────────────────────────┐
│           API Gateway (HIPAA-compliant)             │
├─────────────────────────────────────────────────────┤
│ Claims/Enrollment Submission Layer                  │
│  ├─ Batch ingestion (SFTP, HL7, proprietary)      │
│  ├─ Real-time API (REST, gRPC)                     │
│  ├─ Validation & preprocessing                      │
├─────────────────────────────────────────────────────┤
│ Data Warehouse (Multi-tenant)                       │
│  ├─ Member master (demographics, enrollment)       │
│  ├─ Claims (medical, pharmacy)                      │
│  ├─ Code mappings (HCC, ACG, CDPS versions)       │
│  ├─ HOS-M survey data (frailty)                    │
│  ├─ State-specific configuration                    │
├─────────────────────────────────────────────────────┤
│ Risk Calculation Engines (Microservices)            │
│  ├─ HHS-HCC V127 calculator                        │
│  ├─ CMS-HCC V24 calculator                         │
│  ├─ CMS-HCC V28 calculator (with constraining)     │
│  ├─ CDPS (+ CDPS+Rx) calculator                    │
│  ├─ ACG calculator                                  │
│  ├─ DxCG calculator                                │
│  ├─ Frailty calculator (PACE, D-SNP)               │
│  ├─ ESRD modifier application                       │
│  └─ Parallel execution (Apache Spark, Kubernetes)  │
├─────────────────────────────────────────────────────┤
│ Business Logic Layer                                │
│  ├─ HCC hierarchy enforcement                      │
│  ├─ Pharmacy data inclusion/exclusion              │
│  ├─ Validation rules & MEAT criteria               │
│  ├─ Payment/transfer formula calculations          │
│  ├─ State-specific rate cells                      │
├─────────────────────────────────────────────────────┤
│ Compliance & Audit Layer                            │
│  ├─ EDGE validation (MAO-004 reconciliation)       │
│  ├─ RADV audit trail                                │
│  ├─ Documentation links (code → source)            │
│  ├─ Encryption & access control                     │
│  ├─ Audit logging (all calculations)               │
├─────────────────────────────────────────────────────┤
│ Reporting & Analytics                               │
│  ├─ Risk score distribution by model                │
│  ├─ HCC assignment frequency                        │
│  ├─ Payment reconciliation                          │
│  ├─ Benchmark comparisons                           │
│  ├─ Compliance dashboards                           │
├─────────────────────────────────────────────────────┤
│ Tenant Management                                    │
│  ├─ Multi-tenant isolation                          │
│  ├─ Billing & metering                              │
│  ├─ Configuration management                        │
│  ├─ User access control (RBAC)                      │
└─────────────────────────────────────────────────────┘
```

### 10.6 Technology Stack Recommendations

**Backend**:
- **Language**: Python, Java, or Go (performance + ecosystem)
- **Data Processing**: Apache Spark (batch), Kafka (streaming)
- **Database**: PostgreSQL (relational), TimescaleDB (time-series audit logs)
- **Containerization**: Docker, Kubernetes for microservices

**Risk Calculation**:
- **Model implementation**: Python (scikit-learn, pandas), SQL stored procedures
- **Parallel processing**: Spark clusters, distributed computing
- **Version control**: Git for model specifications, coefficient tracking

**Security**:
- **Encryption**: TLS 1.2+ for transit, AES-256 at rest
- **Access Control**: OAuth2/SAML for SSO, RBAC for authorization
- **Audit**: Immutable audit logs, compliance with HIPAA Technical Safeguards

**Compliance**:
- **Documentation**: Automated evidence gathering for RADV audits
- **Testing**: Regression testing on model updates, validation rule testing
- **Monitoring**: Real-time alerts on validation failures, outlier detection

**Sources:**
- [Risk Adjustment Coding: Technical Architecture Guide - Invene](https://www.invene.com/blog/risk-adjustment-coding)
- [20 Risk adjustment software vendors to consider in 2026 - Arcadia](https://arcadia.io/resources/risk-adjustment-software)
- [SaaS Data Validation Solution - UpperThrust](https://www.upperthrust.com/industry/technology-software-industry/saas-based-data-validation/)
- [Healthcare SaaS Development - Digital Scientists](https://digitalscientists.com/healthcare/capabilities/healthcare-saas-development/)

---

## 11. Key Differences Summary Table

| Program | Model | Population | Data Source | Transfer Mechanism | Key Features |
|---------|-------|-----------|-------------|-------------------|--------------|
| **ACA Marketplace** | HHS-HCC V127 | Commercial (non-elderly) | EDGE server | Risk transfer formula (budget-neutral redistribution) | Pregnancy codes, drug costs included, 10-15% of premiums transferred |
| **Medicare Advantage** | CMS-HCC V28 (blended V24) | Elderly/Disabled | Encounter data | Capitation rate adjustment | ESRD special rules, FIDE SNP frailty adjustment |
| **PACE** | CMS-HCC V22→V28 blend | Frail elderly 75+ | HOS-M survey + encounters | Capitation × frailty multiplier | Organizational frailty score, gradual V28 transition |
| **ESRD** | CMS-HCC (ESRD model) | All ESRD patients | Claims + modality data | Capitation with treatment modality adjustment | Dialysis/renal codes omitted, treatment status critical |
| **Medicaid MCOs** | CDPS+Rx (primarily) | Low-income, disabled, pregnant | Medicaid encounters | State capitation rates | 33 of 38 states use CDPS, fewer categories (gaming-resistant) |
| **D-SNP** | CMS-HCC (MA-based) | Dual-eligible (Medicare + Medicaid) | Medicare encounters | CMS capitation + Medicaid capitation | Higher risk adjustment due to population; FIDE SNP frailty adjustment |
| **Commercial** | ACG / DxCG / Impact Pro | Employer, exchange plans | Claims + pharmacy | Capitation or shared savings | Multimorbidity focus (ACG), cost focus (Impact Pro) |

---

## 12. Critical Implementation Considerations

### 12.1 Regulatory Complexity

1. **Version Management**: Support multiple HCC versions in transition (V24→V28)
2. **State Variation**: Different Medicaid models by state; no federal mandate
3. **Population Determination**: Correct model selection (HHS vs. CMS vs. CDPS vs. ACG)
4. **Time Synchronization**: Different benefit years and submission deadlines across programs

### 12.2 Data Quality Challenges

1. **ICD-10 Validity**: Over 70,000 codes; constantly updated; different subsets per model
2. **Code Mapping Maintenance**: HCC assignments change with model updates
3. **Pharmacy Integration**: Requires NDC-to-therapeutic mapping and separate systems
4. **Documentation Support**: MEAT criteria validation; NLP accuracy critical

### 12.3 Audit Exposure

1. **RADV Audits**: CMS audits MA plans for HCC accuracy; can demand refunds
2. **EDGE Validation**: CMS rejects non-compliant diagnosis codes via MAO-004
3. **State Audits**: Medicaid programs audit MCO submissions and coding
4. **Documentation**: Must maintain source documents linking every HCC to clinical evidence

### 12.4 Financial Risk

- Transfer formula sensitivity: 1% enrollment mix change = millions of dollars
- Coding accuracy: Missing HCC diagnosis = lost capitation payment
- Frailty miscalculation: PACE/D-SNP frailty score errors affect organizational payment
- Reconciliation risk: Permanent vs. advance payments; retroactive adjustments

**Sources referenced throughout document provide deeper guidance on each risk area.**

---

## Conclusion

Risk adjustment extends far beyond Medicare Advantage, spanning seven major program categories with distinct models, methodologies, and compliance requirements. A comprehensive SaaS solution must:

1. **Support multiple concurrent models** (HHS-HCC, CMS-HCC versions, CDPS, ACG, DxCG, Impact Pro)
2. **Handle population-specific logic** (pregnancy, frailty, ESRD, institutional status)
3. **Maintain regulatory compliance** across federal and state programs
4. **Ensure data quality** through validation, audit trails, and documentation
5. **Manage transfer mechanics** (ACA transfer formula, state capitation, frailty adjustments)
6. **Support version transitions** (CMS-HCC V24→V28 blending, CDPS updates)

The architecture must balance performance (calculating scores for millions of members), accuracy (98%+ coding validation), compliance (HIPAA, RADV auditability), and cost-efficiency (multi-tenant isolation with 40-60% savings).

---

## Additional Resources

**CMS/Government:**
- [CMS Risk Adjustment Guidance](https://www.cms.gov/cciio/programs-and-initiatives/premium-stabilization-programs)
- [EDGE Server Documentation](https://www.cms.gov/cciio/resources/presentations/downloads/hie-risk-adjustment-methodology.pdf)
- [Medicare Advantage Rate Setting](https://www.cms.gov/medicare/payment/capitated-payment-systems)

**Academic/Industry:**
- [UCSD CDPS Resource](http://cdps.ucsd.edu/)
- [Johns Hopkins ACG System](https://www.hopkinsacg.org/)
- [Medicaid Innovation Platform](https://medicaidinnovation.org/)

**Vendor Tools:**
- EDGE ASSIST (Milliman)
- RAPID (Wakely)
- Persivia CareSpace
- Cotiviti Risk Solutions
- RAAPID Clinical AI Platform

