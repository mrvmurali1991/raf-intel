# Risk Adjustment Factor (RAF) Calculation: Comprehensive Technical Guide

**Complete Reference for SaaS Product Development**  
**Last Updated**: April 1, 2026

---

## Executive Summary

This document provides authoritative, detailed technical information on RAF (Risk Adjustment Factor) score calculation across all CMS programs. Three comprehensive reference documents have been created:

1. **RAF_Calculation_Deep_Dive.md** - Complete methodology
2. **RAF_Technical_Reference_Coefficients.md** - Coefficient tables and examples
3. **SaaS_Implementation_Architecture.md** - System design and implementation

---

## Part 1: Core RAF Formula and Calculation

### Basic Formula

```
Total RAF = Demographic Component + Σ(HCC Values) + Σ(Interactions) + HCC Count Modifiers

Adjusted RAF = Raw RAF / Normalization Factor
```

### Component Breakdown

#### 1. Demographic Component (Baseline Score)

Calculated from:
- **Age**: Grouped in 5-year bands (65-69, 70-74, etc.)
- **Sex**: Male or Female
- **Eligibility Status**: Original Medicare, Disabled, ESRD
- **Medicaid Status**: Dual eligible (Medicare + Medicaid) vs. non-dual
- **Disability Status**: Under-65 disabled beneficiaries have higher baseline
- **Living Situation**: Community vs. institutional (SNF, nursing home)

**Example Demographic Coefficients (V28)**:
- 72-year-old male, community, non-dual: **0.527**
- 78-year-old female, community, dual: 0.650 + 0.095 = **0.745**
- 85-year-old male, institutional: 0.957 × 1.25 = **1.196**

#### 2. HCC (Hierarchical Condition Category) Coefficients

115 HCCs in V28 model, each with assigned risk coefficient:

| Condition | V28 Coefficient | V24 Coefficient | Change |
|-----------|-----------------|-----------------|--------|
| Metastatic Cancer | 1.089 | 1.073 | +1.5% |
| Chronic Systolic Heart Failure | 0.360 | 0.394 | -8.6% |
| Type 2 Diabetes | 0.166 | 0.105 | +57.6% |
| Chronic Obstructive Pulmonary Disease | 0.441 | 0.416 | +6.0% |
| CKD Stage 5 | 0.530 | 0.434 | +22.1% |

**Important Rule**: Each HCC counted **once per calendar year** regardless of number of encounters or documentation frequency.

#### 3. Disease Interaction Terms

When multiple conditions coexist, additional risk factors apply:

| Interaction | Coefficient | Clinical Rationale |
|-------------|-------------|-------------------|
| Diabetes + Heart Failure | +0.112 | Medication complexity, mortality risk |
| Heart Failure + CKD | +0.189 | Highest risk combination |
| Diabetes + CKD | +0.095 | Vascular complications |

**Key Rule**: Interactions apply **independently of HCC hierarchy** - even if one condition is suppressed by hierarchy, interaction still applies.

#### 4. HCC Count Modifier (V28 Feature)

Bonus for managing multiple complex conditions:

| HCC Count | Modifier |
|-----------|----------|
| 0-4 | 0.000 |
| 5 | +0.050 |
| 6 | +0.075 |
| 7 | +0.095 |
| 8 | +0.115 |
| 9 | +0.130 |
| 10+ | +0.142 (capped) |

---

## Part 2: Model Versions & Transitions

### V24 Model (2014-2023)
- 86 HCC categories
- 9,797 valid ICD-10 codes
- Older calibration data
- Being phased out

### V28 Model (2024-Present)
- 115 HCC categories (↑29)
- 7,770 valid ICD-10 codes (↓2,027)
- More recent calibration data
- Enhanced disease interactions
- Coefficient constraining for diabetes & CHF

### Transition Timeline (Medicare Advantage)

| Payment Year | V24 | V28 | Calculation |
|--------------|-----|-----|-----------|
| 2024 | 67% | 33% | (0.67 × V24) + (0.33 × V28) |
| 2025 | 33% | 67% | (0.33 × V24) + (0.67 × V28) |
| 2026+ | 0% | 100% | 100% V28 |

**Formula for Blend Years**:
```
Adjusted RAF = (V24_score × V24_pct) + (V28_score × V28_pct)
```

