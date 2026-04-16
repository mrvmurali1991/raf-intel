# Risk Adjustment Models: Quick Reference & Comparison Matrix

## 1. Model Selection Decision Tree

```
START: Determine Program/Population
│
├─→ Is this Medicare Advantage, PACE, or ESRD?
│   ├─→ YES: Use CMS-HCC
│   │   ├─→ Payment Year 2024-2025? Use V24/V28 blend
│   │   ├─→ Payment Year 2026+? Use V28
│   │   ├─→ PACE? Add organizational frailty score
│   │   ├─→ FIDE SNP? Add frailty adjustment to standard MA
│   │   └─→ ESRD? Apply ESRD logic (omit kidney disease HCCs)
│   │
│   └─→ NO
│       │
│       ├─→ Is this ACA Marketplace (individual/small group)?
│       │   └─→ YES: Use HHS-HCC V127
│       │
│       └─→ Is this Medicaid Managed Care?
│           └─→ YES: Use CDPS (87% of states)
│               ├─→ Check state for CDPS+Rx variant
│               └─→ Some states use ACG, DxCG, or CRxG instead
│
└─→ Is this Commercial (employer, self-funded)?
    ├─→ For multimorbidity focus: Use Johns Hopkins ACG
    ├─→ For cost prediction: Use Optum DxCG
    ├─→ For avoidable cost targeting: Use Optum Impact Pro
    └─→ For proprietary solution: Use vendor-specific model
```

---

## 2. Model Comparison Matrix

### 2.1 Core Characteristics

| Attribute | HHS-HCC | CMS-HCC V28 | CMS-HCC V24 | CDPS | ACG | DxCG | Impact Pro |
|-----------|---------|-----------|-----------|------|-----|------|-----------|
| **Program** | ACA Marketplace | MA/PACE/ESRD | Legacy MA (transitioning) | Medicaid MCO | Commercial | Commercial | Commercial |
| **Population Design** | Commercial (non-elderly) | Medicare (elderly/disabled) | Medicare (elderly/disabled) | Medicaid beneficiaries | General | General | High-cost subset |
| **HCC Categories** | 127 | 115 | 86 | 52 | 102 ACGs | 80+ groups | Episode-based (ETG) |
| **Total ICD-10 Codes** | 9,797+ | 7,770 | 9,797 | Variable | Multiple mappings | Multiple mappings | Variable |
| **Concurrent/Prospective** | Concurrent | Prospective | Prospective | Current-year spending | Both | Both | Prospective |
| **Includes Pharmacy** | YES (in costs) | NO (traditional) | NO | CDPS+Rx (optional) | Optional | YES | Optional |
| **Pregnancy Codes** | 656 codes mapped | Minimal | Minimal | Standard handling | Standard | Standard | Standard |
| **Hierarchies** | YES | YES (with constraining V28) | YES | Fewer (gaming-resistant) | YES | YES | Episode-based |
| **Constraining** | NO | YES (V28 only) | NO | Limited | NO | NO | NO |
| **Special ESRD Logic** | NA | YES (omit kidney HCCs) | YES | NA | NA | NA | NA |
| **Frailty Adjustment** | NA | YES (PACE/D-SNP) | YES (PACE) | NA | NA | NA | NA |
| **Regulatory** | CMS Federal | CMS Federal | CMS Federal | State Medicaid | Private/Proprietary | Private/Proprietary | Private/Proprietary |

### 2.2 Payment & Transfer Mechanics

| Aspect | HHS-HCC | CMS-HCC | CDPS | Commercial |
|--------|---------|---------|------|-----------|
| **Payment Model** | Risk transfer formula (budget-neutral redistribution) | Capitation rate adjustment | State capitation rates | Capitation or shared savings |
| **Transfer Mechanism** | From low-risk to high-risk plans within state | Base rate × Risk score | State defines rate cells | Plan-specific agreements |
| **Budget Neutral** | YES (sum of transfers = 0 per state) | YES (per plan enrollment) | YES (per state) | Variable |
| **Distribution Frequency** | Annual (August) | Monthly or quarterly | Annual or quarterly | Monthly |
| **Risk Adjustment %** | 10% individual, 6% small group | Integrated into base rate | 20-100% of capitation | Varies |
| **Statewide Aggregation** | Rating area level | Plan level | State level | Plan/group level |
| **Rate Cell Variation** | Age, tobacco, family composition | Age, sex, region, dual status | Age, eligibility category, region | Varies |

