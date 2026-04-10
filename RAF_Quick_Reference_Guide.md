# Patient-Level RAF Analytics: Quick Reference Guide

**Last Updated:** April 2026

---

## 1. RAF Score Calculation Quick Reference

### Basic Formula
```
RAF Score = Demographic Value + Σ (HCC Weights) + Interaction Factors
```

### Score Interpretation
| RAF Score | Meaning | Example Cost |
|-----------|---------|--------------|
| 0.5 | 50% below average cost | $6,000/year baseline |
| 0.7 | 30% below average | $8,400/year baseline |
| 1.0 | Average cost patient | $12,000/year baseline |
| 1.5 | 50% above average | $18,000/year baseline |
| 2.0 | 100% above average (double) | $24,000/year baseline |
| 2.5+ | Highly complex patient | $30,000+/year baseline |

### Demographic Adjustment Factors (Examples)
- **Age 65-69:** Base RAF ~0.80
- **Age 70-74:** Base RAF ~1.00
- **Age 75-79:** Base RAF ~1.20
- **Age 80-84:** Base RAF ~1.40
- **Age 85+:** Base RAF ~1.60+

**Additional Adjustments:**
- **Dual-Eligible:** +15-25% RAF premium
- **Disabled (Age <65):** +40-80% RAF premium
- **Skilled Nursing Facility:** +15-25% RAF premium
- **Long-Term Care:** +20-35% RAF premium

---

## 2. Common HCC Codes and Weights

### High-Value HCCs (Highest Revenue Impact)
| HCC | Condition | Weight | Annual Impact @ $12K Base |
|-----|-----------|--------|---------------------------|
| 70 | Quadriplegia/Paraplegia | 0.480 | $5,760 |
| 85 | Congestive Heart Failure | 0.368 | $4,416 |
| 111 | COPD | 0.346 | $4,152 |
| 157 | Schizophrenia | 0.325 | $3,900 |
| 159 | Substance Use Disorder | 0.333 | $3,996 |
| 18 | Diabetes with Complications | 0.307 | $3,684 |
| 158 | Major Depression/Bipolar | 0.306 | $3,672 |
| 81 | Coronary Artery Disease | 0.266 | $3,192 |
| 135 | CKD Stage 3b | 0.298 | $3,576 |
| 134 | CKD Stage 4-5 | 0.357 | $4,284 |

### Medium-Value HCCs
| HCC | Condition | Weight | Annual Impact |
|-----|-----------|--------|----------------|
| 19 | Diabetes without Complications | 0.106 | $1,272 |
| 27 | Hepatic Cirrhosis | 0.295 | $3,540 |
| 174 | Osteoporosis | 0.098 | $1,176 |
| 82 | Ischemic Heart Disease (other) | 0.181 | $2,172 |

### Key Hierarchies (More Severe Supersedes Less Severe)
- Diabetes with Complications (HCC 18, 0.307) > Diabetes without Complications (HCC 19, 0.106)
- Metastatic Cancer (HCC 8, 0.321) > Non-metastatic Cancer (various weights 0.107-0.298)
- CKD Stage 4-5 (HCC 134, 0.357) > CKD Stage 3b (HCC 135, 0.298)

---

## 3. Revenue Calculation Examples

### Formula
```
Annual Patient Revenue = RAF Score × Base Annual Rate
Monthly PMPM Revenue = RAF Score × Monthly Base Rate

OR if using per-HCC value:
Each 0.1 RAF = $74.85 PMPM = $898.20 PMPY (nationally averaged)
```

### Example 1: Simple Patient (One Condition)
**Patient:** 72-year-old female, Type 2 Diabetes (uncomplicated)

```
Demographic (age/gender): 0.92
HCC 19 (Diabetes): 0.106
Total RAF: 1.026

Annual Revenue = 1.026 × $12,000 = $12,312
Monthly PMPM = $1,026
```

### Example 2: Complex Patient (Multiple Conditions)
**Patient:** 78-year-old male, CHF, CKD Stage 3b, Diabetes with Complications, COPD

```
Demographic (age 78): 1.15
HCC 85 (CHF): 0.368
HCC 135 (CKD): 0.298
HCC 18 (Diabetes+): 0.307
HCC 111 (COPD): 0.346
Interaction Factor (CHF+CKD): +0.082

Total RAF: 2.551

Annual Revenue = 2.551 × $12,000 = $30,612
Monthly PMPM = $2,551
```

### Example 3: Gap Closure Financial Impact
**Patient:** 75-year-old female

Current RAF: 0.95 (no CHF documented)
```
Current Revenue = 0.95 × $12,000 = $11,400/year
```

