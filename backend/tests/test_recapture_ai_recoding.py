"""
Unit tests for app.services.recapture_ai_recoding.

These are pure unit tests that DO NOT touch a live database or Gemini.
We monkeypatch _fetch_recent_notes, _load_gap, _persist_suggestions,
list_pending_suggestions and the accept/reject DB writes so the test
suite has zero side effects.

Coverage:
  * _build_prompt    — prompt contains ICD-10 / HCC and the verbatim-quote rule
  * _parse_response  — happy path, drops non-verbatim phrases, drops bad shapes,
                       handles invalid JSON strings, and graceful empty
  * suggest_recoding — happy path persists + returns enriched suggestions
                     — Gemini timeout/error returns empty list (no raise)
                     — invalid JSON returns empty list
                     — gap not found returns 404-shaped error
  * accept_suggestion promotes evidence to the parent recapture_gap row
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import recapture_ai_recoding as svc


# ---------------------------------------------------------------------------
# Override the autouse server_available fixture so these unit tests run
# without a live backend. Gemini and the database are mocked everywhere.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def server_available():  # noqa: D401 — fixture override
    """No-op override; this module is unit-only and needs no live server."""
    return True


# ---------------------------------------------------------------------------
# Fixtures — fake notes + fake gap
# ---------------------------------------------------------------------------

NOTES = [
    {
        "note_id": "soap:101",
        "encounter_date": "2025-09-12",
        "note_text": (
            "S: 68F with longstanding type 2 diabetes mellitus. "
            "A: Diabetes well controlled, A1c 7.1. "
            "P: Continue metformin 1000mg BID, rechecks A1c in 3 months."
        ),
    },
    {
        "note_id": "cn:202",
        "encounter_date": "2025-06-04",
        "note_text": "Patient on insulin glargine for diabetes.",
    },
]

GAP = {
    "id": 1,
    "tenant_id": 1,
    "patient_id": 7,
    "icd10_code": "E11.9",
    "hcc_code": "HCC36",
    "condition_label": "Type 2 diabetes mellitus",
    "payment_year": 2025,
    "status": "open",
    "evidence_phrase": None,
    "meat_element": None,
    "source_note_id": None,
    "encounter_date": None,
}


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_contains_required_clauses() -> None:
    p = svc._build_prompt(icd10="E11.9", hcc_code="HCC36", notes=NOTES)
    assert "E11.9" in p
    assert "HCC36" in p
    # Verbatim-quote rule is the central hallucination guard
    assert "verbatim" in p.lower()
    # Both note ids must appear in the assembled note block
    assert "soap:101" in p
    assert "cn:202" in p
    # JSON-only directive
    assert "Return JSON only" in p


def test_build_prompt_handles_no_notes() -> None:
    p = svc._build_prompt(icd10="E11.9", hcc_code=None, notes=[])
    assert "no notes available" in p
    # hcc fallback label
    assert "unmapped" in p


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_happy_path_keeps_verbatim_phrase() -> None:
    raw = {
        "found": True,
        "suggestions": [
            {
                "phrase": "longstanding type 2 diabetes mellitus",
                "confidence": 0.92,
                "meat_element": "A",
                "note_id": "soap:101",
                "encounter_date": "2025-09-12",
            }
        ],
    }
    out = svc._parse_response(raw, NOTES)
    assert len(out) == 1
    s = out[0]
    assert s["evidence_phrase"] == "longstanding type 2 diabetes mellitus"
    assert s["confidence"] == pytest.approx(0.92)
    assert s["meat_element"] == "A"
    assert s["source_note_id"] == "soap:101"
    assert s["encounter_date"] == "2025-09-12"


def test_parse_response_drops_non_verbatim_phrase() -> None:
    raw = {
        "found": True,
        "suggestions": [
            {
                # Made up — not a substring of any note
                "phrase": "the patient has severe diabetic neuropathy",
                "confidence": 0.95,
                "meat_element": "A",
                "note_id": "soap:101",
                "encounter_date": "2025-09-12",
            },
            {
                # Real verbatim
                "phrase": "insulin glargine for diabetes",
                "confidence": 0.7,
                "meat_element": "T",
                "note_id": "cn:202",
                "encounter_date": "2025-06-04",
            },
        ],
    }
    out = svc._parse_response(raw, NOTES)
    assert len(out) == 1
    assert out[0]["evidence_phrase"] == "insulin glargine for diabetes"


def test_parse_response_clamps_confidence_and_validates_meat() -> None:
    raw = {
        "suggestions": [
            {
                "phrase": "metformin 1000mg BID",
                "confidence": 4.2,           # out of range → clamp to 1.0
                "meat_element": "x",         # invalid → None
                "note_id": "soap:101",
                "encounter_date": "not-a-date",
            }
        ]
    }
    out = svc._parse_response(raw, NOTES)
    assert len(out) == 1
    assert out[0]["confidence"] == 1.0
    assert out[0]["meat_element"] is None
    assert out[0]["encounter_date"] is None


def test_parse_response_returns_empty_on_invalid_json_string() -> None:
    out = svc._parse_response("this is not json", NOTES)
    assert out == []


def test_parse_response_returns_empty_on_unexpected_shape() -> None:
    out = svc._parse_response(["unexpected", "list"], NOTES)
    assert out == []


def test_parse_response_returns_empty_when_suggestions_missing() -> None:
    out = svc._parse_response({"found": False}, NOTES)
    assert out == []


def test_parse_response_unknown_note_id_nulled_not_dropped() -> None:
    raw = {
        "suggestions": [
            {
                "phrase": "metformin 1000mg BID",
                "confidence": 0.8,
                "meat_element": "T",
                "note_id": "soap:99999",   # unknown id
                "encounter_date": "2025-09-12",
            }
        ]
    }
    out = svc._parse_response(raw, NOTES)
    assert len(out) == 1
    assert out[0]["source_note_id"] is None  # nulled, not dropped


# ---------------------------------------------------------------------------
# suggest_recoding — happy path
# ---------------------------------------------------------------------------

def _stub_persist(captured: list[dict[str, Any]]):
    """Return a _persist_suggestions stub that captures inserted rows."""
    def _persist(gap_id: int, suggestions: list[dict[str, Any]], llm_model_used: str):
        captured.extend(suggestions)
        return list(range(1000, 1000 + len(suggestions)))
    return _persist


def test_suggest_recoding_happy_path(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "_load_gap", lambda gid: GAP)
    monkeypatch.setattr(svc, "_fetch_recent_notes", lambda pid, months=12: NOTES)
    monkeypatch.setattr(svc, "_persist_suggestions", _stub_persist(captured))

    def fake_llm(prompt: str):
        # The prompt must mention the icd10 and hcc — sanity check the wiring
        assert "E11.9" in prompt
        return {
            "found": True,
            "suggestions": [
                {
                    "phrase": "longstanding type 2 diabetes mellitus",
                    "confidence": 0.91,
                    "meat_element": "A",
                    "note_id": "soap:101",
                    "encounter_date": "2025-09-12",
                }
            ],
        }

    result = svc.suggest_recoding(1, llm_call=fake_llm)
    assert result["gap_id"] == 1
    assert result["scanned_note_count"] == 2
    assert len(result["suggestions"]) == 1
    s = result["suggestions"][0]
    assert s["evidence_phrase"] == "longstanding type 2 diabetes mellitus"
    assert s["status"] == "pending"
    assert s["id"] == 1000
    # Persisted exactly the verbatim suggestion
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# suggest_recoding — graceful failures
# ---------------------------------------------------------------------------

def test_suggest_recoding_llm_timeout_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_load_gap", lambda gid: GAP)
    monkeypatch.setattr(svc, "_fetch_recent_notes", lambda pid, months=12: NOTES)
    monkeypatch.setattr(
        svc, "_persist_suggestions",
        lambda *a, **kw: pytest.fail("persist must not be called on LLM error"),
    )

    def boom(_prompt: str):
        raise TimeoutError("Gemini timed out")

    result = svc.suggest_recoding(1, llm_call=boom)
    assert result["suggestions"] == []
    assert "error" in result
    assert result["scanned_note_count"] == 2


def test_suggest_recoding_invalid_json_returns_empty(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "_load_gap", lambda gid: GAP)
    monkeypatch.setattr(svc, "_fetch_recent_notes", lambda pid, months=12: NOTES)
    monkeypatch.setattr(svc, "_persist_suggestions", _stub_persist(captured))

    def garbage(_prompt: str):
        return "not valid json at all"

    result = svc.suggest_recoding(1, llm_call=garbage)
    assert result["suggestions"] == []
    assert captured == []


def test_suggest_recoding_no_notes_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_load_gap", lambda gid: GAP)
    monkeypatch.setattr(svc, "_fetch_recent_notes", lambda pid, months=12: [])
    monkeypatch.setattr(
        svc, "_persist_suggestions",
        lambda *a, **kw: pytest.fail("persist must not be called when no notes"),
    )

    def must_not_call(_prompt: str):
        pytest.fail("LLM must not be called when there are no notes")

    result = svc.suggest_recoding(1, llm_call=must_not_call)
    assert result["suggestions"] == []
    assert result["scanned_note_count"] == 0


def test_suggest_recoding_gap_not_found(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_load_gap", lambda gid: None)
    result = svc.suggest_recoding(9999)
    assert result["suggestions"] == []
    assert "not found" in (result.get("error") or "").lower()


# ---------------------------------------------------------------------------
# accept_suggestion promotes evidence
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Minimal cursor that records executed statements + canned fetchone."""

    def __init__(self, fetch_row: dict[str, Any] | None):
        self._fetch_row = fetch_row
        self.executed: list[tuple[str, tuple]] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()):
        self.executed.append((sql, params))
        # All UPDATEs in the test count as 1 affected row
        self.rowcount = 1

    def fetchone(self):
        return self._fetch_row


