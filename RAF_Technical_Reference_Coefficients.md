# RAF Calculation - Technical Reference: Coefficients & Examples

**For**: SaaS Development, Actuarial Validation, Algorithm Implementation

---

## Section 1: Demographic Coefficient Tables

### Age-Sex Demographic Coefficients (V28 Continuing Enrollees - Community)

These are illustrative examples based on typical Medicare populations. Exact coefficients vary by payment year and are released by CMS annually.

#### Aged Beneficiaries (Age 65+)

| Age Group | Male | Female |
|-----------|------|--------|
| 65-69 | 0.408 | 0.289 |
| 70-74 | 0.527 | 0.523 |
| 75-79 | 0.688 | 0.650 |
| 80-84 | 0.815 | 0.774 |
| 85-89 | 0.957 | 0.923 |
| 90+ | 1.050 | 1.010 |

#### Disabled Beneficiaries (Under 65)

| Age Group | Male | Female |
|-----------|------|--------|
| Under 35 | 1.215 | 1.080 |
| 35-44 | 1.102 | 0.989 |
| 45-54 | 0.891 | 0.800 |
| 55-59 | 0.764 | 0.689 |
| 60-64 | 0.612 | 0.550 |

**Note**: Disabled beneficiaries are significantly higher risk than aged beneficiaries in the same age range, reflecting their enrollment in Medicare before age 65 due to medical conditions.

### Medicaid Dual Eligible Adjustments

Applied in addition to base demographic coefficient:

| Status | Adjustment Factor |
|--------|------------------|
| Non-Dual Eligible | 0.000 (no adjustment) |
| Dual Eligible | +0.062 to +0.095 |
| Full Benefit Dual | +0.095 |
| Limited Benefit Dual | +0.062 |

**Rationale**: Dual-eligible beneficiaries use more healthcare services and have higher costs due to lower income and more complex needs.

### Institutional vs Community Demographic Multipliers

Applied to base demographic coefficients when in institutional setting:

| Living Situation | Multiplier to Base |
|-----------------|------------------|
| Community | 1.00× |
| Skilled Nursing Facility | 1.18× to 1.35× |
| Long-term Care Facility | 1.20× to 1.40× |

**Example Calculation**:
```
Community male age 75-79: 0.688
Institutional male age 75-79: 0.688 × 1.25 = 0.860
Additional institutional premium: 0.172 (25% increase)
```

---

## Section 2: HCC Coefficient Examples

### High-Risk HCC Coefficients (V28)

| HCC Code | Condition | V28 Coefficient | V24 Coefficient | Change |
|----------|-----------|-----------------|-----------------|--------|
| 8 | Metastatic Cancer and Acute Leukemia | 1.089 | 1.073 | +1.5% |
| 9 | Lung, Upper Digestive Tract, and Other Severe Cancers | 0.940 | 0.901 | +4.3% |
| 10 | Fibrosis of Lung and Other Chronic Lung Disorders | 0.587 | 0.559 | +5.0% |
| 11 | Chronic Obstructive Pulmonary Disease | 0.441 | 0.416 | +6.0% |
| 12 | Respiratory Tract Infections | 0.330 | 0.307 | +7.5% |

### Cardiovascular HCC Coefficients (Constrained in V28)

| HCC Code | Condition | V28 Coefficient | V24 Coefficient | Note |
|----------|-----------|-----------------|-----------------|------|
| 85 | Chronic Systolic Heart Failure | 0.360 | 0.394 | -8.6% |
| 86 | Chronic Diastolic Heart Failure | 0.360 | 0.365 | Constrained to same as systolic |
| 87 | Transient Ischemic Attack (TIA) and Stroke | 0.250 | 0.231 | +8.2% |
| 88 | Atrial Fibrillation | 0.299 | 0.298 | +0.3% |
| 89 | Coronary Artery Disease | 0.191 | 0.178 | +7.3% |

**Key Point**: Constrained coefficients (85, 86) mean that mild, moderate, and severe heart failure are assigned the same risk weight, eliminating HCC hierarchy among CHF variants.

### Diabetes HCC Coefficients (Constrained in V28)

| HCC Code | Condition | V28 Coefficient | V24 Coefficient | Change |
|----------|-----------|-----------------|-----------------|--------|
| 19 | Type 1 Diabetes | 0.166 | 0.292 | -43.2% |
| 20 | Type 2 Diabetes Without Complications | 0.166 | 0.105 | +57.6% |
| 21 | Type 2 Diabetes With Acute Complications | 0.166 | 0.312 | -46.8% |

