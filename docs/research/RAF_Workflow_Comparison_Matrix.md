# Risk Adjustment Workflow Comparison Matrix

**Purpose:** Side-by-side comparison of retrospective, concurrent, and prospective methodologies  
**Date:** April 1, 2026

---

## WORKFLOW PROCESS COMPARISON

### RETROSPECTIVE WORKFLOW

```
Timeline: Weeks/Months After Patient Encounter

PHASE 1: CHART SELECTION
├─ When: 4-12 weeks post-encounter
├─ Who: Analytics team, CDI directors
├─ What: Predictive analytics identify high-value charts
│   ├─ Members with multiple conditions
│   ├─ Medication-indicated diagnoses
│   ├─ Unexpected risk score drops
│   └─ Specialty conditions
├─ Duration: 2-4 weeks
└─ Output: Prioritized chart review list

PHASE 2: CHART REVIEW
├─ When: 8-16 weeks post-encounter
├─ Who: Retrospective coders, medical record reviewers
├─ What: Clinical documentation analysis
│   ├─ Read physician notes (30-45 min per chart)
│   ├─ Identify missed diagnoses
│   ├─ Map to valid HCC codes
│   └─ AI tools reduce to 10 min per chart
├─ Duration: 4-8 weeks
└─ Output: Identified missed diagnoses with HCC codes

PHASE 3: PROVIDER QUERY
├─ When: 12-18 weeks post-encounter
├─ Who: CDI specialists, coders
├─ What: Request provider confirmation
│   ├─ Document query in record
│   ├─ Send to provider (email/EHR)
│   ├─ Wait for response (2-4 weeks)
│   └─ High risk of non-response (20-30%)
├─ Duration: 4-8 weeks
└─ Output: Provider response (or none)

PHASE 4: CODE SUBMISSION
├─ When: 16-24 weeks post-encounter
├─ Who: Coders, billing compliance
├─ What: Submit diagnosis codes to CMS
│   ├─ MEAT criteria validation
│   ├─ Documentation compliance check
│   ├─ Quality assurance review
│   └─ Addendum/amendment documentation
├─ Duration: 1-2 weeks
└─ Output: Claims with added HCC codes

PHASE 5: CASH RECEIPT
├─ When: 24-36 weeks post-encounter (6-9+ months)
├─ Who: Finance, Revenue Cycle
├─ What: Initial Run/Midyear/Final Run payment
│   ├─ September Initial Run (month 13)
│   ├─ March Midyear Run (month 16)
│   ├─ July Final Run (month 20)
│   └─ Multi-year adjustment period possible
├─ Duration: Ongoing
└─ Output: Payment receipt and reconciliation

AUDIT RISK: HIGH (Back-dated changes, amendment patterns flagged)
```

---

### CONCURRENT WORKFLOW

