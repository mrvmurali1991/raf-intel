"""
Unit tests for FHIR write-back safety improvements (round-2 review fixes).

Tests cover:
- verification_status logic (provisional vs confirmed)
- note[] population from MEAT evidence letters
- evidence[] element from source_encounter_id
- recorder Practitioner ref when user NPI present
- reverse_problem_list_condition emits audit and updates DB
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers to build condition body without DB / network
# ---------------------------------------------------------------------------

def _build(
    *,
    meat_signed: bool = False,
    force_accepted: bool = False,
    user_role: str | None = None,
    user_npi: str | None = None,
    meat_notes: list | None = None,
    source: dict | None = None,
    verification_status: str = "confirmed",
):
    from app.services.fhir_problem_list import build_condition_body

    return build_condition_body(
        patient_emr_pid="42",
        icd10_code="E11.9",
        hcc_label="Type 2 Diabetes",
        source=source or {"suspect_id": 7, "source": "nlp"},
        meat_signed=meat_signed,
        force_accepted=force_accepted,
        user_role=user_role,
        user_npi=user_npi,
        meat_notes=meat_notes or [],
        verification_status=verification_status,
    )


def _get_ver_code(body: dict) -> str:
    return body["verificationStatus"]["coding"][0]["code"]


# ---------------------------------------------------------------------------
# Test 1 — provisional when MEAT absent
# ---------------------------------------------------------------------------

def test_provisional_without_meat():
    body = _build(meat_signed=False, user_role="coder")
    assert _get_ver_code(body) == "provisional", (
        "Should be provisional when MEAT not signed"
    )


# ---------------------------------------------------------------------------
# Test 2 — provisional when user is not credentialed even with MEAT
# ---------------------------------------------------------------------------

def test_provisional_non_credentialed_role_even_with_meat():
    body = _build(meat_signed=True, user_role="viewer")
    assert _get_ver_code(body) == "provisional"


def test_provisional_null_role_with_meat():
    body = _build(meat_signed=True, user_role=None)
    assert _get_ver_code(body) == "provisional"


# ---------------------------------------------------------------------------
# Test 3 — confirmed when MEAT signed AND credentialed role
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["coder", "admin", "physician"])
def test_confirmed_with_meat_and_credentialed_role(role):
    body = _build(meat_signed=True, user_role=role)
    assert _get_ver_code(body) == "confirmed", (
        f"Role '{role}' with MEAT should yield confirmed"
    )


# ---------------------------------------------------------------------------
# Test 4 — note[] populated from MEAT letters
# ---------------------------------------------------------------------------

def test_notes_populated_from_meat_letters():
    notes = [
        {"authorString": "coder1", "time": "2026-05-01T00:00:00", "text": "[M] Monitoring: HbA1c elevated"},
        {"authorString": "coder1", "time": "2026-05-01T00:00:00", "text": "[E] Evaluation: exam findings confirm DM"},
        {"authorString": "coder1", "time": "2026-05-01T00:00:00", "text": "[A] Assessment: insulin regimen"},
        {"authorString": "coder1", "time": "2026-05-01T00:00:00", "text": "[T] Treatment: metformin prescribed"},
    ]
    body = _build(meat_notes=notes, meat_signed=True, user_role="coder")
    assert "note" in body
    assert len(body["note"]) == 4
    texts = [n["text"] for n in body["note"]]
    assert any("[M]" in t for t in texts)
    assert any("[E]" in t for t in texts)
    assert any("[A]" in t for t in texts)
    assert any("[T]" in t for t in texts)


def test_notes_empty_when_no_meat_evidence():
    body = _build(meat_notes=[], meat_signed=False, user_role="coder")
    assert "note" not in body


# ---------------------------------------------------------------------------
# Test 5 — evidence[] points to source encounter
# ---------------------------------------------------------------------------

def test_evidence_element_with_encounter():
    body = _build(source={"suspect_id": 7, "source_encounter_id": 99})
    assert "evidence" in body
    ref = body["evidence"][0]["detail"][0]["reference"]
    assert ref == "DocumentReference/99"


def test_evidence_absent_when_no_encounter():
    body = _build(source={"suspect_id": 7})
    assert "evidence" not in body


# ---------------------------------------------------------------------------
# Test 6 — recorder present when NPI provided
# ---------------------------------------------------------------------------

def test_recorder_ref_when_npi_present():
    body = _build(user_npi="1234567890")
    assert "recorder" in body
    assert body["recorder"] == {"reference": "Practitioner/1234567890"}


def test_recorder_absent_when_npi_null():
    body = _build(user_npi=None)
    assert "recorder" not in body


# ---------------------------------------------------------------------------
# Test 7 — backward compat: explicit non-"confirmed" verification_status
# is preserved (e.g. callers setting "entered-in-error")
# ---------------------------------------------------------------------------

def test_explicit_non_default_verification_status_preserved():
    body = _build(verification_status="entered-in-error")
    assert _get_ver_code(body) == "entered-in-error"


# ---------------------------------------------------------------------------
# Test 8 — _fetch_meat_notes returns empty list on DB error (non-blocking)
# ---------------------------------------------------------------------------

def test_fetch_meat_notes_graceful_on_db_error():
    from app.services.fhir_problem_list import _fetch_meat_notes

    # raf_cursor is imported inside the function body, so patch via app.db
    with patch("app.db.raf_cursor") as mock_cursor_ctx:
        mock_cursor_ctx.side_effect = Exception("DB unavailable")
        result = _fetch_meat_notes(42)
    assert result == []


# ---------------------------------------------------------------------------
# Test 9 — reverse_problem_list_condition emits audit + updates DB
# ---------------------------------------------------------------------------

def test_reverse_emits_audit_and_updates_db():
    from app.services.fhir_problem_list import reverse_problem_list_condition

    # Mock FHIR HTTP call
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    # Mock DB cursor context manager
    mock_cur = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cur)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    fake_adapter = MagicMock()
    fake_adapter.base_url = "https://emr.example.com/fhir"
    fake_adapter._auth_headers.return_value = {"Authorization": "Bearer tok"}

    with (
        patch("app.services.fhir_problem_list._get_fhir_adapter", return_value=fake_adapter),
        patch("httpx.Client") as mock_client_cls,
        # emit_audit_event is imported locally then called — patch in its home module
        patch("app.services.immutable_audit.append_audit_entry") as mock_emit,
        # raf_cursor is imported locally too — patch in app.db
        patch("app.db.raf_cursor", return_value=mock_ctx),
    ):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.put.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = reverse_problem_list_condition(
            condition_id="cond-abc123",
            reversal_reason="This diagnosis was entered in error by AI without physician review",
            tenant_id="tenant-1",
            user_id=99,
            adapter=fake_adapter,
        )

    assert result == {"success": True, "condition_id": "cond-abc123"}

    # Audit event emitted — append_audit_entry is the final writer called by emit_audit_event
    mock_emit.assert_called_once()
    call_kwargs = mock_emit.call_args[1]
    assert call_kwargs["event_type"] == "SUSPECT_WRITEBACK_REVERSED"
    assert call_kwargs["user_id"] == 99
    assert call_kwargs["resource_id"] == "cond-abc123"

    # DB update executed
    mock_cur.execute.assert_called_once()
    sql_call = mock_cur.execute.call_args[0][0]
    assert "fhir_writeback_reversed_at" in sql_call
    assert "fhir_writeback_reversal_reason" in sql_call


def test_reverse_raises_on_short_reason():
    from app.services.fhir_problem_list import reverse_problem_list_condition

    fake_adapter = MagicMock()
    fake_adapter.base_url = "https://emr.example.com/fhir"

    with pytest.raises(ValueError, match="30 characters"):
        reverse_problem_list_condition(
            condition_id="cond-abc",
            reversal_reason="too short",
            tenant_id="t1",
            user_id=1,
            adapter=fake_adapter,
        )


def test_reverse_raises_on_fhir_error():
    from app.services.fhir_problem_list import reverse_problem_list_condition

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    fake_adapter = MagicMock()
    fake_adapter.base_url = "https://emr.example.com/fhir"
    fake_adapter._auth_headers.return_value = {"Authorization": "Bearer tok"}

    with (
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.put.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="FHIR Condition reversal failed"):
            reverse_problem_list_condition(
                condition_id="cond-xyz",
                reversal_reason="This was incorrectly coded by the AI without clinical review",
                tenant_id="t1",
                user_id=1,
                adapter=fake_adapter,
            )
