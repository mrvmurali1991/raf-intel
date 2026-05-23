"""
Tests for FHIR DocumentReference + Binary ingest pipeline.

Mocks:
  - adapter.list_document_references → 3 entries
  - adapter.fetch_binary             → PDF bytes
  - gemini_document_extractor.extract_from_document → 2 suspects per doc
  - raf_cursor                       → in-memory dedup store

Asserts:
  - 3 docs processed, 6 suspects persisted
  - dedup row inserted after first run
  - second run returns "already_processed" for all 3 docs
"""
from __future__ import annotations

import io
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_PDF = b"%PDF-1.4 fake pdf content for testing"

FAKE_SUSPECTS = [
    {
        "hcc_code": "18",
        "icd10_code": "E11.65",
        "description": "Type 2 DM with hyperglycemia",
        "confidence": 0.92,
        "evidence_sentence": "Patient has type 2 DM with chronic hyperglycemia",
        "page_number": 1,
        "meat": {
            "monitoring": "A1c checked quarterly",
            "evaluation": "HbA1c 8.2",
            "assessment": "Poorly controlled T2DM",
            "treatment": "Metformin 1000mg BID",
        },
    },
    {
        "hcc_code": "85",
        "icd10_code": "I50.32",
        "description": "Chronic systolic heart failure",
        "confidence": 0.88,
        "evidence_sentence": "EF 35% on echo, chronic systolic CHF",
        "page_number": 2,
        "meat": {
            "monitoring": "Echo q6m",
            "evaluation": "EF 35%",
            "assessment": "Chronic systolic HF",
            "treatment": "Carvedilol, Lisinopril",
        },
    },
]


def _make_doc_entry(doc_id: str, url: str) -> dict:
    return {
        "fullUrl": f"https://ehr.example.com/fhir/DocumentReference/{doc_id}",
        "resource": {
            "resourceType": "DocumentReference",
            "id": doc_id,
            "status": "current",
            "date": "2025-03-15T10:00:00Z",
            "content": [
                {
                    "attachment": {
                        "url": url,
                        "title": f"chart_{doc_id}.pdf",
                        "contentType": "application/pdf",
                    }
                }
            ],
        },
    }


THREE_DOC_ENTRIES = [
    _make_doc_entry("docA", "https://ehr.example.com/fhir/Binary/binA"),
    _make_doc_entry("docB", "https://ehr.example.com/fhir/Binary/binB"),
    _make_doc_entry("docC", "https://ehr.example.com/fhir/Binary/binC"),
]


# In-memory dedup store to simulate fhir_documents_processed table
_dedup_store: set[tuple[str, str]] = set()