```
Timeline: During/Immediately After Patient Encounter

PHASE 1: PRE-VISIT PREPARATION
├─ When: 1-2 days before scheduled encounter
├─ Who: CDI team, analytics
├─ What: Prepare suspected conditions list
│   ├─ Compile from medical records
│   ├─ Flag care gaps from claims
│   ├─ Identify high-risk HCC categories
│   └─ Alert providers in EHR
├─ Duration: 1-2 days
└─ Output: Provider-ready suspect list in chart

PHASE 2: DURING ENCOUNTER
├─ When: Same day as patient visit (real-time)
├─ Who: Provider + coder (online or nearby)
├─ What: Real-time clinical interaction
│   ├─ Provider addresses suspected conditions
│   ├─ Documents clinical findings
│   ├─ Coder validates documentation
│   └─ Codes entered same day
├─ Duration: 15-30 minutes (during visit)
└─ Output: Documented diagnoses + codes same day

PHASE 3: POST-VISIT VALIDATION
├─ When: Within 24-48 hours post-visit
├─ Who: Coders, clinical validators
├─ What: Final diagnosis confirmation
│   ├─ MEAT criteria verification
│   ├─ Documentation completeness check
│   ├─ Code accuracy validation
│   └─ Quality assurance review
├─ Duration: 1-2 hours per chart
└─ Output: Validated diagnosis codes ready to submit

PHASE 4: CLAIMS SUBMISSION
├─ When: 24-48 hours post-encounter
├─ Who: Billing/Revenue cycle
├─ What: Submit validated claims
│   ├─ No amendments needed (rare)
│   ├─ Strong documentation trail
│   ├─ First-pass accuracy 80-90%
│   └─ Audit-ready from day one
├─ Duration: Hours to 1-2 days
└─ Output: Clean claims submitted promptly

PHASE 5: CASH RECEIPT
├─ When: 8-12 weeks post-encounter (2-3 months)
├─ Who: Finance, Revenue Cycle
├─ What: Payment through Initial Run or Midyear
│   ├─ September Initial Run (month 8-10)
│   ├─ March Midyear Run (month 10-12)
│   └─ Faster payment than retrospective
├─ Duration: Standard payment processing
└─ Output: Payment receipt with strong compliance positioning

AUDIT RISK: LOW-MODERATE (Time-of-care documentation strong defense)
```

---

### PROSPECTIVE WORKFLOW

```
Timeline: Before/At Patient Encounter

PHASE 1: MEMBER ANALYTICS
├─ When: Continuous (real-time feeds)
├─ Who: AI/Analytics platform, automated
├─ What: Suspect condition identification
│   ├─ Medication analysis
│   ├─ Claims pattern analysis
│   ├─ Lab/test result review
│   ├─ Prior diagnosis reconciliation
│   └─ Alerts generated automatically
├─ Duration: Minutes (continuous)
└─ Output: Real-time suspect list by member

PHASE 2: PRE-VISIT PREPARATION
├─ When: 1-2 days before (or morning of visit)
├─ Who: CDI team, primary care
├─ What: Prioritized action list for visit
│   ├─ Suspect conditions listed
│   ├─ Documentation gaps highlighted
│   ├─ Care gaps identified
│   ├─ Provider education/reminders
│   └─ EHR alert integration
├─ Duration: 15-30 minutes (team review)
└─ Output: Provider-ready intervention checklist

PHASE 3: POINT-OF-CARE CODING
├─ When: During or immediately after encounter
├─ Who: Provider + optional coder guidance
├─ What: Real-time clinical documentation
│   ├─ Provider reviews suspect list
│   ├─ Documents conditions found
│   ├─ System suggests appropriate codes
│   ├─ Provider selects/confirms codes
│   └─ Codes available immediately
├─ Duration: 5-15 minutes (integrated to workflow)
└─ Output: Real-time diagnosis documentation + codes

PHASE 4: AUTOMATED VALIDATION
├─ When: Same day post-encounter
├─ Who: AI system + coder review (minimal)
├─ What: Compliance and accuracy check
│   ├─ MEAT criteria validation (automated)
│   ├─ Documentation completeness scoring
│   ├─ Code appropriateness verification
│   ├─ Outlier flagging for manual review
│   └─ 98% handled without human intervention
├─ Duration: Minutes (automated)
└─ Output: Validated codes ready for claims

PHASE 5: CLAIMS SUBMISSION
├─ When: Next business day (immediate)
├─ Who: Automated billing system
├─ What: Clean claims generation
│   ├─ No back-and-forth needed
│   ├─ Documentation in chart
│   ├─ Audit trail complete
│   └─ Compliance-ready
├─ Duration: Automated (hours)
└─ Output: Claims submitted with confidence

PHASE 6: CASH RECEIPT
├─ When: 8-12 weeks post-encounter (2-3 months)
├─ Who: Finance, Revenue Cycle
├─ What: Fastest payment cycle
│   ├─ September Initial Run (month 6-8)
│   ├─ March Midyear Run (month 9-10)
│   └─ Payment recognized early in contract year
├─ Duration: Standard payment processing
└─ Output: Accelerated cash flow vs. retrospective

AUDIT RISK: LOWEST (Point-of-care documentation, clean claims, automated validation trail)
```