### 2.3 Data Requirements

| Model | Diagnosis Codes | Pharmacy Data | Demographics | Special Data |
|-------|-----------------|---------------|--------------|----|
| **HHS-HCC** | Required (medical claims) | Required (included in scoring) | Age, sex, region, tobacco | Rating area, plan design (AV) |
| **CMS-HCC** | Required (encounters or claims) | Optional | Age, sex, dual status, institutional | ESRD modality (if applicable), HOS-M (PACE frailty) |
| **CDPS** | Required (encounters) | Optional (CDPS+Rx variant) | Age, eligibility category, region | State-specific variables |
| **ACG** | Required | Optional | Age, sex | None typically |
| **DxCG** | Required | Strongly recommended | Age, sex, region | Prior utilization |
| **Impact Pro** | Required | Recommended | Age, sex | Prior ED/hospitalization |

### 2.4 Coding Validation & Compliance

| Model | Accepted Codes | Validation Rule | MEAT Criteria | Audit Exposure |
|-------|---|---|---|---|
| **HHS-HCC** | ICD-10-CM only | EDGE/MAO-004 reconciliation required | Standard (M,E,A,T) | High (CMS RADV possible) |
| **CMS-HCC** | ICD-10-CM only | EDGE/MAO-004 required | Standard (M,E,A,T) | High (CMS RADV audits MA plans) |
| **CDPS** | ICD-10-CM primarily | State-specific validation | State-defined | Moderate (state audits) |
| **Commercial** | ICD-10-CM primarily | Payer-specific rules | Payer-specific | Lower (market-based) |

---

## 3. Feature Comparison: Detailed

### 3.1 HHS-HCC Specifics (ACA Marketplace)

**Unique Characteristics**:
- **Pregnancy Emphasis**: 656 codes specifically mapped to HCC categories
- **Drug Cost Inclusion**: Pharmacy spending directly included in model
- **Concurrent Scoring**: Uses current-year diagnoses to predict current-year costs
- **Transfer Formula**: Budget-neutral redistribution from low-risk to high-risk plans
  - Formula: (Plan Required Revenue / Statewide Avg Required Revenue) - (Plan Allowable Premium / Statewide Avg Allowable Premium) × Enrollment-Weighted Market Average Premium
- **10-15% Premium Transfer**: Significant redistribution in marketplace
- **No Constraining**: Unlike CMS-HCC V28, allows multiple related HCCs

**Key Implementation Points**:
- EDGE server submission required (Oct-April annually)
- MAO-004 monthly acceptance report reconciliation
- State-level aggregation (may differ from CMS regions)
- Rating area variations in rate cells
- Plan attestation requirements (senior officer)

**SaaS Support Required**:
- Transfer formula calculator (statewide aggregation)
- EDGE submission validation
- Rating area rate cell management
- Actuarial value calculations
- Pregnancy code handling (656 codes)

---

### 3.2 CMS-HCC Specifics (Medicare)

**V28 Transition (2024-2029)**:

```
Year    V28 Percent    V24 Percent    Data Source
2024    33%            67%            ICD-10 Claims
2025    67%            33%            ICD-10 Claims
2026    100%           0%             Encounter + Claims
2027    100%           0%             Encounter data
2028    100%           0%             Encounter data
2029    100%           0%             Encounter data (final)
```

**V28 Constraining Rules** (Critical Implementation):
- Diabetes + complications: Only highest coefficient applied
- Psychiatric conditions: Parent HCC preferred over child in conflict
- Cardiovascular: Related HCCs constrained to prevent double-counting

**ESRD Special Handling**:
- HCCs 136, 137, 138 excluded (dialysis, renal failure, nephritis)
- Rationale: ALL ESRD patients already in most severe category
- Treatment modality determines differentiation (dialysis type, transplant)
- Separate payment calculation from non-ESRD