### PACE Transition (Different Timeline)

PACE uses older V22 model (2017) with slower V28 transition:
- 2025: 100% V22
- 2026: 90% V22 + 10% V28
- 2027: 80% V22 + 20% V28
- 2028: 50% V22 + 50% V28
- 2029: 100% V28

**Reason**: PACE serves older, more vulnerable population; needs longer implementation runway

---

## Part 3: Patient vs. Encounter vs. Year-Level Calculations

### Patient-Level RAF (Final Score)
- **Definition**: Single combined score for individual patient
- **Scope**: All diagnoses documented in calendar year (Jan 1 - Dec 31)
- **Used For**: Capitation payment rate calculation
- **Frequency**: Recalculated annually

### Encounter-Level Data Capture
- **Definition**: Diagnoses documented in single clinical visit
- **Types**: Office visit, inpatient stay, ED visit, telehealth
- **Purpose**: Feed into annual patient-level calculation
- **Key Rule**: Same diagnosis in multiple encounters same year = counted once

### Year-Level Reset
- **Annual Reset**: RAF scores completely reset January 1
- **Re-documentation**: Chronic conditions must be documented annually to retain credit
- **Data Collection**: Typically uses 12 months of Part B claims for "continuing enrollee" determination

**Example**:
```
Patient seen 4 times for heart failure in 2025
- January office visit: I50.9 documented
- April hospitalization: I50.9 documented
- July office visit: I50.9 documented
- October office visit: No new diagnosis

Result: HCC 85 (CHF) counted ONCE with 0.360 coefficient
Not: 0.360 × 4 = 1.440 (incorrect)
```

---

## Part 4: Program-Specific Models

### Medicare Advantage (Part C)

**Standard MA Population**:
- Model: CMS-HCC V28 (PY2026+)
- HCCs: 115 categories
- Two settings:
  - **Community**: Standard coefficients
  - **Institutional**: 20-40% higher demographic coefficients

**ESRD Population** (Separate Model):
- All kidney disease HCCs = zero-weighted (already in ESRD by definition)
- Dialysis status HCC = zero (implicit for all)
- Only HCC 174 (Transplant Status) estimated uniquely
- All other HCCs use same coefficients as non-ESRD MA model

**ESRD Segments**:
1. Dialysis (current treatment)
2. Transplant 0-2 months post-transplant
3. Transplant 4-9 months post-transplant
4. Transplant 10+ months post-transplant

Each segment has separate model year coefficients.

### PACE Programs

**Current Model**: CMS-HCC V22 (2017 model)
- Uses 86 HCC categories (like old V24)
- Transitioning slowly to V28
- Encounter-based data (not claims-based like MA)
- Higher baseline risk (older population: average age 83)

### ACA Marketplace (Individual & Small Group)

**Model**: HHS-HCC (Not CMS-HCC)

**Key Differences**:
1. **Timing**: Concurrent year (current diagnoses for current costs) vs. prospective
2. **Population**: All ages (ages 0-18 and obstetric diagnoses included)
3. **Cost**: Includes both medical AND pharmaceutical spending
4. **Categories**: 127 HCCs in HHS model

**HHS-HCC Unique Features**:
- Pregnancy and neonatal diagnoses
- Pediatric-specific conditions
- Different age groupings (0-18, 19-64, 65+)

---

## Part 5: Normalization Factors

### Purpose
Adjust raw RAF scores to maintain population average of exactly 1.0 for Fee-for-Service (FFS) Medicare.

### Formula
```
Adjusted RAF = Raw RAF / Normalization Factor
```

### Recent Values

| Year | PY | Normalization Factor |
|------|----|--------------------|
| 2023 | 2024 | 1.030 |
| 2024 | 2025 | 1.045 |
| 2025 | 2026 | ~1.050 |

### Impact Example
```
Patient with raw RAF of 2.50:
- PY2024: 2.50 / 1.030 = 2.427
- PY2025: 2.50 / 1.045 = 2.392
- PY2026: 2.50 / 1.050 = 2.381

Difference: 0.046 in adjusted RAF from 2024 to 2026
Payment impact: ~$69-92 per member annually
```

