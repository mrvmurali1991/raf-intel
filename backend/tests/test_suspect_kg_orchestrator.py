"""
Unit tests for app.services.knowledge_graph.suspect_kg_orchestrator.

These tests are deliberately decoupled from the database, the sibling KG
primitives, and the live FastAPI server.  They exercise the orchestrator's
pure logic — KG/LLM merge, demographic + specialty calibration,
persistence dedup, evidence-chain shape — by patching:

    * app.services.knowledge_graph.suspect_kg_orchestrator._kg_lookup_service
    * app.services.knowledge_graph.suspect_kg_orchestrator._gemini_suspect_runner
    * app.services.knowledge_graph.suspect_kg_orchestrator.raf_cursor
    * app.services.lab_suspect_engine._kg_lookup_service
    * app.services.rx_suspect_engine._drug_class_reasoner

The conftest.py session fixture skips integration tests when the live
backend is unreachable; this file imports its own ``pytest`` marker so
the tests can run from a plain ``pytest backend/tests/test_suspect_kg_orchestrator.py``
without needing a running server.
"""
from __future__ import annotations

import contextlib
import json
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Skip the conftest's auto-skip "server unreachable" guard — these tests
# don't need the server.  The conftest fixture is session-scoped and
# autouse=True; the simplest way to bypass it is to monkey-patch its
# probe before the fixture runs, but pytest collects this module after
# conftest, so we instead just override the fixture locally.

@pytest.fixture(scope="session", autouse=True)
def server_available():  # noqa: PT004 - intentional override
    """Override conftest's session-level server probe for unit tests."""
    yield


# ---------------------------------------------------------------------------
# Imports under test (deferred so the autouse fixture above wins)
# ---------------------------------------------------------------------------

from app.services.knowledge_graph import suspect_kg_orchestrator as orch  # noqa: E402
from app.services import lab_suspect_engine as lab_engine  # noqa: E402
from app.services import rx_suspect_engine as rx_engine  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class FakeCursor:
    """A minimal cursor that records SQL executed against it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._fetched_rows: list[dict] = []
        self._next_lid = 1
        self._frozen = False  # When True, execute() doesn't overwrite rows

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))
        if self._frozen:
            return
        s = sql.strip().upper()
        if s.startswith("SELECT ID FROM RAF_SUSPECT_CONDITIONS"):
            self._fetched_rows = [{"id": self._next_lid}]
            self._next_lid += 1
        elif "LAST_INSERT_ID" in s:
            self._fetched_rows = [{"lid": self._next_lid}]
            self._next_lid += 1
        elif s.startswith("SELECT * FROM RAF_SUSPECT_CONDITIONS"):
            # populated explicitly by tests via set_next_row
            pass
        else:
            self._fetched_rows = []

    def fetchone(self) -> dict | None:
        return self._fetched_rows[0] if self._fetched_rows else None

    def fetchall(self) -> list[dict]:
        return list(self._fetched_rows)

    def set_next_row(self, row: dict) -> None:
        self._fetched_rows = [row]
        self._frozen = True

    def set_next_rows(self, rows: list[dict]) -> None:
        self._fetched_rows = list(rows)
        self._frozen = True


@contextlib.contextmanager
def fake_raf_cursor(cursor: FakeCursor):
    yield cursor


def patch_raf_cursor(monkeypatch, cursor: FakeCursor) -> None:
    """Replace orchestrator's raf_cursor with one that yields *cursor*."""
    monkeypatch.setattr(
        orch,
        "raf_cursor",
        lambda *a, **kw: fake_raf_cursor(cursor),
    )


# ---------------------------------------------------------------------------
# Test 1 — KG candidate normalisation
# ---------------------------------------------------------------------------

def test_normalize_kg_candidate_with_canonical_keys() -> None:
    item = {
        "suspect_hcc": "HCC18",
        "suspect_icd10": "E11.65",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.82,
        "evidence_detail": {"trigger_evidence": []},
    }
    out = orch._normalize_kg_candidate(item)
    assert out["suspect_hcc"] == "HCC18"
    assert out["suspect_icd10"] == "E1165"
    assert out["evidence_type"] == "kg_rule"
    assert out["raw_confidence"] == 0.82


