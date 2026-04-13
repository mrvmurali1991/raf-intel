# RAF Intelligence Platform — Client Demo Walkthrough

## What is RAF Intelligence?

RAF Intelligence is a healthcare analytics platform that helps Medicare Advantage health plans and provider groups **maximize revenue accuracy** by ensuring every patient's conditions are properly documented, coded, and submitted to CMS.

In simple terms: **Medicare pays health plans based on how sick their patients are.** If a patient has Heart Failure, Diabetes, and Kidney Disease — but only Diabetes gets documented and coded — the plan loses tens of thousands of dollars per year. RAF Intelligence finds those gaps and helps close them.

---

## The Core Problem We Solve

| Without RAF Intelligence | With RAF Intelligence |
|---|---|
| Providers document conditions in free text notes, but forget to code them | AI reads clinical notes and flags missed conditions |
| Conditions documented last year aren't recaptured this year | Automated recapture gap detection alerts providers |
| No visibility into which providers are coding well vs. poorly | Provider scorecards rank documentation quality |
| Revenue leakage is invisible until year-end reconciliation | Real-time revenue opportunity dashboard shows dollar impact |
| Manual chart reviews cost $50-100 per chart | Automated analysis at a fraction of the cost |

---

## Step-by-Step Platform Walkthrough

We'll use a real patient — **Patricia Anderson** — to walk through every feature.

---

### STEP 1: Dashboard — The Command Center

**What you see:** A single-screen summary of your entire patient population.

| Metric | Value |
|---|---|
| Total Patients Managed | 15 |
| Patients Analyzed | 15 (100% coverage) |
| Average RAF Score | 1.28 |
| Revenue Opportunity | $32,166 in uncaptured revenue |

**AI-Powered Insights appear automatically:**

- **"27 Open Suspect Conditions Awaiting Review"** — These are conditions the AI found evidence for but haven't been officially coded yet. Estimated value: **$113,399/year**.
- **"4 High-Risk Patients Have Unreviewed Suspects"** — These patients (avg RAF 2.2) have open suspect conditions worth **$105,600**.
- **"Top Revenue Patient: $22,260 Gap for Patient #30"** — AI-calculated RAF is 2.275 vs. billed RAF of 0.42. That gap = $22,260/year in lost revenue for just ONE patient.
- **"5 CKD Stage Upgrade Opportunities"** — Patients whose kidney disease staging may be under-documented, worth **$15,000**.

> **Key takeaway for the client:** Within seconds of logging in, you see exactly how much money is being left on the table and where to focus first.

---

### STEP 2: Patient List — Find Any Patient Instantly

**What you see:** A searchable, sortable list of all patients with key information at a glance:

- Name, DOB, MRN, MBI (Medicare Beneficiary Identifier)
- Current RAF Score
- Insurance type
- Provider assignment

You can filter by risk level, provider, or condition. Click any patient to drill into their full clinical and financial profile.

---

### STEP 3: Patient Detail — Patricia Anderson (Patient #35)

**This is where the platform shines.** Every tab gives a different clinical and financial lens on this patient.

#### Patient Demographics

| Field | Value |
|---|---|
| Name | Patricia K. Anderson |
| DOB | August 25, 1957 (age 68) |
| Gender | Female |
| Race/Ethnicity | Asian, Non-Hispanic |
| Address | 6718 Gulf Fwy, Houston, TX 77017 |
| MRN | MRN-100035 |
| MBI | 7EG6-TE5-MK29 |
| Insurance | Medicare |
| Current RAF Score | **2.311** |

> A RAF score of 2.311 means CMS expects this patient to cost **2.3x the average Medicare beneficiary.** This drives approximately **$25,450/year** in capitation payments (2.311 x $11,015 base rate).

---

#### Tab: Encounters (5 visits)

The encounters tab shows every clinical visit with full provider details and clinical notes.