---

## DETAILED COMPARISON TABLE

### Process Characteristics

| Characteristic | Retrospective | Concurrent | Prospective |
|----------------|---------------|-----------|-------------|
| **Timing Relative to Care** | 2-6 months after | Same day as/immediately after | Before/during visit |
| **Documentation Defensibility** | Moderate (back-dated) | Good (near-concurrent) | Excellent (point-of-care) |
| **Provider Burden** | High (queries, reviews) | Moderate (feedback loops) | Low (integrated alerts) |
| **Data Source** | Medical records only | Medical records + documentation | Claims + records + analytics |
| **MEAT Criteria Proof** | Difficult (post-visit) | Easier (recent memory) | Easiest (present during visit) |
| **Time to Cash Receipt** | 12-36 months | 8-10 months | 6-9 months |
| **Amendment Frequency** | High (20-30%) | Low (5-10%) | Minimal (<1%) |
| **First-Pass Accuracy** | 65-75% | 80-90% | 90%+ |
| **Provider Satisfaction** | Low (disruptive queries) | High (real-time feedback) | Highest (integrated, no queries) |
| **Coder Efficiency** | Low (time-consuming review) | Moderate (real-time validation) | High (automated mostly) |
| **RADV Audit Defense** | Weak (pattern concerns) | Strong (time-of-care docs) | Strongest (integrated trail) |

---

### Financial Comparison

| Financial Metric | Retrospective | Concurrent | Prospective |
|------------------|---------------|-----------|-------------|
| **Revenue per Member** | $1,500-$2,500 | $2,300-$2,400 | $2,500+ |
| **Implementation Cost** | $265K-$750K | $350K-$600K | $205K-$625K |
| **Annual Operating Cost** | $255K-$715K | $200K-$400K | $115K-$345K |
| **Month to Break-Even** | <1 month | <1 month | <1 month |
| **Average Cash Flow Lag** | 24 months | 8-10 months | 6-9 months |
| **Year 1 ROI** | 52:1-245:1 | 89:1-260:1 | 100:1-543:1 |
| **Year 2+ ROI** | 52:1-245:1 | 110:1-290:1 | 181:1-543:1 |
| **Working Capital Impact** | Negative | Neutral | Positive |
| **5-Year NPV** | $226M | $261M | $281M |

---

### Operational Comparison

| Operational Factor | Retrospective | Concurrent | Prospective |
|-------------------|---------------|-----------|-------------|
| **Staff FTE Required** | 2-3 coders | 1-2 coders + CDI | 0.5 FTE training (existing staff) |
| **EHR Integration Required** | Minimal | Essential | Essential |
| **Training Duration** | 2-4 weeks | 3-6 weeks | 4-8 weeks |
| **Ongoing Training Needs** | Low | Moderate | Moderate |
| **System Complexity** | Low | High | Very High |
| **Data Governance Requirements** | Moderate | High | Very High |
| **Provider IT Skills Needed** | None | Moderate | Moderate |
| **Change Management Effort** | Low | High | Very High |
| **Ongoing Optimization Needs** | Low | Moderate | High (continuous improvement) |

---

### Quality & Compliance Comparison

| Quality/Compliance Factor | Retrospective | Concurrent | Prospective |
|--------------------------|---------------|-----------|-------------|
| **Documentation Timing Strength** | Weak | Strong | Excellent |
| **MEAT Criteria Proof** | Difficult | Easy | Natural/automatic |
| **Coding Accuracy Rate** | 65-75% | 80-90% | 90%+ |
| **Amendment/Correction Rate** | 20-30% | 5-10% | <1% |
| **RADV Audit Selection Probability** | 25-30% | 20-25% | 15-20% |
| **Expected Recoupment if Audited** | 10-15% | 5-8% | 3-5% |
| **Audit Risk Score (1-10)** | 8 | 5 | 2 |
| **Compliance Culture Impact** | Negative (reactive) | Neutral | Positive (proactive) |

