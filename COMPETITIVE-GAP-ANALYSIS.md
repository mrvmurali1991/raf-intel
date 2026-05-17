# RAF Intelligence — Competitive Gap Analysis (Round 2)

*Synthesized from 15 competitor reports + 5 cross-cutting research reports. 2026-05-17.*

## Executive Summary

**Top 3 strategic threats (by name):**
1. **Reveleer** — 50% of Blues plans, EVE Hybrid AI at 99% accuracy, 1.2M charts/4 months throughput, $200M run-rate, and the only RADV-specific SaaS in market ([reveleer.com](https://www.reveleer.com/solutions/radv-audit)). Owns retrospective + payer trust.
2. **Innovaccer Flow Capture** (Mar 2026 launch) — Autonomous coding of 80% of encounters, ambient scribe with in-room CDI assistant, 130+ org installed base ([businesswire](https://www.businesswire.com/news/home/20260309523268/)). Disrupts the coder-augmentation model RAF is building toward.
3. **Apixio + Datavant + Rawlings + VARIS** — Merged into a $3B+ payment-integrity stack with longitudinal RWE across multiple payers, Apicare prospective POC integration via Vim, Health Data Nexus enterprise data layer ([newmountaincapital](https://www.newmountaincapital.com/the-rawlings-group-apixio-payment-integrity-and-varis-merge-to-form-next-generation-payment-accuracy-and-integrity-platform/)). Will outprice and outdata RAF unless we narrow.

**Top 3 strategic advantages (by name):**
1. **Cryptographic immutable audit chain + Force-Accept attestation** — No competitor (Inovalon Black Book #1, Reveleer, Cotiviti, Optum, Edifecs) ships SHA-256 prev_hash per row + server-validated MRN-last-4 + 20-char justification. Inovalon, Cotiviti, ZeOmega all rely on RBAC + row locks.
2. **30-second OpenEMR FHIR auto-sync with SSE push** — Cotiviti Pre-Visit Prep leads by 48–72 hours; Inovalon batch polls; Reveleer prospective requires 6–12 week go-live; Persivia documents 30s polling but no SSE browser push. RAF measurable end-to-end sub-minute.
3. **Honest-math em-dashes + WCAG 2.2 AA axe-core zero violations** — None of Apixio, Reveleer, Inovalon, Optum, Notable publish accessibility audits or refuse to show coefficient-free dollars. Differentiator for risk-averse CFO / compliance buyers.

**Top 5 features to build next (priority order):**
1. **Epic SMART-on-FHIR app + CDS Hooks decision service** — 4–6 weeks. Epic = 35% MA market; every Tier-1 competitor has it. Unlock without it: $0; with it: $0.50 PMPM × 35% TAM ([smarthealthit.org](https://docs.smarthealthit.org/)).
2. **RADV Audit Defense Workflow** (chart-request orchestration, mock audit simulator, MAO-004 batch resubmit, 200-record sampler) — 8–10 weeks. CMS now audits all 550+ contracts/yr w/ 200-record samples; Inovalon Black Book #1 owns this lane today.
3. **NLP suspect mining from unstructured notes** — 10–12 weeks. Every competitor (Apixio, Reveleer EVE 99%, Persivia 99%, Inovalon, Optum CLI, Innovaccer Sara, RAAPID 98.5%) claims this; RAF is rule-based only. Without it RFPs die at table-stakes.
4. **Bi-directional Epic Problem List write-back via Vim-pattern or SMART** — 4–6 weeks after #1. Apixio/Vim, Cotiviti, Notable, Veradigm all write back. Closes the loop providers expect.
5. **Bulk FHIR ingest API + claims/EDI 837 ingestion** — 6–8 weeks. Smile ingests 255k tx/sec; Optum CLI millions of docs/day. RAF cannot onboard a 100k-life plan without it.

**Pricing recommendation:** Publish tiered transparent PMPM: $1.50 Tier-1 (10–50K lives), $1.00 Tier-2 (50–150K), $0.60 Tier-3 + 15% gain-share (150K+), and a standalone "RADV Audit Trail" SKU at $40K/yr for plans already running Reveleer/Apixio. Apixio, Inovalon, Reveleer, Optum, Cotiviti all hide pricing ([impakter.com](https://impakter.com/the-8-best-risk-adjustment-coding-software-platforms-a-compliance-leaders-honest-review/)). Transparency is a wedge into SMB plans (<50K) the incumbents won't quote.

---

## Competitor Landscape

**Tier 1 incumbents (3 lines each):**

- **Optum** ([business.optum.com](https://business.optum.com/en/operations-technology/risk-adjustment.html)) — Owns Clinformatics 84M-life data mart + Professional CAC w/ Clinical Language Intelligence + Risk Analytics. Bundled with UnitedHealth, KLAS Big-Four. **#1 strength:** captive UHC claims data + 20-year CLI NLP. **#1 differentiator vs RAF:** peer-network benchmarking against 84M lives.
- **Inovalon Converged Risk** ([inovalon.com](https://www.inovalon.com/products/payer-cloud/risk/)) — 456M linked lives, 15/15 top plans, all top-25 IDNs, RWE benchmarks, dual prospective/retrospective. **Strength:** Black Book #1 RADV readiness (2024–25). **Differentiator vs RAF:** RWE prevalence API across 5-year longitudinal claims.
- **Cotiviti + Edifecs** ([cotiviti.com](https://www.cotiviti.com/solutions/risk-adjustment)) — 200+ plans, 10M+ charts/yr coded by 100% AAPC/AHIMA staff at 97%+ accuracy, 1.4B+ Edifecs encounter throughput, $10B+ payment integrity recovery. **Strength:** captive certified coder workforce + EDI 837/MAO-004 maturity. **Differentiator:** 1.7M-provider chart-chase logistics network.
- **Apixio (Datavant)** ([apixio.com](https://www.apixio.com/)) — HCC-Complete + Apicare Pre/Post/POC + Health Data Nexus + HCC Auditor; merged 2024 with Rawlings + VARIS into $3B payment-integrity entity. **Strength:** longitudinal RWE post-merger. **Differentiator:** Vim-powered bi-directional Epic problem list writes.
- **Reveleer** ([reveleer.com](https://www.reveleer.com/)) — 50% Blues, 70+ payers, 66M lives, $65M+ funding, EVE Hybrid AI at 99% accuracy, RADV SaaS, 1.2M charts/4 mo. **Strength:** RADV-defensibility evidence-first explainability. **Differentiator:** purpose-built RADV submission orchestration.
- **Edifecs** (now Cotiviti) ([edifecs.com](https://www.edifecs.com/products/encounter-submissions/)) — 1.4B+ encounters/yr, 99%+ acceptance, 100% national plans, KLAS #1 Payer Interop 2026. **Strength:** EDI 837 + FHIR Gateway. **Differentiator:** Concurrent Risk Adjustment (Sept 2024) + Point-of-Care Suspects (Mar 2025).
- **Innovaccer** ([innovaccer.com](https://innovaccer.com/products/risk-adjustment)) — DAP unifying 54M records across 70 entities, Sara AI, Flow Capture autonomous coding launched Mar 2026, 130+ orgs, 7/10 top systems. **Strength:** unified data fabric. **Differentiator:** Flow Capture 80% autonomous + ambient scribe.
- **Episource** (Optum 2023) ([episource.com](https://www.episource.com/)) — 8,000 captive coders, 11M charts/yr, epiCoder NLP coder-assignment, 50 states + PR. **Strength:** captive coder labor. **Differentiator:** chart-difficulty-to-coder ML routing.
- **Persivia CareSpace** ([persivia.com/ai-driven-risk-adjustment](https://persivia.com/ai-driven-risk-adjustment/)) — 100M records, 70+ EHRs, 99% NLP HCC accuracy, Soliton AI multi-model. **Strength:** 3,000+ data sources. **Differentiator:** simultaneous v24/v28 with custom clinical risk overlays.
- **Pareto Intelligence** ([paretointel.com](https://paretointel.com/revenue-iq-risk-adjustment/)) — 75% of top insurers, $2.5B identified, RevenueIQ + StarIQ + RewardsIQ + GHG Advisors. **Strength:** advisory + data governance bundle. **Differentiator:** StarIQ probabilistic Star forecasting tied to RA.
- **ZeOmega Jiva** ([zeomega.com](https://www.zeomega.com/solution-trends/jiva-risk-adjustment-navigator-solution)) — KLAS #1 Payer Care Mgmt 4 years (22–25), Jiva Sentinel Rules, Smart Auth Optimizer, HealthUnity data lake. **Strength:** configurable rules engine. **Differentiator:** UM + RA + Stars + member engagement under one tenant.
- **Notable Health** ([notablehealth.com](https://www.notablehealth.com/solutions/hcc-chart-review)) — 12,000+ sites, 1M+ workflows/day, AI Agents + Flow Builder + HCC Chart Review. Security Health Plan added 440 HCCs / $1.7M ([notablehealth.com](https://www.notablehealth.com/use-cases/quality-risk)). **Strength:** in-encounter provider prompts. **Differentiator:** no-code Flow Builder.
- **Vim** ([getvim.com](https://getvim.com/)) — Middleware EHR layer, 150K+ providers, $71M raised (Sequoia/Optum/Elevance), powers Apixio's Epic write-back. **Strength:** proprietary in-EHR layer across Epic/Cerner/Athena/eCW/NextGen. **Differentiator:** bidirectional ICD-10 write-back with auto-resolve duplicates.

**Startups (4 lines each):**
- **RAAPID** — Neuro-symbolic, M12/Microsoft funded, 98.5% accuracy, 10× ROI, 75% review-time cut, MEAT evidence chains ([raapidinc.com](https://www.raapidinc.com/)). Direct rival; RAF must publish accuracy benchmarks.
- **Keebler Health** — $23M raised, LLM-native unstructured extraction with confidence + counterfactual evidence, Epic/Cerner/Athena out-of-box V28 ([keebler.health](https://keebler.health/)). Coder explainability lead.
- **Penguin AI** — $29.7M Greycroft/UPMC/Snowflake, agentic HCC coding as Snowflake native app ([penguinai.co](https://www.penguinai.co/)). Will undercut on data-warehouse-native deployment.
- **Encipher Health** — Neuro-symbolic, 97% accuracy, multi-specialty coding (anesthesia/radiology/E&M), 60% cost reduction ([encipherhealth.com](https://encipherhealth.com/)). Horizontal expansion threat.

**Infra (1 line):**
- **Smile Digital Health** — FHIR-native data backbone (255k tx/sec, HAPI FHIR, KALM AI, CMS-0057-F prior auth, OmniVera MPI/terminology); not a competitor, a *partner-or-substrate* play ([smiledigitalhealth.com](https://www.smiledigitalhealth.com/)).

---

## Top 20 Gaps Ranked

| Rank | Gap | Competitors who have it | Effort wks | P | Revenue impact | Notes / Citation |
|---|---|---|---|---|---|---|
| 1 | **Epic SMART-on-FHIR app + CDS Hooks decision service** | Reveleer, Apixio, Cotiviti, Inovalon, Optum, Innovaccer, Notable | 4–6 | P0 | Unlocks 35% MA TAM; $0.50–$2 PMPM × millions of lives | Epic dominates 35% of US EHR market. RAF is OpenEMR-only. ([smarthealthit.org](https://docs.smarthealthit.org/), [epic apps](https://apps.smarthealthit.org/apps/ehr/epic)) |
| 2 | **NLP suspect mining from unstructured notes (ICD-10/HCC extraction)** | Apixio, Reveleer EVE 99%, Persivia 99%, Inovalon, Optum CLI, Innovaccer Sara, RAAPID 98.5%, Keebler, Encipher | 10–12 | P0 | Table-stakes for any payer RFP; without it RFP=disqualified | F1 0.79 on MIMIC-IV achievable; fine-tuned medical LLMs hit 97% exact match. ([apixio.com](https://www.apixio.com/), [reveleer EVE PR](https://www.prnewswire.com/news-releases/reveleer-announces-eve-hybrid-ai-302664696.html)) |
| 3 | **RADV Audit Defense Workflow (chart request orchestration, 200-record sampler, MAO-004 batch resubmit, mock audit simulator, CAP tracking)** | Inovalon (Black Book #1), Reveleer RADV SaaS, Cotiviti, Apixio HCC Auditor, Pareto | 8–10 | P0 | CMS audits all 550+ contracts yearly; $15–30M per-plan penalty exposure; 73% lose appeals | Sept 2025 court vacated extrapolation but appeal pending; sample size 35→200. ([reveleer RADV](https://www.reveleer.com/solutions/radv-audit), [inovalon RADV](https://www.inovalon.com/news/inovalon-radv-audit-readiness-solution-earns-top-ranking-from-black-book/), [healthcaredive](https://www.healthcaredive.com/news/cms-medicare-advantage-audits-radv-risk-adjustment-update/811320/)) |
| 4 | **Bi-directional EHR write-back to Problem List / Assessment** | Vim/Apixio, Notable, Innovaccer, Cotiviti, Veradigm, Reveleer | 4–6 | P0 | Closes feedback loop providers expect; 23% of Vim gaps close at POC | Apixio writes via Vim FHIR ProblemList.verificationStatus. ([getvim.com news](https://getvim.com/news-and-events/apixio-partners-with-vim-to-deliver-ai-powered-insights-at-the-point-of-care/)) |
| 5 | **Cerner/Oracle Code App Gallery + PowerChart integration** | Inferscience, Innovaccer, IMO, Cotiviti, Apixio | 6–8 | P0 | Cerner = 27% market; Inferscience HCC Assistant already there | ([code.cerner.com](https://code.cerner.com/apps/)) |
| 6 | **Bulk FHIR ingest API + 50–500k patient cohort onboarding** | Smile (255k tx/s), Apixio HCC-Complete (4–8M charts/mo), Reveleer (1.1B pages/yr), Inovalon myABILITY | 6–8 | P0 | Cannot onboard any plan >100k lives without it | RAF currently single-patient FHIR poll. ([smilecdr docs](https://smilecdr.com/docs/fhir_gateway/introduction.html)) |
| 7 | **Claims/EDI 837 + 834 enrollment ingestion + outbound 837 generation** | Edifecs (1.4B/yr, 99%+ accept), Cotiviti, Optum Real, Apixio, Inovalon | 6–8 | P0 | Pre-submission validator is useless if RAF cannot generate the 837 | Edifecs first-pass rate 99.9%. ([edifecs encounter](https://www.edifecs.com/products/encounter-submissions/), [healthdatamax](https://www.healthdatamax.com/edps-submissions)) |
| 8 | **Real-World Evidence benchmark API (HCC prevalence by demographic/ZIP)** | Inovalon 456M lives, Optum CDM 84M, Datavant/Apixio post-merger | 24–36 | P1 | RFP differentiator; peer-network benchmarking | License IQVIA or aggregate via 2–3 payer partners. ([inovalon RWE PDF](https://www.inovalon.com/wp-content/uploads/2026/03/INOV-RWD-Overview-1.30.26-v9.0.9.pdf)) |
| 9 | **HEDIS / Star Ratings module** | Reveleer (75% efficiency, 95% accuracy), Cotiviti (KLAS Best 2024), Innovaccer, ZeOmega, Pareto StarIQ | 20–24 | P1 | 10–20% of payer SaaS spend; bundleable | NCQA-certified analytics, hybrid + ECDS measure calc. ([reveleer HEDIS](https://www.reveleer.com/blog/reveleer-launches-nlp-first-pass-quality-streamline-hedis-submissions)) |
| 10 | **Ambient AI scribe / in-visit HCC prompts** | Notable, Innovaccer Flow Capture (Mar 2026), Abridge, Nuance DAX, Suki | 16–20 | P1 | Riverside Health saw +14% HCCs/encounter, 11% wRVU lift | Build w/ partner (Abridge/DeepScribe) vs in-house. ([businesswire Flow Capture](https://www.businesswire.com/news/home/20260309523268/en/), [AHA scribes](https://www.aha.org/aha-center-health-innovation-market-scan/2026-04-14-6-health-systems-enhancing-care-delivery-ambient-ai-scribes)) |
| 11 | **Multi-source data fabric: claims + labs (LOINC) + Rx (RxNorm) + SDOH** | Innovaccer DAP (54M, 70 entities, 2,800 elements), Inovalon, Persivia 3,000 sources, ZeOmega HealthUnity, Pareto Hub | 16–20 | P1 | Required for RFPs above 100k lives | ([innovaccer DAP](https://innovaccer.com/data-activation-platform), [persivia POM](https://persivia.com/population-health-management/)) |
| 12 | **MEAT evidence-snippet auto-extraction with source-text offsets** | RAAPID sentence-level, Keebler counterfactual, Apixio, Reveleer evidence-first | 6–8 | P1 | Coder trust + RADV defense readability | RAF surfaces M/E/A/T flags but not the source sentence. ([raapidinc.com](https://www.raapidinc.com/blogs/simplify-hcc-coding-with-meat-criteria/)) |
| 13 | **Athena Marketplace browser plug-in + NextGen / eCW connectors** | Vim, Azara, Arcadia, Cotiviti, Reveleer | 8–12 | P1 | Mid-market 12% TAM, fast distribution | ([marketplace.athenahealth.com](https://marketplace.athenahealth.com/)) |
| 14 | **V28 transition impact calculator (per-patient + portfolio)** | Pareto v28 toolkit, Navina, Inovalon, MedInsight | 6–8 | P1 | CMS-projected -3.12% RAF erosion 2024→26; every plan budgeting now | 2,294 codes retired V24→V28. ([medinsight V28](https://medinsight.com/healthcare-data-analytics-resources/blog/medicare-advantage-2026-cms-hcc-v28-impact/), [paradocs](https://www.paradocshealth.com/post/understanding-cms-hcc-v28-in-5-minutes)) |
| 15 | **Coder productivity analytics (time-on-chart, AI acceptance rate, specificity capture)** | MDaudit, Cavo, Reveleer dashboards, Vatica (KLAS Best 3yrs) | 4–6 | P1 | Sales conversation w/ coding directors; 5–10 charts/hr baseline | ([mdaudit metrics](https://mdaudit.com/news/coder-productivity-metrics-that-matter-in-2026/), [cavohealth](https://cavohealth.com/what-to-look-for-in-next-gen-hcc-coding-software-a-buyers-checklist/)) |
| 16 | **Master Patient Index + cross-source identity resolution** | Smile OmniVera, Inovalon, Innovaccer DAP, Persivia UDM | 8–12 | P1 | Required when ingesting claims + EHR + Rx for same member | ([smiledigitalhealth omnivera](https://www.smiledigitalhealth.com/omnivera)) |
| 17 | **Health Equity Index (HEI) dual-eligible segmentation + reporting** | Inovalon Converged STARS, ZeOmega+MSFT Cloud SDOH, Milliman frameworks | 6–8 | P1 | PY 2027 Star Ratings weight by HEI; mandatory in 18 months | ([milliman HEI](https://www.milliman.com/en/insight/recent-health-equity-focused-initiatives-from-cms-medicare-plans)) |
| 18 | **Provider scorecard with attribution + chart-difficulty routing (epiCoder pattern)** | Episource epiCoder, Pareto Provider Reporting, Cotiviti, Reveleer | 5–7 | P1 | Provider engagement closes 23%+ of gaps at POC; coder routing -30% touch time | ([episource medium](https://medium.com/episource-developers/episource-coding-meets-epianalyst-campaigns-afdd3dc4a38f)) |
| 19 | **Payer-provider network bridge (Particle Health / Health Gorilla / TEFCA QHIN)** | Particle, Health Gorilla, Surescripts, Veradigm | 2–3 | P2 | Bypasses Epic/Cerner integration friction for payer-led deployments | ([particlehealth.com](https://www.particlehealth.com/), [healthgorilla.com](https://www.healthgorilla.com/)) |
| 20 | **Low-code rule builder + tenant-configurable workflows** | ZeOmega Jiva Sentinel Rules, Notable Flow Builder, Pareto | 12–16 | P2 | Required at >200k-life plans to avoid bespoke eng tickets | ([zeomega about](https://www.zeomega.com/company/about), [notablehealth](https://www.notablehealth.com/ai-platform/overview)) |

Honorable mentions (deprioritized but tracked): autonomous batch coding (Innovaccer Flow Capture), KLAS engagement & published benchmarks (Optum/Inovalon), HIPAA-private on-prem LLM option (Med-PaLM/BioMistral), prior-authorization automation (ZeOmega Smart Auth, Smile CMS-0057-F), CMS submission monitoring across 837/MAO-001/MAO-004 lifecycle, Snowflake-native deployment (Penguin AI), gain-share contracting infra.

---

## RAF Strengths to Lean Into

**1. Server-side MEAT gate + Force-Accept attestation.** No competitor (Inovalon Black Book #1, Reveleer EVE, Cotiviti's 100% AAPC reviewers, Optum Professional CAC, Edifecs, ZeOmega, Apixio, Persivia, Pareto) publishes API-layer enforcement of MEAT with MRN-last-4 + 20-char justification before mutation lands. Curl 422 proof. Sell to compliance officers — "coding integrity by architecture, not UI polish."

**2. Immutable SHA-256 hash-chained audit log.** Zero competitors expose `payload_hash` ↔ `prev_hash` per-row. HIPAA + RADV reviewers see "no row was ever edited" as cryptographic fact, not policy promise. Reveleer/Cotiviti/Optum still rely on RBAC + DB locks.

**3. 30-second OpenEMR FHIR auto-sync with SSE browser push.** Cotiviti Pre-Visit leads by 48–72h; Reveleer prospective 6–12 weeks to go-live; Persivia 30s polling but no SSE; Inovalon batch. RAF's measurable end-to-end sub-minute is unique.

**4. WCAG 2.2 AA + axe-core zero-violations.** None of Apixio, Reveleer, Inovalon, Optum, Notable, ZeOmega publish accessibility audits. Wedge for state-Medicaid RFPs (Section 508) and provider buyers.

**5. X-Active-Tenant header role downrank.** Global admin actually becomes viewer in Tenant B at request time. Reveleer/Keebler don't disclose multi-tenant role isolation; ZeOmega configurable but not request-scoped.

**6. Transparent pricing opportunity.** Apixio/Inovalon/Reveleer/Optum/Cotiviti all hide pricing. Publishing $1.50/$1.00/$0.60 PMPM tiers is a wedge into SMB plans (<50K) the incumbents won't quote.

**7. CDS Hooks lockdown (bearer + IP allow-list + per-source rate limit).** Compliance asks for this; Vim, Apixio, Reveleer don't disclose hook-level auth posture publicly.

**8. Honest-math em-dashes.** RAF refuses coefficient-free dollar projections. CFO-resonant. Pareto, Apixio, Reveleer, Inovalon all ship confident projections regardless of data completeness.

---

## 12-Month Roadmap

### Q1 (Months 1–3): Land the EHR + Coder Trust Foundation
- **Epic SMART-on-FHIR launch + CDS Hooks decision service** (Gap #1, 4–6w). Submit to App Orchard.
- **Bi-directional Epic Problem List write-back** (Gap #4, 4–6w follow-on).
- **MEAT evidence-snippet auto-extraction with source-text character offsets** (Gap #12, 6–8w). Coder trust signal — closes RAAPID/Keebler parity.
- **Coder productivity analytics dashboard** (Gap #15, 4–6w). Time-on-chart, AI acceptance rate, specificity capture rate per MDaudit/Cavo benchmarks.
- **Publish transparent PMPM pricing + RADV-Audit-Trail $40K SKU.** Marketing only, 1 week.
- **V28 transition impact calculator** (Gap #14, 6–8w). Plans budgeting now for full V28 cutover Jan 2026.

### Q2 (Months 4–6): Become a Real Payer Platform
- **RADV Audit Defense Workflow** (Gap #3, 8–10w). Chart-request orchestration + 200-record sampler + MAO-004 batch resubmit + CAP tracking + mock-audit revenue exposure simulator. Goes head-to-head with Inovalon Black Book #1 and Reveleer RADV SaaS.
- **Outbound 837 generation + 834 enrollment + claims ingestion** (Gap #7, 6–8w). Without it RAF is a coding tool, not a payer platform.
- **Bulk FHIR ingest API for 50–500k cohorts** (Gap #6, 6–8w). Enables onboarding any plan >50K lives.
- **Cerner Code App Gallery + PowerChart embed** (Gap #5, 6–8w). 27% market opens.
- **Athena Marketplace browser plug-in** (Gap #13, 3–4w portion). Mid-market distribution.

### Q3 (Months 7–9): Match AI Table-Stakes + Quality Bundle
- **NLP suspect mining from unstructured notes** (Gap #2, 10–12w). Fine-tune BioMistral or Meditron on labeled HCC corpus; publish F1 by HCC vs Reveleer 99% claim. Without this RFPs disqualify.
- **HEDIS / Star Ratings module v1** (Gap #9, partial 12w; full 20–24w slips to Q4). NCQA-spec measure logic, hybrid + ECDS, gap-closure workflow. Unlocks 10–20% of payer wallet.
- **Health Equity Index dual-eligible segmentation** (Gap #17, 6–8w). PY 2027 Star Ratings weight by HEI; LIS/Medicaid flagging.
- **Provider scorecard + chart-difficulty routing** (Gap #18, 5–7w). epiCoder-style; reduces coder touch-time 30%.

### Q4 (Months 10–12): Data Fabric + Strategic Bets
- **Multi-source data fabric (claims + LOINC labs + RxNorm + SDOH) + MPI** (Gaps #11 + #16, 16–20w combined). Required at >100k lives.
- **Payer-provider network bridge (Particle Health / Health Gorilla / TEFCA QHIN)** (Gap #19, 2–3w). Unlock payer-led deployments without provider IT friction.
- **Begin RWE benchmark API partnership** (Gap #8, ongoing 24–36w). License IQVIA or aggregate 2–3 regional payer cohorts.
- **Ambient scribe partner integration** (Gap #10, 16–20w; partner w/ Abridge/DeepScribe vs build) — preempt Innovaccer Flow Capture.
- **HEDIS module full ship** (Gap #9 carryover).
- **KLAS engagement + 3 named reference customers** (cite [Optum gap analysis](https://klasresearch.com/review/optum-risk-adjustment-solutions/223156); RAF has no KLAS rating today).

---

## Sales Positioning

**Persona 1 — Humana CMO / VP Risk (Enterprise MA payer, 5M+ lives):**
Lead with **RADV defensibility moat**: immutable hash-chain audit + server-enforced MEAT gate + Force-Accept attestation. Sept 2025 court vacated CMS extrapolation but appeal pending; CMS scaled reviewers 40→2,000 and audits all 550+ contracts now. Frame: "One failed HCC × 200-record sample × 55× extrapolation multiplier = $12K PMPY exposure per failed code." RAF's curl-422 proof + SHA-256 prev_hash chain reconstruct attestation in 5 seconds, not 5 days. Position as **complement to Reveleer/Cotiviti**, not replacement: RAF is the front-office coding-integrity layer that feeds clean defensible 837s into their existing back-office. Sell the standalone "RADV Audit Trail" SKU at $40K/yr as a wedge; expand into full PMPM once compliance trusts the audit chain. Show V28 transition calculator + 200-record mock-audit simulator in first demo.

**Persona 2 — 50-PCP physician group / IPA (50K–100K attributed MA lives):**
Lead with the **30-second OpenEMR magic moment + WCAG 2.2 AA UX**. Provider groups care about coder productivity (5–10 charts/hr baseline; Vatica won KLAS 3 years). Show: new patient registered in OpenEMR → 30 seconds → suspect queue populated, MEAT grid live, RAF gauge visible, SSE toast to every coder. Compare against Reveleer's 6–12 week Epic go-live or Cotiviti's 48–72h Pre-Visit Prep window. Pricing transparency lands here: published $1.50 PMPM avoids the "call sales" fatigue that Apixio/Inovalon/Reveleer force. Emphasize bi-directional Problem List write-back (Q1 ship) so providers see codes in their next encounter. Honest-math em-dashes resonate w/ medical directors burned by overconfident vendor projections.

**Persona 3 — MA startup (10K–50K members, Devoted/Bright/Clover-style):**
Lead with **modern stack + lean economics + transparent pricing**: $1.50 PMPM tier + gain-share option (base + 15–20% of incremental verified RAF uplift). Cite Reveleer's 33% RAF lift and RAAPID's 10× ROI as industry benchmarks but flip the model — "we only win when you do." Show server-side MEAT gate as table-stakes RADV defense that they'd otherwise pay Cotiviti $200K for. Show FHIR + SSE + CDS Hooks + WCAG as 2026-native vs incumbent batch legacy. Position OpenEMR + future Epic/Cerner/Athena/Particle bridges as no-vendor-lock-in (vs Optum's UHC-centric ecosystem). Volunteer co-marketing/case study in exchange for KLAS-eligible reference status — startups want logos, RAF needs analyst validation. Close with "no captive coder workforce, no advisory upsell, no hidden modules" vs Episource/Pareto bundles.

---

*Word count target: 3,500; sources cited inline. Master deliverable: 2026-05-17.*