After CHF gap closure:
```
New RAF = 0.95 + 0.368 = 1.318
New Revenue = 1.318 × $12,000 = $15,816/year
Gap Impact = $4,416/year per patient
5-Year Value = $22,080 (same patient, recaptured condition)
```

### Population-Level Example
**Portfolio:** 10,000 Medicare Advantage patients
- Current Average RAF: 1.08
- Base Rate: $12,000 PMPY
- Current Annual Revenue: $129,600,000

Scenario: Achieve 5% improvement in HCC capture
```
New Average RAF = 1.08 × 1.05 = 1.134
Additional Revenue per Patient = (1.134 - 1.08) × $12,000 = $648/patient
Total Additional Revenue = 10,000 × $648 = $6,480,000/year
5-Year Value = $32,400,000
```

---

## 4. Patient Risk Stratification Tiers

### Population Distribution and Characteristics

| Tier | % of Pop | Avg RAF | Avg Annual Cost | Care Management | HCC Focus |
|------|----------|---------|-----------------|-----------------|-----------|
| **Highly Complex** | 5-10% | 1.8-2.5 | $21,600-30,000 | Intensive, multi-disciplinary | All major HCCs |
| **High-Risk** | 20-30% | 1.2-1.8 | $14,400-21,600 | Proactive coordination | Chronic disease management |
| **Rising-Risk** | 2-10% | 1.0-1.2 | $12,000-14,400 | Early intervention | Condition-specific monitoring |
| **Low-Risk** | 10-20% | 0.5-1.0 | $6,000-12,000 | Preventive, digital | Wellness, screenings |

### Intervention Allocation by Tier
**Highly Complex:**
- Dedicated care coordinator (1:50-75 patients)
- Monthly touchpoints minimum
- Integrated behavioral health
- Palliative care evaluation
- Social services navigation

**High-Risk:**
- Shared care coordinator (1:200-300)
- Quarterly clinical assessments
- Disease management programs
- Remote monitoring for selected conditions

**Rising-Risk:**
- Automated outreach/reminders
- Preventive health screenings
- Digital health tools
- Group education classes

**Low-Risk:**
- Automated preventive reminders
- Annual wellness visit
- Digital self-management tools
- Telehealth for routine visits

---

## 5. MEAT Documentation Standards

### What is MEAT?
**M** = Monitoring
**E** = Evaluation
**A** = Assessment
**T** = Treatment

**Requirement:** Minimum ONE of four criteria required per encounter to validly recapture condition

### Examples of Valid Documentation

**Monitoring Example:**
```
"Diabetes monitored; glucose logs show good control"
"BP check today: 138/82; continues current regimen"
"Patient denies new CHF symptoms; weight stable"
```

**Evaluation Example:**
```
"HbA1c reviewed: 6.8% (improved from 7.2%)"
"BNP reviewed from cardiology: elevated at 450"
"Creatinine stable at 2.1; eGFR 28"
```

**Assessment Example:**
```
"COPD stable on current inhalers"
"CKD Stage 3b, unchanged; continue monitoring"
"Hypertension controlled; no adjustment needed"
```

**Treatment Example:**
```
"Continued Metformin 1000mg BID"
"Adjusted lisinopril to 20mg daily"
"Added home oxygen for COPD management"
```

### Invalid Documentation (Do NOT Meet MEAT)
```
WRONG: "DM, HTN, COPD per chart"
WRONG: "Problem list includes diabetes" (with no note content)
WRONG: Vital signs alone without clinical interpretation
WRONG: Medication list without condition discussion
```

---

## 6. HCC Gap Identification Checklist

### High-Value Gap Opportunities to Prioritize
- [ ] CHF (HCC 85): Do all patients on loop diuretics have CHF documented?
- [ ] CKD Stage 3+ (HCC 134-135): Do all patients with creatinine >2.0 have CKD?
- [ ] Diabetes with Complications (HCC 18): Are diabetics on insulin documented as "with complications"?
- [ ] COPD (HCC 111): Do all smokers or those on respiratory meds have COPD documented?
- [ ] CAD (HCC 81): Do all patients on aspirin/statin have documented diagnosis?
- [ ] Depression (HCC 158): Is behavioral health documentation integrated into primary record?
- [ ] CKD Stage 4-5 (HCC 134): Are dialysis patients documented for highest HCC?

### Validation Steps Before Coding
1. **Clinical Verification:** Chart confirms diagnosis meets clinical criteria
2. **MEAT Criteria Check:** Documentation shows at least one of M, E, A, T
3. **Medication Correlation:** Prescribed medications consistent with diagnosis
4. **Test Result Support:** Lab/imaging results support condition
5. **Specialist Confirmation:** If high-value gap, verify with specialist documentation