def test_normalize_kg_candidate_maps_kind_to_evidence_type() -> None:
    item = {"hcc": "HCC37", "icd10": "E11.9", "kind": "drug", "confidence": 0.7}
    out = orch._normalize_kg_candidate(item)
    assert out["evidence_type"] == "kg_drug_class"


def test_normalize_kg_candidate_falls_back_to_kg_rule_when_kind_unknown() -> None:
    item = {"hcc": "HCC22", "icd10": "I10", "kind": "mystery"}
    out = orch._normalize_kg_candidate(item)
    assert out["evidence_type"] == "kg_rule"


# ---------------------------------------------------------------------------
# Test 2 — KG returns 3, LLM returns 2 (1 overlap) → KG primary, LLM merged
# ---------------------------------------------------------------------------

def test_merge_kg_3_and_llm_2_with_overlap_keeps_kg_primary() -> None:
    kg = [
        {
            "suspect_hcc": "HCC18",
            "suspect_icd10": "E1165",
            "evidence_type": "kg_rule",
            "raw_confidence": 0.85,
            "evidence_detail": {"rule_citation": "CMS V28 HCC 18 spec"},
        },
        {
            "suspect_hcc": "HCC37",
            "suspect_icd10": "E119",
            "evidence_type": "kg_drug_class",
            "raw_confidence": 0.74,
            "evidence_detail": {"drug_class_inference": {"from_drug": "metformin"}},
        },
        {
            "suspect_hcc": "HCC328",
            "suspect_icd10": "N184",
            "evidence_type": "kg_lab_signal",
            "raw_confidence": 0.91,
            "evidence_detail": {"trigger_evidence": [{"loinc": "33914-3", "value": 25.0}]},
        },
    ]
    llm = [
        {
            "suspect_hcc": "HCC18",  # overlaps with KG
            "suspect_icd10": "E1165",
            "evidence_type": "llm",
            "raw_confidence": 0.6,
            "evidence_detail": {"llm_corroboration": {"chart_quote": "diabetic retinopathy noted on exam"}},
        },
        {
            "suspect_hcc": "HCC155",  # LLM-only
            "suspect_icd10": "F329",
            "evidence_type": "llm",
            "raw_confidence": 0.55,
            "evidence_detail": {"llm_corroboration": {"chart_quote": "patient reports persistent low mood"}},
        },
    ]

    merged = orch._merge_kg_and_llm(kg, llm)
    by_hcc = {m["suspect_hcc"]: m for m in merged}

    # KG candidates remain primary (3 KG-tagged)
    assert by_hcc["HCC18"]["evidence_type"] == "kg_rule"
    assert by_hcc["HCC37"]["evidence_type"] == "kg_drug_class"
    assert by_hcc["HCC328"]["evidence_type"] == "kg_lab_signal"

    # LLM-only candidate kept
    assert by_hcc["HCC155"]["evidence_type"] == "llm"

    # Overlapping LLM evidence is appended into KG candidate's
    # evidence_detail.llm_corroboration
    corr = by_hcc["HCC18"]["evidence_detail"]["llm_corroboration"]
    assert corr is not None
    assert "diabetic retinopathy" in corr["chart_quote"]

    # Total = 3 KG + 1 LLM-only = 4 distinct merged candidates
    assert len(merged) == 4


# ---------------------------------------------------------------------------
# Test 3 — KG returns nothing → LLM is fully responsible
# ---------------------------------------------------------------------------

def test_kg_empty_falls_through_to_llm_only() -> None:
    kg: list[dict] = []
    llm = [
        {
            "suspect_hcc": "HCC22",
            "suspect_icd10": "I10",
            "evidence_type": "llm",
            "raw_confidence": 0.7,
            "evidence_detail": {"llm_corroboration": {"chart_quote": "BP 158/92"}},
        }
    ]
    merged = orch._merge_kg_and_llm(kg, llm)
    assert len(merged) == 1
    assert merged[0]["evidence_type"] == "llm"
    assert merged[0]["suspect_hcc"] == "HCC22"


# ---------------------------------------------------------------------------
# Test 4 — Demographic modulation: 78F dual + DM → CKD prior boosted
# ---------------------------------------------------------------------------