@contextmanager
def _mock_raf_cursor():
    """Context-manager mock for app.db.raf_cursor that supports dedup queries."""
    cur = MagicMock()

    def execute_side_effect(sql: str, params=None):
        sql_upper = sql.strip().upper()
        if "SELECT 1 FROM FHIR_DOCUMENTS_PROCESSED" in sql_upper:
            key = (params[0], params[1]) if params else ("", "")
            cur._last_select_result = key in _dedup_store
        elif "INSERT INTO FHIR_DOCUMENTS_PROCESSED" in sql_upper:
            if params:
                _dedup_store.add((params[0], params[1]))
        elif "SELECT" in sql_upper and "RAF_SUSPECT_CONDITIONS" in sql_upper:
            cur._last_select_result = False
        elif "INSERT INTO RAF_SUSPECT_CONDITIONS" in sql_upper:
            cur.lastrowid = 999
        elif "INSERT INTO RAF_MEAT_EVIDENCE" in sql_upper:
            pass

    def fetchone_side_effect():
        result = getattr(cur, "_last_select_result", None)
        if result is True:
            return (1,)
        if isinstance(result, dict):
            return result
        return None

    cur.execute.side_effect = execute_side_effect
    cur.fetchone.side_effect = fetchone_side_effect
    cur.fetchall.return_value = []
    cur.lastrowid = 999
    yield cur


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFhirDocumentReferenceIngest:
    """Core pipeline tests."""

    def setup_method(self) -> None:
        _dedup_store.clear()

    def _run_ingest(self, adapter_mock, patient_row: dict | None = None):
        """Helper: patch everything and call _process_one for each of 3 docs."""
        import app.services.fhir_document_ingest as svc

        processed = []
        for entry in THREE_DOC_ENTRIES:
            resource = entry["resource"]
            doc_id = resource["id"]
            attach_url = resource["content"][0]["attachment"]["url"]
            fname = resource["content"][0]["attachment"].get("title")

            with patch("app.services.fhir_document_ingest.raf_cursor", _mock_raf_cursor), \
                 patch(
                     "app.services.openemr_document_ingest._persist_suspect_to_raf",
                     side_effect=lambda **kw: 42,
                 ) as mock_persist, \
                 patch(
                     "app.services.openemr_document_ingest._persist_meat",
                 ) as mock_meat, \
                 patch(
                     "app.services.gemini_document_extractor.extract_from_document",
                     return_value={"suspects": FAKE_SUSPECTS},
                 ) as mock_gemini:

                result = svc._process_one(
                    tenant_id="tenant1",
                    raf_patient_id=101,
                    fhir_document_id=doc_id,
                    attachment_url=attach_url,
                    filename=fname,
                    adapter=adapter_mock,
                    measurement_year=2025,
                )
                processed.append(result)

        return processed

    def test_three_docs_processed(self) -> None:
        """3 docs → each returns status success."""
        adapter = MagicMock()
        adapter.fetch_binary.return_value = (FAKE_PDF, "application/pdf")

        results = self._run_ingest(adapter)

        assert len(results) == 3
        for r in results:
            assert r["status"] == "success", f"Expected success, got {r}"

    def test_six_suspects_persisted(self) -> None:
        """2 suspects × 3 docs = 6 suspects_persisted total."""
        adapter = MagicMock()
        adapter.fetch_binary.return_value = (FAKE_PDF, "application/pdf")

        results = self._run_ingest(adapter)
        total = sum(r.get("suspects_persisted", 0) for r in results)
        assert total == 6

    def test_dedup_row_inserted(self) -> None:
        """After first run, fhir_documents_processed must contain all 3 doc IDs."""
        adapter = MagicMock()
        adapter.fetch_binary.return_value = (FAKE_PDF, "application/pdf")

        self._run_ingest(adapter)

        assert ("tenant1", "docA") in _dedup_store
        assert ("tenant1", "docB") in _dedup_store
        assert ("tenant1", "docC") in _dedup_store

    def test_idempotency_second_run_already_processed(self) -> None:
        """Second run on same docs returns 'already_processed' for all 3."""
        adapter = MagicMock()
        adapter.fetch_binary.return_value = (FAKE_PDF, "application/pdf")

        # First run — populate dedup store
        self._run_ingest(adapter)

        # Second run — all should be already_processed
        results2 = self._run_ingest(adapter)

        for r in results2:
            assert r["status"] == "already_processed", (
                f"Expected already_processed on second run, got {r}"
            )

    def test_fetch_binary_called_for_each_doc(self) -> None:
        """fetch_binary must be called once per document."""
        adapter = MagicMock()
        adapter.fetch_binary.return_value = (FAKE_PDF, "application/pdf")

        self._run_ingest(adapter)

        assert adapter.fetch_binary.call_count == 3

    def test_fetch_binary_error_captured(self) -> None:
        """If fetch_binary raises, status is 'fetch_error' and no suspects persisted."""
        import app.services.fhir_document_ingest as svc

        adapter = MagicMock()
        adapter.fetch_binary.side_effect = Exception("connection refused")

        entry = THREE_DOC_ENTRIES[0]
        resource = entry["resource"]

        with patch("app.services.fhir_document_ingest.raf_cursor", _mock_raf_cursor):
            result = svc._process_one(
                tenant_id="tenant1",
                raf_patient_id=101,
                fhir_document_id=resource["id"],
                attachment_url=resource["content"][0]["attachment"]["url"],
                filename=None,
                adapter=adapter,
                measurement_year=2025,
            )

        assert result["status"] == "fetch_error"
        assert "suspects_persisted" not in result or result.get("suspects_persisted", 0) == 0