### Why Normalization Changes
- Population health improvements/deterioration
- Coding intensity increases (more diagnoses documented)
- Diagnostic drift (disease patterns shift)
- Model updates (V24 to V28 transition)
- COVID-19 pandemic impacts (2020-2023)

---

## Part 6: New vs. Continuing Enrollee Models

### Continuing Enrollee
**Definition**: 12+ months of Part B claims data in data collection period

**RAF Components**:
- Demographic factors ✓
- HCC disease factors ✓
- Disease interactions ✓
- HCC count modifiers ✓

**Full Calculation**: All components included

### New Enrollee
**Definition**: Less than 12 months of Part B claims data

**RAF Components**:
- Demographic factors ✓
- HCC disease factors ✗ (ZERO)
- Disease interactions ✗ (ZERO)
- HCC count modifiers ✗ (ZERO)

**Limited Calculation**: Demographic factors only

### Example
```
Patient A: Enrolled Jan 1, 2025 (New in 2025)
- 12 months Part B data from 2024
- PY2025: CONTINUING ENROLLEE
- Receives HCC credit for all documented conditions
- RAF: ~1.200-1.500 possible

Patient B: Enrolled June 1, 2025 (New in 2025)
- Less than 12 months Part B data in prior year
- PY2025: NEW ENROLLEE
- NO HCC credit (demographics only)
- RAF: ~0.450-0.700
- Upgrades to continuing after 12 months

Financial Impact: Patient B underpaid by ~50-75% first year
```

---

## Part 7: Community vs. Institutional Models

### Community Setting (95% of MA Population)
- Standalone homes, apartments
- Independent senior housing
- Family care
- Assisted living (day services only)

**Demographic Multiplier**: 1.00× (baseline)

### Institutional Setting (5% of MA Population)
- Skilled Nursing Facilities (SNF)
- Nursing homes
- Long-term care facilities
- Intermediate care facilities

**Demographic Multiplier**: 1.20× to 1.40× higher

### Example Difference
```
78-year-old female, non-dual

Community RAF:
- Demographic: 0.650 × 1.00 = 0.650
- Other components: same
- Total: Let's say 1.250

Institutional RAF (same diagnoses):
- Demographic: 0.650 × 1.30 = 0.845
- Other components: same (or may differ for some HCCs)
- Total: Let's say 1.445

Difference: 0.195 (+15.6%)
Annual payment difference: ~$2,500-3,500 per member
```

---

## Part 8: HCC Coefficients - Key Examples

### Cancer HCCs (Highest Risk)
- HCC 8 (Metastatic cancer): 1.089
- HCC 9 (Lung/GI cancers): 0.940
- HCC 10 (Fibrosis/chronic lung): 0.587

### Cardiovascular HCCs
- HCC 85 (Chronic systolic heart failure): 0.360
- HCC 86 (Chronic diastolic heart failure): 0.360 (constrained same as systolic)
- HCC 88 (Atrial fibrillation): 0.299

### Endocrine HCCs (Constrained in V28)
- HCC 19 (Type 1 Diabetes): 0.166
- HCC 20 (Type 2 Diabetes uncomplicated): 0.166
- HCC 21 (Type 2 Diabetes with complications): 0.166 (constrained to same)

**Note**: V24 had HCC 21 at 0.312 (more severe); V28 constrains to 0.166 to prevent upcoding incentive

### Kidney Disease HCCs (Reorganized in V28)
- HCC 327 (CKD Stage 5): 0.530
- HCC 328 (CKD Stage 3B): 0.095 (split category in V28)
- HCC 329 (CKD Stage 3): 0.047 (more granular than V24)

