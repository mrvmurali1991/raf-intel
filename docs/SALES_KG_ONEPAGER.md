# RAF Intelligence Knowledge Graph — Buyer One-Pager

> Audience: VP Risk Adjustment, CFO, COO at a health plan or large MSO.
> Reading time: ~5 minutes.

---

## Headline value

**78% of HCC suggestions on the platform are backed by a stored, peer-reviewed
clinical citation — ADA, KDIGO, ACC/AHA, GOLD, AHA Coding Clinic, CMS V28
spec, AAFP — not LLM hallucination.** The remaining 22% are LLM
verifications that run *on top of* a knowledge-graph candidate, never as
a free-form invention.

Every recommendation we surface comes with a click-through citation chain
your coder can defend in a RADV audit, your CMO can read the source paper
on, and your compliance officer can store as evidence.

---

## Three problems we solve

**1. "Our coding tool suggests HCCs but no one knows where they came from."**
We solve this with a 573-concept, 503-edge curated knowledge graph and 50
literature-backed evidence rules. Every suggestion expands into a verbatim
citation chain — rule ID, source paper, DOI/URL, contribution-to-confidence
breakdown.

**2. "We pay $2,000–$2,500 per provider per year for the incumbent and we
need to cut admin cost without losing recapture revenue."**
We are priced at $500 per provider per year — roughly one-quarter of the
market rate — and we publish how we got there. For a 200-provider health
plan that is $300K–$400K of annual budget freed up.

**3. "We can't justify Navina's price for our smaller MSO / IPA / regional
plan, but we still owe our coders the same evidence-quality."**
The platform is shipped as a self-hosted Docker stack with a 30-day pilot
on real (or synthetic-augmented) data. Time-to-deploy is days, not months.
You see ROI on real charts before signing the contract.

---

## Concrete numbers (verified at deploy)

| Asset | Count |
|---|---|
| Curated KG concepts | **573** (UMLS, SNOMED CT, ICD-10, HCC V28, ATC, LOINC) |
| KG relationship edges | **503** across 8 relationship types |
| Comorbidity patterns (CMS V28 + KDIGO + ACC/AHA + AHA Coding Clinic) | **121** |
| Literature-backed evidence rules with peer-reviewed citations | **50** |
| LOINC lab-signal thresholds (HbA1c, eGFR, NT-proBNP, troponin, FEV1/FVC, …) | **52** |
| WHO ATC drug classes + RxNorm bridges | **86 + 106** |
| Demographic risk factors (across 52 HCCs) | **163** |
| Specialty-calibrated priors (across 10 specialties) | **251** |
| API endpoints surfacing the KG to your tenants | **47** |
| Frontend "Why this HCC?" components | **5** |

Every count above is grep-verifiable in the codebase. We will share the seed
scripts on request.

---

## Pricing position

| | RAF Intelligence | Incumbent enterprise solution |
|---|---|---|
| Per-provider list price | **$500 / year** | $2,000 – $2,500 / year |
| 200-provider plan annual cost | **$100K** | $400K – $500K |
| Annual savings | **— baseline —** | **$300K – $400K** below incumbent |
| Implementation fee | $0 (self-hosted Docker) | typically $50K – $150K |

We are intentionally priced at one-quarter of the market because our cost
structure is one-quarter as well — no proprietary 600-rule maintenance team,
just curated open ontologies and a small clinical-informatics review board.

---

## 30-day pilot offer

- **Free POC**, scoped to a single line of business (MA, ACO, Commercial)
  on **your real chart data** (or a 1,000-patient synthetic-augmented sample
  if PHI access takes longer than 30 days).
- Deliverables on day 30:
  - Concrete dollars-of-recapture identified by the KG-first pipeline.
  - Side-by-side comparison vs. your current vendor's last-month output
    on the same chart sample.
  - Coder time-to-close benchmark (target: ≤ 60 seconds per suggestion
    with citation chain expanded).
  - Audit-defensibility worksheet (which suggestions would survive RADV
    on citation alone).
- Conversion math: if the pilot identifies even half a percent of incremental
  RAF on a 50,000-member plan, that's typically $5M–$8M of annualized
  recapture — vs. our list price of $25K – $50K per year for that plan size.

---

## RAF Intelligence vs. incumbent enterprise solutions

| Dimension | RAF Intelligence | Incumbent |
|---|---|---|
| Per-provider list price | **$500 / yr** | $2,000 – $2,500 / yr |
| Time-to-deploy | **Days** (Docker) | Weeks to months |
| Audit defensibility | **Verbatim peer-reviewed citation per suggestion** | Vendor-attested; sources not externally auditable |
| Source transparency | **Every rule has DOI / URL / page reference** | Proprietary, not externally citable |
| Customer-extensible KG | **Yes** (admin endpoints to add concepts/edges) | No — vendor-managed only |
| LLM use | **Verification only**, on top of KG-resolved candidates, under Vertex BAA | Limited / undisclosed |
| PHI exposure to third-party LLMs | **None** outside Vertex BAA | Vendor-dependent |
| Self-hosted option | **Yes** | No |
| Pilot model | **30-day, free, real outcome dollars** | Multi-month paid implementation |

---

## What we are honest about

- We seeded **50** evidence rules vs. the incumbent's disclosed **600+
  algorithms**. We close that gap with deterministic comorbidity patterns
  (121), specialty priors (251), demographic factors (163), and LLM
  verification — total reasoning surface comparable.
- Our peer-reviewed validation study is **on the roadmap, not yet
  published**. We will share methodology, sample size targets, and
  pre-registration before kickoff.
- Pilot data today is **synthetic-augmented**; we are actively onboarding
  design partners with real Medicare Advantage and ACO REACH datasets.

We tell you this up front because the same transparency we apply to every
HCC suggestion applies to how we sell.

---

## Call to action

**Book a 45-minute demo with a sample patient from your panel** (or one of
ours, if PHI provisioning takes longer). You'll see:

1. The "Why this HCC?" panel expand a single suggestion into its full
   citation chain — rule, source paper, threshold, lab value, comorbidity
   path.
2. Live drug-class reasoning on a tirzepatide / semaglutide patient — agent
   we may not have an exact RxNorm bridge for yet, where ATC parent
   inference still classifies the drug correctly.
3. The 30-day pilot scoping conversation, with a written statement of
   work in your inbox before you leave the call.

Email **mrvmurali1991@gmail.com** or book directly at
`https://rafintelligence.com/demo`.

We will tell you within 15 minutes of the call whether we are a fit for
your panel — and if not, who in the market we think is.
