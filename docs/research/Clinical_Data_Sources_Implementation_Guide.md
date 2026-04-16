# Clinical Data Sources for HCC/RAF Scoring
## Quick Reference Implementation Guide

---

## 1. Seven Primary Data Source Categories (Prioritized)

### Tier 1: High-Impact, Immediate ROI
These address largest gaps and have highest audit risk

#### Laboratory Values (eGFR, HbA1c, BNP)
**Effort Required:** Medium (requires lab system integration)
**ROI:** Very High (objective validation of condition stages)
**Implementation Timeline:** 1-3 months

| Condition | Key Lab | Normal Range | Suspect Threshold | HCC |
|-----------|---------|--------------|-------------------|-----|
| CKD Stage 3 | eGFR | >60 | 30-59 | HCC 328 |
| CKD Stage 4 | eGFR | >60 | 15-29 | HCC 329 |
| Diabetes | HbA1c | <5.7% | ≥6.5% or ≥7% controlled | HCC 23+ |
| Heart Failure | BNP | <100 | >100 (symptomatic) | HCC 85/86 |
| CHF Severity | EF (Echo) | >50% | <40% (systolic) | HCC 86 |

**Integration Approach:**
```
Step 1: Connect EHR to Lab System (HL7 interface)
Step 2: Create alerts when lab crosses thresholds
Step 3: Link labs to visit encounter for documentation
Step 4: Provider dashboard shows trending over 12 months
Step 5: Pre-visit report flags abnormal labs 2 days before visit
```

**Expected Outcome:** Capture 20-30% of missed HCC diagnoses within 90 days

---