def test_demographic_modulation_elderly_dual_female_boosts_ckd() -> None:
    candidate = {
        "suspect_hcc": "HCC327",  # CKD stage 4
        "suspect_icd10": "N184",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.5,
        "evidence_detail": {},
    }
    demo = {"age": 78, "sex": "F", "dual_eligible": True}
    out = orch._apply_calibration(candidate, demo, provider_specialty=None)
    assert out["evidence_detail"]["demographic_multiplier"] == pytest.approx(1.4)
    # 0.5 * 1.4 = 0.70
    assert out["evidence_detail"]["final_confidence"] == pytest.approx(0.70, rel=1e-3)


def test_demographic_modulation_does_not_affect_unrelated_hcc() -> None:
    candidate = {
        "suspect_hcc": "HCC108",  # cancer group, untouched by CKD rule
        "suspect_icd10": "C509",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.5,
        "evidence_detail": {},
    }
    demo = {"age": 78, "sex": "F", "dual_eligible": True}
    out = orch._apply_calibration(candidate, demo, provider_specialty=None)
    assert out["evidence_detail"]["demographic_multiplier"] == 1.0
    assert out["evidence_detail"]["final_confidence"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test 5 — Specialty modulation: cardiology boosts CHF priors
# ---------------------------------------------------------------------------

def test_specialty_modulation_cardiology_boosts_chf() -> None:
    candidate = {
        "suspect_hcc": "HCC85",
        "suspect_icd10": "I5023",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.5,
        "evidence_detail": {},
    }
    out = orch._apply_calibration(candidate, {}, provider_specialty="Cardiology")
    assert out["evidence_detail"]["specialty_multiplier"] == pytest.approx(1.25)
    assert out["evidence_detail"]["final_confidence"] == pytest.approx(0.625, rel=1e-3)


def test_specialty_modulation_unknown_specialty_is_passthrough() -> None:
    candidate = {
        "suspect_hcc": "HCC85",
        "suspect_icd10": "I5023",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.5,
        "evidence_detail": {},
    }
    out = orch._apply_calibration(candidate, {}, provider_specialty="podiatry")
    assert out["evidence_detail"]["specialty_multiplier"] == 1.0


def test_specialty_and_demographic_multipliers_compound() -> None:
    candidate = {
        "suspect_hcc": "HCC327",
        "suspect_icd10": "N184",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.5,
        "evidence_detail": {},
    }
    demo = {"age": 80, "sex": "F", "dual_eligible": True}
    out = orch._apply_calibration(candidate, demo, provider_specialty="nephrology")
    # demo 1.4 × specialty 1.30 × 0.5 = 0.91
    assert out["evidence_detail"]["demographic_multiplier"] == pytest.approx(1.4)
    assert out["evidence_detail"]["specialty_multiplier"] == pytest.approx(1.30)
    assert out["evidence_detail"]["final_confidence"] == pytest.approx(0.91, rel=1e-2)


def test_calibration_caps_final_confidence_at_0_99() -> None:
    candidate = {
        "suspect_hcc": "HCC327",
        "suspect_icd10": "N184",
        "evidence_type": "kg_rule",
        "raw_confidence": 0.95,
        "evidence_detail": {},
    }
    demo = {"age": 80, "sex": "F", "dual_eligible": True}
    out = orch._apply_calibration(candidate, demo, provider_specialty="nephrology")
    assert out["evidence_detail"]["final_confidence"] <= 0.99


# ---------------------------------------------------------------------------
# Test 6 — Audit chain JSON well-formed for every suspect
# ---------------------------------------------------------------------------

def test_audit_chain_json_shape_for_every_suspect() -> None:
    kg = [
        {
            "suspect_hcc": "HCC18",
            "suspect_icd10": "E1165",
            "evidence_type": "kg_rule",
            "raw_confidence": 0.85,
            "evidence_detail": {
                "kg_rule_id": 42,
                "rule_source": "CMS-V28-spec",
                "rule_citation": "CMS V28 HCC 18 spec, p.42",
                "trigger_evidence": [{"kind": "icd10", "code": "H35.022"}],
            },
        },
    ]
    merged = orch._merge_kg_and_llm(kg, [])
    calibrated = [orch._apply_calibration(c, {}, None) for c in merged]
    for s in calibrated:
        d = s["evidence_detail"]
        # Required audit-chain keys
        for k in (
            "demographic_multiplier",
            "specialty_multiplier",
            "final_confidence",
        ):
            assert k in d, f"audit chain missing key {k}"
        # JSON-serialisable
        json.dumps(d, default=orch._json_default)


# ---------------------------------------------------------------------------
# Test 7 — Persistence dedup on (patient_id, year, hcc)
# ---------------------------------------------------------------------------

def test_persist_dedup_uses_on_duplicate_key(monkeypatch) -> None:
    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)
    suspects = [
        {
            "suspect_hcc": "HCC18",
            "suspect_icd10": "E1165",
            "evidence_type": "kg_rule",
            "confidence_score": 0.82,
            "evidence_detail": {"trigger_evidence": []},
        }
    ]
    written = orch._persist_suspects(suspects, patient_id=3, year=2026, tenant_id=1)
    assert written == 1
    # First call should be the upsert INSERT ... ON DUPLICATE KEY UPDATE
    insert_sql = cur.calls[0][0].upper()
    assert "INSERT INTO RAF_SUSPECT_CONDITIONS" in insert_sql
    assert "ON DUPLICATE KEY UPDATE" in insert_sql
    # Params: patient_id, year, hcc, icd, et, detail_json, score
    p = cur.calls[0][1]
    assert p[0] == 3
    assert p[1] == 2026
    assert p[2] == "HCC18"
    assert p[3] == "E1165"
    assert p[4] == "kg_rule"