**PACE Frailty Calculation**:
```
Risk Score = Base Rate × [CMS-HCC Risk Score + Organizational Frailty Score]

Organizational Frailty Score = Average of ADL limitations across enrollees
- Walking
- Dressing
- Bathing
- Toilet use
- Getting in/out of bed
- Eating
```

**FIDE SNP Frailty** (Dual-Eligible Fully Integrated):
```
Frailty Score (CY 2025) = 33% × V24 Frailty Factor + 67% × V28 Frailty Factor

Only applied if plan frailty ≥ PACE minimum threshold (0.129 in 2023)
```

**SaaS Support Required**:
- V24/V28 blending logic by payment year
- Constraining rules engine (V28)
- ESRD determination and modifier logic
- HOS-M survey data integration (PACE, D-SNP)
- Frailty score calculation
- Separate calculations for institutional vs. community

---

### 3.3 CDPS Specifics (Medicaid)

**State Usage** (87% of 38 risk-adjusting states):
- Florida, Illinois, Kansas, Kentucky, Louisiana, Michigan, New Jersey, Washington (update data states)
- 33 total states use CDPS as primary

**Core Philosophy**:
- Fewer categories (52 vs. 115) to resist gaming/overcoding
- Linear regression model: Diagnoses predict spending
- Medicaid-specific conditions emphasized
- Social determinants NOT directly modeled (limitation)

**19 Major Categories**:
1. Addiction & substance abuse
2. AIDS/HIV
3. Cancer
4. Cardiovascular
5. Dermatologic
6. Endocrine/metabolic
7. Gastrointestinal
8. Genitourinary
9. Hematologic
10. Infectious disease (non-HIV)
11. Injuries & poisonings
12. Mental health/psychiatric
13. Musculoskeletal
14. Neurologic
15. Pregnancy/neonatal
16. Pulmonary/respiratory
17. Renal/kidney
18. Sensory (vision/hearing)
19. Other chronic conditions

**Recent Updates (2022)**:
Six categories substantially revised:
- Psychiatric: Better differentiation of severity
- Pulmonary: Updated for modern asthma/COPD treatment
- Renal: Distinction between CKD stages
- Cancer: Type-specific categorization
- Infectious disease: Separation of common vs. serious conditions
- Hematological: Better differentiation

**CDPS+Rx Variant**:
- Includes pharmacy claims in risk adjustment
- Therapeutic class mapping
- Better captures drug cost variation
- Current version: 7.0+ (released 2024)

**SaaS Support Required**:
- CDPS category assignment from ICD-10
- Pharmacy therapeutic class mapping (CDPS+Rx)
- State-specific rate cell definitions (varies by state)
- Linear regression coefficient management
- Encounter data validation (state-specific)
- Multi-state support (different CDPS versions possible)

---

### 3.4 Commercial Models

**Johns Hopkins ACG System**:
- **102 ACGs**: Actuarial grouping cells
- **Multimorbidity Focus**: Designed to handle complex patients
- **Use Cases**: 
  - Capitation rate-setting (commercial, government programs)
  - Quality benchmarking
  - Care management targeting
  - Patient stratification
- **Strength**: Best for understanding interaction of multiple conditions
- **Implementation**: ADG assignment → ACG grouping

**Optum DxCG**:
- **80+ Diagnostic Cost Groups**: Episode-based approach
- **Pharmacy Integration**: Explicitly includes pharmacy data
- **Recalibration**: Every 2-3 years
- **Strength**: Excellent cost prediction accuracy
- **History**: Foundation for CMS-HCC model
- **Use**: Commercial plans, self-funded employers

**Optum Impact Pro**:
- **Episode-Based (ETG™)**: Focuses on episodes of care
- **Avoidable Cost Focus**: Targets preventable/reducible spending
- **Use Case**: Case management targeting, high-risk identification
- **Strength**: Identifies patients benefiting from intervention
- **Time Models**: Prospective, retrospective, actuarial options

---

## 4. Implementation Checklist by Program

### 4.1 ACA Marketplace (HHS-HCC)