| Date | Type | Provider | Facility | Notes |
|---|---|---|---|---|
| Feb 8, 2026 | Lab Visit | Dr. Lisa Thompson | Downtown Health Center | BNP 450, down from 680. Continue current regimen. |
| Dec 2, 2025 | Follow-up | Dr. Lisa Thompson | Main Street Medical | CHF follow-up. BNP 450, eGFR stable. No med changes. Return 6 weeks. |
| Sep 8, 2025 | Annual Wellness Visit | Dr. David Park | Sunrise Health Clinic | Comprehensive AWV. Active: CHF, Afib, CKD Stage 4. Weight up 3 lbs, ankle swelling. 9 active meds reconciled. |
| Aug 26, 2025 | Follow-up | Dr. Michael Rivera | Main Street Medical | CHF follow-up with cardiology. |
| Jul 15, 2025 | Office Visit | Dr. Sarah Mitchell | Sunrise Health Clinic | Initial comprehensive assessment. |

> **Why this matters:** Each encounter is an opportunity to document and code conditions. The platform tracks which conditions were captured at each visit and which were missed.

---

#### Tab: Active Medications (12 medications)

| Medication | Dosage | Frequency | Purpose |
|---|---|---|---|
| Lisinopril | 10mg | Daily | ACE inhibitor for CHF |
| Carvedilol | 25mg | BID | Beta-blocker for CHF |
| Furosemide | 40mg | Daily | Loop diuretic (fluid management) |
| Spironolactone | 25mg | Daily | Aldosterone antagonist |
| Digoxin | 0.125mg | Daily | Heart rate control |
| Amiodarone | 200mg | Daily | Antiarrhythmic (Afib) |
| Apixaban | 5mg | BID | Blood thinner (stroke prevention) |
| Losartan | 100mg | Daily | Renal protection (CKD) |
| Sodium Bicarbonate | 650mg | BID | Acidosis correction (CKD) |
| Atorvastatin | 40mg | Daily | Cholesterol management |
| Aspirin | 81mg | Daily | Cardiovascular prophylaxis |
| Omeprazole | 20mg | Daily | Gastric protection |

> **Why this matters:** Medications are **evidence of conditions.** A patient on Amiodarone + Apixaban + Digoxin clearly has a cardiac arrhythmia. If that arrhythmia isn't coded, the AI flags it. This is one of the ways RAF Intelligence discovers suspect conditions.

---

#### Tab: Problem List (5 active conditions)

| Condition | ICD-10 | Since | HCC | Severity |
|---|---|---|---|---|
| Systolic Heart Failure | I50.20 | Aug 2023 | HCC 85 | Severe |
| Atrial Fibrillation | I48.91 | Jul 2024 | HCC 96 | Moderate |
| CKD Stage 4 | N18.4 | Dec 2023 | HCC 137 | Moderate |
| Hyperlipidemia | E78.5 | Aug 2022 | — | Mild |
| Essential Hypertension | I10 | May 2022 | — | Moderate |

> **Key insight:** 3 of 5 conditions map to HCCs (revenue-driving codes). Hyperlipidemia and Hypertension are common but do NOT drive RAF payment. The platform clearly shows which conditions matter financially.

---

#### Tab: Diagnoses (23 coded diagnoses across all encounters)

This shows every ICD-10 code submitted per encounter. Examples:

| Code | Description | HCC | Encounter Date |
|---|---|---|---|
| I50.43 | Acute on chronic combined CHF | HCC 85 | Feb 8, 2026 |
| N18.4 | CKD Stage 4 | HCC 137 | Feb 8, 2026 |
| I48.19 | Persistent Atrial Fibrillation | HCC 96 | Feb 8, 2026 |
| I50.22 | Chronic Systolic Heart Failure | HCC 85 | Dec 2, 2025 |
| I10 | Essential Hypertension | — | Dec 2, 2025 |
| K21.0 | GERD | — | Dec 2, 2025 |
| M54.5 | Low Back Pain | — | Feb 8, 2026 |

> **Key insight:** The platform shows which diagnoses carry HCC weight (revenue impact) and which don't. This helps coders and providers focus on what matters most.

---

