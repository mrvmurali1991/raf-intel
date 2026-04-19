# Patient2Trial — Adaptation Plan for RAF Intelligence

**Status:** Backlog — to be implemented after current sprint
**Owner:** Kriya
**Source:** Datta et al., "Patient2Trial: From patient to participant in clinical trials using large language models," *Informatics in Medicine Unlocked* 53 (2025) 101615
**DOI:** https://doi.org/10.1016/j.imu.2025.101615
**Decision:** ADAPT (techniques only; not the trial-matching use case itself)

---

## 1. Why this paper matters to us

Patient2Trial built a GPT-4 pipeline that filters ClinicalTrials.gov, expands patient information using domain knowledge, and scores each trial inclusion criterion against the patient. They reported NDCG@10 = 0.81 and Precision@10 = 0.74 across 8 disorders.

The **use case** (clinical trial matching) is not our product. The **techniques** map almost 1:1 onto the gaps in our HCC suspect detection and MEAT readiness scoring.

---

## 2. What we will adapt

### 2.1 Knowledge mappings for clinical-term expansion (HIGH PRIORITY)

**Their approach:** Per-disorder tables of hypernyms (broader umbrella terms), hyponyms (specific child terms), synonyms, and abbreviations — curated by clinical experts. Used to expand patient topics before retrieval.

> Example from paper: "uveitic glaucoma" → "secondary glaucoma" (hypernym) + "UG" (abbreviation).

**RAF application:**
- Today our suspect engine likely matches ICD-10 / HCC by literal token match in OpenEMR notes.
- We miss obvious variants: "DM2" / "T2DM" / "uncontrolled diabetes" / "diabetes mellitus, type 2" all should hit the same HCC.
- Build per-HCC knowledge mapping tables (hypernym/hyponym/synonym/abbreviation) and expand chart text before suspect detection.

**Estimated lift:** Recall improvement on suspect detection. Probably +5–15 % more true suspects found per chart.

**Where it lives:**
- New table: `hcc_term_mappings` (hcc_code, term, term_type, source)
- Hook into existing suspect detection in the candidate-generation stage
- Seed initial mappings from ICD-10-CM index + UMLS where licensed

---

### 2.2 Per-criterion 0/1/2 scoring for MEAT (HIGH PRIORITY)

**Their approach:** Instead of binary include/exclude, GPT-4 scores each inclusion criterion as:
- `0` — criterion missing in patient information
- `1` — partial match (entity present, details missing)
- `2` — fully matched

**RAF application:**
- Today MEAT readiness is probably binary or coarse (`ready` / `not ready`).
- Score each MEAT element separately:
  - **M**onitor — vitals/labs trended? 0/1/2
  - **E**valuate — diagnostic workup documented? 0/1/2
  - **A**ssess — provider's clinical judgment recorded? 0/1/2
  - **T**reat — treatment plan / med change documented? 0/1/2
- Surface the lowest-scoring element so providers fix the *specific* gap.

**Estimated lift:** Provider trust + fewer abandoned suspects. Currently providers see "MEAT not ready" with no path to action.

**Where it lives:**
- Extend `meat_assessment` (or equivalent) table with per-letter scores
- Update `_fetch_meat_letters` in `app/routers/raf_central.py` to return scores
- Frontend MEAT panel renders 4 colored chips instead of one badge

---

### 2.3 "Cannot determine" trichotomy (MEDIUM PRIORITY)

**Their approach:** Three categories — `Include`, `Exclude`, `Cannot determine`.

**RAF application:**
- Today we probably have accept-suspect / dismiss-suspect (binary).
- Add a third state: **insufficient documentation → auto-trigger MEAT letter**.
- Closes the loop on suspects that are neither confirmed nor disproven, just under-documented.

**Where it lives:**
- New action endpoint: `POST /api/raf-central/{pid}/suspect/{id}/needs-info`
- Wires into the existing MEAT-letter push pipeline
- Audit-logged like accept/dismiss

---

### 2.4 Two-stage retrieval pattern (LOW PRIORITY — already partial)

**Their approach:** BM25 lexical filter → GPT-4 semantic re-rank in batches of 50.

**RAF application:**
- We already do this implicitly (SQL filter → display).
- Formalize when LLM costs/latency become a bottleneck:
  - SQL: candidate HCCs from claims/labs/problems
  - LLM: rank only top-N for MEAT readiness
- Not urgent until we have >100 candidate suspects per patient.

---

### 2.5 Structured prompt scaffolding (MEDIUM PRIORITY)

**Their approach:** Prompt template with explicit slots for:
1. Task description
2. Decision categories with definitions
3. Scoring rubric (0/1/2) with examples
4. Output format (table with `Criterion No. | Criterion Name | Score`)
5. Disorder-specific guidance

**RAF application:**
- Reuse this *structure* for our MEAT scoring prompt.
- Per-HCC guidance (analogous to per-disorder) — e.g., diabetes wants A1c trend, CHF wants ejection fraction.
- Force tabular output → easier to parse, easier to audit.

**Do NOT copy:** their exact prompt text. It is tuned for trial-criterion semantics, not HCC documentation. Copy the skeleton, write our own slots.

---

## 3. What we are explicitly NOT doing

- **Bolting on clinical-trial matching as a new tab.** Different buyer, different workflow, different compliance surface. Scope creep that dilutes the product story. Revisit only if a customer asks.
- **Adopting BM25 / Pyserini.** We are not building a retrieval system over millions of documents; OpenEMR + our DB is small enough that SQL + targeted LLM passes is simpler.
- **Their evaluation harness (TREC).** Useful only if we publish or benchmark externally.

---

## 4. Implementation order (rough)

1. **Knowledge mappings table + suspect-detection expansion** (1–2 weeks)
   - Highest ROI, smallest blast radius, easiest to A/B test
2. **MEAT 0/1/2 per-letter scoring** (1 week)
   - Backend column + scoring prompt + UI chips
3. **"Needs info" suspect state + MEAT-letter wire-up** (3–5 days)
   - Mostly endpoint + UI work; reuses existing MEAT infra
4. **Per-HCC prompt guidance** (ongoing — add as we observe failures)

---

## 5. Risks / open questions

- **Knowledge-mapping curation cost.** Paper used clinical experts. We may need to bootstrap from UMLS / ICD-10-CM index rather than hand-curate per HCC.
- **GPT-4 cost at scale.** Their batch-of-50 pattern suggests cost was real even for them. We need to confirm Bedrock / OpenAI per-suspect cost is acceptable before rolling out 0/1/2 scoring on every suspect.
- **Score calibration.** "1 = partial match" is fuzzy. Need a small held-out set of provider-verified MEAT scores to validate the LLM's 0/1/2 calls before showing them in production.
- **Audit trail.** CMS-RADV defensibility requires we can show *why* a suspect was flagged. Knowledge-mapping expansion must be logged (which synonym matched, from which mapping table, which version).

---

## 6. References

- Paper PDF: `/Users/murali/Desktop/1-s2.0-S2352914825000036-main.pdf`
- Related internal docs:
  - `docs/research/NLP_AI_HCC_Risk_Adjustment_Research.md`
  - `docs/research/clinical_nlp_optimization_guide.md`
  - `docs/research/ICD-10-CM_to_HCC_Mapping_Research.md`
  - `docs/MULTI_STAGE_PIPELINE_DESIGN.md`
