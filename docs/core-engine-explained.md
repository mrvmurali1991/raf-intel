# RAF Intelligence — Core Engine Explained

## What Happens After AI Finds the Diagnoses

```
Gemini outputs 3 diagnoses:
  E11.22 → Diabetes with CKD
  I50.30 → Heart Failure
  N18.32 → CKD Stage 3b

Then 4 engines process them:
```

---

## Engine 1: hccinfhir (RAF Score Calculator)

**What it does:** Converts ICD-10 codes into a dollar value

```
INPUT:                          OUTPUT:
3 ICD-10 codes                  RAF Score = 1.337
+ Patient age (73)
+ Patient sex (Male)

HOW:
  Step A: Map ICD → HCC
    E11.22 → HCC 37 (Diabetes complicated)
    I50.30 → HCC 226 (Heart failure)
    N18.32 → HCC 328 (CKD)

  Step B: Look up CMS coefficient for each HCC
    Demographic (73M):     0.396
    HCC 37 (Diabetes):    +0.166
    HCC 226 (CHF):        +0.360
    HCC 328 (CKD):        +0.127

  Step C: Check interactions (condition combos)
    Diabetes + Heart Failure = +0.112
    Heart Failure + CKD      = +0.176

  Step D: Add it all up
    0.396 + 0.166 + 0.360 + 0.127 + 0.112 + 0.176 = 1.337

RESULT: RAF Score = 1.337
        This patient costs 33.7% MORE than average Medicare patient
        CMS pays the health plan ~$13,370/year for this patient
```

---

## Engine 2: Suspect Condition Engine

**What it does:** Finds conditions that SHOULD be coded but AREN'T

```
INPUT:                          OUTPUT:
Patient medications             List of suspect conditions
Patient lab results             with evidence
Current billing codes

HOW:

  Check 1: MEDICATION SCAN
    Patient takes furosemide (diuretic)
    → Furosemide is for Heart Failure
    → Is Heart Failure coded? YES → OK

    Patient takes apixaban (blood thinner)
    → Apixaban is for Atrial Fibrillation
    → Is AFib coded? NO → SUSPECT!

    ⚠️ SUSPECT: Atrial Fibrillation
       Evidence: Patient on apixaban 5mg BID
       Suggested ICD: I48.91
       Potential HCC: 238

  Check 2: LAB SCAN
    eGFR = 41
    → eGFR < 60 means CKD Stage 3+
    → Is CKD coded? NO → SUSPECT!

    ⚠️ SUSPECT: CKD Stage 3b
       Evidence: eGFR 41 mL/min
       Suggested ICD: N18.32
       Potential HCC: 328

  Check 3: HISTORICAL SCAN
    Last year patient had HCC 85 (CHF)
    → Is CHF coded this year? YES → OK

    Last year patient had HCC 96 (AFib)
    → Is AFib coded this year? NO → NEEDS RECAPTURE!

RESULT: 2 suspect conditions found
        Estimated revenue impact: +$3,000/year
```

---

## Engine 3: MEAT Evidence Storage

**What it does:** Stores proof that each diagnosis is documented (for CMS audits)

```
INPUT:                          OUTPUT:
Gemini's MEAT extraction        Audit-ready evidence trail
per diagnosis                   per HCC code

HOW:

  For HCC 37 (Diabetes):
  ┌─────────────────────────────────────────────────┐
  │ M (Monitor):  "HbA1c 8.2%, monitored quarterly" │
  │ E (Evaluate): "A1c improved from 8.9%"          │
  │ A (Assess):   "T2DM with hyperglycemia"         │
  │ T (Treat):    "Metformin 1000mg BID, insulin"    │
  │                                                   │
  │ Score: 4/4 ✅ COMPLETE                           │
  │ Encounter: #6, Date: 2025-09-05                  │
  │ Provider: Dr. Smith                               │
  └─────────────────────────────────────────────────┘

  For HCC 226 (CHF):
  ┌─────────────────────────────────────────────────┐
  │ M (Monitor):  "BNP 310, Weight 192 stable"      │
  │ E (Evaluate): "Bibasilar crackles, edema"        │
  │ A (Assess):   "NYHA class II, euvolemic"         │
  │ T (Treat):    "Furosemide 40mg, lisinopril 10mg" │
  │                                                   │
  │ Score: 4/4 ✅ COMPLETE                           │
  └─────────────────────────────────────────────────┘

  For HCC 328 (CKD):
  ┌─────────────────────────────────────────────────┐
  │ M (Monitor):  "Creatinine 1.8, eGFR 41"         │
  │ E (Evaluate): "Consistent with CKD 3b"           │
  │ A (Assess):   "On ACEi, renal protective"        │
  │ T (Treat):    "Lisinopril, nephrology referral"   │
  │                                                   │
  │ Score: 4/4 ✅ COMPLETE                           │
  └─────────────────────────────────────────────────┘

WHY THIS MATTERS:
  If CMS audits this patient:
  → Every HCC has documented MEAT evidence
  → Exact text quotes from the clinical note
  → Linked to specific encounter + date
  → Ready to defend in RADV audit
```