class TestListDocumentReferences:
    """Unit tests for the adapter method."""

    def test_returns_entries_list(self) -> None:
        """list_document_references should filter to DocumentReference resourceType."""
        from app.services.vendor_adapters.openemr_fhir import OpenEMRFhirAdapter

        connection = {
            "id": 1,
            "base_url": "https://ehr.example.com/fhir",
            "token_url": "",
            "client_id": "cid",
            "client_secret": "csec",
            "access_token": "tok",
        }
        adapter = OpenEMRFhirAdapter(connection)

        with patch.object(adapter, "_fhir_get_all", return_value=THREE_DOC_ENTRIES) as mock_get_all, \
             patch.object(adapter, "_get_access_token", return_value="tok"):

            from app.services.circuit_breaker import CircuitState
            with patch("app.services.circuit_breaker.get_breaker") as mock_gb:
                mock_cb = MagicMock()
                mock_cb.state = CircuitState.CLOSED
                mock_gb.return_value = mock_cb

                entries = adapter.list_document_references("patient-123", since="2025-01-01")

        assert len(entries) == 3
        assert all(e["resource"]["resourceType"] == "DocumentReference" for e in entries)

    def test_params_built_correctly(self) -> None:
        """since and _count should appear in the FHIR query params."""
        from app.services.vendor_adapters.openemr_fhir import OpenEMRFhirAdapter

        connection = {
            "id": 1,
            "base_url": "https://ehr.example.com/fhir",
            "access_token": "tok",
        }
        adapter = OpenEMRFhirAdapter(connection)

        captured_params: dict = {}

        def fake_get_all(resource_type: str, params=None, max_pages=20):
            captured_params.update(params or {})
            return []

        with patch.object(adapter, "_fhir_get_all", side_effect=fake_get_all), \
             patch.object(adapter, "_get_access_token", return_value="tok"):

            from app.services.circuit_breaker import CircuitState
            with patch("app.services.circuit_breaker.get_breaker") as mock_gb:
                mock_cb = MagicMock()
                mock_cb.state = CircuitState.CLOSED
                mock_gb.return_value = mock_cb

                adapter.list_document_references("pid-42", since="2025-06-01", _count=25)

        assert captured_params.get("subject") == "Patient/pid-42"
        assert captured_params.get("date") == "ge2025-06-01"
        assert captured_params.get("_count") == "25"


class TestFetchBinary:
    """Unit tests for fetch_binary."""

    def test_raw_bytes_returned(self) -> None:
        """fetch_binary returns (bytes, mime_type) for raw PDF response."""
        from app.services.vendor_adapters.openemr_fhir import OpenEMRFhirAdapter
        import httpx

        connection = {
            "id": 1,
            "base_url": "https://ehr.example.com/fhir",
            "access_token": "tok",
        }
        adapter = OpenEMRFhirAdapter(connection)

        fake_response = MagicMock(spec=httpx.Response)
        fake_response.status_code = 200
        fake_response.headers = {"content-type": "application/pdf"}
        fake_response.content = FAKE_PDF

        with patch("httpx.Client") as mock_client_cls, \
             patch.object(adapter, "_get_access_token", return_value="tok"):

            from app.services.circuit_breaker import CircuitState
            with patch("app.services.circuit_breaker.get_breaker") as mock_gb:
                mock_cb = MagicMock()
                mock_cb.state = CircuitState.CLOSED
                mock_gb.return_value = mock_cb

                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.get.return_value = fake_response
                mock_client_cls.return_value = mock_client

                result_bytes, result_mime = adapter.fetch_binary("Binary/binA")

        assert result_bytes == FAKE_PDF
        assert result_mime == "application/pdf"

    def test_full_url_passed_directly(self) -> None:
        """Full https:// URL must be used as-is, not prefixed with base_url."""
        from app.services.vendor_adapters.openemr_fhir import OpenEMRFhirAdapter
        import httpx

        connection = {
            "id": 1,
            "base_url": "https://ehr.example.com/fhir",
            "access_token": "tok",
        }
        adapter = OpenEMRFhirAdapter(connection)

        fake_response = MagicMock(spec=httpx.Response)
        fake_response.status_code = 200
        fake_response.headers = {"content-type": "application/pdf"}
        fake_response.content = b"data"

        called_urls = []

        with patch("httpx.Client") as mock_client_cls, \
             patch.object(adapter, "_get_access_token", return_value="tok"):

            from app.services.circuit_breaker import CircuitState
            with patch("app.services.circuit_breaker.get_breaker") as mock_gb:
                mock_cb = MagicMock()
                mock_cb.state = CircuitState.CLOSED
                mock_gb.return_value = mock_cb

                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)

                def capture_get(url, **kwargs):
                    called_urls.append(url)
                    return fake_response

                mock_client.get.side_effect = capture_get
                mock_client_cls.return_value = mock_client

                adapter.fetch_binary("https://external-ehr.org/fhir/Binary/xyz")

        assert called_urls[0] == "https://external-ehr.org/fhir/Binary/xyz"
