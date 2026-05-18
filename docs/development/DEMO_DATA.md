# Demo Data — Realistic 50-Patient Longitudinal Dataset

## Purpose

This document describes the synthetic dataset seeded by
`backend/scripts/seed_realistic_demo.py` for CMO / MA-plan executive demos.
All data is HIPAA Safe Harbor synthetic — no real patient names, no real MBIs,
no real addresses.

---

## What Gets Seeded

| Category | Volume | Notes |
|---|---|---|
| Patients | 50 | Age / sex / race / geo per MA-plan distribution |
| Encounters | ~500-600 | 4-12/year x 2 years, PCP + specialists |
| Lab results | ~352 | Quarterly A1c + CMP + lipid + UACR for 11 diabetic pts |
| HCC rows | ~150-200 | V28 codes, prior-year + current-year |
| Open suspects | ~12-15 | Dropped HCCs not yet recaptured this year |
| Outreach messages | 8 | Mix of sent / failed / queued |
| Chart-chase requests | 3 | pending / in_progress / completed |
| RADV audit run | 1 | 7 sampled patients, mixed decisions |

### Patient Demographics

- Age distribution: 18% 50-64, 45% 65-74, 30% 75-84, 7% 85+
- Sex: 52% Female, 48% Male
- Race/ethnicity: CMS MA approximate mix (58% White NH, 12% Black NH, 14% Hispanic, 5% Asian, 11% other)
- Cities: New York, Los Angeles, Chicago, Dallas, Atlanta (5 zipcodes each)
- Insurance: 80% MA HMO, 15% MA PPO, 5% D-SNP (dual eligible)

### Condition Distribution

| Bundle | % | Key HCCs | Dropped HCC suspect |
|---|---|---|---|
| DM2 only | 10% | HCC 37 | — |
| DM2 + CHF | 8% | HCC 37, 85 | CHF (85) |
| DM2 + CKD | 4% | HCC 37, 138 | CKD stage 3 (138) |
| CHF only | 15% | HCC 85 | — |
| COPD | 12% | HCC 112 | COPD exacerbation (112) |
| Depression | 10% | HCC 155 | — |
| AFib | 8% | HCC 96 | AFib not coded (96) |
| Complex (DM+CHF+CKD+AFib) | 8% | HCC 37, 85, 137, 96 | CKD stage 4 (137) |
| Dementia | 5% | HCC 52 | — |
| Healthy / preventive | 20% | HCC 0 | — |

### Quality Measure Tiers (Diabetic Patients)

| Tier | A1c | % | HEDIS CDC Status |
|---|---|---|---|
| Controlled | <8.0% | 30% | Met — closed gap |
| Borderline | 8.0-9.0% | 40% | Near miss |
| Failed | >9.0% | 30% | Open gap — high-value target |

### Lab History Pattern (Diabetic Patients)

Each diabetic patient receives 4 quarterly labs per year (8 total over 2 years):
- HbA1c (LOINC 4548-4) — trended realistically; some improving, some deteriorating
- Creatinine (LOINC 2160-0)
- LDL Cholesterol (LOINC 13457-7)
- UACR (LOINC 9318-7)

---

## Running the Seeder

```bash
# Standard run — 50 patients, 2 years history, tenant 1
python backend/scripts/seed_realistic_demo.py --tenant 1 --patients 50 --years 2

# Environment variables for non-default DB config
export RAF_DB_HOST=127.0.0.1
export RAF_DB_PORT=3306
export RAF_DB_USER=root
export RAF_DB_PASSWORD=root
export RAF_DB_NAME=raf_intelligence
export OPENEMR_DB_HOST=127.0.0.1
export OPENEMR_DB_PORT=3309
python backend/scripts/seed_realistic_demo.py --tenant 1
```

The script is **idempotent** — re-running uses `ON DUPLICATE KEY UPDATE` and
`INSERT IGNORE` everywhere. Existing rows are updated in-place; no duplicate
patients or encounters are created.

---

## Demo Script — Executive Walk-Through

### Opening Frame: Population Dashboard

**What to show:** Heatmap with 50 patients spread across NYC, LA, Chicago, Dallas, Atlanta.

**Talking point:** "This is a 5,000-member MA plan — we're showing you 50 as a representative
cohort. The dots are real geo-distribution you'd see in a typical HMO book of business."