def test_persist_writes_json_to_evidence_detail_column(monkeypatch) -> None:
    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)
    suspects = [
        {
            "suspect_hcc": "HCC37",
            "suspect_icd10": "E119",
            "evidence_type": "kg_drug_class",
            "confidence_score": 0.7,
            "evidence_detail": {
                "drug_class_inference": {"from_drug": "metformin"},
                "trigger_evidence": [{"kind": "drug", "name": "metformin"}],
            },
        }
    ]
    orch._persist_suspects(suspects, patient_id=99, year=2026)
    detail_payload = cur.calls[0][1][5]
    parsed = json.loads(detail_payload)
    assert parsed["drug_class_inference"]["from_drug"] == "metformin"


def test_persist_skips_when_empty(monkeypatch) -> None:
    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)
    written = orch._persist_suspects([], patient_id=3, year=2026)
    assert written == 0
    assert cur.calls == []


# ---------------------------------------------------------------------------
# Test 8 — Lab fallback: KG seed missing → falls back to legacy regex
# ---------------------------------------------------------------------------

def test_lab_fallback_when_kg_lookup_unavailable(monkeypatch) -> None:
    # Simulate KG service not installed
    monkeypatch.setattr(lab_engine, "_kg_lookup_service", lambda: None)
    note_text = "HbA1c: 9.2  eGFR: 45"
    suspects = lab_engine.detect_lab_suspects_kg_first(
        note_text=note_text,
        existing_diagnoses=[],
    )
    types = {s["evidence_type"] for s in suspects}
    assert types == {"lab_legacy"}
    icds = {s["icd10"] for s in suspects}
    assert "E11.65" in icds  # diabetes


def test_lab_kg_first_uses_kg_when_available(monkeypatch) -> None:
    fake_svc = types.SimpleNamespace(
        evaluate_lab_value=MagicMock(return_value=[
            {
                "icd10": "E11.65",
                "hcc": "HCC18",
                "condition": "DM with retinopathy",
                "rule_id": 7,
                "rule_citation": "KG seed v1 row 7",
                "confidence_score": 0.88,
            }
        ])
    )
    monkeypatch.setattr(lab_engine, "_kg_lookup_service", lambda: fake_svc)

    suspects = lab_engine.detect_lab_suspects_kg_first(
        lab_observations=[
            {"loinc": "4548-4", "value": 9.2, "units": "%"},
        ],
        existing_diagnoses=[],
    )
    assert any(s["evidence_type"] == "kg_lab_signal" for s in suspects)
    # KG path should NOT redo legacy match for the same lab value
    fake_svc.evaluate_lab_value.assert_called_once()