#### Medication Reconciliation (Active Rx List)
**Effort Required:** Low (most EHRs have this)
**ROI:** Very High (medications don't lie)
**Implementation Timeline:** 2-4 weeks

| Medication Class | Inferred Condition | Action |
|------------------|-------------------|--------|
| Insulin OR Metformin | Type 2 Diabetes | Check if DM2 coded |
| Loop Diuretics | Heart Failure | Check if CHF coded |
| Tiotropium/Albuterol | COPD | Check if COPD coded |
| ACE-I/ARB | Hypertension + CKD/CHF | Check specificity |
| SSRI/SNRI | Depression | Check if Depression coded |
| Anticoagulants | Afib | Check if Afib coded |

**Integration Approach:**
```
Step 1: Monthly automated report of "Rx without matching diagnosis"
Step 2: Flag top 10 by prevalence (e.g., insulin without DM = 200 patients)
Step 3: Route to providers with education (not accusation)
Step 4: Easy click-to-add mechanism if provider agrees
Step 5: Track acceptance rate (target: 60-80% lead to new HCC codes)
```

**Expected Outcome:** Capture 15-25% of missed HCCs from medication patterns within 60 days

---

### Tier 2: Essential Support Functions
These provide validation/specificity for Tier 1 findings

#### Vital Signs & Anthropometrics (BMI, BP trending)
**Effort Required:** Low (existing EHR data)
**ROI:** Medium (supports specificity of Tier 1)
**Implementation Timeline:** Immediate

**Critical for:**
- BMI documentation (morbid obesity requires SPECIFIC value, not calculation)
- BP trending validation for hypertension severity
- Weight gain patterns indicating CHF exacerbation
- O2 sat monitoring for COPD severity

---

#### Problem List Management
**Effort Required:** Medium (workflow change for providers)
**ROI:** High (forms foundation for MEAT documentation)
**Implementation Timeline:** 2-3 months (phased)

**Best Practices:**
- Problem list should contain ONLY active conditions
- Remove/mark inactive annually
- Each problem must have associated encounter in current/prior year
- Provider attests to accuracy quarterly

---

### Tier 3: Secondary Enrichment
These provide context and corroboration

#### Specialist Referrals & Visit Data
**Effort Required:** Medium (requires referral system integration)
**ROI:** Medium (identifies uncaptured complexity)
**Implementation Timeline:** 2-3 months

**Workflow:**
```
Referral Pattern Detection:
1. Patient referred to cardiology → likely heart disease gap
2. Patient referred to nephrology → likely CKD severity gap
3. Patient referred to pulmonology → likely COPD severity gap
4. Patient has psychiatry visits → likely depression/mental health gap

Action:
→ Pre-visit alert before patient sees specialist
→ Ensure specialist findings documented in PCP note
→ Validate diagnoses from specialist encounter
→ Update HCC codes from specialist documentation
```

**Outcome:** Captures diagnoses that present primarily through specialist care

---

#### SDOH & Member Self-Report
**Effort Required:** Medium (screening integration required)
**ROI:** Low Currently (non-revenue), High Future (regulatory trend)
**Implementation Timeline:** 3-6 months

**Capture Opportunity:**
- HRA completion (Health Risk Assessment)
- Standardized screening during visits (PRAPARE tool)
- Care management program data
- Community resource referrals

**Future Value:**
As SDOH incorporation into risk models occurs, early adopters will have data advantage.

---

#### Immunization Records & Quality Data
**Effort Required:** Low (already in claims)
**ROI:** Low Direct (supportive documentation mainly)
**Implementation Timeline:** Immediate

**Application:**
- Validates preventive care engagement
- Immunization gaps may indicate immunocompromised status
- Aligns with HEDIS quality measurement

---

## 2. RAPS vs. EDPS Quick Reference

### Why This Matters Now
**CMS moved 100% to EDPS by 2025.** Submitting via RAPS only will result in zero RAF weight.

| Element | RAPS (Legacy) | EDPS (Current) |
|---------|--------------|----------------|
| **Data Detail** | Minimal—diagnosis only | Full service line detail (CPT, modifiers, revenue codes) |
| **Validation** | Simple (format + diagnosis codes) | Complex (7-layer validation) |
| **Editing** | Basic checks only | Format + Logic + Content + Clinical + CCI edits |
| **Duplicate Detection** | Limited | Advanced (service date + provider + diagnosis) |
| **Risk Adjustment Eligibility** | All diagnoses considered | CMS applies filtering logic |
| **Current Status** | Sunsetting (still submitted but not weighted) | 100% primary system |
| **Migration Impact** | Average 11.9% revenue decrease | Organizations with clean data: <5% impact |

---

### Critical Migration Requirements

**By 2025 (Now):**
- [ ] All encounters submitted via EDPS format
- [ ] X12 837 5010 compliance verified
- [ ] Encounter data submission team trained
- [ ] Feedback reports (MAO-001, MAO-002) reviewed monthly
- [ ] Duplicate detection process in place
- [ ] Editing rules understood and validated

**Revenue Protection:**
Organizations that moved to EDPS with clean documentation lost 1-5% revenue. Organizations with sloppy data lost 15-27%.

---

## 3. CMS V28 Quick Facts & Checklists

### What Changed
- **HCC Count:** 86 → 115 (29 new HCCs)
- **ICD-10 Codes:** 9,797 → 7,770 (2,294 deleted, 268 added)
- **Specificity:** Requires much more granular documentation
- **Risk Impact:** -3.12% overall (but variable by organization)

### Documentation Specificity Examples

**What V28 Requires (Not V24):**

| Condition | V24 OK | V28 Required |
|-----------|--------|-------------|
| Diabetes | "Type 2 Diabetes" | "Type 2 Diabetes without complications" OR "...with complications" + specify |
| Heart Failure | "Congestive Heart Failure" | Specify: Systolic/Diastolic/Combined; Acute/Chronic/Acute-on-Chronic |
| CKD | "Chronic Kidney Disease" | MUST specify stage (1, 2, 3a, 3b, 4, or 5) |
| Depression | "Depression" | Severity if documented; code type (single vs. recurrent) |
| COPD | "COPD" | Specify severity if documented (mild, moderate, severe, very severe) |

### Pre-V28 Audit Checklist

Before 2025 DOS (dates of service):
- [ ] Identify all diabetes HCCs—review for Type 1 vs. Type 2 split
- [ ] Heart failure encounters—add systolic/diastolic/combined specificity
- [ ] CKD documentation—add specific stage references
- [ ] Depression—add severity or screening tool scores
- [ ] COPD—add severity when available
- [ ] ESRD—ensure accurate stage assignment

---

## 4. Prospective vs. Retrospective vs. Concurrent (Comparison)

### Timeline & Workflow

```
PROSPECTIVE (Pre-Visit)
T-48 hours: Coder reviews chart, identifies likely HCCs
T-24 hours: Provider receives alert/preparation list
T-0:       Visit occurs; provider documents findings
Result:    Captures condition during encounter

CONCURRENT (Point-of-Care)
T-0:       Provider documents in real-time
T+30min:   System validates MEAT criteria, alerts if gaps
T+4 hours: Coder reviews note, identifies additional coding
T+24 hrs:  Follow-up if documentation issues
Result:    Validates and reinforces during same visit

RETROSPECTIVE (Post-Visit)
T+7 days:  Provider note completed, submitted
T+30 days: Coder reviews, identifies gaps
T+45 days: Provider contacted to add documentation
T+60 days: Corrected claims submitted
Result:    Delays feedback 30-60 days; less effective
```

### Outcome Comparison

| Approach | Time to Capture | Effectiveness | Cost | Provider Burden |
|----------|-----------------|----------------|------|-----------------|
| Prospective | 2-3 days | 70% first-visit | High setup, low ongoing | Medium (prep time) |
| Concurrent | Same visit | 85% same-day | Medium setup & ongoing | Low (real-time support) |
| Retrospective | 30-60 days | 60% (delayed) | Low | High (delayed feedback) |

**Industry Consensus:** Hybrid model (prospective + concurrent) optimal. Reduces retrospective needs by 30-50%.

---

## 5. MEAT Criteria: Practical Application

### The Four Elements (Only ONE needed, but more = stronger)

#### M = Monitor
**Objective tracking of condition status**

Examples:
- "Lab reviewed: eGFR 32 (Stage 4 CKD)"
- "Vital signs: BP 165/95 (elevated)"
- "Patient reports shortness of breath x 2 weeks"
- "Weight gained 5 lbs in past week"
- "Spirometry: FEV1 58% of predicted"

---

#### E = Evaluate
**Assessment of test results or disease progression**

Examples:
- "eGFR declined from 45 to 32—progression to Stage 4"
- "BNP elevated at 450, compared to 285 last month"
- "HbA1c 8.2%—above goal despite current regimen"
- "EF decreased to 35% on echocardiogram"

---

#### A = Assess/Address
**Clinical decision-making based on findings**

Examples:
- "Discussed findings with patient"
- "Ordered additional testing (urine protein)"
- "Considered medication adjustment"
- "Referred to specialist for evaluation"
- "Counseled on lifestyle modifications"

---

#### T = Treat
**Active management initiated or modified**

Examples:
- "Increased lisinopril from 10 to 20 mg daily"
- "Started insulin therapy for uncontrolled diabetes"
- "Referred to cardiology for CHF optimization"
- "Started pulmonary rehab for COPD"
- "Prescribed antidepressant—sertraline 50 mg daily"

---

### Scoring HCC Documentation Quality (Self-Audit)

**Chart Review Rubric:**

```
Documentation Review Score:

For HCC Code Claim, Rate 1-4:

1 = No MEAT (just diagnosis on problem list)
    → AUDIT RISK: VERY HIGH
    → Action: REQUEST ADDITIONAL DOCUMENTATION

2 = One MEAT element (typically just "T" from problem list Rx)
    → AUDIT RISK: HIGH
    → Action: STRENGTHEN DOCUMENTATION

3 = Two MEAT elements (e.g., "E" + "T": eval + treatment)
    → AUDIT RISK: MEDIUM
    → Action: ACCEPTABLE, Document findings

4 = Three+ MEAT elements (M + E + A + T)
    → AUDIT RISK: LOW
    → Action: WELL-DOCUMENTED, Approve coding

Target Distribution:
- 60%+ coding at Level 4 = Low audit risk
- 25-35% coding at Level 3 = Moderate risk (acceptable)
- <5% coding at Level 2 = Optimization needed
- 0% coding at Level 1 = Coding integrity issue
```

---

## 6. Clinical Indicators by HCC (Top 20)

### High-Volume, High-Risk HCCs

#### HCC 18: Type 2 Diabetes (No Complications)
- **Lab Indicators:** HbA1c result (usually ≥6.5 or ≥7%)
- **Medications:** Metformin, sulfonylureas, DPP-4 inhibitors
- **Documentation:** "Type 2 Diabetes" explicitly (not just "DM")
- **Audit Risk:** Medium (extremely common, easy to miss)
- **V28 Change:** Must distinguish Type 1 vs. Type 2 more carefully

#### HCC 23: Type 2 Diabetes with Complications
- **Lab Indicators:** HbA1c + evidence of complication
- **Complications:** Retinopathy, neuropathy, nephropathy, CAD
- **Specialist:** Ophthalmology, podiatry, nephrology involvement
- **Documentation:** Specific complication documented
- **Audit Risk:** Medium (higher RAF, more scrutiny)
- **V28 Change:** New separate codes for specific complications

#### HCC 48: Morbid Obesity
- **Vital Signs:** **SPECIFIC BMI value MUST be documented** (e.g., "BMI 42")
- **Critical:** Coder CANNOT calculate BMI from height/weight
- **Value:** RAF 0.273 (significant reimbursement)
- **Medications:** GLP-1 agonists, liraglutide, semaglutide
- **Documentation:** "Morbid obesity" + specific BMI in current visit
- **Audit Risk:** HIGH (often improperly calculated)

#### HCC 85: Congestive Heart Failure—Systolic
- **Lab Indicators:** BNP >100, Ejection Fraction <40% on echo
- **Medications:** ACE-I, ARB, beta-blocker, aldosterone antagonist
- **Vital Signs:** BP trending, weight gain, orthopnea, edema
- **Specialist:** Cardiology involved
- **Documentation:** "Systolic heart failure" or "EF 35%" explicitly
- **Audit Risk:** Very High (extremely audited condition)

#### HCC 86: Congestive Heart Failure—Diastolic
- **Lab Indicators:** BNP elevated, EF preserved (>50%) on echo
- **Similar:** Same medications as systolic (ACE-I, ARB, beta-blocker)
- **Critical:** Must distinguish from systolic HCC 85
- **Documentation:** "Diastolic heart failure" OR "HFpEF" OR "EF 58%"
- **Audit Risk:** Very High

#### HCC 96: Specified Arrhythmias (Atrial Fibrillation)
- **Lab Indicators:** EKG showing A-fib rhythm
- **Medications:** Rate control (beta-blocker, diltiazem) + anticoagulation (warfarin, DOAC)
- **Specialist:** Cardiology or EP specialist
- **Documentation:** "Atrial fibrillation" explicitly (not just "cardiac arrhythmia")
- **Audit Risk:** Medium

#### HCC 111: Chronic Obstructive Pulmonary Disease (COPD)
- **Lab Indicators:** Spirometry with FEV1 <80% predicted (mild-very severe spectrum)
- **Medications:** Albuterol, tiotropium, fluticasone/salmeterol combinations
- **Specialist:** Pulmonology involved or community-based pulmonary rehab
- **Documentation:** "COPD" + severity if available
- **Audit Risk:** Very High (frequently audited; often "history of COPD" inappropriately)
- **V28 Changes:** New severity-based HCC hierarchy

#### HCC 155: Depression
- **Lab Indicators:** PHQ-9 score ≥10 (moderate depression) or PHQ-2 screening positive
- **Medications:** SSRI, SNRI, tricyclic antidepressant, MAOI
- **Mental Health Visits:** Psychiatry or psychology encounters
- **Documentation:** "Depression" + severity or screening score if available
- **Audit Risk:** Medium (increasing scrutiny for appropriateness)

#### HCC 326-329: Chronic Kidney Disease (Stages 1-5)
- **Lab Indicators:** eGFR-based stage assignment (Stage 3a/3b/4/5 most impactful)
- **Supporting Labs:** Creatinine trending, proteinuria/albuminuria
- **Medications:** ACE-I/ARB for kidney protection
- **Specialist:** Nephrology involvement for Stage 4-5
- **Documentation:** MUST specify stage (not just "CKD")
- **Audit Risk:** Very High (objective lab-based, easy to validate/invalidate)
- **V28 Change:** Clearer stage-based HCC separation

---

## 7. RADV Audit Prep Checklist (2025-2026)

### CMS RADV Program Facts
- **Scope:** 550+ Medicare Advantage plans now audited annually
- **Sample Size:** 200 records per contract (vs. 35 previously)
- **Reviewer Pool:** 2,000 coders (vs. 40 previously)
- **Focus:** Bidirectional validation (add missed AND remove unsupported)
- **Extrapolation:** Audit findings used to calculate overpayments
- **Settlement Trend:** Aetna/CVS $117.7M (March 2026); enforcement active

### Pre-Audit Readiness

**Documentation Audit (Do This Quarterly):**

```
□ Sample 50 random encounters with HCC coding
□ For each HCC, verify:
  □ At least ONE MEAT element present
  □ Documentation dated in service year
  □ Provider signature (digital acceptable)
  □ Sufficient specificity (V28 standards)
  □ Diagnosis-medication alignment
  □ Lab values support condition claim

Scoring:
- Deficiency rate >5% = Systemic issue (plan intervention)
- Deficiency rate 2-5% = Acceptable (continue monitoring)
- Deficiency rate <2% = Excellent (audit-ready)
```

**Data Quality Audit (Monthly):**

```
□ EDPS submission compliance
□ Duplicate encounter detection working
□ No CCI edit violations
□ Provider credentials valid
□ Diagnosis codes valid
□ Service dates within coverage
□ Clinical consistency checks pass
  (e.g., no pediatric codes for 87-year-old)
```

**Risk Assessment Report (Quarterly):**

```
□ Top 10 HCCs by volume—each audit-ready?
□ Top 10 HCCs by revenue—each audit-ready?
□ High-risk conditions: CHF, COPD, diabetes, CKD—documentation quality?
□ V28 transition impact analyzed?
□ Pharmacy-diagnosis alignment spot-checked?
```

**Remediation Plan (If Deficiencies Found):**

```
□ Identify root cause (provider behavior? Coder training? System issue?)
□ Correct identified deficient diagnoses (BOTH directions: add AND remove)
□ Provider education (what was missing, why it matters)
□ System improvement (process change to prevent recurrence)
□ Trend reporting (show improvement over 3-6 months)
```

---

## 8. Data Integration Architecture (Visual Framework)

### Recommended System Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION LAYER                      │
├─────────┬──────────┬─────────┬──────────┬──────────┬──────────┤
│   EHR   │  Claims  │  Labs   │ Pharmacy │ Imaging  │  Member  │
│ Notes   │  Detail  │ Results │  Rx List │ Reports  │  Reports │
└────┬────┴────┬─────┴────┬────┴────┬─────┴────┬─────┴────┬─────┘
     │         │          │         │          │          │
     └─────────┴──────────┴────┬────┴──────────┴──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  NORMALIZATION HUB  │
                    │ (Date, Units, ICD)  │
                    └──────────┬──────────┘
                               │
     ┌─────────────────────────┼─────────────────────────┐
     │                         │                         │
     ▼                         ▼                         ▼
┌──────────────┐      ┌──────────────────┐      ┌──────────────┐
│ PROSPECTIVE  │      │   CONCURRENT     │      │RETROSPECTIVE │
│ CODING       │      │   CODING         │      │ CODING       │
│ (T-48h)      │      │   (Real-time)    │      │ (T+30d)      │
└──────────────┘      └──────────────────┘      └──────────────┘
     │                        │                         │
     └─────────────┬──────────┴──────────┬──────────────┘
                   │                     │
                   ▼                     ▼
            ┌──────────────────────────────────┐
            │    UNIFIED HCC CODING OUTPUT     │
            │  (Provider Alerts + Coding Recs) │
            └──────────────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────────────┐
            │   QUALITY ASSURANCE VALIDATION   │
            │  (Coder → Supervisor → Auditor)  │
            └──────────────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────────────┐
            │   ENCOUNTER DATA SUBMISSION      │
            │   (EDPS X12 837 5010)            │
            └──────────────────────────────────┘
```

---

## 9. ROI Analysis Framework

### Quick ROI Calculation Example

**Scenario:** Organization with 50,000 Medicare Advantage members

#### Current State (Estimated)
- HCC capture rate: 75% (vs. 95%+ benchmark)
- Average RAF score: 1.15 (vs. 1.25 benchmark)
- **Revenue Impact:** -$5 million annually (50K × $1,000 per member × 0.10 RAF gap)

#### After Multi-Source Data Integration (12 months)
- Implementation cost: $200K (systems, training, staff)
- HCC capture rate improvement: 75% → 87% (+12%)
- Average RAF score improvement: 1.15 → 1.22 (+0.07)
- **Revenue Recovery:** +$3.5 million annually

#### ROI Calculation
```
Net Revenue Gain = $3.5M - $200K = $3.3M
ROI = $3.3M / $200K = 16.5x (1,650%)
Payback Period = $200K / $3.5M = 0.7 months (3 weeks)
3-Year Value = ($3.5M × 3) - $500K setup = $9.5M net
```

---

## 10. Implementation Roadmap (Phase-Based)

### Phase 1: Foundation (Months 1-3)
**Goal:** Enable data collection infrastructure

- [ ] Audit current data sources/gaps
- [ ] Identify lab system connectivity requirements
- [ ] Establish medication reconciliation process
- [ ] Begin V28 documentation assessment
- [ ] Review EDPS submission compliance
- [ ] Cost: ~$50K; Outcome: Foundation in place

### Phase 2: Integration (Months 4-6)
**Goal:** Connect data sources to HCC workflow

- [ ] Deploy lab integration (eGFR, HbA1c, BNP focus)
- [ ] Activate medication-diagnosis correlation rules
- [ ] Implement pre-visit alert system
- [ ] Establish concurrent coding process
- [ ] Remediate high-risk V28 transitions
- [ ] Cost: ~$100K; Outcome: 10-15% HCC capture improvement

### Phase 3: Optimization (Months 7-12)
**Goal:** Deploy advanced analytics and refine processes

- [ ] Implement NLP/AI suspect condition detection
- [ ] Expand SDOH data capture
- [ ] Enhance specialist referral integration
- [ ] Develop comprehensive analytics dashboard
- [ ] Establish RADV audit preparedness program
- [ ] Cost: ~$150K; Outcome: 20-30% total HCC improvement

### Phase 4: Maturity (Year 2)
**Goal:** Sustain and continuous improvement

- [ ] Ongoing monitoring and optimization
- [ ] Provider education evolution
- [ ] Competitive benchmarking
- [ ] Emerging regulatory change tracking
- [ ] Cost: ~$100K annually; Outcome: Sustained optimization

---

## 11. Metrics Dashboard (Track Quarterly)

### Key Performance Indicators (KPIs)

**HCC Capture Metrics:**
- [ ] HCC capture rate by condition (target: 90%+)
- [ ] RAF score vs. peer benchmarks
- [ ] Prospective coding volume (capture before claims)
- [ ] Medication-diagnosis alignment percentage

**Process Metrics:**
- [ ] Pre-visit alerts generated per month
- [ ] Provider alert acceptance rate
- [ ] Time from identification to coding (target: <7 days)
- [ ] Concurrent coding review rate (target: 50%+)

**Quality Metrics:**
- [ ] Documentation deficiency rate (target: <3%)
- [ ] MEAT criteria compliance (target: 85%+)
- [ ] QA coder agreement rate (target: 95%+)

**Compliance Metrics:**
- [ ] EDPS submission acceptance rate (target: 100%)
- [ ] Duplicate encounter rate (target: 0%)
- [ ] RADV audit vulnerability scoring (target: <10% high-risk)

**Financial Metrics:**
- [ ] RAF score trending YoY
- [ ] Revenue impact per new HCC (average ~$1,000 member/year)
- [ ] Cost per captured HCC
- [ ] ROI of data integration investment

---

## 12. Vendor Selection Criteria

### If Implementing Multi-Source Data Platform

**Evaluation Scorecard (Weight each 1-5):**

| Capability | Weight | Score | Notes |
|-----------|--------|-------|-------|
| EHR Integration | 20% | ___ | Real-time access required |
| Lab Value Parsing | 15% | ___ | eGFR, HbA1c, BNP at minimum |
| Medication Intelligence | 15% | ___ | Drug-disease correlation accuracy |
| NLP/AI Accuracy | 15% | ___ | 90%+ accuracy on suspect detection |
| Provider UX | 10% | ___ | Point-of-care usability |
| Reporting/Analytics | 10% | ___ | Dashboard, trending, benchmarking |
| Compliance Support | 10% | ___ | RADV prep, documentation validation |
| Implementation Timeline | 5% | ___ | Can deploy in <6 months |
| Cost Structure | 5% | ___ | Reasonable per-member pricing |

**Scoring:** >4 average = Strong fit; 3-4 = Acceptable; <3 = Evaluate alternatives

---

## Final Recommendation Summary

### Three Paths Forward

**Path A: Conservative (Minimal Investment)**
- Focus on medication reconciliation + vital signs
- Manual processes, limited automation
- Cost: $50-100K
- Expected Improvement: 5-10% HCC capture gain
- Timeline: 3-6 months
- Best for: Small practices, limited IT resources

**Path B: Moderate (Standard Approach)**
- Multi-source integration (EHR, labs, pharmacy, claims)
- Semi-automated with coder support
- Point-of-care concurrent review capability
- Cost: $200-300K implementation + $100K/yr ongoing
- Expected Improvement: 15-25% HCC capture gain
- Timeline: 6-12 months
- Best for: Mid-size health systems, payers

**Path C: Advanced (Competitive Advantage)**
- Full multi-source intelligence platform
- NLP/AI suspect condition detection
- Real-time provider decision support
- Predictive risk modeling
- Cost: $500K+ implementation + $150K+/yr ongoing
- Expected Improvement: 25-40% HCC capture gain
- Timeline: 12-18 months
- Best for: Large health systems, ambitious payers

---

**Document Version:** 1.0 (Implementation Guide)
**Last Updated:** March 30, 2026
**Review Frequency:** Quarterly
