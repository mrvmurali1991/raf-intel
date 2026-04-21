"""End-to-end AI pipeline smoke test (task #45).

Builds a realistic fake PatientContextBundle and drives the orchestrator
through every stage with canned LLM responses. No DB, no real LLM calls.

We assert:
  * orchestrator returns a success-shaped summary
  * every pipeline stage was invoked
  * SQL recorded against raf_cursor contains the expected INSERTs
  * zero Postgres-only SQL idioms leaked into MySQL persistence
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Recording cursor
# ---------------------------------------------------------------------------


class _RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._id = 0
        self.lastrowid = 0

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params) if params is not None else ()))
        self._id += 1
        self.lastrowid = self._id

    def fetchone(self):
        return {"id": self._id}

    def fetchall(self):
        return []


@contextmanager
def _cursor_cm(cur):
    yield cur


# ---------------------------------------------------------------------------
# Bundle fixture — realistic 67M with DM2 + CKD3 + HTN
# ---------------------------------------------------------------------------


NOTE_TEXT = (
    "Follow-up visit 2026-04-16. Patient with diabetes type 2, A1c 9.2, "
    "continues on metformin 1000mg BID. eGFR 52, stable CKD stage 3. "
    "BP 142/88, on lisinopril."
)


@pytest.fixture
def fake_bundle():
    demo = SimpleNamespace(
        age=67, sex="M", dob="1959-01-01", mrn="MRN-SMOKE",
        first_name="Jane", last_name="Doe", has_esrd=False,
    )
    problem = SimpleNamespace(
        icd10="E11.9", description="Type 2 diabetes mellitus without complications",
        onset_date="2020-01-01", clinical_status="active",
    )
    encounter = SimpleNamespace(
        encounter_id="enc-1", date="2026-04-16", type="office visit",
        provider="Dr Smith", status="finished",
    )
    labs = [
        SimpleNamespace(code="4548-4", name="A1c", value="9.2", unit="%",
                        date="2026-04-10", abnormal_flag=True),
        SimpleNamespace(code="33914-3", name="eGFR", value="52", unit="mL/min",
                        date="2026-04-10", abnormal_flag=True),
    ]
    meds = [
        SimpleNamespace(name="metformin", rxnorm="6809", start_date="2020-01-01", status="active"),
        SimpleNamespace(name="lisinopril", rxnorm="29046", start_date="2021-03-01", status="active"),
    ]
    note = SimpleNamespace(
        id="note-1", encounter_id="enc-1", date="2026-04-16",
        type="office visit", text=NOTE_TEXT,
    )
    return SimpleNamespace(
        patient_id="1",
        measurement_year=2026,
        hcc_model_version="V28",
        cutoff_date="2025-01-01",
        demographics=demo,
        active_problem_list=[problem],
        prior_encounters_this_year=[encounter],
        recent_labs_12mo=labs,
        active_medications=meds,
        clinical_notes=[note],
        meta=SimpleNamespace(char_count=len(NOTE_TEXT), trimmed_notes=0,
                             trimmed_labs=0, source_tables=[]),
    )


def _hcc_candidate(icd10="E11.9", hcc="HCC37"):
    return SimpleNamespace(
        icd10=icd10,
        hcc=hcc,
        meat_status=SimpleNamespace(monitor=True, evaluate=True, assess=True, treat=True),
        recapture_vs_new="recapture",
        confidence=0.92,
        evidence_span="diabetes type 2, A1c 9.2",
        rationale="Active DM2 with elevated A1c, on metformin",
    )


def _meat_evidence():
    return SimpleNamespace(
        m_quote="A1c 9.2",
        e_quote="A1c 9.2",
        a_quote="diabetes type 2",
        t_quote="continues on metformin 1000mg BID",
        encounter_date="2026-04-16",
        is_face_to_face=True,
        overall_valid=True,
        reason_if_invalid=None,
        dropped_quotes=[],
    )


def _suspect():
    return SimpleNamespace(
        icd10="N18.3",
        hcc="HCC138",
        rule_id="ckd_stage3_egfr",
        reason="eGFR 52 consistent with CKD stage 3",
        confidence=0.85,
        supporting_evidence=[{"lab": "eGFR", "value": "52"}],
        source="rule",
    )


def _provider_query():
    return SimpleNamespace(
        to_provider_id="prov-1",
        patient_id="1",
        subject="Clarify CKD staging",
        body="Please confirm CKD stage based on eGFR 52.",
        supporting_citations=[{"note_id": "note-1", "quote": "eGFR 52"}],
        compliance_flags=[],
        requires_human_review=False,
    )


# ---------------------------------------------------------------------------
# Canned LLM responses
# ---------------------------------------------------------------------------


_LLM_BLIND = json.dumps({
    "candidates": [{
        "icd10_guess": "E11.9",
        "condition_text": "diabetes type 2",
        "evidence_span_start": 0,
        "evidence_span_end": 20,
        "confidence": 0.9,
    }]
})


def _canned_llm_generate(*args, **kwargs):
    # Generic JSON envelope accepted by extractor/meat/suspect/provider_query
    return _LLM_BLIND


def _canned_llm_generate_content(*args, **kwargs):
    return {"text": _LLM_BLIND}


# ---------------------------------------------------------------------------
# The actual smoke test
# ---------------------------------------------------------------------------


def test_pipeline_end_to_end_smoke(fake_bundle):
    from app.services.ai_pipeline import orchestrator

    raf_cur = _RecordingCursor()
    openemr_cur = _RecordingCursor()

    stages_called: list[str] = []

    def _mk(name, retval):
        def _fn(*a, **kw):
            stages_called.append(name)
            return retval
        return _fn

    mapper_result = SimpleNamespace(hcc="HCC37", label="Diabetes with chronic complications",
                                    source="csv")

    # Patch llm_generate* at the package level for any downstream imports.
    # Wrap the real eligibility functions so the INSERT INTO ai_analysis_runs
    # and UPDATE ai_analysis_runs SQL hits our recording cursor — this is
    # required to satisfy the "writes to ai_analysis_runs" assertion.
    from app.services.ai_pipeline import eligibility as _elig
    from app.services.llm import vertex_client

    _real_record_start = _elig.record_run_start
    _real_record_finish = _elig.record_run_finish

    def _wrapped_can_run(pid, tid):
        stages_called.append("eligibility")
        return True

    def _wrapped_record_start(patient_id, tenant_id, trigger_reason=None):
        stages_called.append("record_run_start")
        return _real_record_start(
            patient_id=patient_id, tenant_id=tenant_id, trigger_reason=trigger_reason
        )

    def _wrapped_record_finish(run_id, status="success"):
        stages_called.append("record_run_finish")
        return _real_record_finish(run_id=run_id, status=status)

    with patch.object(vertex_client, "llm_generate", side_effect=_canned_llm_generate, create=True), \
         patch.object(vertex_client, "llm_generate_content", side_effect=_canned_llm_generate_content, create=True), \
         patch.object(_elig, "raf_cursor", lambda: _cursor_cm(raf_cur)), \
         patch.object(orchestrator.eligibility, "can_run_analysis",
                      side_effect=_wrapped_can_run), \
         patch.object(orchestrator.eligibility, "record_run_start",
                      side_effect=_wrapped_record_start), \
         patch.object(orchestrator.eligibility, "record_run_finish",
                      side_effect=_wrapped_record_finish), \
         patch.object(orchestrator.context_bundle, "assemble_bundle",
                      side_effect=_mk("context_bundle", fake_bundle)), \
         patch.object(orchestrator.extractor, "extract_blind",
                      side_effect=_mk("extract_blind", [
                          SimpleNamespace(icd10_guess="E11.9", condition_text="DM2",
                                          evidence_span_start=0, evidence_span_end=3,
                                          confidence=0.9)
                      ])), \
         patch.object(orchestrator.extractor, "extract_contextual",
                      side_effect=_mk("extract_contextual", [_hcc_candidate()])), \
         patch.object(orchestrator.meat_extractor, "extract_meat_evidence",
                      side_effect=_mk("meat", _meat_evidence())), \
         patch.object(orchestrator.suspect_engine, "detect_suspects",
                      side_effect=_mk("suspects", [_suspect()])), \
         patch.object(orchestrator, "map_icd_to_hcc", return_value=mapper_result), \
         patch.object(orchestrator.provider_query, "generate_query",
                      side_effect=_mk("provider_query", _provider_query())), \
         patch.object(orchestrator, "raf_cursor", lambda: _cursor_cm(raf_cur)), \
         patch("app.db.raf_cursor", lambda: _cursor_cm(raf_cur)), \
         patch("app.db.openemr_cursor", lambda: _cursor_cm(openemr_cur)):
        result = orchestrator.run_for_patient.apply(
            args=(1, "tenant-demo", "smoke")
        ).get()

    # --- Stage assertions ---
    for needed in ("eligibility", "record_run_start", "context_bundle",
                   "extract_blind", "extract_contextual", "meat", "suspects",
                   "provider_query", "record_run_finish"):
        assert needed in stages_called, f"stage {needed} was not invoked"

    # --- Summary assertions ---
    assert isinstance(result["run_id"], int) and result["run_id"] >= 1
    assert result["tenant_id"] == "tenant-demo"
    assert result["trigger_reason"] == "smoke"
    assert result["stages"]["extract"] == {"candidates": 1}
    assert result["stages"]["suspects"] == 1
    assert result["stages"]["mapped"] == 1
    assert result["stages"]["persist"] == "ok"
    assert result["stages"]["provider_queries"] == 2  # 1 candidate + 1 suspect

    # --- SQL assertions ---
    all_sql = " ".join(sql for sql, _ in raf_cur.calls)
    assert "ai_analysis_runs" in all_sql or any(
        "ai_analysis_runs" in sql for sql, _ in raf_cur.calls
    ), "no write to ai_analysis_runs"
    assert any("INSERT INTO ai_hcc_candidates" in sql for sql, _ in raf_cur.calls), \
        "no INSERT INTO ai_hcc_candidates"
    assert any("INSERT INTO ai_suspect_candidates" in sql for sql, _ in raf_cur.calls), \
        "no INSERT INTO ai_suspect_candidates"
    assert any("INSERT INTO ai_meat_evidence" in sql for sql, _ in raf_cur.calls), \
        "no INSERT INTO ai_meat_evidence"

    # --- Zero Postgres idioms ---
    for sql, _ in raf_cur.calls:
        upper = sql.upper()
        assert "::JSONB" not in upper, f"Postgres ::jsonb leaked: {sql!r}"
        assert "JSONB_BUILD_OBJECT" not in upper, f"jsonb_build_object leaked: {sql!r}"
        assert "JSONB_BUILD_ARRAY" not in upper, f"jsonb_build_array leaked: {sql!r}"
        assert not re.search(r"\bRETURNING\b", upper), f"RETURNING leaked: {sql!r}"