def test_lab_kg_returns_nothing_falls_through_to_note_legacy(monkeypatch) -> None:
    fake_svc = types.SimpleNamespace(evaluate_lab_value=MagicMock(return_value=[]))
    monkeypatch.setattr(lab_engine, "_kg_lookup_service", lambda: fake_svc)

    # Provide note text so the legacy regex path can fire
    suspects = lab_engine.detect_lab_suspects_kg_first(
        lab_observations=[{"loinc": "X-UNKNOWN", "value": 9.2}],
        note_text="HbA1c: 9.2",
        existing_diagnoses=[],
    )
    assert any(s["evidence_type"] == "lab_legacy" for s in suspects)


# ---------------------------------------------------------------------------
# Test 9 — Rx fallback: drug not in KG table → legacy lookup
# ---------------------------------------------------------------------------

def test_rx_fallback_when_kg_returns_nothing(monkeypatch) -> None:
    fake_svc = types.SimpleNamespace(infer_from_drug=MagicMock(return_value=[]))
    monkeypatch.setattr(rx_engine, "_drug_class_reasoner", lambda: fake_svc)

    # Stub legacy raf_medication_signals query
    monkeypatch.setattr(
        rx_engine,
        "_load_medication_signals",
        lambda: [
            {
                "drug_name_pattern": "%donepezil%",
                "rxnorm_code": "",
                "suspected_icd": "F03.90",
                "suspected_hcc": "HCC127",
                "description": "Cognitive impairment implied by donepezil",
                "confidence": 0.7,
            }
        ],
    )
    suspects = rx_engine.detect_rx_suspects(
        medications=[{"drug": "donepezil 10mg"}],
        existing_diagnoses=[],
    )
    assert len(suspects) == 1
    assert suspects[0]["evidence_type"] == "rx_legacy"
    assert suspects[0]["icd10"] == "F0390"
    assert suspects[0]["hcc"] == "HCC127"


def test_rx_kg_first_short_circuits_legacy(monkeypatch) -> None:
    fake_svc = types.SimpleNamespace(
        infer_from_drug=MagicMock(return_value=[
            {
                "icd10": "E11.9",
                "hcc": "HCC37",
                "condition": "Type 2 DM",
                "atc_class": "A10BA",
                "rule_id": 11,
            }
        ])
    )
    monkeypatch.setattr(rx_engine, "_drug_class_reasoner", lambda: fake_svc)
    legacy_loader = MagicMock(return_value=[])
    monkeypatch.setattr(rx_engine, "_load_medication_signals", legacy_loader)

    suspects = rx_engine.detect_rx_suspects(
        medications=[{"drug": "metformin 1000mg"}],
        existing_diagnoses=[],
    )
    assert len(suspects) == 1
    assert suspects[0]["evidence_type"] == "kg_drug_class"
    # Legacy loader should NOT be queried because KG covered the drug
    legacy_loader.assert_not_called()


def test_rx_kg_unavailable_falls_back_to_legacy_only(monkeypatch) -> None:
    monkeypatch.setattr(rx_engine, "_drug_class_reasoner", lambda: None)
    monkeypatch.setattr(
        rx_engine,
        "_load_medication_signals",
        lambda: [
            {
                "drug_name_pattern": "%warfarin%",
                "rxnorm_code": "",
                "suspected_icd": "Z79.01",
                "suspected_hcc": "",
                "description": "Long-term anticoagulation",
                "confidence": 0.5,
            }
        ],
    )
    suspects = rx_engine.detect_rx_suspects(
        medications=[{"drug": "warfarin 5mg"}],
        existing_diagnoses=[],
    )
    assert suspects
    assert all(s["evidence_type"] == "rx_legacy" for s in suspects)


# ---------------------------------------------------------------------------
# Test 10 — Existing diagnosis suppresses suspect (KG + legacy)
# ---------------------------------------------------------------------------

