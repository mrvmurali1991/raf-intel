# RAF Intelligence — Accuracy Benchmark (2026)

## Executive Summary

**RAF Intelligence achieves 84.8% precision / 100.0% recall / 0.92 F1 on N=52 synthetic MA charts under kg-first mode.**

> NOTE: This benchmark was executed in **mock mode** (no live Gemini calls). LLM predictions come from a deterministic stub that reads the `llm_mock` field on each fixture. Numbers are reproducible but reflect the stub's calibrated performance, not a production Gemini run.

| Metric | Value |
|---|---|
| Mode (headline) | `kg-first` |
| Charts evaluated | 52 |
| Total predictions | 79 |
| True positives | 67 |
| False positives | 12 |
| False negatives | 0 |
| Precision (micro) | 0.848 |
| Recall (micro) | 1.000 |
| F1 (micro) | 0.918 |
| F1 (macro, per-chart avg) | 0.955 |
| Wall-clock runtime | 0.00 s |

## Methodology

- **Fixture**: `extended_charts.json` (52 synthetic Medicare Advantage charts).
  Charts are not derived from real PHI; they were authored to mirror the
  most common HCC categories (DM, CKD, HF, COPD, dementia, cancer history,
  major depression-vs-bipolar, schizophrenia, AFib, drug-use disorders).
- **Ground truth**: each chart's `gold_hccs` field is the expert-labeled
  set of HCCs that should be coded if the chart were a real audit. Labels
  reflect CMS-HCC V28 (2026 model files).
- **Modes evaluated**:
  - `llm-only` — current Gemini-only path (production baseline).
  - `kg-first` — `kg_lookup_service.patient_full_inference` runs first,
    then the LLM augments with anything missed (de-duplicated union).
  - `hybrid` — both run independently; predictions are unioned.
- **Metric definitions**:
  - HCC-level set comparison per chart.
  - Micro P/R/F1: pool TPs/FPs/FNs across charts, compute once.
  - Macro P/R/F1: per-chart P/R, averaged uniformly.

## Mode Comparison

| Mode | Charts | Precision | Recall | F1 | Macro F1 | Runtime (s) |
|---|---|---|---|---|---|---|
| kg-first | 52 | 0.848 | 1.000 | 0.918 | 0.955 | 0.001 |
| llm-only | 52 | 1.000 | 0.955 | 0.977 | 0.978 | 0.000 |
| hybrid | 52 | 0.848 | 1.000 | 0.918 | 0.955 | 0.001 |

## Per-HCC Performance (top 20 by support, headline mode = `kg-first`)

| HCC | Support | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| 226 | 8 | 8 | 2 | 0 | 0.800 | 1.000 | 0.889 |
| 238 | 8 | 8 | 1 | 0 | 0.889 | 1.000 | 0.941 |
| 127 | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 280 | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 37 | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 38 | 6 | 6 | 7 | 0 | 0.462 | 1.000 | 0.632 |
| 327 | 5 | 5 | 2 | 0 | 0.714 | 1.000 | 0.833 |
| 137 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 151 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 154 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 18 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 19 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 326 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 383 | 3 | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| 224 | 1 | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 |

## By Evidence Type (headline mode = `kg-first`)

| Evidence Type | TP | FP | Precision |
|---|---|---|---|
| historical_hcc_gap | 12 | 0 | 1.000 |
| lab | 18 | 7 | 0.720 |
| llm | 5 | 0 | 1.000 |
| medication | 24 | 5 | 0.828 |
| problem_list_chain | 8 | 0 | 1.000 |

## Limitations

1. **Synthetic data only.** All fixtures are author-constructed; they do
   not contain PHI and have not been independently labeled by an external
   coder.  Inter-rater reliability is therefore not measured.
2. **CMS-HCC V28 only.** Numbers do not generalize to V24 or V21
   models; some prevalent ICD-10 codes (Parkinson's, hypertension,
   hyperlipidemia, anemia of CKD) do not map to V28 HCCs and are excluded
   from the benchmark.
3. **N=50 charts is statistically thin.** Confidence intervals around
   per-HCC numbers are wide, especially for rare HCCs (support ≤ 3).
4. **Mock-mode caveat.** When the real Gemini API is unavailable, the
   `llm-only` line of the comparison table is approximated by the
   `llm_mock` field on each fixture rather than measured. Each fixture's
   `llm_mock` was authored to reflect the LLM's typical behavior on a
   chart of that complexity, but it is not a substitute for a live run.

## Roadmap to Scale

- **Q1 2027** — partner with two MA-focused IPAs to label 1,000 real
  charts under BAA. Re-run benchmark; publish point estimates with 95%
  Wilson intervals.
- **Q2 2027** — peer-validated study with two CCS-P/CRC certified
  external coders; report Cohen's kappa for inter-coder agreement and
  agreement vs RAF Intelligence.
- **Q3 2027** — production-shadow benchmark: run KG-first against live
  prospective panels for 90 days, compare predicted gaps to gaps
  ultimately closed by the provider. Publish realized RAF lift.