**Pre-Launch**:
- [ ] Implement HHS-HCC V127 calculator (9,797 ICD-10 codes)
- [ ] Build transfer formula engine (statewide calculations)
- [ ] Set up EDGE server submission interfaces
- [ ] Create MAO-004 reconciliation logic
- [ ] Develop rating area management
- [ ] Build plan attestation workflows

**Operational**:
- [ ] Daily diagnosis code validation
- [ ] Monthly MAO-004 reconciliation reports
- [ ] Transfer formula calculations (state-level)
- [ ] EDGE submission preparation (monthly)
- [ ] Coding pattern monitoring
- [ ] Pregnancy code tracking

**Audit Readiness**:
- [ ] Maintain diagnosis-to-source documentation links
- [ ] MEAT criteria validation
- [ ] CMS audit package generation (if requested)
- [ ] Premium/rate cell documentation

---

### 4.2 Medicare Advantage (CMS-HCC)

**Pre-Launch**:
- [ ] Implement CMS-HCC V24 calculator (legacy)
- [ ] Implement CMS-HCC V28 calculator (new)
- [ ] Build V24/V28 blending logic (payment year-based)
- [ ] Implement constraining rules (V28)
- [ ] Set up RADV audit evidence gathering
- [ ] Configure encounter data processing

**Operational**:
- [ ] Daily HCC assignment validation
- [ ] Monthly risk score reconciliation
- [ ] MAO-004 acceptance tracking
- [ ] Coding pattern analysis
- [ ] Frailty adjustment monitoring (if applicable)
- [ ] ESRD patient identification (if applicable)

**Audit Readiness**:
- [ ] RADV audit package generation
- [ ] Source documentation linkage (every HCC to clinical evidence)
- [ ] MEAT criteria validation for each diagnosis
- [ ] Provider audit trails
- [ ] CMS reconciliation reports

---

### 4.3 PACE (CMS-HCC + Frailty)

**Pre-Launch**:
- [ ] CMS-HCC calculator (V22/V28 blended)
- [ ] Frailty score calculator (HOS-M integration)
- [ ] V22→V28 transition schedule (2024-2029)
- [ ] ESRD special logic (if applicable)
- [ ] Institutional vs. community classification
- [ ] HOS-M survey data integration

**Operational**:
- [ ] Annual HOS-M survey processing
- [ ] Organizational frailty score calculation
- [ ] Participant-level HCC assignment
- [ ] Blended risk score application
- [ ] PACE minimum threshold comparison
- [ ] Separate ESRD calculations

**Transition (2024-2029)**:
- [ ] 2024: 33% V28 / 67% V22
- [ ] 2025: 67% V28 / 33% V22
- [ ] 2026: 100% V28
- [ ] 2029: Encounter data implementation

---

### 4.4 Medicaid MCO (CDPS)

**Pre-Launch**:
- [ ] Identify state's risk adjustment model (CDPS likely)
- [ ] Implement CDPS category assignment
- [ ] Check for CDPS+Rx variant
- [ ] Define state rate cells (varies by state)
- [ ] Set up encounter data validation
- [ ] Configure capitation calculations

**Operational**:
- [ ] Monthly encounter data processing
- [ ] CDPS category assignment
- [ ] Linear regression scoring
- [ ] State rate cell aggregation
- [ ] Capitation payment calculations
- [ ] State reporting requirements

**State-Specific**:
- [ ] Arizona: Competitive bidding integration
- [ ] California: Pharmacy data emphasis, 20% risk adjustment
- [ ] New York: Three rate cell structure
- [ ] Others: Varying sophistication

---

### 4.5 D-SNP (Dual-Eligible)

**Pre-Launch**:
- [ ] CMS-HCC calculator (MA-based)
- [ ] State Medicaid model integration (CDPS or other)
- [ ] Frailty adjustment (if FIDE SNP)
- [ ] Model of Care (MOC) documentation
- [ ] Dual-eligible status determination

**Operational**:
- [ ] Medicare risk adjustment (CMS-HCC)
- [ ] State Medicaid risk adjustment (CDPS or state model)
- [ ] Frailty calculation (FIDE SNP only)
- [ ] Dual capitation aggregation
- [ ] NCQA MOC compliance

---

### 4.6 Commercial Plans

