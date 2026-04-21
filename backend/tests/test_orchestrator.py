"""Unit test for ai_pipeline.orchestrator.run_for_patient.

All stage functions are mocked; no DB, no LLM. We verify that the
orchestrator chains the stages in the correct order with the correct
positional/keyword arguments, and that persistence + provider-query
generation are invoked as expected.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _FakeCursor:
    """Minimal dict-cursor that returns sequential ids from fetchone()."""

    def __init__(self):
        self._id = 0
        self.calls: list[tuple[str, tuple]] = []
        self.lastrowid = 0

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self._id += 1
        self.lastrowid = self._id

    def fetchone(self):
        return {"id": self._id}

    def fetchall(self):
        return []


class _FakeCtxMgr:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self.cur

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_cur():
    return _FakeCursor()


@pytest.fixture
def fake_bundle():
    demo = SimpleNamespace(age=72, sex="F", has_esrd=False)
    note = SimpleNamespace(id=101, date="2026-01-15", type="office", text="Patient has well-controlled DM2.")
    return SimpleNamespace(
        demographics=demo,
        hcc_model_version="V28",
        clinical_notes=[note],
        patient_id="42",
    )


def _make_hcc_candidate(icd10="E11.9", hcc="HCC19"):
    meat = SimpleNamespace(monitor=True, evaluate=False, assess=True, treat=True)
    return SimpleNamespace(
        icd10=icd10,
        hcc=hcc,
        meat_status=meat,
        recapture_vs_new="recapture",
        confidence=0.9,
        evidence_span="well-controlled DM2",
        rationale="active condition",
    )


def _make_meat_evidence():
    return SimpleNamespace(
        m_quote="monitoring A1c",
        e_quote=None,
        a_quote="stable",
        t_quote="continue metformin",
        encounter_date="2026-01-15",
        is_face_to_face=True,
        overall_valid=True,
        reason_if_invalid=None,
        dropped_quotes=[],
    )


def _make_suspect():
    return SimpleNamespace(
        icd10="N18.3",
        hcc="HCC138",
        rule_id="ckd_stage3_egfr",
        reason="eGFR < 60 across 2 labs",
        confidence=0.8,
        supporting_evidence=[],
        source="rule",
    )


def _make_provider_query():
    return SimpleNamespace(
        to_provider_id="prov-1",
        patient_id="42",
        subject="Query",
        body="Please clarify...",
        supporting_citations=[],
        compliance_flags=[],
        requires_human_review=False,
    )


def test_run_for_patient_chains_stages_in_order(fake_cur, fake_bundle):
    from app.services.ai_pipeline import orchestrator

    call_log: list[str] = []

    # Eligibility stubs
    def can_run(patient_id, tenant_id):
        call_log.append("can_run_analysis")
        assert patient_id == "42"
        assert tenant_id == "tenant-a"
        return True

    def record_start(patient_id, tenant_id, trigger_reason):
        call_log.append("record_run_start")
        assert patient_id == "42"
        assert tenant_id == "tenant-a"
        assert trigger_reason == "manual"
        return 999

    def record_finish(run_id, status):
        call_log.append("record_run_finish")
        assert run_id == 999
        assert status == "success"

    def assemble(patient_id):
        call_log.append("assemble_bundle")
        assert patient_id == 42
        return fake_bundle

    def extract_blind(note_text):
        call_log.append("extract_blind")
        assert "DM2" in note_text
        return [SimpleNamespace(icd10_guess="E11.9", condition_text="DM2",
                                evidence_span_start=0, evidence_span_end=3,
                                confidence=0.8)]

    def extract_contextual(note_text, bundle, blind):
        call_log.append("extract_contextual")
        assert bundle is fake_bundle
        assert len(blind) == 1
        return [_make_hcc_candidate()]

    def extract_meat_evidence(cand, note, context=None):
        call_log.append("extract_meat_evidence")
        assert cand.icd10 == "E11.9"
        assert "DM2" in note
        return _make_meat_evidence()

    def detect_suspects(bundle_dict, use_llm=True):
        call_log.append("detect_suspects")
        assert isinstance(bundle_dict, dict)
        assert use_llm is True
        return [_make_suspect()]

    def generate_query(candidate, bundle):
        call_log.append("generate_query")
        return _make_provider_query()

    mapper_result = SimpleNamespace(hcc="HCC19", label="Diabetes", source="csv")

    with patch.object(orchestrator.eligibility, "can_run_analysis", side_effect=can_run), \
         patch.object(orchestrator.eligibility, "record_run_start", side_effect=record_start), \
         patch.object(orchestrator.eligibility, "record_run_finish", side_effect=record_finish), \
         patch.object(orchestrator.context_bundle, "assemble_bundle", side_effect=assemble), \
         patch.object(orchestrator.extractor, "extract_blind", side_effect=extract_blind), \
         patch.object(orchestrator.extractor, "extract_contextual", side_effect=extract_contextual), \
         patch.object(orchestrator.meat_extractor, "extract_meat_evidence", side_effect=extract_meat_evidence), \
         patch.object(orchestrator.suspect_engine, "detect_suspects", side_effect=detect_suspects), \
         patch.object(orchestrator.provider_query, "generate_query", side_effect=generate_query), \
         patch.object(orchestrator, "map_icd_to_hcc", return_value=mapper_result), \
         patch.object(orchestrator, "raf_cursor", lambda: _FakeCtxMgr(fake_cur)):
        result = orchestrator.run_for_patient.run(
            patient_id=42, tenant_id="tenant-a", trigger_reason="manual"
        )

    # Verify chain order
    assert call_log[0] == "can_run_analysis"
    assert call_log[1] == "record_run_start"
    assert call_log[2] == "assemble_bundle"
    # extractors happen per note
    assert "extract_blind" in call_log
    assert "extract_contextual" in call_log
    # extract_blind must precede extract_contextual for the same note
    assert call_log.index("extract_blind") < call_log.index("extract_contextual")
    # MEAT runs after extract
    assert call_log.index("extract_contextual") < call_log.index("extract_meat_evidence")
    # Suspects run after extraction
    assert call_log.index("extract_meat_evidence") < call_log.index("detect_suspects")
    # Provider query runs after suspects
    assert call_log.index("detect_suspects") < call_log.index("generate_query")
    # Finish is last
    assert call_log[-1] == "record_run_finish"

    # Summary shape
    assert result["run_id"] == 999
    assert result["tenant_id"] == "tenant-a"
    assert result["stages"]["extract"] == {"candidates": 1}
    assert result["stages"]["suspects"] == 1
    assert result["stages"]["mapped"] == 1
    assert result["stages"]["persist"] == "ok"
    # 1 candidate + 1 suspect -> 2 provider queries
    assert result["stages"]["provider_queries"] == 2


def test_run_for_patient_skips_when_over_limit(fake_bundle):
    from app.services.ai_pipeline import orchestrator

    with patch.object(orchestrator.eligibility, "can_run_analysis", return_value=False), \
         patch.object(orchestrator.eligibility, "record_run_start") as start_mock, \
         patch.object(orchestrator.context_bundle, "assemble_bundle") as assemble_mock:
        result = orchestrator.run_for_patient.run(
            patient_id=42, tenant_id="tenant-a", trigger_reason="manual"
        )

    assert result["stages"]["eligibility"] == "skipped_over_limit"
    start_mock.assert_not_called()
    assemble_mock.assert_not_called()


def test_meat_extractor_receives_real_encounter_type(fake_cur):
    """A note linked to a telephone encounter must cause meat_extractor to
    receive encounter_type='telephone' — NOT the old hardcoded 'office visit'.
    """
    from app.services.ai_pipeline import orchestrator

    demo = SimpleNamespace(age=72, sex="F", has_esrd=False)
    note = SimpleNamespace(
        id=101, encounter_id="55", date="2026-01-15",
        type="clinical_note",
        text="Patient has well-controlled DM2.",
    )
    encounter = SimpleNamespace(
        encounter_id="55", date="2026-01-15", type="telephone",
        provider="Dr A", status="finished",
    )
    bundle = SimpleNamespace(
        demographics=demo,
        hcc_model_version="V28",
        clinical_notes=[note],
        prior_encounters_this_year=[encounter],
        patient_id="42",
    )

    captured: dict = {}

    def extract_meat_evidence(cand, note_text, context=None):
        captured["context"] = context
        return _make_meat_evidence()

    mapper_result = SimpleNamespace(hcc="HCC19", label="Diabetes", source="csv")

    with patch.object(orchestrator.eligibility, "can_run_analysis", return_value=True), \
         patch.object(orchestrator.eligibility, "record_run_start", return_value=999), \
         patch.object(orchestrator.eligibility, "record_run_finish"), \
         patch.object(orchestrator.context_bundle, "assemble_bundle", return_value=bundle), \
         patch.object(orchestrator.extractor, "extract_blind", return_value=[
             SimpleNamespace(icd10_guess="E11.9", condition_text="DM2",
                             evidence_span_start=0, evidence_span_end=3,
                             confidence=0.8)
         ]), \
         patch.object(orchestrator.extractor, "extract_contextual",
                      return_value=[_make_hcc_candidate()]), \
         patch.object(orchestrator.meat_extractor, "extract_meat_evidence",
                      side_effect=extract_meat_evidence), \
         patch.object(orchestrator.suspect_engine, "detect_suspects", return_value=[]), \
         patch.object(orchestrator.provider_query, "generate_query",
                      return_value=_make_provider_query()), \
         patch.object(orchestrator, "map_icd_to_hcc", return_value=mapper_result), \
         patch.object(orchestrator, "raf_cursor", lambda: _FakeCtxMgr(fake_cur)):
        orchestrator.run_for_patient.run(
            patient_id=42, tenant_id="tenant-a", trigger_reason="manual"
        )

    assert captured["context"]["encounter_type"] == "telephone"
    assert captured["context"]["encounter_type"] != "office visit"
    assert captured["context"]["encounter_date"] == "2026-01-15"


def test_meat_extractor_gets_none_when_encounter_unresolved(fake_cur):
    """Unresolvable encounter => encounter_type=None (RADV-safe)."""
    from app.services.ai_pipeline import orchestrator

    demo = SimpleNamespace(age=72, sex="F", has_esrd=False)
    note = SimpleNamespace(
        id=101, encounter_id="9999", date="2026-01-15",
        type="clinical_note", text="Patient has DM2.",
    )
    bundle = SimpleNamespace(
        demographics=demo,
        hcc_model_version="V28",
        clinical_notes=[note],
        prior_encounters_this_year=[],
        patient_id="42",
    )

    captured: dict = {}

    def extract_meat_evidence(cand, note_text, context=None):
        captured["context"] = context
        return _make_meat_evidence()

    mapper_result = SimpleNamespace(hcc="HCC19", label="Diabetes", source="csv")

    with patch.object(orchestrator.eligibility, "can_run_analysis", return_value=True), \
         patch.object(orchestrator.eligibility, "record_run_start", return_value=999), \
         patch.object(orchestrator.eligibility, "record_run_finish"), \
         patch.object(orchestrator.context_bundle, "assemble_bundle", return_value=bundle), \
         patch.object(orchestrator.extractor, "extract_blind", return_value=[
             SimpleNamespace(icd10_guess="E11.9", condition_text="DM2",
                             evidence_span_start=0, evidence_span_end=3,
                             confidence=0.8)
         ]), \
         patch.object(orchestrator.extractor, "extract_contextual",
                      return_value=[_make_hcc_candidate()]), \
         patch.object(orchestrator.meat_extractor, "extract_meat_evidence",
                      side_effect=extract_meat_evidence), \
         patch.object(orchestrator.suspect_engine, "detect_suspects", return_value=[]), \
         patch.object(orchestrator.provider_query, "generate_query",
                      return_value=_make_provider_query()), \
         patch.object(orchestrator, "map_icd_to_hcc", return_value=mapper_result), \
         patch.object(orchestrator, "raf_cursor", lambda: _FakeCtxMgr(fake_cur)):
        orchestrator.run_for_patient.run(
            patient_id=42, tenant_id="tenant-a", trigger_reason="manual"
        )

    assert captured["context"]["encounter_type"] is None


def test_schedule_daily_passes_tenant_id():
    from app.services.ai_pipeline import orchestrator

    with patch.object(orchestrator, "_all_tenant_ids", return_value=["t1"]), \
         patch.object(orchestrator.eligibility, "get_eligible_patients", return_value=["7", "8"]), \
         patch.object(orchestrator.run_for_patient, "apply_async") as aa:
        out = orchestrator.schedule_daily.run()

    assert out == {"enqueued": 2}
    # Each call must include tenant_id
    for call in aa.call_args_list:
        kwargs = call.kwargs.get("kwargs") or call.args[0] if call.args else call.kwargs["kwargs"]
        assert kwargs["tenant_id"] == "t1"
        assert kwargs["trigger_reason"] == "daily_beat"


def test_orchestrator_sql_is_mysql_compatible(fake_cur, fake_bundle):
    """Regression guard: the orchestrator must not emit Postgres-only idioms
    (``::jsonb`` casts, ``RETURNING`` clauses, ``jsonb_build_*`` functions,
    or ``$1``-style numbered placeholders) because production runs on MySQL.
    """
    from app.services.ai_pipeline import orchestrator

    mapper_result = SimpleNamespace(hcc="HCC19", label="Diabetes", source="csv")

    with patch.object(orchestrator.eligibility, "can_run_analysis", return_value=True), \
         patch.object(orchestrator.eligibility, "record_run_start", return_value=999), \
         patch.object(orchestrator.eligibility, "record_run_finish"), \
         patch.object(orchestrator.context_bundle, "assemble_bundle", return_value=fake_bundle), \
         patch.object(orchestrator.extractor, "extract_blind", return_value=[]), \
         patch.object(orchestrator.extractor, "extract_contextual",
                      return_value=[_make_hcc_candidate()]), \
         patch.object(orchestrator.meat_extractor, "extract_meat_evidence",
                      return_value=_make_meat_evidence()), \
         patch.object(orchestrator.suspect_engine, "detect_suspects",
                      return_value=[_make_suspect()]), \
         patch.object(orchestrator.provider_query, "generate_query",
                      return_value=_make_provider_query()), \
         patch.object(orchestrator, "map_icd_to_hcc", return_value=mapper_result), \
         patch.object(orchestrator, "raf_cursor", lambda: _FakeCtxMgr(fake_cur)):
        orchestrator.run_for_patient.run(
            patient_id=42, tenant_id="tenant-a", trigger_reason="manual"
        )

    assert fake_cur.calls, "expected at least one SQL statement to be executed"
    import re
    for sql, params in fake_cur.calls:
        upper = sql.upper()
        assert "::JSONB" not in upper, f"Postgres ::jsonb cast leaked into SQL: {sql!r}"
        assert "::JSON" not in upper, f"Postgres ::json cast leaked into SQL: {sql!r}"
        assert "JSONB_BUILD_OBJECT" not in upper, f"jsonb_build_object leaked: {sql!r}"
        assert "JSONB_BUILD_ARRAY" not in upper, f"jsonb_build_array leaked: {sql!r}"
        # RETURNING clauses are not MySQL-compatible.
        assert not re.search(r"\bRETURNING\b", upper), f"RETURNING leaked: {sql!r}"
        # No numbered Postgres placeholders.
        assert not re.search(r"\$\d+", sql), f"numbered placeholder leaked: {sql!r}"
