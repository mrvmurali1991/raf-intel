"""
KG-first accuracy benchmark.

Three modes:
    llm-only   — predictions come from `_run_llm_only(chart)`
                  (Gemini in production; in tests / mock mode it is
                  routed through a stub).
    kg-first   — predictions come from kg_lookup_service.patient_full_inference,
                  then the LLM augments with anything the KG missed.
    hybrid     — KG and LLM both run independently; predictions are unioned
                  and de-duplicated.

Metrics:
    Macro & micro precision / recall / F1
    Per-HCC P/R/F1 (rolled up across charts)
    Per-evidence-type breakdown (medication, lab, problem_list_chain, recapture, llm)

The Gemini caller is exposed as `_gemini_predict` so tests can monkey-patch
it; nothing here calls the network unless `_gemini_predict` is wired to a
real backend.  Call `run_kg_benchmark(..., gemini_caller=...)` to inject a
deterministic substitute (mock-mode benchmarks).
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from app.services.evaluation import kg_lookup_service


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

VALID_MODES = ("llm-only", "kg-first", "hybrid")


def _gemini_predict(chart: dict[str, Any]) -> list[dict[str, Any]]:
    """Default LLM predictor.

    Production wiring lives in `app.services.skill_pipeline.run_pipeline`.
    The benchmark deliberately keeps that import optional so the harness
    can run in CI without a `GOOGLE_API_KEY`.  When Gemini is unavailable,
    the harness expects callers to pass a substitute via `gemini_caller`.
    """
    raise RuntimeError(
        "Real Gemini caller not wired. Pass `gemini_caller=` to run_kg_benchmark "
        "or use mock mode."
    )


# ---------------------------------------------------------------------------
# Mock predictor used by tests and offline benchmark runs
# ---------------------------------------------------------------------------

def mock_gemini_caller(chart: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic substitute for the LLM.

    Each fixture carries an `llm_mock` field that lists the HCCs the
    LLM is expected to surface for the chart along with confidence.
    The structure mirrors what the real Gemini path returns after
    post-processing: a list of {icd10, hcc, confidence, source}.

    Charts that lack `llm_mock` fall back to an empty list, modelling
    a cautious LLM that abstains.
    """
    items = chart.get("llm_mock") or []
    out: list[dict[str, Any]] = []
    for item in items:
        out.append({
            "icd10": item.get("icd10", ""),
            "hcc": str(item.get("hcc", "")).strip(),
            "confidence": float(item.get("confidence", 0.7)),
            "source": "llm",
            "evidence_type": "llm",
            "evidence": item.get("evidence", {}),
        })
    return out


# ---------------------------------------------------------------------------
# Per-mode prediction
# ---------------------------------------------------------------------------

def _kg_predict(chart: dict[str, Any]) -> list[dict[str, Any]]:
    res = kg_lookup_service.patient_full_inference(chart)
    return list(res.get("predictions") or [])