### Neurological HCCs
- HCC 52 (Dementia excluding Alzheimer's): 0.308
- HCC 51 (Alzheimer's disease): 0.258
- HCC 53 (Parkinson's/Huntington's): 0.291

---

## Part 9: Disease Interactions Matrix

### Primary Interactions with Known Coefficients

| Interaction | HCC Pair | V28 Coefficient | Applied When |
|-------------|----------|-----------------|--------------|
| Diabetes + Heart Failure | 20-21 + 85-86 | +0.112 | Both conditions present |
| Heart Failure + CKD | 85-86 + 327-330 | +0.189 | Both conditions present |
| Diabetes + CKD | 20-21 + 327-330 | +0.095 | Both conditions present |
| CHF + Pulmonary Complications | 85-86 + 10-12 | +0.105 | Both conditions present |
| HIV/AIDS + Opportunistic Infection | 164 + 165-166 | +0.201 | Both conditions present |

### Removed in V28
- **Immune Disorders + Cancer**: Was +0.600-0.800 in V24, REMOVED in V28
  - Impact: Significant RAF reduction for dual immune + cancer patients

---

## Part 10: HCC Hierarchy Rules

### Hierarchy Logic
Some HCC diagnoses "suppress" lower-severity variants of same condition.

**Examples**:

1. **Cancer Hierarchy**:
   - Metastatic cancer (HCC 8) suppresses primary cancer (HCC 9)
   - Only HCC 8 (higher coefficient) counted

2. **Diabetes Hierarchy** (Constrained in V28):
   - Type 2 with complications (HCC 21) historically suppressed uncomplicated (HCC 20)
   - In V28: Both assigned same coefficient (0.166) to prevent upcoding

3. **Heart Failure Hierarchy** (Constrained in V28):
   - Systolic (HCC 85) and diastolic (HCC 86) constrained to same coefficient
   - Previously different severity levels; now treated equally

4. **CKD Hierarchy**:
   - Stage 5 (HCC 327: 0.530) is more severe than Stage 3B (HCC 328: 0.095)
   - If both documented, only HCC 327 counted

### Important: Hierarchy Doesn't Suppress Interactions
Even if hierarchy suppresses one condition, interaction terms still apply:

```
Patient has:
- Type 2 Diabetes uncomplicated (HCC 20): would be 0.166
- Type 2 Diabetes with complications (HCC 21): would be 0.166
- Heart Failure (HCC 85): 0.360
- CKD (HCC 328): 0.095

HCC List after hierarchy:
- HCC 20 or 21 (only one, same coefficient): 0.166
- HCC 85: 0.360
- HCC 328: 0.095

Interactions applied:
- Diabetes + CHF: +0.112 (applied)
- Diabetes + CKD: +0.095 (applied)
- CHF + CKD: +0.189 (applied)

Total: 0.166 + 0.360 + 0.095 + 0.112 + 0.095 + 0.189 = 1.017
```

---

## Part 11: Worked Calculation Example

### Patient Profile
- 72-year-old male
- Community-dwelling
- Non-Medicaid dual eligible
- Not disabled
- Continuing enrollee

### Documented Diagnoses (CY 2025)
1. E11.9 (Type 2 Diabetes) → HCC 20
2. I50.9 (Heart Failure) → HCC 85
3. N18.3 (CKD Stage 3B) → HCC 328
4. J44.9 (COPD) → HCC 111
5. I10 (Hypertension) → HCC 106

### Step-by-Step Calculation

**Step 1: Demographic Component**
```
Age 72, male, community, non-dual
Demographic coefficient (V28): 0.527
```

**Step 2: HCC Coefficients**
```
HCC 106 (Hypertension): 0.086
HCC 111 (COPD): 0.441
HCC 20 (Diabetes): 0.166
HCC 85 (CHF): 0.360
HCC 328 (CKD Stage 3B): 0.095
Sum: 1.148
```

**Step 3: Disease Interactions**
```
Diabetes (20) + CHF (85): +0.112
CHF (85) + CKD (328): +0.189
Diabetes (20) + CKD (328): +0.095
Sum: 0.396
```

**Step 4: HCC Count Modifier**
```
5 HCCs documented
Modifier: +0.050
```

**Step 5: Raw RAF**
```
0.527 + 1.148 + 0.396 + 0.050 = 2.121
```

**Step 6: Apply Normalization (PY2026: 1.050)**
```
Adjusted RAF: 2.121 / 1.050 = 2.020
```

**Step 7: Payment Calculation**
```
Benchmark rate (varies by geography): $12,500
Annual capitation: $12,500 × 2.020 = $25,250
Monthly capitation: $25,250 / 12 = $2,104
```

---

## Part 12: Data Quality and Validation

### Essential Data Elements

**Patient Demographics**:
- Date of birth (exact, not age alone)
- Sex/Gender
- Medicare eligibility status
- Medicaid status (dual eligible? Full or limited benefit?)
- Institutional status (community or facility type)
- Disability status

**Diagnoses**:
- Valid ICD-10-CM code (must exist in current year)
- Service date (within calendar year)
- Encounter type (office, inpatient, ED, telehealth)
- Source (claims, EHR, chart review)

**Enrollment**:
- Plan enrollment dates
- Benefit year
- Plan type (MA, PACE, ACA, ESRD)
- 12-month Part B history (for new vs. continuing determination)

### Validation Rules

**Red Flags for QA**:
- [ ] ICD-10 code doesn't map to any HCC
- [ ] Service date outside benefit year
- [ ] Same ICD-10 code documented multiple times (should deduplicate)
- [ ] New enrollee (< 12 months data) showing disease HCCs
- [ ] Very low RAF (< 0.5) for continuing enrollee (might indicate missing diagnoses)
- [ ] Very high RAF (> 3.0) without documented complex conditions
- [ ] Demographic adjustment missing
- [ ] Normalization factor not applied

---

## Part 13: Implementation Checklist

### Data Infrastructure
- [ ] Patient demographic database
- [ ] Diagnosis/encounter table with date tracking
- [ ] Enrollment status table (new vs. continuing)
- [ ] Institutional status tracking
- [ ] Part B claims history (12-month lookback)

### Reference Tables
- [ ] HCC coefficients (V28, V24, V22, ESRD variants)
- [ ] ICD-10 to HCC mapping table
- [ ] Disease interaction matrix
- [ ] HCC count modifier table
- [ ] Normalization factors (by year and program)
- [ ] Demographic coefficient matrices (age-sex-status)

### Calculation Engine
- [ ] Demographic coefficient lookup
- [ ] HCC mapping function
- [ ] Hierarchy rule engine
- [ ] Disease interaction calculator
- [ ] HCC count modifier application
- [ ] Normalization factor application
- [ ] Blend calculation (V24/V28 for transition years)

### Validation & QA
- [ ] ICD-10 validity check
- [ ] Date range validation
- [ ] Hierarchy conflict detection
- [ ] Duplicate diagnosis deduplication
- [ ] New vs. continuing enrollee verification
- [ ] Outlier detection (very high/low RAF)

### Reporting
- [ ] Individual patient RAF scores
- [ ] Population RAF distribution
- [ ] Diagnosis capture rate
- [ ] HCC prevalence by condition
- [ ] Coding accuracy audit trails
- [ ] OIG compliance reporting

---

## Part 14: Key Numbers and Benchmarks

### Model Sizes
- **V28**: 115 HCCs, 7,770 valid ICD-10 codes
- **V24**: 86 HCCs, 9,797 valid ICD-10 codes
- **V22**: 86 HCCs (PACE)
- **HHS-HCC**: 127 HCCs (ACA marketplace)
- **ESRD**: Subset with kidney disease HCCs zero-weighted

### Typical RAF Ranges

| Population | Min | Mode | Max |
|-----------|-----|------|-----|
| New enrollee (demo only) | 0.30 | 0.50 | 0.75 |
| Continuing enrollee | 0.60 | 1.10 | 2.50 |
| Community, healthy | 0.70 | 0.90 | 1.20 |
| Community, chronically ill | 1.20 | 1.80 | 3.50 |
| Institutional, average | 1.50 | 2.00 | 4.00 |
| ESRD dialysis patient | 1.30 | 1.70 | 3.00 |

### Financial Impact
- Average MA beneficiary RAF: ~1.2-1.4
- Payment per 0.01 RAF difference: $120-200 annually
- V28 transition impact: -3.12% average (billions in Medicare savings)
- New enrollee penalty vs. continuing: -50-75% payment first year

### Timeline Milestones
- **April 2024**: V28 live at 33% (with 67% V24)
- **April 2025**: V28 at 67% (with 33% V24)
- **April 2026**: V28 at 100%
- **October annually**: ICD-10 code set updates
- **Monthly**: Plans submit diagnosis data (RAPS)

---

## Part 15: Common Errors and How to Avoid Them

### Error 1: Counting Same HCC Multiple Times in One Year
❌ **Wrong**: 4 office visits for heart failure = 0.360 × 4 = 1.440  
✓ **Correct**: 1 HCC per category per year = 0.360

### Error 2: Forgetting Interaction Terms
❌ **Wrong**: Diabetes (0.166) + CHF (0.360) = 0.526  
✓ **Correct**: 0.166 + 0.360 + 0.112 = 0.638

### Error 3: Not Applying Hierarchy
❌ **Wrong**: Both HCC 20 and HCC 21 (diabetes variants) counted  
✓ **Correct**: Count only the more severe HCC

### Error 4: Using New Enrollee Model for Continuing Enrollee
❌ **Wrong**: Patient with 24 months data gets demographics only  
✓ **Correct**: Patient with 12+ months data gets full HCC calculation

### Error 5: Not Applying Normalization Factor
❌ **Wrong**: Raw RAF = 2.100 is final score  
✓ **Correct**: 2.100 / 1.050 = 2.000 (normalized)

### Error 6: Wrong Blend Percentages
❌ **Wrong**: PY2024 = 33% V24 + 67% V28 (reversed)  
✓ **Correct**: PY2024 = 67% V24 + 33% V28

### Error 7: Institutional Coefficient Adjustment Forgotten
❌ **Wrong**: SNF patient gets community demographic coefficient  
✓ **Correct**: SNF patient gets 1.20-1.40× multiplier on demographics

### Error 8: ESRD Zero-Weighting Missed
❌ **Wrong**: ESRD dialysis patient receives HCC 327 (CKD Stage 5) credit  
✓ **Correct**: HCC 327 = 0.0 for all ESRD patients (implicit in status)

### Error 9: Using Wrong Model Year
❌ **Wrong**: 2026 calculation uses 2024 coefficients  
✓ **Correct**: Each year uses current year's coefficients released in April

### Error 10: Demographic Adjustment Scope
❌ **Wrong**: Medicaid adjustment applied to all patients  
✓ **Correct**: Medicaid adjustment applied only to dual-eligible

---

## Part 16: Regulatory and Compliance Notes

### CMS Oversight
- Annual RAF audits on accuracy
- Upcoding detection (assigning more severe diagnosis than clinically supported)
- Unsupported diagnoses (no clinical evidence)
- Demographic misclassification
- Failure to re-document chronic conditions

### OIG Focus Areas
- Coding intensity trends (year-over-year increases)
- Provider upcoding patterns
- Institutional status misclassification
- Unsupported ESRD vs. non-ESRD classifications

### Data Submission Deadlines
- **RAPS (Risk Adjustment Processing System)**: Monthly and annual submissions
- **Data Lock**: Typically 30 days after end of calendar year
- **Payment Year**: RAF scores published April, effective for that calendar year

### Appeals and Corrections
- Plans can submit corrected diagnoses within specified windows
- Rebates issued if RAF scores found to be inflated
- Documentation standards enforced by OIG audits

---

## Part 17: Resource List for Implementation

### Official CMS Documents Needed
1. Current year HCC model (coefficients)
2. Current year ICD-10 to HCC mapping
3. Normalization factors (by program and year)
4. Age-sex demographic coefficient tables
5. Advance Notices (methodological updates)

### Systems to Build/Integrate
1. Patient master database
2. Diagnosis data warehouse
3. RAF calculation engine
4. Reporting dashboard
5. Compliance audit system
6. Payment integration APIs

### External Data Needed
1. Claims data (daily/weekly feed)
2. EHR/clinical data (real-time or batch)
3. Chart review inputs
4. Enrollment/demographic updates
5. Institutional status changes

---

## Conclusion

RAF calculation is complex but systematic. Success requires:

1. **Accurate Data**: Clean demographics, complete diagnoses, proper date tracking
2. **Correct Logic**: HCC hierarchy, interactions, normalization all properly implemented
3. **Annual Updates**: New coefficients, codes, normalization factors each year
4. **Validation**: QA processes to catch errors before payment
5. **Compliance**: Clear audit trails and OIG-friendly documentation

The three companion documents provide comprehensive coverage of all aspects needed to build a production RAF calculation system:

- **RAF_Calculation_Deep_Dive.md**: Methodology and formulas
- **RAF_Technical_Reference_Coefficients.md**: Coefficients and examples
- **SaaS_Implementation_Architecture.md**: System design and integration

---

**Document Version**: 1.0  
**Last Updated**: April 1, 2026  
**For**: raf-intelligence SaaS product development