**Pre-Launch**:
- [ ] Select model (ACG, DxCG, Impact Pro, or proprietary)
- [ ] Negotiate licensing/implementation
- [ ] Build data connectors
- [ ] Define metrics and benchmarks
- [ ] Plan stakeholder training

**Operational**:
- [ ] Risk score calculation
- [ ] Member stratification
- [ ] Care management targeting
- [ ] Benchmark reporting
- [ ] Model recalibration (per vendor schedule)

---

## 5. Key Regulatory Requirements by Model

### 5.1 HHS-HCC (ACA)

**Submission Requirements**:
- EDGE server data: Oct 1 - April 30 annually
- Diagnosis codes: ICD-10-CM only
- Medical + pharmacy claims required
- Plan design/benefit information
- Rate and enrollment data

**Validation**:
- MAO-004 acceptance report monthly
- CMS reconciliation points
- Senior officer attestation required
- Data quality standards (completeness, accuracy)

**Compliance**:
- No explicit RADV program (risk pool mechanism instead)
- Premium transparency requirements
- Rate justification documentation
- Actuarial certification

---

### 5.2 CMS-HCC (MA/PACE/ESRD)

**Submission Requirements**:
- Encounter or claim data (transition from claims → encounter)
- ICD-10-CM diagnosis codes
- Demographics and eligibility
- HOS-M survey data (PACE, D-SNP frailty)
- Treatment modality (ESRD)

**Validation**:
- MAO-004 monthly acceptance
- EDGE data processing
- CMS reconciliation
- Audit preparation obligations

**Audit Exposure** (Critical):
- **RADV Audits**: CMS randomly audits MA plans
- **Sample-based**: Typically 200 members per plan
- **Chart Review**: CMS validates every diagnosis code
- **Recoupment Risk**: If HCCs unsupported, plan must refund (can be significant)
- **Documentation Required**: Every HCC linked to clinical evidence (ICD-10 code must appear in medical record with MEAT criteria support)

---

### 5.3 CDPS (Medicaid)

**Submission Requirements**:
- State-specific (varies)
- Encounter data (increasingly mandated)
- ICD-10-CM codes
- State demographics/eligibility
- Pharmacy data (if using CDPS+Rx)

**Validation**:
- State-specific validation rules
- Encounter data completeness
- Rate cell compliance
- Capitation reconciliation

**Compliance**:
- State audit exposure
- Managed care rate setting rules
- HIPAA requirements

---

## 6. Common Implementation Pitfalls

| Pitfall | Impact | Prevention |
|---------|--------|-----------|
| **ICD-10 code validity** | Invalid codes rejected by CMS; lost revenue | Maintain current CMS ICD-10-CM master list; validate all codes before submission |
| **Missing hierarchies** | Overcounting risk; audit findings | Enforce hierarchies in calculation engine; audit trail every decision |
| **MEAT criteria failure** | CMS rejects HCC in RADV audit | Document M, E, A, T in clinical record; automated validation before coding |
| **Pharmacy data inconsistency** | Duplicate or missed costs | Single source of truth for pharmacy claims; deduplication process |
| **Wrong model for population** | Fundamental methodological error | Decision tree at enrollment; periodic compliance audits |
| **Version mismatch** | Payment calculation errors | Version control for all models; change management process |
| **Transfer formula miscalculation** | Incorrect transfers; financial loss | Statewide validation; secondary calculation review |
| **Frailty score errors** | PACE/D-SNP payment impact | HOS-M survey validation; aggregation logic testing |
| **ESRD determination failure** | Wrong HCC exclusions | Automated ESRD status determination; validation against claims |
| **MAO-004 discrepancies not resolved** | Compounding audit risk | Monthly reconciliation; investigation protocols |

---

## 7. Performance Benchmarks (SaaS)

### 7.1 Calculation Speed

| Metric | Target | Best Practice |
|--------|--------|--------------|
| Score calculation per member (single model) | <500ms | <200ms for batch, <1s for real-time API |
| Batch processing (1M members, 6 models) | <4 hours | <2 hours on Spark cluster |
| EDGE submission validation | <30 minutes | <10 minutes for 100K members |
| Transfer formula calculation (state-level) | <5 minutes | <2 minutes |
| RADV package generation (200 samples) | <30 minutes | <10 minutes |

