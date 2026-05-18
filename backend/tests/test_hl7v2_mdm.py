"""
HL7 v2 MDM listener — unit tests
=================================

Tests cover:
  1. Parser: MDM^T02 with base64 PDF in OBX-5 (ED value type)
  2. Parser: MDM^T08 with multi-line text (TX value type)
  3. Receiver: POST without HMAC header → 401
  4. Receiver: POST with invalid HMAC key → 403
  5. Receiver: POST with valid HMAC key → 200 + HL7 ACK
  6. Idempotency: same msg_control_id twice → 200 but no duplicate row

All DB calls are patched.  No real database or Gemini connection required.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Sample HL7 messages
# ---------------------------------------------------------------------------

# A tiny valid PDF header (not a full PDF — just enough to survive b64 decode)
_DUMMY_PDF_B64 = base64.b64encode(b"%PDF-1.4 fake pdf content").decode()

# MDM^T02 — original document notification with embedded base64 PDF
_MDM_T02_PDF = (
    "MSH|^~\\&|MIRTH|HOSPITAL|RAF-INTELLIGENCE|RAF"
    "|20260101120000||MDM^T02|CTRL-001|P|2.5\r"
    "EVN|T02|20260101120000\r"
    "PID|1||MRN-12345^^^HOSPITAL^MR||Doe^John^A||19600101|M\r"
    "PV1|1|I|ICU^101^1\r"
    # TXA field map (1-based HL7 / 0-based list index):
    #   [0]=TXA [1]=SetID [2]=DocType [3]=DocContentPres [4]=ActivityDT
    #   [5..11]=empty(TXA-5 to TXA-11)  [12]=UniqueDocFilename(TXA-12)
    #   [13..16]=empty(TXA-13 to TXA-16)  [17]=DocumentCompletionStatus(TXA-17)
    "TXA|1|HP|TX|20260101||||||||DOC-FILE-001.pdf|||||AU\r"
    f"OBX|1|ED|18842-5^Discharge Summary^LN||PDF^application^pdf^Base64^{_DUMMY_PDF_B64}||||||F|||20260101120000\r"
)

# MDM^T08 — document edit notification with multi-line text report
_MDM_T08_TEXT = (
    "MSH|^~\\&|RHAPSODY|CLINIC|RAF-INTELLIGENCE|RAF"
    "|20260102090000||MDM^T08|CTRL-002|P|2.5\r"
    "EVN|T08|20260102090000\r"
    "PID|1||MRN-99999^^^CLINIC^MR||Smith^Jane^B||19750315|F\r"
    "TXA|1|PN|TX|20260102||||||||||NOTE-AMEND.txt||2|AU\r"
    "OBX|1|TX|11506-3^Progress Note^LN||Patient presents with uncontrolled T2DM.||||||F\r"
    "OBX|2|TX|11506-3^Progress Note^LN||HbA1c 9.8 — recommend insulin adjustment.||||||F\r"
)


# ---------------------------------------------------------------------------
# Parser tests (pure unit — no DB, no HTTP)
# ---------------------------------------------------------------------------


class TestParseMDM:
    """Tests for ``hl7v2_mdm_listener.parse_mdm``."""

    def test_t02_extracts_all_fields(self):
        from app.services.hl7v2_mdm_listener import parse_mdm

        result = parse_mdm(_MDM_T02_PDF)

        assert result["msg_type"] == "MDM^T02"
        assert result["msg_control_id"] == "CTRL-001"
        assert result["patient_external_id"] == "MRN-12345"
        assert result["document_type"] == "HP"
        assert result["document_status"] == "AU"
        assert result["document_filename"] == "DOC-FILE-001.pdf"
        # PDF payload decoded
        assert result["encoded_payload"] is not None
        assert result["encoded_payload"].startswith(b"%PDF")
        assert result["payload_mime"] == "application/pdf"
        assert result["text_payload"] is None

    def test_t08_text_mode(self):
        from app.services.hl7v2_mdm_listener import parse_mdm

        result = parse_mdm(_MDM_T08_TEXT)

        assert result["msg_type"] == "MDM^T08"
        assert result["msg_control_id"] == "CTRL-002"
        assert result["patient_external_id"] == "MRN-99999"
        assert result["encoded_payload"] is None
        assert result["payload_mime"] == "text/plain"
        # Both OBX lines concatenated
        assert "uncontrolled T2DM" in result["text_payload"]
        assert "HbA1c 9.8" in result["text_payload"]

    def test_non_mdm_raises(self):
        from app.services.hl7v2_mdm_listener import HL7MDMParseError, parse_mdm

        adt = (
            "MSH|^~\\&|EMR|HOSP|RAF|RAF|20260101||ADT^A01|X001|P|2.5\r"
            "EVN|A01|20260101\r"
        )
        with pytest.raises(HL7MDMParseError, match="ADT"):
            parse_mdm(adt)

    def test_empty_raises(self):
        from app.services.hl7v2_mdm_listener import HL7MDMParseError, parse_mdm

        with pytest.raises(HL7MDMParseError, match="Empty"):
            parse_mdm("")

    def test_sending_app_and_facility(self):
        from app.services.hl7v2_mdm_listener import parse_mdm

        result = parse_mdm(_MDM_T02_PDF)
        assert result["sending_app"] == "MIRTH"
        assert result["sending_facility"] == "HOSPITAL"

    def test_observation_date_extracted(self):
        from app.services.hl7v2_mdm_listener import parse_mdm

        result = parse_mdm(_MDM_T02_PDF)
        assert result["observation_date"] == "20260101120000"


# ---------------------------------------------------------------------------
# Receiver endpoint tests — HTTP layer
# ---------------------------------------------------------------------------


def _make_source_row(source_key: str = "test-secret-key") -> dict:
    return {
        "id": 42,
        "tenant_id": "tenant_test",
        "name": "Test Mirth Channel",
        "hmac_secret": source_key,
        "is_active": 1,
    }


@contextmanager
def _patch_db(
    source_key: str = "test-secret-key",
    source_exists: bool = True,
    is_duplicate: bool = False,
    persist_row_id: int = 1,
):
    """Patch all DB calls in the receiver so no real MySQL is needed."""
    source_row = _make_source_row(source_key) if source_exists else None

    # raf_cursor context manager mock
    cur_mock = MagicMock()
    cur_mock.fetchone.return_value = source_row  # _lookup_source
    cur_mock.lastrowid = persist_row_id

    @contextmanager
    def _cursor_cm(*args, **kwargs):
        yield cur_mock

    with (
        patch(
            "app.routers.hl7v2_mdm_receiver.raf_cursor",
            side_effect=_cursor_cm,
        ),
        patch(
            "app.routers.hl7v2_mdm_receiver._is_duplicate",
            return_value=is_duplicate,
        ),
        patch(
            "app.routers.hl7v2_mdm_receiver._persist_message",
            return_value=persist_row_id,
        ),
        patch(
            "app.routers.hl7v2_mdm_receiver._update_message_status",
        ),
        patch(
            "app.routers.hl7v2_mdm_receiver._resolve_patient_id",
            return_value=None,
        ),
        patch(
            "app.routers.hl7v2_mdm_receiver._run_pipeline",
            return_value=0,
        ),
    ):
        yield


def _get_test_client():
    """Build a minimal FastAPI app with just the MDM receiver router."""
    from fastapi import FastAPI
    from app.routers.hl7v2_mdm_receiver import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestReceiverAuth:
    """Authentication / HMAC header enforcement."""

    def test_missing_header_returns_401(self):
        client = _get_test_client()
        with _patch_db(source_exists=True):
            resp = client.post(
                "/api/hl7v2/mdm",
                content=_MDM_T02_PDF,
                headers={"Content-Type": "application/hl7-v2"},
            )
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self):
        client = _get_test_client()
        # source_exists=False → _lookup_source returns None → 403
        with _patch_db(source_exists=False):
            resp = client.post(
                "/api/hl7v2/mdm",
                content=_MDM_T02_PDF,
                headers={
                    "Content-Type": "application/hl7-v2",
                    "X-RAF-HL7-Source-Key": "wrong-key",
                },
            )
        assert resp.status_code == 403

    def test_valid_key_returns_200_with_ack(self):
        client = _get_test_client()
        with _patch_db(source_key="good-key", source_exists=True):
            resp = client.post(
                "/api/hl7v2/mdm",
                content=_MDM_T02_PDF,
                headers={
                    "Content-Type": "application/hl7-v2",
                    "X-RAF-HL7-Source-Key": "good-key",
                },
            )
        assert resp.status_code == 200
        body = resp.text
        # Must contain an HL7 ACK header and MSA segment
        assert "MSH|" in body
        assert "MSA|AA|" in body


class TestReceiverIdempotency:
    """Same msg_control_id ingested twice must not create a duplicate row."""

    def test_duplicate_returns_200_no_insert(self):
        client = _get_test_client()

        persist_mock = MagicMock(return_value=1)

        with (
            patch(
                "app.routers.hl7v2_mdm_receiver._verify_source_key",
                return_value=_make_source_row(),
            ),
            patch(
                "app.routers.hl7v2_mdm_receiver._is_duplicate",
                return_value=True,
            ),
            patch(
                "app.routers.hl7v2_mdm_receiver._persist_message",
                persist_mock,
            ),
        ):
            resp = client.post(
                "/api/hl7v2/mdm",
                content=_MDM_T02_PDF,
                headers={
                    "Content-Type": "application/hl7-v2",
                    "X-RAF-HL7-Source-Key": "good-key",
                },
            )

        assert resp.status_code == 200
        assert "MSA|AA|" in resp.text
        # _persist_message must NOT have been called for a duplicate
        persist_mock.assert_not_called()