def _merge_predictions(*lists: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by HCC, keeping the highest-confidence record and
    accumulating evidence_types from every contributor."""
    by_hcc: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for rec in lst:
            hcc = (rec.get("hcc") or "").strip()
            if not hcc:
                continue
            etype = rec.get("evidence_type") or rec.get("source") or "unknown"
            existing = by_hcc.get(hcc)
            if existing is None:
                merged = dict(rec)
                merged["evidence_types"] = sorted(
                    set(rec.get("evidence_types") or [etype])
                )
                by_hcc[hcc] = merged
            else:
                if rec.get("confidence", 0) > existing.get("confidence", 0):
                    existing["confidence"] = rec["confidence"]
                    existing["source"] = rec.get("source", existing.get("source"))
                existing["evidence_types"] = sorted(
                    set(existing.get("evidence_types", [])) |
                    set(rec.get("evidence_types") or [etype])
                )
    return list(by_hcc.values())


def predict_for_chart(
    chart: dict[str, Any],
    mode: str,
    gemini_caller: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Return predictions for one chart under the chosen mode."""
    if mode == "llm-only":
        return _merge_predictions(gemini_caller(chart))
    if mode == "kg-first":
        kg = _kg_predict(chart)
        kg_hccs = {p["hcc"] for p in kg}
        # KG-first: trust KG, then ask the LLM for the GAP (anything not
        # already surfaced).  We pass the chart unchanged; in production,
        # the pipeline informs the LLM which HCCs are already covered so
        # it focuses on novel ones.  For evaluation purposes we union and
        # let dedup take care of overlaps.
        llm = [p for p in gemini_caller(chart) if p.get("hcc") not in kg_hccs]
        return _merge_predictions(kg, llm)
    if mode == "hybrid":
        kg = _kg_predict(chart)
        llm = gemini_caller(chart)
        return _merge_predictions(kg, llm)
    raise ValueError(f"Unknown mode: {mode!r}. Choose from {VALID_MODES}")


# ---------------------------------------------------------------------------
# Metric math
# ---------------------------------------------------------------------------

def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def _safe_div(n: float, d: float) -> float:
    return n / d if d > 0 else 0.0


def _platt_fit(
    samples: list[tuple[float, int]],
    n_iter: int = 200,
    lr: float = 0.05,
) -> tuple[float, float]:
    # Fit Platt scaling: a logistic regression of observed outcome on raw
    # confidence.  Calibrated probability = sigmoid(A * raw + B).
    # Stdlib-only gradient descent so we don't need scipy in this layer.
    if not samples:
        return 1.0, 0.0
    a, b = 1.0, 0.0
    n = len(samples)
    for _ in range(n_iter):
        ga, gb = 0.0, 0.0
        for raw, y in samples:
            z = a * raw + b
            # numerically stable sigmoid
            if z >= 0:
                ez = math.exp(-z)
                p = 1.0 / (1.0 + ez)
            else:
                ez = math.exp(z)
                p = ez / (1.0 + ez)
            err = p - y
            ga += err * raw
            gb += err
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def _platt_apply(raw: float, a: float, b: float) -> float:
    z = a * raw + b
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _brier_score(samples: list[tuple[float, int]]) -> float:
    # Mean squared error between predicted probability and actual outcome
    # (1 = HCC was in gold, 0 = HCC was not). Lower is better; 0.0 is
    # perfect calibration, 0.25 is the chance baseline for binary outcomes.
    if not samples:
        return 0.0
    return sum((p - y) ** 2 for p, y in samples) / len(samples)


def _reliability_bins(
    samples: list[tuple[float, int]],
    n_bins: int = 10,
) -> list[dict[str, Any]]:
    # Group predictions into equal-width confidence bins and report observed
    # accuracy per bin.  A well-calibrated classifier has bin midpoint ≈
    # observed accuracy across all bins.  Used to compute ECE.
    if not samples:
        return []
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for conf, y in samples:
        idx = min(int(conf * n_bins), n_bins - 1)
        bins[idx].append((conf, y))
    rows = []
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        observed = sum(y for _, y in bucket) / len(bucket)
        rows.append({
            "bin_lower": round(i / n_bins, 2),
            "bin_upper": round((i + 1) / n_bins, 2),
            "count": len(bucket),
            "avg_confidence": round(avg_conf, 4),
            "observed_accuracy": round(observed, 4),
            "gap": round(avg_conf - observed, 4),
        })
    return rows


def _expected_calibration_error(
    samples: list[tuple[float, int]],
    n_bins: int = 10,
) -> float:
    # Weighted average of |confidence - accuracy| across bins.  0.0 means
    # the model knows what it knows; >0.10 is significant miscalibration.
    if not samples:
        return 0.0
    total = len(samples)
    ece = 0.0
    for row in _reliability_bins(samples, n_bins):
        weight = row["count"] / total
        ece += weight * abs(row["gap"])
    return ece


def _per_class_pr_f1(
    tp_by_cls: dict[str, int],
    fp_by_cls: dict[str, int],
    fn_by_cls: dict[str, int],
) -> list[dict[str, Any]]:
    classes = sorted(set(tp_by_cls) | set(fp_by_cls) | set(fn_by_cls))
    rows = []
    for c in classes:
        tp = tp_by_cls.get(c, 0)
        fp = fp_by_cls.get(c, 0)
        fn = fn_by_cls.get(c, 0)
        p = _safe_div(tp, tp + fp)
        r = _safe_div(tp, tp + fn)
        rows.append({
            "key": c,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(_f1(p, r), 4),
            "support": tp + fn,
        })
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_fixtures(fixture_path: str | Path) -> list[dict[str, Any]]:
    """Load and validate the fixture JSON file."""
    path = Path(fixture_path)
    if not path.exists():
        raise FileNotFoundError(f"Fixture file not found: {path}")
    raw = json.loads(path.read_text())
    charts = raw.get("charts") if isinstance(raw, dict) else raw
    if not isinstance(charts, list):
        raise ValueError("Fixture file must contain a list of charts (or {'charts': [...]})")
    for i, chart in enumerate(charts):
        if "id" not in chart:
            raise ValueError(f"Chart at index {i} missing required field 'id'")
        if "gold_hccs" not in chart:
            raise ValueError(f"Chart {chart.get('id')} missing required field 'gold_hccs'")
    return charts


def run_kg_benchmark(
    fixture_path: str | Path,
    mode: str = "kg-first",
    gemini_caller: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the benchmark and return a metrics report.

    Args:
        fixture_path:    Path to a JSON file with the charts.
        mode:            One of {'llm-only', 'kg-first', 'hybrid'}.
        gemini_caller:   Optional function used in place of the real LLM.
                         Defaults to `mock_gemini_caller`, which reads the
                         fixture's `llm_mock` field.

    Returns:
        Dict with the structure documented in the task spec.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown mode: {mode!r}. Choose from {VALID_MODES}")

    charts = load_fixtures(fixture_path)
    caller = gemini_caller or mock_gemini_caller

    total_tp = total_fp = total_fn = 0
    per_chart: list[dict[str, Any]] = []

    tp_by_hcc: dict[str, int] = defaultdict(int)
    fp_by_hcc: dict[str, int] = defaultdict(int)
    fn_by_hcc: dict[str, int] = defaultdict(int)

    tp_by_etype: dict[str, int] = defaultdict(int)
    fp_by_etype: dict[str, int] = defaultdict(int)
    # FNs cannot be tied to an evidence_type (we missed them entirely),
    # so we attribute them to a synthetic "uncovered" bucket as well as
    # report them in by_hcc.

    chart_p_sum = 0.0
    chart_r_sum = 0.0
    chart_count_with_gold = 0

    # (predicted_confidence, actual_outcome) pairs for calibration metrics.
    # actual_outcome is 1 if the predicted HCC was in gold, else 0.
    calibration_samples: list[tuple[float, int]] = []

    t0 = time.perf_counter()
    for chart in charts:
        gold = {str(h).strip() for h in (chart.get("gold_hccs") or []) if str(h).strip()}
        preds = predict_for_chart(chart, mode, caller)
        pred_hccs = {p["hcc"] for p in preds}

        tp_set = pred_hccs & gold
        fp_set = pred_hccs - gold
        fn_set = gold - pred_hccs

        tp = len(tp_set)
        fp = len(fp_set)
        fn = len(fn_set)
        total_tp += tp
        total_fp += fp
        total_fn += fn

        for hcc in tp_set:
            tp_by_hcc[hcc] += 1
        for hcc in fp_set:
            fp_by_hcc[hcc] += 1
        for hcc in fn_set:
            fn_by_hcc[hcc] += 1

        for p in preds:
            etype = (p.get("evidence_types") or [p.get("evidence_type") or "unknown"])[0]
            in_gold = 1 if p["hcc"] in gold else 0
            if in_gold:
                tp_by_etype[etype] += 1
            else:
                fp_by_etype[etype] += 1
            # Calibration: pair the model's stated confidence with the
            # actual outcome.  Default 0.5 if a prediction lacks confidence
            # so the baseline at least lands at chance.
            conf = float(p.get("confidence") or 0.5)
            calibration_samples.append((max(0.0, min(1.0, conf)), in_gold))
        for hcc in fn_set:
            fp_by_etype  # no-op: we keep FN bucket separate from etype precision math

        # Per-chart precision/recall (used for macro averaging)
        if gold:
            chart_count_with_gold += 1
            chart_p_sum += _safe_div(tp, tp + fp)
            chart_r_sum += _safe_div(tp, tp + fn)

        per_chart.append({
            "chart_id": chart.get("id"),
            "gold_hccs": sorted(gold),
            "predicted_hccs": sorted(pred_hccs),
            "tp": sorted(tp_set),
            "fp": sorted(fp_set),
            "fn": sorted(fn_set),
            "precision": round(_safe_div(tp, tp + fp), 4),
            "recall": round(_safe_div(tp, tp + fn), 4),
        })
    runtime = time.perf_counter() - t0

    micro_p = _safe_div(total_tp, total_tp + total_fp)
    micro_r = _safe_div(total_tp, total_tp + total_fn)
    micro_f1 = _f1(micro_p, micro_r)

    macro_p = _safe_div(chart_p_sum, chart_count_with_gold)
    macro_r = _safe_div(chart_r_sum, chart_count_with_gold)
    macro_f1 = _f1(macro_p, macro_r)

    by_hcc = _per_class_pr_f1(tp_by_hcc, fp_by_hcc, fn_by_hcc)

    # by_evidence_type: precision only (no FN attribution); recall is N/A here.
    etypes = sorted(set(tp_by_etype) | set(fp_by_etype))
    by_evidence_type = []
    for et in etypes:
        tp = tp_by_etype.get(et, 0)
        fp = fp_by_etype.get(et, 0)
        by_evidence_type.append({
            "evidence_type": et,
            "true_positives": tp,
            "false_positives": fp,
            "precision": round(_safe_div(tp, tp + fp), 4),
        })

    total_predictions = sum(len(c["predicted_hccs"]) for c in per_chart)

    brier = _brier_score(calibration_samples)
    ece = _expected_calibration_error(calibration_samples)
    reliability = _reliability_bins(calibration_samples)

    # Platt-scaling fit: learn (A, B) such that calibrated = sigmoid(A*raw + B).
    # Apply to the same samples and re-measure Brier + ECE — this is the
    # post-hoc calibrated version of the model.  In production deployment
    # the (A, B) fit on a held-out validation set would be persisted and
    # applied to every new prediction.
    platt_a, platt_b = _platt_fit(calibration_samples)
    calibrated_samples = [
        (_platt_apply(raw, platt_a, platt_b), y) for raw, y in calibration_samples
    ]
    brier_calibrated = _brier_score(calibrated_samples)
    ece_calibrated = _expected_calibration_error(calibrated_samples)
    reliability_calibrated = _reliability_bins(calibrated_samples)

    return {
        "mode": mode,
        "fixture_path": str(fixture_path),
        "charts_processed": len(charts),
        "total_predictions": total_predictions,
        "true_positives": total_tp,
        "false_positives": total_fp,
        "false_negatives": total_fn,
        # Headline numbers — micro is what we report externally.
        "precision": round(micro_p, 4),
        "recall": round(micro_r, 4),
        "f1": round(micro_f1, 4),
        "macro_precision": round(macro_p, 4),
        "macro_recall": round(macro_r, 4),
        "macro_f1": round(macro_f1, 4),
        "micro_precision": round(micro_p, 4),
        "micro_recall": round(micro_r, 4),
        "micro_f1": round(micro_f1, 4),
        "by_hcc": by_hcc,
        "by_evidence_type": by_evidence_type,
        "per_chart": per_chart,
        "runtime_seconds": round(runtime, 4),
        # Calibration block — turns the confidence floats into a number a
        # CMO/QA reviewer can interpret.  Brier 0.0 = perfect; 0.25 = chance
        # baseline for binary outcomes.  ECE > 0.10 = significant
        # miscalibration that should be flagged in the demo deck.
        # The "calibrated" sub-block reports the same metrics after Platt
        # scaling — the lift in Brier/ECE shows how much trust we recover.
        "calibration": {
            "brier_score": round(brier, 4),
            "expected_calibration_error": round(ece, 4),
            "sample_count": len(calibration_samples),
            "reliability_bins": reliability,
            "calibrated": {
                "method": "platt_scaling",
                "params": {"a": round(platt_a, 4), "b": round(platt_b, 4)},
                "brier_score": round(brier_calibrated, 4),
                "expected_calibration_error": round(ece_calibrated, 4),
                "reliability_bins": reliability_calibrated,
                "ece_improvement": round(ece - ece_calibrated, 4),
                "brier_improvement": round(brier - brier_calibrated, 4),
            },
        },
    }


# ---------------------------------------------------------------------------
# Markdown report renderer
# ---------------------------------------------------------------------------

def render_markdown_report(
    *,
    fixture_path: str | Path,
    fixture_count: int,
    results_by_mode: dict[str, dict[str, Any]],
    mock_mode: bool,
    headline_mode: str = "kg-first",
) -> str:
    """Render the documented Markdown report."""
    fp = Path(fixture_path).name
    head = results_by_mode[headline_mode]

    summary_one_liner = (
        f"RAF Intelligence achieves {head['precision']*100:.1f}% precision / "
        f"{head['recall']*100:.1f}% recall / {head['f1']:.2f} F1 on N={fixture_count} "
        f"synthetic MA charts under {headline_mode} mode."
    )

    mock_banner = (
        "> NOTE: This benchmark was executed in **mock mode** (no live Gemini calls). "
        "LLM predictions come from a deterministic stub that reads the `llm_mock` "
        "field on each fixture. Numbers are reproducible but reflect the stub's "
        "calibrated performance, not a production Gemini run."
    ) if mock_mode else (
        "> Benchmark executed against the live Gemini API."
    )

    # Mode comparison table
    mode_rows = ["| Mode | Charts | Precision | Recall | F1 | Macro F1 | Runtime (s) |",
                 "|---|---|---|---|---|---|---|"]
    for m in ("kg-first", "llm-only", "hybrid"):
        if m not in results_by_mode:
            continue
        r = results_by_mode[m]
        mode_rows.append(
            f"| {m} | {r['charts_processed']} | {r['precision']:.3f} | "
            f"{r['recall']:.3f} | {r['f1']:.3f} | {r['macro_f1']:.3f} | "
            f"{r['runtime_seconds']:.3f} |"
        )

    # Per-HCC top 20 (by support, descending)
    sorted_by_support = sorted(head["by_hcc"], key=lambda r: -r["support"])[:20]
    hcc_rows = ["| HCC | Support | TP | FP | FN | Precision | Recall | F1 |",
                "|---|---|---|---|---|---|---|---|"]
    for r in sorted_by_support:
        hcc_rows.append(
            f"| {r['key']} | {r['support']} | {r['true_positives']} | "
            f"{r['false_positives']} | {r['false_negatives']} | "
            f"{r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} |"
        )

    # by evidence_type for headline mode
    et_rows = ["| Evidence Type | TP | FP | Precision |", "|---|---|---|---|"]
    for r in head["by_evidence_type"]:
        et_rows.append(
            f"| {r['evidence_type']} | {r['true_positives']} | "
            f"{r['false_positives']} | {r['precision']:.3f} |"
        )

    md = f"""# RAF Intelligence — Accuracy Benchmark (2026)

## Executive Summary

**{summary_one_liner}**

{mock_banner}

| Metric | Value |
|---|---|
| Mode (headline) | `{headline_mode}` |
| Charts evaluated | {head['charts_processed']} |
| Total predictions | {head['total_predictions']} |
| True positives | {head['true_positives']} |
| False positives | {head['false_positives']} |
| False negatives | {head['false_negatives']} |
| Precision (micro) | {head['precision']:.3f} |
| Recall (micro) | {head['recall']:.3f} |
| F1 (micro) | {head['f1']:.3f} |
| F1 (macro, per-chart avg) | {head['macro_f1']:.3f} |
| Wall-clock runtime | {head['runtime_seconds']:.2f} s |

## Methodology

- **Fixture**: `{fp}` ({fixture_count} synthetic Medicare Advantage charts).
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

{chr(10).join(mode_rows)}

## Per-HCC Performance (top 20 by support, headline mode = `{headline_mode}`)

{chr(10).join(hcc_rows)}

## By Evidence Type (headline mode = `{headline_mode}`)

{chr(10).join(et_rows)}

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
"""
    return md