---

## Engine 4: Confidence Router

**What it does:** Decides if AI result can be auto-accepted or needs human review

```
INPUT:                          OUTPUT:
MedCAT entities                 Routing decision:
Gemini diagnoses                AUTO-ACCEPT or
Assertion results               HUMAN-REVIEW or
MEAT scores                     FULL-AUDIT

HOW:

  Score each diagnosis on 6 signals:

  ┌──────────────────────────────────────────────┐
  │ Signal              Weight  Score  Weighted   │
  │──────────────────────────────────────────────│
  │ Gemini confidence    0.30   1.00   0.300     │
  │ MedCAT agreement     0.25   0.85   0.213     │
  │ In candidate list    0.20   1.00   0.200     │
  │ MEAT completeness    0.15   1.00   0.150     │
  │ Negation agreement   0.05   1.00   0.050     │
  │ ICD-10 valid         0.05   1.00   0.050     │
  │──────────────────────────────────────────────│
  │ TOTAL                1.00          0.963     │
  └──────────────────────────────────────────────┘

  Routing rules:
  ┌────────────────────────────────────────────────┐
  │ Score ≥ 0.95 AND all agree  → AUTO-ACCEPT     │
  │   → Goes directly to billing (60-70% of cases) │
  │                                                 │
  │ Score 0.80-0.94             → HUMAN REVIEW     │
  │   → Coder reviews in 2 min (25% of cases)      │
  │                                                 │
  │ Score < 0.80 OR disagree    → FULL AUDIT       │
  │   → Full manual review (10% of cases)           │
  └────────────────────────────────────────────────┘

RESULT: This patient → HUMAN REVIEW (score 0.963)
        Reason: MedCAT and Gemini use different code specificity
```

---

## All 4 Engines Together

```
AI Pipeline finds:
  E11.22 (Diabetes + CKD)
  I50.30 (Heart Failure)
  N18.32 (CKD Stage 3b)
       │
       ▼
┌─── ENGINE 1: hccinfhir ───────────────────────┐
│  E11.22 → HCC 37   coefficient 0.166          │
│  I50.30 → HCC 226  coefficient 0.360          │
│  N18.32 → HCC 328  coefficient 0.127          │
│  Interactions: DM+HF=0.112, HF+CKD=0.176     │
│  Demographics: 73M = 0.396                     │
│                                                 │
│  RAF SCORE = 1.337                             │
└────────────────────────┬──────────────────────┘
                         │
                         ▼
┌─── ENGINE 2: Suspect Engine ──────────────────┐
│  Medications: metformin, insulin, furosemide,  │
│               lisinopril                       │
│  Labs: eGFR 41, A1c 8.2, BNP 310             │
│                                                │
│  Billing has: E11.65, I50.32 (only 2 codes)   │
│  AI found:    E11.22, I50.30, N18.32 (3 codes)│
│                                                │
│  ⚠️ SUSPECT: CKD not billed!                  │
│  Revenue gap: +$3,030/year                     │
└────────────────────────┬──────────────────────┘
                         │
                         ▼
┌─── ENGINE 3: MEAT Storage ────────────────────┐
│  HCC 37:  MEAT 4/4 ✅ (quoted from note)      │
│  HCC 226: MEAT 4/4 ✅ (quoted from note)      │
│  HCC 328: MEAT 4/4 ✅ (quoted from note)      │
│                                                │
│  All evidence stored in database               │
│  Ready for RADV audit PDF generation           │
└────────────────────────┬──────────────────────┘
                         │
                         ▼
┌─── ENGINE 4: Confidence Router ───────────────┐
│  Overall score: 0.963                          │
│  MedCAT + Gemini agree: YES                    │
│  MEAT complete: YES (12/12)                    │
│  All codes valid: YES                          │
│                                                │
│  ROUTING: HUMAN REVIEW                         │
│  (Provider confirms in dashboard, 2 min)       │
└───────────────────────────────────────────────┘
```

---

## For the Client

> "After our AI extracts diagnoses from clinical notes, four specialized engines process the results:
>
> 1. **RAF Calculator** converts diagnoses to a dollar value using the exact CMS formula
> 2. **Suspect Engine** cross-references medications and labs to find undocumented conditions
> 3. **MEAT Storage** saves audit-ready evidence linking every code to the clinical documentation
> 4. **Confidence Router** decides if the result can be auto-accepted or needs a human review
>
> The result: accurate RAF scores, discovered revenue gaps, audit-proof documentation, and intelligent human-in-the-loop workflow — all in under 30 seconds."