---

## 7. Annual Recapture Workflow Timeline

### Optimal Recapture Windows
| Timeframe | Visit Type | Effectiveness | Action |
|-----------|-----------|----------------|---------|
| **Jan-Mar** | Annual Wellness Visit | Excellent | Primary recapture opportunity |
| **Apr-Sep** | Chronic disease follow-up | Good | Opportunistic recapture |
| **Oct-Dec** | End-of-year visits | Fair | Last-chance recapture |

### Pre-Visit Workflow Preparation
```
1. Query EHR for patient's prior-year HCCs
2. Flag conditions requiring recapture in chart
3. Add HCC list to pre-visit summary
4. Create discussion prompt for provider
5. Prepare condition review form for patient
```

### In-Visit Execution
```
1. Provider reviews prior HCCs with patient
2. Confirms/updates status for each condition
3. Examines patient if clinically indicated
4. Documents per MEAT criteria (minimum one)
5. Coder processes while patient still in office
6. Closes gap same-day vs. weeks later
```

### Performance Metrics to Track
- % Recapture Rate (target: 90%+)
- Average HCCs recaptured per patient (target: >90% of prior year)
- Days to recapture (target: <7 days of encounter)
- Providers meeting recapture targets (target: >85%)

---

## 8. Patient Engagement Channel Preferences

### Effectiveness and Engagement Rates

| Channel | Engagement Rate | Best For | Adoption |
|---------|-----------------|----------|----------|
| **SMS/Text** | 45% | Young-mid age, quick action | High |
| **Phone Call** | 35% | Older adults (65+), barrier discussion | Moderate |
| **Email** | 25% | Detailed information | Moderate |
| **Patient Portal** | 30% | Routine scheduling | Growing |
| **In-Clinic Prompt** | 90%+ | Gap closure during visit | Best |

### Recommended Multi-Channel Sequence

**Week 1-2:** Email campaign
```
Subject: "Annual Health Check: Update Your Medical Records"
CTR (Click-through): 12-15%
Conversion (Appointment): 8-10%
```

**Week 3:** SMS reminder
```
"Hi [Name], annual health check available. Schedule: [link]"
Incremental Conversion: +8-12%
```

**Week 4-6:** Phone outreach (high-risk tier only)
```
Care coordinator calls patients 65+ or complex
Conversion: 35-45% (with personal barrier discussion)
```

**Week 7-12:** In-encounter resolution
```
Any visit provider checks: "Due for annual wellness?"
In-visit gap closure: 90%+ effectiveness
```

### Patient Barrier Identification and Mitigation

| Barrier | Patient Segment | Solution | Effectiveness |
|---------|-----------------|----------|---|
| Cost | Low-income dual-eligible | Financial assistance programs | 40-50% improved adherence |
| Transportation | Older/disabled/rural | Telehealth + community transport | 35-45% improvement |
| Health Literacy | Limited English/low education | Plain language, visual aids, interpretation | 30-40% improvement |
| Navigation | Complex/elderly | Appointment assistance, reminders | 50-60% improvement |
| Distrust | Underserved communities | Community health worker engagement | 45-55% improvement |

---

## 9. HIPAA Privacy Controls Checklist

### Access Control Requirements
- [ ] Role-based access control (RBAC) implemented
- [ ] Staff can only see records needed for their job
- [ ] Quarterly access reviews performed
- [ ] Audit logs reviewed regularly for suspicious access
- [ ] Automatic de-provisioning when staff leave

### Data Security Requirements
- [ ] Patient RAF data encrypted at rest (database encryption)
- [ ] Patient RAF data encrypted in transit (TLS 1.2+)
- [ ] Encryption keys managed separately from data
- [ ] USB drives containing patient data encrypted
- [ ] No patient data on personal devices

### Workforce Training
- [ ] Annual HIPAA training for all staff (required)
- [ ] Specialized training for high-risk roles (developers, analysts)
- [ ] Incident reporting procedures documented and understood
- [ ] "Need-to-know" principle enforced and explained

### Business Associate Agreements
- [ ] Written BAA with all vendors handling patient data
- [ ] Subcontractors covered by BAA
- [ ] Vendor security assessments completed
- [ ] Right-to-audit clause included
- [ ] Breach notification requirements specified