### STEP 4: RAF Score Breakdown — Where the Money Is

This is the financial heart of the platform. For Patricia Anderson:

| Component | Score |
|---|---|
| **Demographic Score** (age 68, Female, Community) | 0.786 |
| **Disease Score** (5 HCCs) | 1.294 |
| **Interaction Score** (disease combinations) | 0.231 |
| **Total RAF Score** | **2.311** |

**Her 5 HCC conditions and their individual revenue impact:**

| HCC | Condition | Coefficient | Annual Revenue Impact |
|---|---|---|---|
| HCC 93 | Rheumatoid Arthritis | 0.617 | $6,794 |
| HCC 226 | Heart Failure | 0.360 | $3,965 |
| HCC 36 | Diabetes with Severe Complications | 0.346 | $3,811 |
| HCC 280 | COPD | 0.319 | $3,514 |
| HCC 238 | Heart Arrhythmias | 0.299 | $3,293 |

> **Total disease-driven revenue: ~$21,377/year** — this is ON TOP of the demographic base payment.

**MEAT Compliance Status** (Monitor, Evaluate, Assess, Treat):

CMS requires that each HCC condition is supported by MEAT documentation. The platform tracks this:

| HCC | M | E | A | T | Status |
|---|---|---|---|---|---|
| HCC 226 — Heart Failure | Yes | Yes | Yes | Yes | **Complete** |
| HCC 280 — COPD | Yes | Yes | Yes | No | Partial |
| HCC 93 — Rheumatoid Arthritis | Yes | No | Yes | No | Partial |
| HCC 36 — Diabetes | — | — | — | — | Missing |
| HCC 238 — Arrhythmias | — | — | — | — | Missing |

> **Why this matters:** Even if a condition is coded, CMS can **claw back** the payment if the chart doesn't show proper MEAT documentation. The platform flags exactly which elements are missing so providers can fix them at the next visit.

---

### STEP 5: Suspect Conditions — AI-Discovered Revenue Opportunities

This is where AI adds the most value. For Patricia Anderson, the platform found **3 suspect conditions** that are NOT currently coded but have clinical evidence:

| Suspect HCC | Condition | ICD-10 | Evidence Source | Confidence | Est. Revenue |
|---|---|---|---|---|---|
| HCC 55 | Major Depressive Disorder, Recurrent | F33.1 | Medication history | 79% | ~$4,000/yr |
| HCC 19 | Diabetes without Complications | E11.9 | Lab results | 78% | ~$2,500/yr |
| HCC 111 | Bacterial Pneumonia | J15.9 | Prior year diagnosis (not recaptured) | 76% | ~$3,000/yr |

**How the AI found these:**

1. **Depression (HCC 55):** The AI noticed medications in her profile consistent with depression treatment. If she's being treated for depression, it should be documented and coded.

2. **Diabetes (HCC 19):** Lab results suggest diabetes indicators. Clinical notes reference symptoms. But no diabetes diagnosis is on her current problem list.

3. **Pneumonia (HCC 111):** This diagnosis was coded in a prior year but was NOT recaptured in the current measurement year. CMS requires annual recapture of chronic conditions — missing it means losing that revenue for the entire year.

> **Total potential revenue from suspects: ~$9,500/year** — for just ONE patient.

**The workflow:** A provider or coder reviews each suspect, clicks "Accept" (which queues it for coding) or "Dismiss" (with a reason). This creates an audit trail for compliance.

---

### STEP 6: RAF Score Calculator (Crosswalk Tool)

A standalone calculator that lets anyone instantly score a set of ICD-10 codes.

**Example:** Enter codes I50.30, E11.22, J44.9, N18.6 for a 65-year-old male:

| Component | RAF Score | Annual Payment |
|---|---|---|
| Demographic (Male, 65-69) | 0.332 | $3,657 |
| HCC 226 — Heart Failure | 0.360 | $3,965 |
| HCC 37 — Diabetes w/ Chronic Complications | 0.166 | $1,828 |
| HCC 280 — COPD | 0.319 | $3,514 |
| HCC 326 — CKD Stage 5 | 0.815 | $8,977 |
| Diabetes + HF Interaction | 0.112 | $1,234 |
| HF + Chronic Lung Interaction | 0.078 | $859 |
| HF + Kidney Interaction | 0.176 | $1,939 |
| **Grand Total** | **2.358** | **$25,969** |
| After Normalization | 1.967 | $21,668 |
| **Final Payment RAF** | **1.851** | **$20,385** |

> **Use case:** Before a patient visit, a provider can see exactly how much each condition is worth. After a visit, a coder can verify the financial impact of their coding choices.

---

### STEP 7: Provider Scorecards & Leaderboard

The platform ranks providers by their documentation quality and coding effectiveness.

| Rank | Provider | Specialty | Patients | Avg RAF | HCC Capture Rate | Revenue Opportunity |
|---|---|---|---|---|---|---|
| 1 | Dr. Sarah Mitchell | Internal Medicine | 9 | 1.72 | 80.8% | $24,560 |
| 2 | Dr. Michael Rivera | Cardiology | 5 | 1.39 | 72.2% | $18,700 |
| 3 | Dr. David Park | Family Medicine | — | — | — | — |

**What this tells you:**
- Dr. Mitchell manages the most patients and has the highest capture rate (80.8%), but still has $24,560 in uncaptured revenue
- Dr. Rivera's lower capture rate (72.2%) suggests documentation gaps — targeted education could close those gaps
- The leaderboard creates healthy competition and accountability

---

### STEP 8: Reports & Analytics

| Report | What It Shows |
|---|---|
| **Revenue Opportunity** | Total gap between billed and AI-calculated RAF across all patients ($32,166 identified) |
| **HCC Distribution** | Which conditions are most prevalent — Diabetes (9 patients), Heart Failure (4), COPD (4), CKD (3) |
| **Recapture Gaps** | Conditions from prior years not yet documented this year |
| **Suspects Summary** | Pipeline of AI-identified conditions awaiting review |
| **Data Completeness** | How complete is the clinical data for each patient |

---

## How It All Connects — The Revenue Recovery Workflow

```
  EMR/EHR Data          RAF Intelligence              Revenue Impact
  ============          ================              ==============

  Patient visits    -->  AI analyzes notes,       -->  Finds $113,399 in
  Clinical notes         medications, labs,            missed revenue across
  Lab results            prior year claims             15 patients
  Medications                    |
                                 v
                         Flags suspect HCCs      -->  Provider reviews &
                         with confidence scores        accepts/dismisses
                                 |
                                 v
                         Checks MEAT compliance  -->  Ensures documentation
                         for each HCC                  survives CMS audit
                                 |
                                 v
                         Provider scorecards     -->  Drives behavior change
                         & leaderboards                and accountability
                                 |
                                 v
                         Accurate RAF submitted  -->  Maximum legitimate
                         to CMS                        reimbursement captured
```

---

## Key Numbers for Your Organization

| Metric | Value |
|---|---|
| Average revenue recovered per patient | ~$2,144/year |
| Suspect conditions identified by AI | 27 across 14 patients |
| Estimated total uncaptured revenue | $113,399/year |
| MEAT compliance gaps found | Tracked per HCC per patient |
| Provider documentation improvement | Measurable via scorecards |
| Time saved vs. manual chart review | 80-90% reduction |

---

## Why RAF Intelligence?

1. **Automated, not manual** — AI reads every note, every med, every lab. No human reviewer can match that consistency.
2. **Compliant by design** — MEAT tracking, audit trails, and evidence-based suspect identification. No upcoding.
3. **Real-time visibility** — Don't wait until year-end to find out you missed revenue. See it today.
4. **Provider-friendly** — Actionable insights at the point of care, not just reports for the back office.
5. **Measurable ROI** — Every dollar of uncaptured revenue is tracked and attributable.

---

*Document prepared for client demonstration — RAF Intelligence Platform, April 2026*