class _FakeCM:
    """Context manager wrapping a _FakeCursor."""

    def __init__(self, cursor: _FakeCursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *a):
        return False


def test_accept_suggestion_promotes_evidence_to_gap(monkeypatch) -> None:
    fetch_row = {
        "id": 1000,
        "gap_id": 1,
        "evidence_phrase": "longstanding type 2 diabetes mellitus",
        "meat_element": "A",
        "encounter_date": None,
        "source_note_id": "soap:101",
        "status": "pending",
    }
    cursor = _FakeCursor(fetch_row=fetch_row)
    monkeypatch.setattr(svc, "raf_cursor", lambda: _FakeCM(cursor))

    result = svc.accept_suggestion(1000, reviewer="kriya")

    assert result == {
        "ok": True,
        "suggestion_id": 1000,
        "gap_id": 1,
        "status": "accepted",
    }
    # Three statements: SELECT, UPDATE recapture_gaps, UPDATE recapture_ai_suggestions
    assert len(cursor.executed) == 3
    sqls = [s.strip().split()[0].upper() for s, _ in cursor.executed]
    assert sqls == ["SELECT", "UPDATE", "UPDATE"]
    # The recapture_gaps update carried the evidence phrase + MEAT element
    update_gap_sql, update_gap_params = cursor.executed[1]
    assert "recapture_gaps" in update_gap_sql
    assert update_gap_params[0] == "longstanding type 2 diabetes mellitus"
    assert update_gap_params[1] == "A"