### De-identification
If removing identifiers for research/analytics:
```
Remove these 18 identifiers (Safe Harbor):
1. Name
2. Geographic subdivisions <state
3. Dates (except year) of clinical care
4. Phone numbers
5. Fax numbers
6. Email addresses
7. Social security numbers
8. Medical record numbers
9. Health plan beneficiary numbers
10. Account numbers
11. Certificate/license numbers
12. Vehicle identifiers
13. Device identifiers
14. URLs
15. IP addresses
16. Biometric identifiers
17. Full-face photos
18. Other unique ID numbers
```

---

## 10. SDOH Integration Framework

### SDOH Categories and Z-Codes

| Category | ICD-10 Range | Example Codes | Revenue Impact |
|----------|-------------|---------------|---|
| Housing | Z59.0-Z59.1 | Homelessness, inadequate housing | Non-billable (currently) |
| Economic | Z59.5-Z59.6 | Extreme poverty, low income | Non-billable (currently) |
| Food Security | Z59.8 | Food insecurity | Non-billable (currently) |
| Transportation | Z58.9 | Transportation barriers | Non-billable (currently) |
| Social Isolation | Z60.0-Z60.2 | Social isolation, rejection | Non-billable (currently) |
| Education | Z55 | Education/literacy problems | Non-billable (currently) |
| Substance Use | Z65.8 | Drug/alcohol use issues | Non-billable (currently) |

### New Code G0136 (Effective Jan 2026)
```
Description: Administration of standardized, evidence-based SDOH 
             risk assessment tool, 5-15 minutes
Reimbursement: ~$15-25 per assessment (MA plans vary; Medicare doesn't reimburse)
Use Cases: Annual wellness, care management enrollment, high-risk onboarding
Tools: PRAPARE, AHC, CMS-endorsed assessments
```

### SDOH Analytics Baseline Metrics
Track in population health dashboard:
- % screened for SDOH annually
- Average unmet needs per patient (target: <1.0)
- % of identified needs with documented interventions
- Cost per social need addressed
- Health outcomes correlation (readmissions, ED visits)

### SDOH and HCC Interaction
```
Traditional HCC captures: "Patient has heart failure"
SDOH-aware documentation: "Patient has CHF but homelessness 
limiting medication adherence; referred to housing resource"

Result: Same HCC code, but better clinical context for care 
management and outcomes prediction
```

---

## 11. Compliance and Audit Quick Facts

### RADV Program (Medicare Advantage Risk Adjustment Data Validation)
**What:** CMS audits MA plans to verify diagnoses are supported by medical records

**Scope Expansion (2025-2026):**
- CMS coders: 40 → ~2,000 by Sept 2025
- MA plans audited: ~60/year → all 550+ eligible annually
- Timeline: Complete all outstanding audits by early 2026

**Most Common Audit Findings:**
1. Undocumented diagnoses (code submitted, no chart support)
2. Hierarchical violations (both parent and child HCC codes)
3. Z-code misuse (non-billable codes treated as HCC)
4. Transient as chronic (acute diagnosis coded as chronic)
5. Duplicate diagnoses (same condition counted twice)

**Financial Penalties:**
- Unsupported diagnosis = repayment to CMS
- 2018-2024 PY estimates: 9.5% of MA payments are improper (per CMS)
- Extrapolation applies (sample audits extrapolated to full year)

### Risk Mitigation Steps
1. **Pre-submission Validation:** Clinical review of high-risk codes (sample)
2. **Continuous Auditing:** Vendor compliance monitoring tools
3. **Documentation Links:** Electronic connection from diagnosis to chart support
4. **Provider Education:** CMS coding requirements and high-risk codes
5. **Internal RADV Simulation:** Annual mock audit of organization's submissions

---

## 12. Technology Vendor Comparison Summary

### Major Categories

**Comprehensive Platforms** (RA + Analytics + Engagement)
- Veradigm, Inovalon, Innovaccer, Optum/UnitedHealthcare
- Cost: $50K-150K/year for mid-size organizations
- ROI: 2.5-6x (payback 3-6 months)

**Gap Identification Specialists**
- Clinical Architecture, Inferscience, MDSynergy
- Focus: NLP, documentation analysis, real-time suggestions
- Cost: $30K-80K/year

**Patient Engagement Platforms**
- Arcadia, Navvis, GoHealth
- Focus: Outreach automation, appointment scheduling
- Cost: $20K-60K/year

**Analytics and Reporting**
- MedInsight, Veradigm, Health Catalyst
- Focus: Population health, dashboard analytics
- Cost: $25K-100K/year