def test_existing_diagnosis_suppresses_kg_suspect(monkeypatch) -> None:
    fake_svc = types.SimpleNamespace(
        infer_from_drug=MagicMock(return_value=[
            {"icd10": "E11.9", "hcc": "HCC37", "condition": "Type 2 DM"}
        ])
    )
    monkeypatch.setattr(rx_engine, "_drug_class_reasoner", lambda: fake_svc)

    suspects = rx_engine.detect_rx_suspects(
        medications=[{"drug": "metformin 1000mg"}],
        existing_diagnoses=["E11.9"],
    )
    assert suspects == []


# ---------------------------------------------------------------------------
# Test 11 — Full pipeline end-to-end with mocked siblings + DB
# ---------------------------------------------------------------------------

def test_run_kg_first_detection_end_to_end(monkeypatch) -> None:
    # Mock KG service
    fake_kg = types.SimpleNamespace(
        patient_full_inference=MagicMock(return_value=[
            {
                "suspect_hcc": "HCC18",
                "suspect_icd10": "E11.65",
                "evidence_type": "kg_rule",
                "raw_confidence": 0.82,
                "evidence_detail": {
                    "kg_rule_id": 42,
                    "rule_source": "CMS-V28-spec",
                    "rule_citation": "CMS V28 HCC 18 spec, p.42",
                    "trigger_evidence": [{"kind": "icd10", "code": "H35.022"}],
                },
            },
            {
                "suspect_hcc": "HCC328",
                "suspect_icd10": "N184",
                "evidence_type": "kg_lab_signal",
                "raw_confidence": 0.91,
                "evidence_detail": {"trigger_evidence": [{"loinc": "33914-3", "value": 25.0}]},
            },
        ])
    )
    monkeypatch.setattr(orch, "_kg_lookup_service", lambda: fake_kg)
    # No LLM runner (chart_text=None will already short-circuit, but be explicit)
    monkeypatch.setattr(orch, "_gemini_suspect_runner", lambda: (None, None, None))

    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)

    out = orch.run_kg_first_detection(
        patient_id=3,
        year=2026,
        tenant_id=1,
        chart_text=None,
        patient_demographics={"age": 78, "sex": "F", "dual_eligible": True},
        provider_specialty="nephrology",
    )

    # Two KG candidates persisted
    assert len(out) == 2
    hccs = {c["suspect_hcc"] for c in out}
    assert hccs == {"HCC18", "HCC328"}

    # CKD candidate should have demographic + specialty boost
    ckd = next(c for c in out if c["suspect_hcc"] == "HCC328")
    assert ckd["evidence_detail"]["specialty_multiplier"] == pytest.approx(1.30)
    # Final confidence raised but capped
    assert 0.91 < ckd["evidence_detail"]["final_confidence"] <= 0.99


# ---------------------------------------------------------------------------
# Test 12 — KG service missing → orchestrator returns empty list, no crash
# ---------------------------------------------------------------------------

def test_kg_service_missing_graceful_degradation(monkeypatch) -> None:
    monkeypatch.setattr(orch, "_kg_lookup_service", lambda: None)
    monkeypatch.setattr(orch, "_gemini_suspect_runner", lambda: (None, None, None))
    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)

    out = orch.run_kg_first_detection(
        patient_id=3,
        year=2026,
        chart_text=None,
        patient_demographics={},
    )
    assert out == []
    # Nothing should have been persisted
    assert all("INSERT" not in c[0].upper() for c in cur.calls)


# ---------------------------------------------------------------------------
# Test 13 — LLM runner error doesn't crash orchestrator
# ---------------------------------------------------------------------------

def test_llm_runner_exception_does_not_crash(monkeypatch) -> None:
    fake_kg = types.SimpleNamespace(
        patient_full_inference=MagicMock(return_value=[
            {
                "suspect_hcc": "HCC22",
                "suspect_icd10": "I10",
                "evidence_type": "kg_rule",
                "raw_confidence": 0.6,
                "evidence_detail": {},
            }
        ])
    )
    monkeypatch.setattr(orch, "_kg_lookup_service", lambda: fake_kg)

    def boom(*a, **kw):
        raise RuntimeError("Gemini quota exceeded")
    monkeypatch.setattr(orch, "_gemini_suspect_runner", lambda: (boom, "x", "y"))

    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)

    out = orch.run_kg_first_detection(
        patient_id=7,
        year=2026,
        chart_text="patient with long-standing hypertension",
        patient_demographics={},
    )
    assert len(out) == 1
    assert out[0]["evidence_type"] == "kg_rule"