---

## WORKFLOW VOLUME & THROUGHPUT COMPARISON

### Processing Capacity (per FTE Coder per Year)

```
RETROSPECTIVE:
  Charts reviewed per year: 1,200-1,500 charts
  Time per chart: 30-45 minutes
  Quality review time: 10-15 minutes per chart
  Queries sent: 300-400 per year
  Query response rate: 70-80%
  ════════════════════════════════════════
  Annual HCC captures: 800-1,200
  Revenue impact: $1.2M-$3M per FTE per year
  
  With AI assistance:
  Time per chart: 10 minutes (3-4X improvement)
  Charts reviewed per year: 3,600-4,500
  Annual HCC captures: 2,400-3,600
  Revenue impact: $3.6M-$9M per FTE per year

CONCURRENT:
  Encounters processed per year: 8,000-12,000
  Time per encounter validation: 5-10 minutes
  Real-time review: 2-3 minutes
  Post-validation: 2-3 minutes
  ════════════════════════════════════════
  Validation accuracy: 80-90% on first pass
  Revenue impact: $2M-$4M per FTE per year
  
  Note: Coders + CDI team collaboration
  (Distributed across team, not per coder)

PROSPECTIVE:
  Automated alerts processed: 25,000-50,000+ per year
  Human review time: <1 minute per alert (filtering)
  Manual validation rate: 5-10% (outliers only)
  ════════════════════════════════════════
  Documentation triggered: 10,000-15,000+
  Validation accuracy: 95%+ (mostly automated)
  Revenue impact: $4M-$8M per 0.5 FTE per year
  
  Note: 0.5 FTE can manage entire 25K member population
  (Leverages automation, not manual effort)
```

---

## MEMBER EXPERIENCE COMPARISON

### Patient/Member Impact

| Factor | Retrospective | Concurrent | Prospective |
|--------|---------------|-----------|-------------|
| **Visit Experience** | No change | Enhanced (real-time help) | Enhanced (preventive focus) |
| **Documentation Quality** | No impact | Improved immediately | Improved over time |
| **Care Continuity** | No change | Better (gaps caught early) | Best (proactive outreach) |
| **Care Coordination** | No change | Moderate | Excellent (integrated) |
| **Quality Metrics Impact** | Minimal | Moderate | Excellent |
| **Stars Performance** | Minimal | Moderate | Excellent |
| **Member Satisfaction** | No change | Improved | Improved |
| **Health Outcomes** | No change | Slight improvement | Improvement likely |

---

## PROVIDER EXPERIENCE COMPARISON

### Physician/Provider Perspective

```
RETROSPECTIVE WORKFLOW:
┌─────────────────────────────────────────┐
│ Provider Perspective:                   │
├─────────────────────────────────────────┤
│ ✗ Unexpected queries weeks later        │
│ ✗ Distracted by requests for old visits │
│ ✗ No context on why codes questioned    │
│ ✗ Defensive posture (feels audited)     │
│ ✗ High administrative burden            │
│ ✗ Low engagement with RAF process       │
│ ✓ Minimal change to existing workflow   │
│                                         │
│ Satisfaction: Low (30-40%)              │
└─────────────────────────────────────────┘

CONCURRENT WORKFLOW:
┌─────────────────────────────────────────┐
│ Provider Perspective:                   │
├─────────────────────────────────────────┤
│ ✓ Real-time feedback during visit       │
│ ✓ Can address gaps immediately          │
│ ✓ Better documentation outcomes         │
│ ✓ Feels supported (not audited)         │
│ ✓ Moderate workflow integration         │
│ ✓ Collaborative with coding team        │
│ ~ Some workflow change required         │
│                                         │
│ Satisfaction: Moderate-Good (60-75%)    │
└─────────────────────────────────────────┘

PROSPECTIVE WORKFLOW:
┌─────────────────────────────────────────┐
│ Provider Perspective:                   │
├─────────────────────────────────────────┤
│ ✓ Helpful alerts at right time          │
│ ✓ Flags gaps before patient leaves      │
│ ✓ Integrated into EHR naturally         │
│ ✓ Educates on best practices            │
│ ✓ Improves care quality directly        │
│ ✓ Minimal extra documentation burden    │
│ ✓ Partnership model (not policing)      │
│                                         │
│ Satisfaction: High (75-85%)             │
└─────────────────────────────────────────┘
```

