# Knowledge Graph — 5-Minute Demo Script

> Audience: anyone giving a Knowledge Graph demo (founder, future SE, partner SE).
> Total runtime: 5 minutes. Seven distinct moments. Each moment carries: ACTION / NARRATION / LIKELY PROSPECT QUESTIONS + ANSWERS.

Pre-flight (do before the call starts):
- Open `/providers` page on the demo tenant.
- Confirm Sarah Mitchell row is loaded (she has a populated KG-first chain).
- Confirm `/api/kg/query/sub-services` returns all 8 services available.
- Have the ADA Standards of Care 2024 PDF open on a second tab.

---

## Minute 0:00–1:00 — The hook (60 seconds)

**SHOW**: `/providers` page, default view.

**SAY (verbatim opener)**:
> "Most risk-adjustment tools are black boxes — they tell you 'patient probably has HCC 18' and the coder has to guess why. We are going to show you exactly why we suggest each HCC, with a peer-reviewed citation you can click through to the source paper. The same level of evidence you'd accept in a UpToDate consult."

**CLICK**: Sarah Mitchell row → drawer expands.

**SHOW**: The suspect rows. Point to the small `KgGapBadge` pill that says `kg_rule` (purple) on the top suspect.

**LIKELY PROSPECT QUESTION**: *"What does that 'kg_rule' tag mean?"*
**ANSWER**:
> "It tells you the suggestion came from our deterministic Knowledge Graph rule engine, not from an LLM guess. The other tags you'll see are `kg_comorbidity`, `kg_drug_class`, `kg_lab_signal`, and `llm` — and we always show you which is which."

---

## Minute 1:00–2:30 — The reasoning chain (90 seconds)

**CLICK**: The top suspect row (HCC 18 — Diabetes with chronic complications).
The "Why this HCC?" panel (`EvidenceChainPanel.tsx`) opens.

**NARRATE while pointing**:
> "Sarah is on metformin and basal insulin, her last HbA1c was 9.4, and she has a documented background retinopathy. Watch what fires:
> 1. **Evidence rule** — `ada_dm_uncontrolled_hba1c_gt9` from ADA Standards of Care 2024, Section 6. Hard ICD prefix match on E11 plus a LOINC threshold on the A1c.
> 2. **Lab signal** — LOINC 4548-4 above the threshold, contributing 0.4 to confidence.
> 3. **Comorbidity upgrade** — the retinopathy plus the DM upgrades from HCC 19 (uncomplicated) to HCC 18 (with complications). That's KDIGO + ADA combined.
>
> End result: HCC 18 at 92% confidence, citing *Diabetes Care* volume 47, supplement 1, pages S111–S125. The citation is a clickable link."

**SHOW**: Click the citation link. ADA Standards of Care PDF opens in a new tab.

**LIKELY PROSPECT QUESTION**: *"Is any of this hallucinated?"*
**ANSWER (the most important answer in the demo)**:
> "No. Every rule is in our database — `kg_evidence_rules` table, 50 rows, every one has a verbatim citation. Click any rule ID and you see the source. The LLM's job in our system is *verification*: read the chart and confirm the rule applies. The LLM cannot invent a rule that isn't already in the graph. That is the architectural difference between us and pure-LLM coding tools."

**LIKELY PROSPECT QUESTION**: *"How many rules do you have vs. Navina?"*
**ANSWER (be honest)**:
> "We have 50 evidence rules plus 121 comorbidity patterns plus 251 specialty priors plus 163 demographic factors — about 585 reasoning units total. Navina publishes '600+ algorithms', so the same order of magnitude. Where we differ is *how* we got there — ours are individually attributed to ADA, KDIGO, ACC/AHA, GOLD, AHA Coding Clinic, AAFP, USPSTF; theirs are proprietary. If you ever face a RADV audit, our citation trail is externally verifiable. Theirs is vendor-attested."

---

## Minute 2:30–3:30 — Drug-class reasoning + the unseen-drug story (60 seconds)