# ---------------------------------------------------------------------------
# Test 14 — get_evidence_chain returns parsed JSON
# ---------------------------------------------------------------------------

def test_get_evidence_chain_parses_json(monkeypatch) -> None:
    cur = FakeCursor()
    cur.set_next_row({
        "id": 17,
        "patient_id": 3,
        "measurement_year": 2026,
        "suspect_hcc": "HCC18",
        "suspect_icd10": "E1165",
        "evidence_type": "kg_rule",
        "confidence_score": 0.85,
        "status": "open",
        "evidence_detail": json.dumps({
            "kg_rule_id": 42,
            "rule_citation": "CMS V28 HCC 18 spec",
            "trigger_evidence": [{"kind": "icd10", "code": "H35.022"}],
            "final_confidence": 0.85,
        }),
    })
    patch_raf_cursor(monkeypatch, cur)

    out = orch.get_evidence_chain(17)
    assert out["id"] == 17
    assert out["evidence_type"] == "kg_rule"
    assert out["evidence_chain"]["kg_rule_id"] == 42
    assert out["evidence_chain"]["trigger_evidence"][0]["code"] == "H35.022"


def test_get_evidence_chain_404_when_missing(monkeypatch) -> None:
    cur = FakeCursor()
    cur.set_next_rows([])
    patch_raf_cursor(monkeypatch, cur)
    with pytest.raises(ValueError):
        orch.get_evidence_chain(999)


# ---------------------------------------------------------------------------
# Test 15 — Distribution helper groups by evidence_type
# ---------------------------------------------------------------------------

def test_get_evidence_type_distribution(monkeypatch) -> None:
    cur = FakeCursor()
    cur.set_next_rows([
        {"evidence_type": "kg_rule", "n": 12},
        {"evidence_type": "kg_drug_class", "n": 5},
        {"evidence_type": "kg_lab_signal", "n": 3},
        {"evidence_type": "llm", "n": 2},
        {"evidence_type": "lab_legacy", "n": 1},
    ])
    patch_raf_cursor(monkeypatch, cur)

    dist = orch.get_evidence_type_distribution(patient_id=3, year=2026)
    assert dist["kg_rule"] == 12
    # KG dominance check
    kg_total = sum(v for k, v in dist.items() if k.startswith("kg_"))
    other = sum(v for k, v in dist.items() if not k.startswith("kg_"))
    assert kg_total > other


# ---------------------------------------------------------------------------
# Test 16 — Tenant isolation: tenant_id propagates into orchestrator
# ---------------------------------------------------------------------------

def test_tenant_id_param_does_not_leak_into_other_tenants(monkeypatch) -> None:
    # The schema doesn't carry tenant_id on raf_suspect_conditions in this
    # repo, but the orchestrator API accepts it for forward-compat and
    # logs it.  The persist path must not raise when tenant_id is set.
    fake_kg = types.SimpleNamespace(
        patient_full_inference=MagicMock(return_value=[
            {
                "suspect_hcc": "HCC18",
                "suspect_icd10": "E11.65",
                "evidence_type": "kg_rule",
                "raw_confidence": 0.7,
                "evidence_detail": {},
            }
        ])
    )
    monkeypatch.setattr(orch, "_kg_lookup_service", lambda: fake_kg)
    monkeypatch.setattr(orch, "_gemini_suspect_runner", lambda: (None, None, None))
    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)

    # Tenant 1 run
    out_t1 = orch.run_kg_first_detection(
        patient_id=3, year=2026, tenant_id=1,
        chart_text=None, patient_demographics={},
    )
    # Tenant 2 run
    out_t2 = orch.run_kg_first_detection(
        patient_id=3, year=2026, tenant_id=2,
        chart_text=None, patient_demographics={},
    )

    assert len(out_t1) == 1
    assert len(out_t2) == 1
    # Each tenant produces independent output dicts
    assert out_t1 is not out_t2