---

## DECISION TREE: WORKFLOW SELECTION

```
                        START: Choose RAF Workflow
                               |
                        ________v________
                       |                 |
                    Existing EHR?        No
                       |                 |
                      Yes                v
                       |           Consider
                       |         Upgrading EHR
                       |           First
                       v
                  Budget for
                  Integration?
                       |
        _______________v_______________
       |              No              |
       v                              v
    Tight budget             Moderate-High budget
       |                          |
       v                          v
RETROSPECTIVE-ONLY         Provider Adoption
  (if must choose)           Feasibility?
  But consider:                   |
  • Slower cash flow     __________|__________
  • Higher RADV risk     |                  |
  • Legacy approach    High                Low
    not ideal            |                  |
                         v                  v
                    PROSPECTIVE-        CONCURRENT
                      ONLY            or HYBRID
                        |              (if gradual
                        |              rollout needed)
                        |
                  Consider adding
                  RETROSPECTIVE
                  for specialty
                  conditions
                  (HYBRID approach)
```

---

## TRANSITION STRATEGIES: Moving Between Approaches

### From Retrospective to Prospective

```
PHASE 1: ASSESSMENT (Month 1-2)
├─ Evaluate current program performance
├─ Assess EHR integration capability
├─ Survey provider adoption readiness
├─ Identify staff reallocation options
└─ Calculate financial impact

PHASE 2: PILOT (Month 3-6)
├─ Select high-engagement primary care group
├─ Implement prospective platform with limited subset
├─ Run parallel retrospective program
├─ Measure prospective capture rates vs. baseline
└─ Gather provider feedback for optimization

PHASE 3: SCALE (Month 7-12)
├─ Expand to additional specialties (20-30% population)
├─ Transition retrospective team (retrain for support roles)
├─ Integrate prospective + retrospective workflows
├─ Establish governance for method separation
└─ Measure combined program performance

PHASE 4: OPTIMIZE (Month 13+)
├─ Full prospective deployment
├─ Retrospective becomes supplemental/specialty focus
├─ Rebalance staffing (reduce retrospective FTE)
├─ Achieve 10:1+ ROI run-rate
└─ Continuous improvement cycles

Timeline: 12-18 months for smooth transition
Cost: $50K-$200K additional for parallel running
Risk: Managed (testing before full transition)
```

### From Either Approach to Hybrid

```
HYBRID CONFIGURATION:

Prospective Tier (70% of population):
  └─ Routine primary/ambulatory care
  └─ Point-of-care coding
  └─ Real-time alert system
  └─ Monthly updates/continuous

Concurrent Tier (20% of population):
  └─ Complex/high-risk encounters
  └─ Post-visit validation
  └─ Real-time error prevention
  └─ Weekly review cycles

Retrospective Tier (10% of population):
  └─ Specialty conditions post-visit
  └─ Model transition recapture (V24→V28)
  └─ Outlier/variance analysis
  └─ Monthly review cycles

Integration Points:
  ├─ Shared suspect database
  ├─ Unified MEAT criteria validation
  ├─ Common code submission pathways
  ├─ Consolidated reporting/analytics
  └─ Unified quality standards

Expected Outcomes:
  ├─ Highest combined revenue capture
  ├─ Balanced cash flow timing
  ├─ Risk diversification
  ├─ Flexibility for optimization
  └─ Total ROI: 107:1-287:1
```