### 7.2 Data Quality

| Metric | Target | Best Practice |
|--------|--------|--------------|
| ICD-10 code validity rate | >99.5% | >99.9% (invalid codes auto-rejected) |
| HCC assignment accuracy | >98% | >99.5% (validated against CMS samples) |
| Hierarchy application accuracy | 100% | 100% (deterministic rules) |
| MEAT criteria detection | >95% | >98% (NLP + human review) |
| Deduplication accuracy | 99.9% | 99.99% |

### 7.3 Compliance

| Metric | Target | Best Practice |
|--------|--------|--------------|
| MAO-004 reconciliation rate | >95% | 99.5%+ (investigate all discrepancies) |
| Documentation linkage rate | 100% | 100% (mandatory audit trail) |
| Transfer formula reconciliation | Balance within ±$10K | Balance within ±$1K (per state) |
| RADV audit readiness | 100% | 100% (proactive package generation) |

---

## 8. Cost Estimation for SaaS Implementation

### 8.1 Development Costs (One-time)

| Component | Low Estimate | High Estimate |
|-----------|---|---|
| HHS-HCC implementation | $50K | $150K |
| CMS-HCC V24/V28 with blending | $75K | $200K |
| CDPS implementation | $30K | $100K |
| Transfer formula engine | $40K | $120K |
| EDGE/MAO-004 validation | $30K | $80K |
| Frailty calculator (PACE/D-SNP) | $20K | $60K |
| Database/code mapping infrastructure | $50K | $150K |
| RADV audit infrastructure | $30K | $80K |
| **Total Development** | **$325K** | **$940K** |

### 8.2 Operational Costs (Annual per payer)

| Component | Low Estimate | High Estimate |
|-----------|---|---|
| Platform SaaS fee (per member per month) | $0.05-$0.15 | $0.10-$0.30 |
| Data validation services | $10K | $50K |
| Compliance/audit support | $20K | $100K |
| Support & training | $10K | $50K |
| Model updates/maintenance | $10K | $50K |
| **Total Annual (1M members)** | **$50K-$180K** | **$130K-$450K** |

---

## 9. Vendor Selection Criteria

### 9.1 Multi-Model Support

| Vendor | HHS-HCC | CMS-HCC | CDPS | ACG | DxCG | Impact Pro | Proprietary |
|--------|---------|---------|------|-----|------|-----------|------------|
| **Arcadia** | Yes | Yes | Yes | Optional | Yes | Optional | No |
| **Persivia** | Yes | Yes | Yes | Optional | Optional | No | No |
| **Innovaccer** | Yes | Yes | Yes | Optional | Optional | Optional | No |
| **RAAPID** | Yes | Yes | No | No | No | No | No |
| **Edifecs** | Yes | Yes | Yes | Yes | Yes | Optional | No |
| **In-house build** | Custom | Custom | Custom | Custom | Custom | Custom | Yes |

### 9.2 Evaluation Matrix

```
Scoring: 1-5 (5 = excellent)

Criteria                      Weight    Vendor A    Vendor B    In-house
─────────────────────────────────────────────────────────────────────
Model coverage                 20%        5           4           5
EDGE/MAO-004 compliance        15%        4           5           3
RADV audit support             15%        4           4           2
Scalability                    15%        5           4           4
Data security/HIPAA            15%        5           5           4
Cost                          10%        3           4           5
Customization                 10%        2           3           5
─────────────────────────────────────────────────────────────────────
WEIGHTED TOTAL                100%       4.2         4.2         4.1
```

---

## 10. Migration Path for Model Transitions

### 10.1 CMS-HCC V24 → V28 (2024-2026)

```
Year 1 (2024): Preparation
┌─────────────────────────────────────┐
│ Implement V28 alongside V24          │
│ Parallel calculation & comparison    │
│ Validate differences in 5-10% sample │
│ Prepare staff for changes            │
│ Update audit procedures              │
└─────────────────────────────────────┘
           │
           ▼
Year 2 (2025): Blended Transition
┌─────────────────────────────────────┐
│ 67% V28 + 33% V24 for payment        │
│ Monitor differences and reconcile    │
│ Address highest-impact changes       │
│ Update coding protocols              │
│ Provider communication               │
└─────────────────────────────────────┘
           │
           ▼
Year 3+ (2026+): V28 Full Implementation
┌─────────────────────────────────────┐
│ 100% V28 for Medicare Advantage      │
│ Encounter data mandate (2029)        │
│ Legacy systems decommission          │
│ Continuous monitoring                │
└─────────────────────────────────────┘
```