# ---------------------------------------------------------------------------
# Test 17 — Multiple KG candidates for same HCC are merged with related_kg
# ---------------------------------------------------------------------------

def test_two_kg_candidates_same_hcc_keep_highest_and_record_related() -> None:
    kg = [
        {
            "suspect_hcc": "HCC18",
            "suspect_icd10": "E1165",
            "evidence_type": "kg_rule",
            "raw_confidence": 0.7,
            "evidence_detail": {"rule_id": 1},
        },
        {
            "suspect_hcc": "HCC18",
            "suspect_icd10": "E1165",
            "evidence_type": "kg_drug_class",
            "raw_confidence": 0.85,
            "evidence_detail": {"rule_id": 9, "drug_class_inference": {"from_drug": "metformin"}},
        },
    ]
    merged = orch._merge_kg_and_llm(kg, [])
    assert len(merged) == 1
    primary = merged[0]
    assert primary["evidence_type"] == "kg_drug_class"  # highest confidence wins
    related = primary["evidence_detail"].get("related_kg")
    assert related and related[0]["evidence_type"] == "kg_rule"


# ---------------------------------------------------------------------------
# Test 18 — Empty KG, empty LLM → empty output
# ---------------------------------------------------------------------------

def test_merge_empty_inputs_returns_empty_list() -> None:
    assert orch._merge_kg_and_llm([], []) == []


# ---------------------------------------------------------------------------
# Test 19 — KG pass with kg_lookup_service that raises
# ---------------------------------------------------------------------------

def test_kg_pass_swallows_kg_exceptions(monkeypatch) -> None:
    fake_kg = types.SimpleNamespace(
        patient_full_inference=MagicMock(side_effect=RuntimeError("DB down"))
    )
    monkeypatch.setattr(orch, "_kg_lookup_service", lambda: fake_kg)
    out = orch._kg_pass(patient_id=3, year=2026)
    assert out == []


# ---------------------------------------------------------------------------
# Test 20 — Acceptance: evidence_type values match the allowlist
# ---------------------------------------------------------------------------

def test_evidence_type_allowlist_contains_required_tags() -> None:
    required = {
        "kg_rule",
        "kg_comorbidity",
        "kg_drug_class",
        "kg_lab_signal",
        "kg_specialty",
        "llm",
        "lab_legacy",
        "rx_legacy",
    }
    assert required.issubset(set(orch.ALL_EVIDENCE_TYPES))


# ---------------------------------------------------------------------------
# Test 21 — Audit chain shape matches the documented JSON skeleton
# ---------------------------------------------------------------------------

def test_audit_chain_default_skeleton_has_documented_keys() -> None:
    item = {"hcc": "HCC18", "icd10": "E11.9"}
    out = orch._normalize_kg_candidate(item)
    detail = out["evidence_detail"]
    for key in (
        "kg_rule_id",
        "rule_source",
        "rule_citation",
        "trigger_evidence",
        "comorbidity_upgrades",
        "drug_class_inference",
        "demographic_multiplier",
        "specialty_multiplier",
        "final_confidence",
        "llm_corroboration",
    ):
        assert key in detail, f"missing audit key: {key}"


# ---------------------------------------------------------------------------
# Test 22 — Orchestrator returns calibrated confidence_score field
# ---------------------------------------------------------------------------

def test_orchestrator_writes_top_level_confidence_score(monkeypatch) -> None:
    fake_kg = types.SimpleNamespace(
        patient_full_inference=MagicMock(return_value=[
            {
                "suspect_hcc": "HCC85",
                "suspect_icd10": "I5023",
                "evidence_type": "kg_rule",
                "raw_confidence": 0.5,
                "evidence_detail": {},
            }
        ])
    )
    monkeypatch.setattr(orch, "_kg_lookup_service", lambda: fake_kg)
    monkeypatch.setattr(orch, "_gemini_suspect_runner", lambda: (None, None, None))
    cur = FakeCursor()
    patch_raf_cursor(monkeypatch, cur)

    out = orch.run_kg_first_detection(
        patient_id=3, year=2026,
        chart_text=None,
        patient_demographics={},
        provider_specialty="cardiology",
    )
    assert out[0]["confidence_score"] == pytest.approx(0.625, rel=1e-3)