---

## COMMON PITFALLS BY APPROACH

### Retrospective Pitfalls

1. **Over-Reliance on Queries**
   - Problem: Heavy querying creates audit red flags
   - Solution: Limit queries to genuinely unclear documentation

2. **Amendment Clustering**
   - Problem: Bulk amendments before deadlines appear suspicious
   - Solution: Spread amendments across year, justify each one

3. **Documentation Timing Issues**
   - Problem: Back-dating diagnoses months after visit
   - Solution: Use addendums, not amendments; document reason

4. **Provider Fatigue**
   - Problem: Excessive queries damage relationships
   - Solution: Educate vs. query; focus on high-value opportunities

5. **Cash Flow Gap**
   - Problem: 12-36 month delay impacts working capital
   - Solution: Model prospective additions to fill gap

### Concurrent Pitfalls

1. **Over-Burden on Coders**
   - Problem: Real-time validation requires coder availability
   - Solution: Prioritize high-complexity encounters only

2. **EHR Integration Complexity**
   - Problem: Technical challenges in real-time workflows
   - Solution: Phased rollout, test thoroughly before scale

3. **Provider Friction from Feedback**
   - Problem: Real-time corrections feel like micro-management
   - Solution: Frame as support/education, not critique

4. **Quality Control at Scale**
   - Problem: Maintaining accuracy with high volume
   - Solution: Automated validation + sampling for manual QA

5. **Transition Logistics**
   - Problem: Moving from retrospective disrupts workflows
   - Solution: Parallel running period, gradual transition

### Prospective Pitfalls

1. **Alert Fatigue**
   - Problem: Too many suspects overwhelm providers
   - Solution: Precision filtering; prioritize high-confidence alerts

2. **False Positive Rates**
   - Problem: AI suggests diagnoses not clinically present
   - Solution: Hybrid AI (3X reduction in false positives)

3. **EHR Integration Challenges**
   - Problem: Custom API development expensive/complex
   - Solution: Use modern SaaS platforms with standard EHR APIs

4. **Provider Adoption Resistance**
   - Problem: Physicians skeptical of AI-driven suggestions
   - Solution: Education, transparent accuracy metrics, early wins

5. **System Complexity**
   - Problem: Requires sophisticated data flows and governance
   - Solution: Phased implementation, dedicated team initially

---

## SUMMARY SCORECARD

### Overall Rating by Approach

```
RETROSPECTIVE-ONLY: ★★★☆☆ (3/5 stars)
Pros:  Good ROI, proven approach, low upfront complexity
Cons:  Slow cash flow, high audit risk, provider burden
Use:   Small plans, legacy systems, budget constraints
Grade: ADEQUATE (but not optimal)

CONCURRENT REVIEW: ★★★★☆ (4/5 stars)
Pros:  High accuracy, audit defensible, provider feedback
Cons:  Requires EHR integration, operational complexity
Use:   Mid-size organizations, quality-focused plans
Grade: VERY GOOD (solid choice)

PROSPECTIVE-ONLY: ★★★★★ (5/5 stars)
Pros:  Best ROI, fastest cash flow, lowest audit risk
Cons:  Requires sophisticated platform, AI learning curve
Use:   Large organizations, modern IT, aggressive growth
Grade: EXCELLENT (best financial & compliance outcome)

HYBRID: ★★★★☆ (4.5/5 stars)
Pros:  Balanced approach, flexibility, risk diversification
Cons:  Most complex operationally, higher total costs
Use:   Competitive markets, mid-to-large organizations
Grade: VERY GOOD (practical, optimal balance)
```

---

**Document Prepared:** April 1, 2026  
**Intended Use:** Workflow selection, team training, process documentation  
**For Questions:** Refer to main research document RAF_Workflow_Research_2026.md