### Implementation ROI Model (10K patient portfolio)
```
Annual Costs:
  Software licensing: $30-50K
  Staffing (gap coordinators): $200-300K
  Training/change management: $20-40K
  ────────────────────────────
  Total: $250-390K

Annual Benefits:
  5% RAF improvement: $800K-1.2M
  Reduced audit risk: $100-200K
  Workflow efficiency: $50-100K
  ────────────────────────────
  Total: $950K-1.5M

ROI: 2.5-6x
Payback Period: 3-6 months
```

---

## 13. Key Metrics Dashboard (Monthly Tracking)

### Provider Performance
```
Provider A (n=200 patients):
  Current Average RAF: 1.18
  Monthly HCC Recapture Rate: 92%
  Gap Closure Rate: 68%
  MEAT Documentation Compliance: 94%
  Status: ✓ Exceeds targets
```

### Population Health
```
Total Population: 10,000
Current Average RAF: 1.08
YTD HCC Captures: 8,540 / 9,200 possible (92.8%)
YTD Gap Closures: 412 / 610 opportunities (67.5%)
YTD Revenue Impact: $2.8M vs. $3.1M target
Status: On track; monitor Dec recapture cycle
```

### Program Operations
```
Highly Complex Patients: 812 (8.1% of pop) | Avg RAF 2.14
High-Risk Patients: 2,440 (24.4%) | Avg RAF 1.52
Rising-Risk Patients: 610 (6.1%) | Avg RAF 1.08
Low-Risk Patients: 6,138 (61.4%) | Avg RAF 0.72

Top Gap Closure Opportunities (by revenue):
  1. CHF (missing 142 patients): $627,600/year value
  2. CKD Stage 3b (missing 187): $638,700/year
  3. Diabetes+ (missing 94): $345,600/year
  4. COPD (missing 73): $302,800/year
```

### Compliance
```
Provider Audit Risk Score (0-100): 34
  - Documentation Quality: 42/50
  - MEAT Criteria Compliance: 43/50
  - High-Risk Code Scrutiny: 35/50

Recent RADV Audit Results: PASSED
  - Sample size: 50 records
  - Error rate: 2%
  - Unsupported diagnoses: 1
  - Findings: Minor (non-extrapolated)
```

---

## 14. Common Abbreviations and Definitions

| Term | Definition |
|------|-----------|
| RAF | Risk Adjustment Factor |
| HCC | Hierarchical Condition Category |
| PMPM | Per Member Per Month |
| PMPY | Per Member Per Year |
| MA | Medicare Advantage |
| ACO | Accountable Care Organization |
| EHR | Electronic Health Record |
| SDOH | Social Determinants of Health |
| MEAT | Monitoring, Evaluation, Assessment, Treatment |
| RADV | Risk Adjustment Data Validation (CMS audit program) |
| NLP | Natural Language Processing |
| HIPAA | Health Insurance Portability and Accountability Act |
| PHI | Protected Health Information |
| BAA | Business Associate Agreement |
| CMS | Centers for Medicare & Medicaid Services |
| ICD-10 | International Classification of Diseases, 10th Edition |
| CPT | Current Procedural Terminology |
| CKD | Chronic Kidney Disease |
| CHF | Congestive Heart Failure |
| COPD | Chronic Obstructive Pulmonary Disease |
| CAD | Coronary Artery Disease |
| PRAPARE | Protocol for Responding to and Assessing Patients' Assets, Risks, and Experiences |
| AHC | Accountable Health Communities |

---

## 15. Resources and Next Steps

### Immediate Actions (Week 1)
1. Review organization's current RAF performance vs. benchmarks
2. Calculate current average RAF and identify top 10% of patients
3. Identify top 5 gap closure opportunities by financial value
4. Assess current documentation practices against MEAT criteria
5. Review HIPAA and privacy controls compliance

### Short-Term (Month 1-3)
1. Implement pre-visit HCC recapture workflows in EHR
2. Establish MEAT criteria training for provider teams
3. Launch pilot annual wellness visit promotion campaign
4. Conduct baseline RADV compliance audit (sample)
5. Deploy patient engagement multi-channel outreach for top gaps

### Medium-Term (Month 3-6)
1. Evaluate technology vendors for real-time gap identification
2. Establish internal RAF monitoring dashboard
3. Develop high-risk code audit processes
4. Integrate SDOH screening into care management workflows
5. Train care coordinators on gap closure and patient barriers

### Strategic (6+ months)
1. Full technology platform implementation
2. Establish RAF incentive program for providers
3. Develop SDOH care coordination partnerships
4. Prepare for 2027 SDOH model updates
5. Plan for expanded CMS RADV audit environment

---

*Quick Reference Guide | Patient-Level RAF Analytics | April 2026*
*For complete research, refer to: Patient_Level_RAF_Analytics_Research.md*