def test_accept_suggestion_rejects_non_pending(monkeypatch) -> None:
    fetch_row = {
        "id": 1000,
        "gap_id": 1,
        "evidence_phrase": "x",
        "meat_element": None,
        "encounter_date": None,
        "source_note_id": None,
        "status": "accepted",
    }
    cursor = _FakeCursor(fetch_row=fetch_row)
    monkeypatch.setattr(svc, "raf_cursor", lambda: _FakeCM(cursor))

    result = svc.accept_suggestion(1000)
    assert result["ok"] is False
    assert "already accepted" in result["error"]


def test_reject_suggestion_marks_rejected(monkeypatch) -> None:
    cursor = _FakeCursor(fetch_row=None)
    cursor.rowcount = 1
    monkeypatch.setattr(svc, "raf_cursor", lambda: _FakeCM(cursor))

    # The reject path uses a single UPDATE that sets rowcount to 1 in the stub
    def execute(sql, params=()):
        cursor.executed.append((sql, params))
        cursor.rowcount = 1
    cursor.execute = execute  # type: ignore[assignment]

    result = svc.reject_suggestion(1000, reviewer="kriya")
    assert result == {"ok": True, "suggestion_id": 1000, "status": "rejected"}
    assert "rejected" in cursor.executed[0][0]


# ---------------------------------------------------------------------------
# Sanity — JSON-loadable response is also accepted
# ---------------------------------------------------------------------------

def test_parse_response_accepts_json_string() -> None:
    raw = json.dumps({
        "suggestions": [
            {
                "phrase": "metformin 1000mg BID",
                "confidence": 0.88,
                "meat_element": "T",
                "note_id": "soap:101",
                "encounter_date": "2025-09-12",
            }
        ]
    })
    out = svc._parse_response(raw, NOTES)
    assert len(out) == 1
    assert out[0]["evidence_phrase"] == "metformin 1000mg BID"