### 10.2 State Medicaid Model Changes

```
Example: Transition to CDPS+Rx from legacy model

Phase 1 (Months 1-3): Assessment
- Inventory current model usage
- Identify gaps in CDPS+Rx coverage
- Plan data enrichment needs

Phase 2 (Months 4-6): Parallel Running
- Implement CDPS+Rx alongside legacy
- Validate pharmacy mapping
- Establish reconciliation procedures
- Provider/plan education

Phase 3 (Months 7-9): Cutover
- Transition to CDPS+Rx for new rate setting
- Run legacy in parallel for verification
- Monitor capitation accuracy
- Address discrepancies

Phase 4 (Months 10-12): Stabilization
- Legacy model decommission
- Standard operations
- Process improvement identification
```

---

## 11. References by Model

### HHS-HCC
- [CMS CCIIO Risk Adjustment Guidance](https://www.cms.gov/cciio/programs-and-initiatives/premium-stabilization-programs)
- [EDGE Server Documentation](https://www.cms.gov/cciio/resources/files)
- [HHS-HCC Model Algorithm - CMS DIY Instructions](https://www.cms.gov/files/document/cy2023-diy-instructions-08222023.pdf)

### CMS-HCC
- [Medicare Advantage Rate Setting - CMS](https://www.cms.gov/medicare/payment/capitated-payment-systems)
- [2024-2025 Risk Adjustment Transition Guidance](https://www.cms.gov/newsroom/fact-sheets)
- [RADV Program Guidance](https://www.cms.gov/files/document/radv-program-guidance)

### CDPS
- [UCSD CDPS Resource Center](http://cdps.ucsd.edu/)
- [2022 CDPS Update Documentation](https://medicaidinnovation.org/wp-content/uploads/2023/04/CDPS_April_Fact-Sheet_FINAL.pdf)

### PACE
- [CMS PACE Payment & Risk Adjustment](https://www.cms.gov/medicare/managed-care/programs-of-all-inclusive-care-elderly-pace)

### Commercial
- [Johns Hopkins ACG System](https://www.hopkinsacg.org/)
- [Optum DxCG Resources](https://www.optum.com/business/solutions/risk-adjustment)

---

## 12. Glossary

**ADL**: Activities of Daily Living (frailty assessment component)
**AV**: Actuarial Value (plan's cost-sharing level: 60%, 70%, 80%, 90%)
**CMS**: Centers for Medicare & Medicaid Services (federal agency)
**D-SNP**: Dual-eligible Special Needs Plan (serves Medicare+Medicaid beneficiaries)
**EDGE**: Encounter Data, Group, and Enrollment system (ACA data submission)
**ESRD**: End-Stage Renal Disease (kidney failure requiring dialysis/transplant)
**ETG**: Episode Treatment Group (Optum methodology)
**FIDE SNP**: Fully Integrated Dual-Eligible Special Needs Plan
**HCC**: Hierarchical Condition Category (diagnostic grouping)
**HOS-M**: Health Outcomes Survey - Modified (frailty assessment for PACE/D-SNP)
**MAO-004**: Monthly CMS report showing accepted diagnosis codes per member
**MEAT**: Monitoring, Evaluating, Assessing, Treating (documentation criteria)
**MCO**: Managed Care Organization (state contracts)
**NPI**: National Provider Identifier (physician/provider code)
**PACE**: Programs of All-Inclusive Care for the Elderly
**PMPM**: Per Member Per Month (capitation unit)
**RADV**: Risk Adjustment Data Validation (CMS audit program)
**RAF**: Risk Adjustment Factor (coefficient weight)
**RLS**: Row-Level Security (data isolation method)
**SNP**: Special Needs Plan (specialized MA plans)

