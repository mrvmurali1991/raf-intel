"""
Tests for the KG-first accuracy benchmark.

Covers:
  * metric math (precision/recall/F1, micro vs macro)
  * mode wiring (llm-only / kg-first / hybrid)
  * fixture loader (happy path + validation errors)
  * KG lookup service basics (med, lab, problem-list, recapture)
  * Markdown report rendering

No real Gemini calls; no DB calls.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

# `hccinfhir` (a transitive import) calls `importlib.resources.path()`,
# which is deprecated in 3.12 and emits a DeprecationWarning at import time.
# Our pytest.ini turns DeprecationWarning into errors globally, which would
# block collection for this module.  Suppress just that one warning.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*path is deprecated.*",
)

import pytest

# Belt-and-braces for collection-time imports.
pytestmark = [
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]

from app.services.evaluation import kg_benchmark, kg_lookup_service


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "app/services/evaluation/fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_fixture(tmp_path: Path, charts: list[dict]) -> Path:
    p = tmp_path / "charts.json"
    p.write_text(json.dumps({"version": "test", "charts": charts}))
    return p


def _stub_caller(predictions_per_chart: dict[str, list[dict]]):
    """Return a Gemini stub that emits the given predictions per chart id."""
    def caller(chart):
        return predictions_per_chart.get(chart["id"], [])
    return caller


# ---------------------------------------------------------------------------
# 1. Metric math
# ---------------------------------------------------------------------------

def test_perfect_predictions_yield_f1_one(tmp_path):
    charts = [
        {"id": "a", "gold_hccs": ["38"], "llm_mock": [{"icd10": "E119", "hcc": "38", "confidence": 0.9}]},
        {"id": "b", "gold_hccs": ["226"], "llm_mock": [{"icd10": "I5022", "hcc": "226", "confidence": 0.9}]},
    ]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="llm-only")
    assert res["precision"] == 1.0
    assert res["recall"] == 1.0
    assert res["f1"] == 1.0
    assert res["true_positives"] == 2
    assert res["false_positives"] == 0
    assert res["false_negatives"] == 0


def test_all_misses_yield_zero(tmp_path):
    charts = [{"id": "a", "gold_hccs": ["38"], "llm_mock": []}]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="llm-only")
    assert res["precision"] == 0.0
    assert res["recall"] == 0.0
    assert res["f1"] == 0.0
    assert res["false_negatives"] == 1


def test_partial_match_metrics(tmp_path):
    # Predicted {38, 226}, gold {38, 127}.  TP=1, FP=1 (226), FN=1 (127)
    charts = [{
        "id": "a", "gold_hccs": ["38", "127"],
        "llm_mock": [{"icd10": "E119", "hcc": "38", "confidence": 0.9},
                     {"icd10": "I5022", "hcc": "226", "confidence": 0.9}],
    }]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="llm-only")
    assert res["true_positives"] == 1
    assert res["false_positives"] == 1
    assert res["false_negatives"] == 1
    # precision = 1/2 = 0.5, recall = 1/2 = 0.5, F1 = 0.5
    assert res["precision"] == 0.5
    assert res["recall"] == 0.5
    assert res["f1"] == 0.5


def test_macro_vs_micro_differ_with_class_imbalance(tmp_path):
    # Chart A: 1 gold HCC, perfect prediction -> per-chart P=R=1
    # Chart B: 4 gold HCCs, none predicted -> per-chart P=R=0
    charts = [
        {"id": "a", "gold_hccs": ["38"],
         "llm_mock": [{"icd10": "E119", "hcc": "38", "confidence": 0.9}]},
        {"id": "b", "gold_hccs": ["127", "226", "238", "280"], "llm_mock": []},
    ]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="llm-only")
    # micro: TP=1, FP=0, FN=4 → P=1.0, R=0.2
    assert res["micro_precision"] == 1.0
    assert res["micro_recall"] == 0.2
    # macro: avg of (1.0, 0.0) = 0.5
    assert res["macro_precision"] == 0.5
    assert res["macro_recall"] == 0.5


# ---------------------------------------------------------------------------
# 2. Mode wiring
# ---------------------------------------------------------------------------

def test_llm_only_uses_only_mock(tmp_path):
    # KG would predict HCC 38 from metformin, but llm-only mode ignores KG
    charts = [{
        "id": "a", "gold_hccs": ["38"],
        "medications": [{"drug": "Metformin"}],
        "llm_mock": [],
    }]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="llm-only")
    assert res["true_positives"] == 0
    assert res["false_negatives"] == 1


def test_kg_first_uses_kg_when_llm_silent(tmp_path):
    # llm_mock is empty; KG must surface HCC 38 from metformin
    charts = [{
        "id": "a", "gold_hccs": ["38"],
        "medications": [{"drug": "Metformin"}],
        "llm_mock": [],
    }]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="kg-first")
    assert res["true_positives"] == 1
    assert res["false_negatives"] == 0
    # evidence_type should record medication
    etypes = {e["evidence_type"] for e in res["by_evidence_type"]}
    assert "medication" in etypes


def test_hybrid_unions_both(tmp_path):
    # KG picks 38 from metformin; LLM picks 127 from note.  Hybrid -> both.
    charts = [{
        "id": "a", "gold_hccs": ["38", "127"],
        "medications": [{"drug": "Metformin"}],
        "llm_mock": [{"icd10": "G309", "hcc": "127", "confidence": 0.85}],
    }]
    fp = _write_fixture(tmp_path, charts)
    res = kg_benchmark.run_kg_benchmark(fp, mode="hybrid")
    assert res["true_positives"] == 2
    assert res["false_negatives"] == 0


def test_invalid_mode_rejected(tmp_path):
    fp = _write_fixture(tmp_path, [{"id": "a", "gold_hccs": []}])
    with pytest.raises(ValueError):
        kg_benchmark.run_kg_benchmark(fp, mode="bogus-mode")


# ---------------------------------------------------------------------------
# 3. Fixture loader
# ---------------------------------------------------------------------------

def test_load_fixtures_happy_path():
    charts = kg_benchmark.load_fixtures(FIXTURE_DIR / "extended_charts.json")
    assert len(charts) >= 50
    assert all("id" in c and "gold_hccs" in c for c in charts)


def test_load_fixtures_rejects_missing_id(tmp_path):
    fp = _write_fixture(tmp_path, [{"gold_hccs": []}])
    with pytest.raises(ValueError, match="missing required field 'id'"):
        kg_benchmark.load_fixtures(fp)


def test_load_fixtures_rejects_missing_gold(tmp_path):
    fp = tmp_path / "charts.json"
    fp.write_text(json.dumps({"charts": [{"id": "a"}]}))
    with pytest.raises(ValueError, match="missing required field 'gold_hccs'"):
        kg_benchmark.load_fixtures(fp)


def test_load_fixtures_missing_file():
    with pytest.raises(FileNotFoundError):
        kg_benchmark.load_fixtures("/tmp/does-not-exist-xyz.json")


def test_load_fixtures_accepts_bare_list(tmp_path):
    fp = tmp_path / "bare.json"
    fp.write_text(json.dumps([{"id": "a", "gold_hccs": []}]))
    charts = kg_benchmark.load_fixtures(fp)
    assert charts[0]["id"] == "a"


# ---------------------------------------------------------------------------
# 4. KG lookup service
# ---------------------------------------------------------------------------

def test_kg_medication_signal_metformin():
    res = kg_lookup_service.patient_full_inference({
        "id": "x", "medications": [{"drug": "metformin 500"}],
        "gold_hccs": [],
    })
    assert "38" in res["predicted_hccs"]


def test_kg_lab_signal_egfr_stage_4():
    res = kg_lookup_service.patient_full_inference({
        "id": "x", "labs": [{"name": "eGFR", "value": 25}], "gold_hccs": [],
    })
    assert "327" in res["predicted_hccs"]


def test_kg_problem_list_dm_neuropathy_chain():
    res = kg_lookup_service.patient_full_inference({
        "id": "x",
        "problem_list": [{"diagnosis": "E119", "title": "diabetes"}],
        "note_text": "patient reports diabetic polyneuropathy of feet",
        "gold_hccs": [],
    })
    assert "37" in res["predicted_hccs"]


def test_kg_recapture_gap_emitted():
    res = kg_lookup_service.patient_full_inference({
        "id": "x",
        "prior_year_hccs": ["280"],
        "current_year_hccs": [],
        "gold_hccs": [],
    })
    assert "280" in res["predicted_hccs"]
    sources = {p["source"] for p in res["predictions"]}
    assert "recapture" in sources


def test_kg_drops_predictions_without_v28_hcc():
    # G20 (Parkinson's) does not map to a V28 HCC. Even if a rule fires,
    # the prediction should be dropped at the HCC level.
    res = kg_lookup_service.patient_full_inference({
        "id": "x",
        "problem_list": [{"diagnosis": "G20", "title": "Parkinson disease"}],
        "gold_hccs": [],
    })
    # No HCC should be predicted
    assert res["predicted_hccs"] == []


# ---------------------------------------------------------------------------
# 5. Custom gemini caller injection
# ---------------------------------------------------------------------------

def test_custom_gemini_caller_is_used(tmp_path):
    charts = [{"id": "a", "gold_hccs": ["38"], "llm_mock": []}]
    fp = _write_fixture(tmp_path, charts)
    caller = _stub_caller({"a": [{"hcc": "38", "icd10": "E119", "confidence": 0.9,
                                   "source": "llm", "evidence_type": "llm"}]})
    res = kg_benchmark.run_kg_benchmark(fp, mode="llm-only", gemini_caller=caller)
    assert res["true_positives"] == 1


# ---------------------------------------------------------------------------
# 6. End-to-end on extended fixtures
# ---------------------------------------------------------------------------

def test_extended_fixture_runs_all_modes_without_error():
    fp = FIXTURE_DIR / "extended_charts.json"
    for mode in ("llm-only", "kg-first", "hybrid"):
        res = kg_benchmark.run_kg_benchmark(fp, mode=mode)
        assert res["charts_processed"] >= 50
        # bounds sanity
        assert 0.0 <= res["precision"] <= 1.0
        assert 0.0 <= res["recall"] <= 1.0
        assert 0.0 <= res["f1"] <= 1.0


def test_kg_first_beats_llm_only_or_matches_on_recall():
    """KG-first should never lose recall vs llm-only on the extended set:
    KG-first is a strict superset of llm-only's prediction power."""
    fp = FIXTURE_DIR / "extended_charts.json"
    llm = kg_benchmark.run_kg_benchmark(fp, mode="llm-only")
    kg  = kg_benchmark.run_kg_benchmark(fp, mode="kg-first")
    assert kg["recall"] >= llm["recall"] - 1e-9


# ---------------------------------------------------------------------------
# 7. Markdown report
# ---------------------------------------------------------------------------

def test_render_markdown_report_contains_required_sections(tmp_path):
    fp = FIXTURE_DIR / "extended_charts.json"
    res = {m: kg_benchmark.run_kg_benchmark(fp, mode=m)
           for m in ("kg-first", "llm-only", "hybrid")}
    md = kg_benchmark.render_markdown_report(
        fixture_path=fp, fixture_count=len(kg_benchmark.load_fixtures(fp)),
        results_by_mode=res, mock_mode=True, headline_mode="kg-first",
    )
    for section in ("Executive Summary", "Methodology", "Mode Comparison",
                    "Per-HCC Performance", "Limitations", "Roadmap"):
        assert section in md
    # Mock-mode banner present
    assert "mock mode" in md