**CLICK**: Switch to a different patient — one on tirzepatide (or another novel agent that isn't yet in our RxNorm bridge).

**NARRATE**:
> "This patient is on tirzepatide. We don't have a direct RxNorm bridge row for tirzepatide yet — it's that new. But watch what happens."

**SHOW**: The KG still classifies it. Point to the Why panel.

**NARRATE**:
> "Our `unseen_drug_inference` walks up the ATC hierarchy. Tirzepatide doesn't match level-5, but the parent class A10BJ — 'glucagon-like peptide-1 (GLP-1) receptor analogues' — does. That class is associated with diabetes management, which routes the suggestion to HCC 19 / 18. We logged it as drug-class inference with lower confidence than an exact bridge — 0.5 vs. 0.7 — and we tell you that in the chain."

**LIKELY PROSPECT QUESTION**: *"What happens when a brand-new drug gets approved?"*
**ANSWER**:
> "The ATC parent inference path keeps the suggestion working at reduced confidence until our next quarterly bridge update — which any customer can trigger themselves through the admin endpoints. You don't wait for a vendor release."

---

## Minute 3:30–4:15 — Polypharmacy + GDMT (45 seconds)

**CLICK**: A heart-failure patient on GDMT — sacubitril/valsartan, carvedilol, dapagliflozin.

**NARRATE**:
> "Three drug classes consistent with stage-C heart failure GDMT per ACC/AHA 2022. None of those individual drugs are HCC-specific — beta-blockers are used for hypertension too — but the *combination* fires the comorbidity engine.
>
> Watch the chain: drug-class A reasoner returns 'CV agents'. Drug-class B reasoner returns 'SGLT2'. Drug-class C reasoner returns 'ARNI'. Our `comorbidity_engine` sees the pattern, fires rule `acc_aha_hf_gdmt_pattern_2022`, and surfaces HCC 226 (CHF). The citation links to the ACC/AHA 2022 HF guideline."

**LIKELY PROSPECT QUESTION**: *"What if the patient stops one of those medications?"*
**ANSWER**:
> "The pattern stops firing the next time we run inference, because the rule has AND-semantics across required evidence buckets. We don't carry stale suggestions forward."

---

## Minute 4:15–4:45 — The audit packet (30 seconds)

**CLICK**: Click "Export evidence" on any expanded Why panel.

**SHOW**: The downloaded JSON / PDF — full evidence chain, every citation, every rule ID, every contribution-to-score, the LLM corroboration if any.

**NARRATE**:
> "This is what your coder sends to a CMS auditor or a downstream payer when an HCC is challenged. Rule ID, source paper with DOI, the exact lab value that triggered the threshold, the chart quote the LLM corroborated, the demographic multiplier that applied. RADV-defensible by construction."

**LIKELY PROSPECT QUESTION**: *"Has this been used in an actual RADV audit?"*
**ANSWER (be honest)**:
> "Not yet — we are pre-audit. What we can show you is the *defensibility surface*: every suggestion expands into this packet today. Our peer-validated study is on the roadmap for Q3 — we'll share the pre-registration with design partners."

---

## Minute 4:45–5:00 — The close (15 seconds)

**SAY**:
> "Three things we want you to remember:
> One — every suggestion expands into a peer-reviewed citation chain you can show your CMO.
> Two — our list price is $500 per provider per year, roughly one-quarter of the market.
> Three — we'll do a 30-day pilot on your data, free, and you'll see real recapture dollars before signing anything.
>
> Want to walk through the pilot scope right now, or take 24 hours to look at the architecture doc and circle back?"

---

## Backup moments (use only if 5 minutes runs short)

### Backup A — Specialty calibration (60s)

**SHOW**: `/api/kg/query/explain/108` (HCC 108, Vascular Disease).

**NARRATE**:
> "Same patient, same chart. If the rendering provider is a cardiologist, the prior weight on HCC 108 is 1.8× baseline. If primary care, it's 0.9×. We learned that from 251 specialty priors covering 10 specialties. So our suggestion ranking is calibrated to *what your provider actually sees in their panel* — not a generalist average."

### Backup B — Demographic modulation honesty (45s)

**NARRATE**:
> "Our demographic modulator multiplies suspect-priors by age/sex/dual-eligibility. We **never** apply it to the official RAF calculator — that has to report exactly what CMS pays on. The boundary is enforced at the module level, with the comment in the source: `This service is **never** used by the official RAF calculator`. Important regulatory hygiene we want you to know about."

### Backup C — Customer-extensible KG (30s)

**SHOW**: `POST /api/kg/concepts` and `POST /api/kg/edges` in API docs.

**NARRATE**:
> "Your clinical informatics team can add house rules — say, your network's specific cancer-survivorship pattern — without waiting for a vendor release. Admin-only, audit-logged, but yours."

---

## Pre-emptive "hard" prospect questions (and crisp answers)

| Question | Answer |
|---|---|
| *"Why should we trust a startup over Navina for risk adjustment?"* | "Don't yet — pilot us. We are betting that 30 days on your data will speak louder than our slide deck. If we don't beat your current vendor on identified-recapture dollars, walk away with the architecture doc and a line item for next year's RFP." |
| *"How do we know the citations are accurate?"* | "Click any of them in the demo. They open the actual ADA / KDIGO / ACC-AHA paper. We can also send you the seed scripts — every rule's source string is in `seed_kg_evidence_rules.py` and is grep-able. We'll do a citation audit walkthrough on a follow-up call." |
| *"What about latency? You're calling 8 services."* | "p95 of `patient_full_inference` is well under 1 second on our reference cluster — services run in process, the KG tables are read-mostly with `lru_cache` on the hot path, and we have a per-call execution log so you'll always see where time is spent. We'll send the perf benchmark from the pilot." |
| *"What if your evidence rule conflicts with our coding policy?"* | "You override. The KG ships with `is_active` flags on every rule, every concept, every edge. Your clinical informatics lead can disable any rule via admin API and we expose an audit trail of who disabled what when." |
| *"Are you HITRUST certified?"* | "Not yet — Q3-Q4 2026 target. We are HIPAA-compliant in deployment and the only LLM in the path is Vertex AI Gemini under Google's BAA. No third-party LLM has ever seen PHI through our platform." |
| *"What happens to my data if you go out of business?"* | "Self-hosted Docker. The KG and the suspect engine run in your environment. If we disappear tomorrow, your deployment keeps working — you just stop getting our quarterly KG updates. We'll commit that posture in writing." |

---

## What you must not say

- **Never** claim peer-reviewed validation we don't have yet. Roadmap, not present.
- **Never** name Navina as inferior. Compare on dimensions; let the prospect draw the conclusion.
- **Never** promise specific recapture dollars before the pilot. Frame as a hypothesis to test.
- **Never** promise FedRAMP / SOC 2 / HITRUST today. All are roadmap.
- **Never** disable a prospect's existing vendor relationship in the conversation. We complement, then convert.