**Explanation**: All diabetes HCCs now weighted equally at 0.166, preventing "upcoding" incentive to claim complications. This addresses concern that V24 encouraged coders to document diabetes with complications even without clinical support.

### Kidney Disease HCC Coefficients (Reorganized in V28)

| HCC Code | Condition | V28 Coefficient | V24 Equivalent | Note |
|----------|-----------|-----------------|-----------------|------|
| 327 | Stage 5 Chronic Kidney Disease (CKD) | 0.530 | CKD Stage 5 (V24: 0.434) | +22.1% |
| 328 | Stage 3B CKD (eGFR 30-44) | 0.095 | CKD Stage 3-4 (V24: 0.076) | Split category |
| 329 | Stage 3 CKD except 3B (eGFR 45-59) | 0.047 | CKD Stage 3-4 (V24: 0.076) | More granular |
| 330 | Stage 1-2 CKD and Unspecified CKD | 0.016 | CKD Stage 1-2 (V24: 0.014) | +14.3% |

**Reorganization Rationale**: V28 splits CKD stages more granularly to better distinguish clinical severity and predict costs accurately.

### Neurological HCC Coefficients

| HCC Code | Condition | V28 Coefficient | V24 Coefficient |
|----------|-----------|-----------------|-----------------|
| 51 | Alzheimer's Disease | 0.258 | 0.238 |
| 52 | Dementia (excluding Alzheimer's) | 0.308 | 0.285 |
| 53 | Parkinson's and Huntington's Diseases | 0.291 | 0.272 |
| 54 | Seizure Disorders and Convulsions | 0.165 | 0.146 |

---

## Section 3: Disease Interaction Coefficients

### V28 Disease Interaction Terms

Disease interactions are **additive** and applied **independently of HCC hierarchy**.

#### Known Interactions with Estimated Coefficients

| Interaction | HCC1 | HCC2 | Interaction Coefficient | Clinical Rationale |
|-------------|------|------|------------------------|--------------------|
| Diabetes + Heart Failure | 20-21 | 85-86 | +0.112 | Increased complexity, medication interactions |
| Heart Failure + CKD | 85-86 | 327-330 | +0.189 | High mortality, medication restrictions |
| Chronic Lung Disease + Cor Pulmonale | 10-12 | 107 | +0.087 | Right heart failure risk |
| Diabetes + CKD | 20-21 | 327-330 | +0.095 | Vascular/renal complications |
| Cancer + Metastatic Disease | 8-12 | any severe | +0.145 | Multiple organ involvement |
| HIV/AIDS + Opportunistic Infection | 164 | 165-166 | +0.201 | Immune compromise |

#### REMOVED in V28

| Interaction | Coefficient (V24) | Reason |
|-------------|------------------|--------|
| Immune Disorders (HCC 47) + Cancer (HCC 8-12) | 0.600-0.800 | Removed due to statistical analysis |

**Impact**: Patients with immune disorders and cancer no longer receive 0.6-0.8 interaction bonus in V28, representing significant RAF reduction for this population.

### Important Rule: Interactions Apply Regardless of Hierarchy

**Scenario**: Patient has Type 2 Diabetes (HCC 20) and Metastatic Cancer (HCC 8)

```
HCC 20 (Diabetes, uncomplicated): 0.166
HCC 8 (Metastatic Cancer): 1.089
Interaction (Diabetes + Cancer): Could be +0.145 (if interaction exists)
Other HCCs: Various

Total RAF includes:
- Demographic base
- 0.166 (diabetes)
- 1.089 (cancer)
- +0.145 (interaction applied independently)
- Other HCCs
- Count modifier if 5+ HCCs
```

**Key**: Even if diabetes severity was "trumped" by cancer hierarchy, the interaction would still apply.

---

## Section 4: HCC Count Modifier Coefficients (V28)

### Payment HCC Count Modifiers

Applied when patient has 5 or more documented HCCs in a calendar year.

| Number of HCCs | Count Modifier Coefficient | Cumulative Bonus |
|--------|---------------------------|-------------------|
| 0-4 HCCs | 0.000 | 0.000 |
| 5 HCCs | +0.050 | 0.050 |
| 6 HCCs | +0.075 | 0.075 |
| 7 HCCs | +0.095 | 0.095 |
| 8 HCCs | +0.115 | 0.115 |
| 9 HCCs | +0.130 | 0.130 |
| 10 HCCs | +0.142 | 0.142 (cap) |
| 11+ HCCs | +0.142 | 0.142 (capped) |

**Interpretation**: 
- Patient with exactly 5 documented HCCs receives +0.050 to RAF
- Patient with exactly 6 gets +0.075
- Patient with 10+ HCCs gets +0.142 maximum (doesn't increase further)

**Rationale**: Recognizes increased complexity and coordination burden for poly-morbid patients. Incentivizes complete, accurate documentation of all patient conditions.

---

## Section 5: Normalization Factor Examples

### Year-by-Year Normalization Factors

| Calendar Year | Diagnosis Collection | Payment Year | Normalization Factor | Change from Prior |
|---------------|-------------------|--------------|-------------------|------------------|
| 2023 | CY 2023 | PY 2024 | 1.030 | - |
| 2024 | CY 2024 | PY 2025 | 1.045 | +1.5% |
| 2025 | CY 2025 | PY 2026 | ~1.050 | +0.5% |

### Normalization Impact Example

**Patient with raw RAF of 2.50**:

| Year | Raw RAF | Normalization Factor | Adjusted RAF | Payment Difference |
|------|---------|-------------------|--------------|-------------------|
| 2024 | 2.50 | 1.030 | 2.43 | - |
| 2025 | 2.50 | 1.045 | 2.39 | -0.04 (-1.6%) |
| 2026 | 2.50 | 1.050 | 2.38 | -0.01 (-0.4%) |

**Takeaway**: Even with identical patient health, adjusted RAF decreases due to normalization factor increases. Plans must capture additional diagnoses to maintain payment.

---

## Section 6: Blend Calculation Examples

### V24/V28 Blend Calculation (2024-2025)

#### Payment Year 2024 Calculation (67% V24 + 33% V28)

**Scenario**: 78-year-old female, community, non-dual with diagnoses:
- E11.9 (Type 2 Diabetes)
- I50.9 (Heart Failure)
- N18.3 (CKD Stage 3B)

**Step 1: Calculate V24 RAF**

```
Demographic (V24): 0.650 (78F community)
HCC 20 (Diabetes V24): 0.105
HCC 85 (CHF V24): 0.394
HCC 328 equivalent (V24): 0.076
Interaction (Diabetes + CHF V24): 0.098
Subtotal: 1.323

Applied to normalized 2023 population
Adjusted V24 = 1.323 / 1.030 = 1.284
```

**Step 2: Calculate V28 RAF**

```
Demographic (V28): 0.650 (78F community)
HCC 20 (Diabetes V28): 0.166
HCC 85 (CHF V28): 0.360
HCC 328 (CKD V28): 0.095
Interaction (Diabetes + CHF V28): 0.112
Subtotal: 1.383

Applied to normalized 2024 population
Adjusted V28 = 1.383 / 1.030 = 1.343
```

**Step 3: Apply Blend**

```
PY2024 Final RAF = (67% × 1.284) + (33% × 1.343)
                 = 0.861 + 0.443
                 = 1.304
```

#### Payment Year 2025 Calculation (33% V24 + 67% V28)

Using same patient with same conditions:

```
Adjusted V24: 1.284 (from prior)
Adjusted V28: 1.343 (from prior)

PY2025 Final RAF = (33% × 1.284) + (67% × 1.343)
                 = 0.424 + 0.900
                 = 1.324
```

**Comparison**: 
- PY2024: 1.304
- PY2025: 1.324
- Change: +1.5% (V28 is higher in this example)

**Note**: V28 impact varies by patient. Some populations saw decreases, others increases depending on condition mix.

---

## Section 7: Program-Specific RAF Calculation Examples

### Medicare Advantage (Standard MA) Example

**Patient Profile**:
- Age: 72, Male
- Status: Continuing Enrollee, Community, Non-Dual
- Diagnoses submitted for CY 2025:
  - I10 (Essential Hypertension) → HCC 106
  - E11.65 (Type 2 DM with hyperglycemia) → HCC 20
  - I50.9 (Heart Failure) → HCC 85
  - N18.3 (CKD Stage 3B) → HCC 328
  - J44.9 (COPD) → HCC 111

**Calculation**:

```
Step 1: Demographic
  V28 Age-Sex (72M): 0.527

Step 2: HCC Values (V28)
  HCC 106 (Hypertension): 0.086
  HCC 20 (Diabetes): 0.166
  HCC 85 (CHF): 0.360
  HCC 328 (CKD): 0.095
  HCC 111 (COPD): 0.441
  Sum: 1.148

Step 3: Disease Interactions (V28)
  Diabetes + CHF (HCC 20 + 85): +0.112
  CHF + CKD (HCC 85 + 328): +0.189
  Sum Interactions: +0.301

Step 4: HCC Count Modifier
  5 HCCs documented: +0.050

Step 5: Raw RAF
  0.527 + 1.148 + 0.301 + 0.050 = 2.026

Step 6: Apply Normalization (PY2026 factor: ~1.050)
  Adjusted RAF = 2.026 / 1.050 = 1.929

Step 7: Payment Calculation
  Benchmark Rate (varies by geography) × 1.929
  Example: $12,500 × 1.929 = $24,112.50 annual capitation
```

### ESRD Example (Dialysis Patient)

**Patient Profile**:
- Age: 65, Female
- Status: ESRD on Dialysis (Continuing Enrollee)
- Diagnoses:
  - E11.9 (Type 2 DM) → HCC 20
  - I50.9 (Heart Failure) → HCC 85
  - N18.5 (CKD Stage 5) → Would be HCC 327, but ZERO-WEIGHTED in ESRD model
  - I10 (Hypertension) → HCC 106
  - Anemia of CKD (managed) → HCC not specifically coded

**ESRD Model Calculation**:

```
Step 1: Demographic (ESRD-specific)
  Age 65F ESRD: 0.750 (higher than community MA)

Step 2: HCC Values (ESRD Model - non-kidney HCCs only)
  HCC 20 (Diabetes): 0.166 (same as community)
  HCC 85 (CHF): 0.360 (same as community)
  HCC 106 (Hypertension): 0.086 (same)
  HCC 327 (CKD Stage 5): 0.000 (ZERO-WEIGHTED - all dialysis patients)
  Sum: 0.612

Step 3: Disease Interactions
  Diabetes + CHF: +0.112
  (Not CHF + CKD since CKD is zero-weighted)
  Sum: +0.112

Step 4: HCC Count Modifier
  3 HCCs (excluding zero-weighted): 0.000 (less than 5)

Step 5: Raw RAF
  0.750 + 0.612 + 0.112 = 1.474

Step 6: Apply ESRD Normalization
  ESRD normalization factor (2026): ~1.025
  Adjusted RAF = 1.474 / 1.025 = 1.437

Step 7: ESRD MA Capitation
  ESRD benchmark (different from standard MA) × 1.437
  Example: $18,000 × 1.437 = $25,866 annual payment
```

### PACE Program Example

**Important**: PACE uses V22 model (2017) until 2026, then blended transition

**Patient Profile**:
- Age: 84, Female
- Status: PACE Enrollee, Continuing Enrollee
- Program Status: Non-ESRD
- Diagnoses:
  - E11.9 (Type 2 DM) → HCC 20
  - I50.9 (CHF) → HCC 85
  - I10 (Hypertension) → HCC 106

**PACE Calculation (2025 using V22)**:

```
Step 1: Demographic (V22 PACE)
  Age 84F PACE: 0.950 (higher than community MA due to age)

Step 2: HCC Values (V22 Model)
  HCC 20 (Diabetes V22): 0.105
  HCC 85 (CHF V22): 0.394
  HCC 106 (Hypertension V22): 0.093
  Sum: 0.592

Step 3: Interactions (V22)
  Diabetes + CHF (V22): 0.098

Step 4: No Count Modifier in V22/PACE

Step 5: Raw RAF
  0.950 + 0.592 + 0.098 = 1.640

Step 6: PACE Normalization (historical)
  PACE normalization factor (2025): ~1.020
  Adjusted RAF = 1.640 / 1.020 = 1.608

Step 7: PACE Capitation
  PACE per-member-per-year rate × 1.608
  Example: $15,000 × 1.608 = $24,120
```

**Note**: In 2026, PACE will transition to 10% V28 + 90% V22 blend.

### New Enrollee Example

**Patient Profile**:
- Age: 68, Male
- Status: NEW to Medicare, NEW to MA Plan (joined March 2025)
- Diagnoses documented March-December 2025:
  - E11.9 (Type 2 DM)
  - I50.9 (CHF)
  - N18.3 (CKD)

**New Enrollee Calculation (for PY2026 payment)**:

```
Step 1: Demographic (New Enrollee - Age 68M)
  New Enrollee (68M): 0.475

Step 2: HCC Values
  **ZERO** - New enrollees do not receive disease (HCC) values
  (Insufficient 12 months of diagnostic data)

Step 3: Disease Interactions
  **ZERO** - No interactions applied

Step 4: HCC Count Modifier
  **ZERO** - No count modifier

Step 5: Raw RAF
  0.475 (demographic only)

Step 6: Normalization
  0.475 / 1.050 = 0.452

Step 7: Payment
  Benchmark × 0.452
  Example: $12,500 × 0.452 = $5,650 annual capitation

Comparison to if continuing:
  If had 12 months data: would likely be 1.200-1.500
  Actual: 0.452
  Difference: Significant underpayment until reaching continuing status
```

---

## Section 8: Validation Checklist for SaaS Implementation

### Data Validation Rules

- [ ] ICD-10-CM code is valid (exists in current year's CMS file)
- [ ] ICD-10-CM code maps to valid HCC
- [ ] Service date is in collection year
- [ ] Patient age is calculated correctly
- [ ] Gender field is populated (M/F)
- [ ] Medicare status is one of: Aged, Disabled, ESRD, End-Stage Renal Disease
- [ ] Institutional status is clearly documented or defaulted to Community
- [ ] Medicaid status is accurately reflected
- [ ] Enrollment dates are valid and within calculation period
- [ ] Only one diagnosis per HCC category counted per calendar year (hierarchy applied)

### Calculation Validation Rules

- [ ] Demographic component is positive (0.4 to 1.5 typical)
- [ ] Total HCC value sum is reasonable (typically 0.5 to 3.0)
- [ ] Interaction terms do not exceed component values
- [ ] Count modifier applied only when HCC count >= 5
- [ ] Normalization factor applied correctly (divide, not multiply)
- [ ] Blend calculation uses correct percentages for payment year
- [ ] Final RAF is positive and within expected range (0.3 to 4.0)
- [ ] Final RAF is reproducible (round-trip validation)

### Program-Specific Validation

**Medicare Advantage**:
- [ ] Using V28 coefficients (PY2026+) or blend if transition year
- [ ] ESRD patients using ESRD model, not standard MA
- [ ] Institutional patients using institutional coefficients
- [ ] New enrollees have zero HCC values

**PACE**:
- [ ] Using V22 model until 2026
- [ ] Blend applied correctly in 2026-2028
- [ ] Encounter-based data handling (if applicable)

**ACA Marketplace**:
- [ ] Using HHS-HCC model (not CMS-HCC)
- [ ] 127 HCC categories (not 115)
- [ ] Concurrent year calculation
- [ ] Age 0-18 and obstetric diagnoses included if applicable

**ESRD**:
- [ ] Using ESRD-specific model
- [ ] Kidney disease HCCs zero-weighted (except HCC 174)
- [ ] HCC 174 (Transplant status) estimated
- [ ] Separate dialysis/transplant/functioning graft segments if applicable

---

## Section 9: Common RAF Calculation Errors

### Error 1: Counting Same HCC Multiple Times in One Year
**Wrong**: Patient seen 3 times for CHF (HCC 85), each visit generates 0.360 point = 1.080 total
**Correct**: CHF counted once per calendar year = 0.360 total

### Error 2: Not Applying Hierarchy Rules
**Wrong**: Coding both "Metastatic cancer" (HCC 8: 1.089) AND "Primary lung cancer" (HCC 9: 0.940)
**Correct**: Only code highest-severity cancer = 1.089

### Error 3: Forgetting Interaction Terms
**Wrong**: Diabetes (0.166) + CHF (0.360) = 0.526
**Correct**: Diabetes (0.166) + CHF (0.360) + Interaction (0.112) = 0.638

### Error 4: Applying Count Modifier with Less Than 5 HCCs
**Wrong**: 4 HCCs documented, apply count modifier +0.050
**Correct**: No count modifier until 5+ HCCs

### Error 5: Using Wrong Normalization Factor
**Wrong**: Using previous year's normalization factor (1.030) for current calculation
**Correct**: Using current payment year's normalization factor (1.045 or later)

### Error 6: Not Distinguishing New vs. Continuing Enrollees
**Wrong**: New enrollee (less than 12 mo data) receives HCC values
**Correct**: New enrollee receives demographic only; no HCC values until 12 months data

### Error 7: Institutional vs. Community Confusion
**Wrong**: Using community coefficients for SNF patient
**Correct**: Using institutional coefficients (20-40% higher)

### Error 8: ESRD Zero-Weighting HCCs
**Wrong**: ESRD dialysis patient gets HCC credit for HCC 327 (CKD Stage 5)
**Correct**: HCC 327 is zero-weighted for all ESRD patients

### Error 9: Missing Normalization Step
**Wrong**: Raw RAF = 2.100 is final score
**Correct**: Raw RAF / Normalization Factor = 2.100 / 1.045 = 2.009

### Error 10: Blend Calculation Direction Wrong
**Wrong**: PY2024 = 33% V24 + 67% V28 (reversed)
**Correct**: PY2024 = 67% V24 + 33% V28

---

**Document Version**: 1.0  
**Last Updated**: April 2026  
**For SaaS Implementation**: Use sections 1-4 for coefficient tables, Section 6 for blending logic, Section 7 for end-to-end examples, Section 9 for validation