---

### Scene 1: High-RAF Complex Patient

**Patient to demo:** Find the "Complex" bundle patient with the highest RAF score
(DM2 + Systolic CHF + CKD stage 4 + AFib). Expected RAF: 1.45-1.85.

**HCCs present:** 37 (diabetes), 85 (CHF), 137 (CKD 4), 96 (AFib)

**Dollar value to point at:** At $10,000 base rate:
- With all 4 HCCs: ~$14,500-$18,500 per-member payment
- With dropped CKD (HCC 137 suspect open): gap = ~$2,900/year revenue risk

**Demo script:**
> "Every year CMS recalculates payment. If CKD stage 4 drops off because
> we didn't recapture the code, that is a $2,900 revenue hole per member.
> RAF Intelligence flagged it before the year closed."

---

### Scene 2: HEDIS Gap Closure — The 30% Failing A1c

**What to show:** Filter diabetic patients → sort by A1c → show 30% with A1c > 9%.

**Labs to highlight:** Trending A1c from 2 years back — show the deteriorating trajectory.

**Outreach context:** 8 outreach messages seeded — show 3 queued (next in line),
2 sent, 2 failed (no answer), 1 opted-out.

**Talking point:** "We're not just flagging a gap. We're showing the 2-year clinical
trajectory so the care manager knows this patient has been deteriorating for 6 quarters,
not just one bad reading."

---

### Scene 3: Chart Chase in Progress

**What to show:** Chart-chase board — 3 requests:
1. "Westside Cardiology" — in_progress — CHF recapture
2. "Downtown Medical Group" — pending — DM2 + CKD
3. "Northside Family Care" — completed

**Talking point:** "This is the chart-chase workflow. When the AI detects a dropped HCC
we didn't code, it auto-generates the fax request to the facility. Once charts arrive,
the coder worklist is pre-populated with the suspect code and supporting evidence."

---

### Scene 4: RADV Readiness

**What to show:** RADV audit run — 7 sampled patients.

**Outcome distribution seeded:**
- 3 defensible (documentation solid)
- 2 needs remediation (documentation gaps — fixable)
- 1 undefensible (extrapolated exposure: $3,450)
- 1 pending review

**Estimated total exposure shown:** ~$6,871 across the sample of 7.

**Talking point:** "In a real RADV audit, CMS extrapolates that error rate across
your entire book. If 14% of sampled HCCs are undefensible, the repayment demand
is 14% of total capitation. We surface this before CMS knocks."

---

### Scene 5: V24 vs V28 Delta (close the demo)

**What to show:** Filter "COPD" patients — show HCC 112 (V28) vs COPD coding prior year.

**Talking point:** "The V28 model restructured COPD. Under V24 an exacerbation
earned HCC 111 at 0.335 coefficient. Under V28 it is HCC 112 but only codes
with an acute exacerbation — stable COPD no longer maps. These patients need a
new encounter with documented exacerbation language or they drop off the risk score.
Our suspects engine catches that before you lose the payment."

---

## Patient MBI Policy

All MBIs follow the format `PID{pid}` (e.g., `PID42`). These are placeholder
identifiers — not real Medicare Beneficiary Identifiers. Never substitute real
MBIs during demo setup.

## Data Cleanup

To remove all demo data:

```sql
-- Shadow tables (OpenEMR DB)
DELETE FROM patient_data      WHERE is_demo = 1;
DELETE FROM form_encounter    WHERE is_demo = 1;
DELETE FROM billing           WHERE is_demo = 1;
DELETE FROM form_soap         WHERE is_demo = 1;
DELETE FROM prescriptions     WHERE is_demo = 1;
DELETE FROM demo_lab_results  WHERE is_demo = 1;

-- RAF DB
DELETE p FROM raf_patient_hcc p
  JOIN raf_patient_demographics d ON d.patient_id = p.patient_id
  WHERE d.patient_id IN (SELECT pid FROM patient_data WHERE is_demo = 1);

DELETE FROM outreach_messages        WHERE is_demo = 1;
DELETE FROM chart_chase_requests     WHERE is_demo = 1;
DELETE FROM raf_radv_audit_records   WHERE is_demo = 1;
DELETE FROM raf_radv_audit_runs      WHERE is_demo = 1;
```
