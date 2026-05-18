"""HIE adapter unit tests — CommonWell and Carequality FHIR R4 adapters.

All tests mock httpx.AsyncClient to avoid real network calls.
The rate-limit state is reset between tests via monkeypatching.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to reset rate-limit state between tests
# ---------------------------------------------------------------------------

def _reset_rate_state():
    from app.services.hie import base as base_mod
    base_mod._network_rate_state.clear()


# ---------------------------------------------------------------------------
# Shared FHIR fixture builders
# ---------------------------------------------------------------------------

def _make_patient_bundle(patients: list[dict]) -> dict:
    """Build a minimal FHIR Bundle containing Patient resources."""
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(patients),
        "entry": [
            {
                "resource": p,
                "search": {"score": p.pop("_score", 0.9)},
            }
            for p in patients
        ],
    }


def _make_doc_ref_bundle(doc_refs: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(doc_refs),
        "entry": [{"resource": d} for d in doc_refs],
    }


def _make_patient(pid: str, given: str, family: str, dob: str, gender: str, score: float = 0.95) -> dict:
    return {
        "resourceType": "Patient",
        "id": pid,
        "name": [{"given": [given], "family": family}],
        "birthDate": dob,
        "gender": gender,
        "_score": score,
    }


def _make_doc_ref(doc_id: str, binary_url: str, mime: str = "application/pdf") -> dict:
    return {
        "resourceType": "DocumentReference",
        "id": doc_id,
        "content": [{"attachment": {"url": binary_url, "contentType": mime}}],
    }


def _make_mock_response(json_body: dict, status: int = 200, content_type: str = "application/fhir+json") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_body)
    resp.content = json.dumps(json_body).encode()
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def _make_mock_binary_response(raw: bytes, content_type: str = "application/pdf") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.content = raw
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# CommonWell adapter tests
# ---------------------------------------------------------------------------

class TestCommonWellAdapter:

    def setup_method(self):
        _reset_rate_state()
        # Inject required env vars
        os.environ["HIE_COMMONWELL_CERT_PATH"] = "/fake/cert.pem"
        os.environ["HIE_COMMONWELL_KEY_PATH"] = "/fake/key.pem"
        os.environ["HIE_COMMONWELL_TRUST_BUNDLE"] = "/fake/ca.pem"
        os.environ["HIE_COMMONWELL_BASE_URL"] = "https://cw.test"

    def teardown_method(self):
        for k in ["HIE_COMMONWELL_CERT_PATH", "HIE_COMMONWELL_KEY_PATH",
                  "HIE_COMMONWELL_TRUST_BUNDLE", "HIE_COMMONWELL_BASE_URL"]:
            os.environ.pop(k, None)
        _reset_rate_state()

    # --- discover_patient ---

    def test_discover_patient_zero_matches(self):
        from app.services.hie.commonwell import CommonWellAdapter

        empty_bundle = _make_patient_bundle([])
        mock_resp = _make_mock_response(empty_bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                adapter.discover_patient("John", "Doe", "1960-01-01", "male")
            )

        assert result == []
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/v1/patients/match" in call_args[0][0]

    def test_discover_patient_single_match(self):
        from app.services.hie.commonwell import CommonWellAdapter

        patients = [_make_patient("cw-001", "John", "Doe", "1960-01-01", "male", score=0.97)]
        bundle = _make_patient_bundle(patients)
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                adapter.discover_patient("John", "Doe", "1960-01-01", "male")
            )

        assert len(result) == 1
        assert result[0]["hie_patient_id"] == "cw-001"
        assert result[0]["network"] == "commonwell"

    def test_discover_patient_many_matches_sorted_by_confidence(self):
        from app.services.hie.commonwell import CommonWellAdapter

        patients = [
            _make_patient("cw-low", "John", "Doe", "1960-01-01", "male", score=0.60),
            _make_patient("cw-high", "John", "Doe", "1960-01-01", "male", score=0.98),
            _make_patient("cw-mid", "John", "Doe", "1960-01-01", "male", score=0.80),
        ]
        bundle = _make_patient_bundle(patients)
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                adapter.discover_patient("John", "Doe", "1960-01-01", "male")
            )

        assert len(result) == 3
        # Should be sorted descending by confidence
        confidences = [r["confidence"] for r in result]
        assert confidences == sorted(confidences, reverse=True)

    def test_discover_patient_includes_mbi_identifier(self):
        from app.services.hie.commonwell import CommonWellAdapter

        bundle = _make_patient_bundle([])
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            asyncio.run(
                adapter.discover_patient("Jane", "Smith", "1975-06-15", "female", mbi="1EG4-TE5-MK72")
            )

        posted_body = mock_client.post.call_args[1]["json"]
        param_names = [p["name"] for p in posted_body["parameter"]]
        assert "identifier" in param_names

    def test_mtls_cert_passed_to_httpx_client(self):
        from app.services.hie.commonwell import CommonWellAdapter

        bundle = _make_patient_bundle([])
        mock_resp = _make_mock_response(bundle)
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client_instance) as mock_cls:
            asyncio.run(adapter.discover_patient("A", "B", "2000-01-01", "male"))
            init_kwargs = mock_cls.call_args[1]
            assert init_kwargs["cert"] == ("/fake/cert.pem", "/fake/key.pem")
            assert init_kwargs["verify"] == "/fake/ca.pem"

    # --- list_document_references ---

    def test_list_document_references_parses_bundle(self):
        from app.services.hie.commonwell import CommonWellAdapter

        docs = [
            _make_doc_ref("doc-1", "https://cw.test/Binary/bin-1"),
            _make_doc_ref("doc-2", "https://cw.test/Binary/bin-2"),
        ]
        bundle = _make_doc_ref_bundle(docs)
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(adapter.list_document_references("cw-001"))

        assert len(result) == 2
        assert result[0]["id"] == "doc-1"
        # Verify correct URL called
        call_url = mock_client.get.call_args[0][0]
        assert "cw-001" in call_url
        assert "DocumentReference" in call_url

    def test_list_document_references_with_since_param(self):
        from app.services.hie.commonwell import CommonWellAdapter

        bundle = _make_doc_ref_bundle([])
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            asyncio.run(adapter.list_document_references("cw-001", since="2025-01-01"))

        call_params = mock_client.get.call_args[1].get("params", {})
        assert "date" in call_params
        assert call_params["date"].startswith("ge")

    # --- fetch_binary ---

    def test_fetch_binary_pdf_direct(self):
        from app.services.hie.commonwell import CommonWellAdapter

        pdf_bytes = b"%PDF-1.4 fake pdf content"
        mock_resp = _make_mock_binary_response(pdf_bytes, "application/pdf")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            raw, mime = asyncio.run(adapter.fetch_binary("https://cw.test/Binary/bin-1"))

        assert raw == pdf_bytes
        assert mime == "application/pdf"

    def test_fetch_binary_fhir_json_base64_fallback(self):
        from app.services.hie.commonwell import CommonWellAdapter

        pdf_bytes = b"%PDF-1.4 fake content"
        b64 = base64.b64encode(pdf_bytes).decode()
        fhir_binary = {
            "resourceType": "Binary",
            "contentType": "application/pdf",
            "data": b64,
        }
        mock_resp = _make_mock_response(fhir_binary, content_type="application/fhir+json")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        adapter = CommonWellAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            raw, mime = asyncio.run(adapter.fetch_binary("Binary/bin-1"))

        assert raw == pdf_bytes
        assert mime == "application/pdf"

    # --- network not configured ---

    def test_network_not_configured_raises(self):
        from app.services.hie.base import NetworkNotConfiguredError
        from app.services.hie.commonwell import CommonWellAdapter

        # Remove one required env var
        os.environ.pop("HIE_COMMONWELL_KEY_PATH", None)
        adapter = CommonWellAdapter()

        with pytest.raises(NetworkNotConfiguredError):
            asyncio.run(adapter.discover_patient("A", "B", "2000-01-01", "male"))

    def test_is_configured_false_when_missing_vars(self):
        from app.services.hie.commonwell import CommonWellAdapter
        os.environ.pop("HIE_COMMONWELL_TRUST_BUNDLE", None)
        adapter = CommonWellAdapter()
        assert adapter.is_configured() is False


# ---------------------------------------------------------------------------
# Carequality adapter tests
# ---------------------------------------------------------------------------

class TestCarequalityAdapter:

    def setup_method(self):
        _reset_rate_state()
        os.environ["HIE_CAREQUALITY_CERT_PATH"] = "/fake/cq-cert.pem"
        os.environ["HIE_CAREQUALITY_KEY_PATH"] = "/fake/cq-key.pem"
        os.environ["HIE_CAREQUALITY_TRUST_BUNDLE"] = "/fake/cq-ca.pem"
        os.environ["HIE_CAREQUALITY_BASE_URL"] = "https://cq.test/r4"

    def teardown_method(self):
        for k in ["HIE_CAREQUALITY_CERT_PATH", "HIE_CAREQUALITY_KEY_PATH",
                  "HIE_CAREQUALITY_TRUST_BUNDLE", "HIE_CAREQUALITY_BASE_URL"]:
            os.environ.pop(k, None)
        _reset_rate_state()

    def _make_cq_bundle(self, patients_with_scores: list[tuple[dict, float]]) -> dict:
        entries = []
        for patient, score in patients_with_scores:
            entries.append({
                "resource": patient,
                "search": {"score": score},
            })
        return {"resourceType": "Bundle", "type": "searchset", "entry": entries}

    def test_discover_patient_zero_matches(self):
        from app.services.hie.carequality import CarequalityAdapter

        bundle = {"resourceType": "Bundle", "entry": []}
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CarequalityAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                adapter.discover_patient("Jane", "Doe", "1975-03-12", "female")
            )
        assert result == []

    def test_discover_patient_uses_patient_match_url(self):
        from app.services.hie.carequality import CarequalityAdapter

        bundle = {"resourceType": "Bundle", "entry": []}
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CarequalityAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            asyncio.run(adapter.discover_patient("Jane", "Doe", "1975-03-12", "female"))

        url = mock_client.post.call_args[0][0]
        assert url.endswith("/Patient/$match")

    def test_discover_patient_multiple_matches_sorted(self):
        from app.services.hie.carequality import CarequalityAdapter

        p1 = {"resourceType": "Patient", "id": "cq-001", "name": [{"given": ["Jane"], "family": "Doe"}],
               "birthDate": "1975-03-12", "gender": "female"}
        p2 = {"resourceType": "Patient", "id": "cq-002", "name": [{"given": ["Jane"], "family": "Doe"}],
               "birthDate": "1975-03-12", "gender": "female"}
        bundle = self._make_cq_bundle([(p1, 0.95), (p2, 0.70)])
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        adapter = CarequalityAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(
                adapter.discover_patient("Jane", "Doe", "1975-03-12", "female")
            )

        assert len(result) == 2
        assert result[0]["confidence"] >= result[1]["confidence"]
        assert result[0]["network"] == "carequality"

    def test_list_document_references_parses_bundle(self):
        from app.services.hie.carequality import CarequalityAdapter

        docs = [
            _make_doc_ref("cq-doc-1", "https://cq.test/r4/Binary/b1"),
            _make_doc_ref("cq-doc-2", "https://cq.test/r4/Binary/b2"),
            _make_doc_ref("cq-doc-3", "https://cq.test/r4/Binary/b3"),
        ]
        bundle = _make_doc_ref_bundle(docs)
        mock_resp = _make_mock_response(bundle)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        adapter = CarequalityAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(adapter.list_document_references("cq-001"))

        assert len(result) == 3
        assert result[2]["id"] == "cq-doc-3"

    def test_mtls_cert_passed_to_httpx_client(self):
        from app.services.hie.carequality import CarequalityAdapter

        bundle = {"resourceType": "Bundle", "entry": []}
        mock_resp = _make_mock_response(bundle)
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_resp)

        adapter = CarequalityAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client_instance) as mock_cls:
            asyncio.run(adapter.discover_patient("A", "B", "2000-01-01", "male"))
            init_kwargs = mock_cls.call_args[1]
            assert init_kwargs["cert"] == ("/fake/cq-cert.pem", "/fake/cq-key.pem")
            assert init_kwargs["verify"] == "/fake/cq-ca.pem"

    def test_fetch_binary_fhir_json_base64_fallback(self):
        from app.services.hie.carequality import CarequalityAdapter

        raw_pdf = b"%PDF-1.4 carequality test doc"
        b64 = base64.b64encode(raw_pdf).decode()
        fhir_binary = {
            "resourceType": "Binary",
            "contentType": "application/pdf",
            "data": b64,
        }
        mock_resp = _make_mock_response(fhir_binary, content_type="application/fhir+json")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        adapter = CarequalityAdapter()
        with patch("httpx.AsyncClient", return_value=mock_client):
            raw, mime = asyncio.run(adapter.fetch_binary("Binary/b1"))

        assert raw == raw_pdf
        assert mime == "application/pdf"


# ---------------------------------------------------------------------------
# Sync flow tests (mocking DB + Gemini + adapter)
# ---------------------------------------------------------------------------

class TestSyncPatientFromHie:

    def setup_method(self):
        _reset_rate_state()
        os.environ["HIE_COMMONWELL_CERT_PATH"] = "/fake/cert.pem"
        os.environ["HIE_COMMONWELL_KEY_PATH"] = "/fake/key.pem"
        os.environ["HIE_COMMONWELL_TRUST_BUNDLE"] = "/fake/ca.pem"
        os.environ["HIE_COMMONWELL_BASE_URL"] = "https://cw.test"

    def teardown_method(self):
        for k in ["HIE_COMMONWELL_CERT_PATH", "HIE_COMMONWELL_KEY_PATH",
                  "HIE_COMMONWELL_TRUST_BUNDLE", "HIE_COMMONWELL_BASE_URL"]:
            os.environ.pop(k, None)
        _reset_rate_state()

    def _mock_adapter_for_sync(self, n_docs: int = 3):
        """Return a mock adapter for sync tests."""
        match = {
            "hie_patient_id": "cw-sync-001",
            "confidence": 0.97,
            "name": "John Doe",
            "dob": "1960-01-01",
            "sex": "male",
            "network": "commonwell",
        }
        doc_refs = [
            _make_doc_ref(f"doc-{i}", f"https://cw.test/Binary/bin-{i}")
            for i in range(n_docs)
        ]
        mock_adapter = AsyncMock()
        mock_adapter.is_configured = MagicMock(return_value=True)
        mock_adapter.discover_patient = AsyncMock(return_value=[match])
        mock_adapter.list_document_references = AsyncMock(return_value=doc_refs)
        mock_adapter.fetch_binary = AsyncMock(return_value=(b"%PDF-1.4 content", "application/pdf"))
        return mock_adapter

    def test_sync_3_docs_3_vision_3_dedup_rows(self):
        from app.services.hie.sync import sync_patient_from_hie

        mock_adapter = self._mock_adapter_for_sync(n_docs=3)

        demo = {"first_name": "John", "last_name": "Doe", "dob": "1960-01-01",
                "sex": "male", "mbi": None}

        suspects_per_doc = [
            {"hcc_code": "18", "icd10_code": "E11.65", "confidence": 0.9,
             "evidence_sentence": "type 2 diabetes"},
        ]

        with (
            patch("app.services.hie.sync._get_adapter", return_value=mock_adapter),
            patch("app.services.hie.sync._fetch_patient_demographics", return_value=demo),
            patch("app.services.hie.sync._upsert_hie_match") as mock_upsert,
            patch("app.services.hie.sync._log_hie_query"),
            patch("app.services.hie.sync._is_document_processed", return_value=False),
            patch("app.services.hie.sync._mark_document_processed") as mock_mark,
            patch(
                "app.services.hie.sync.extract_from_document",
                return_value={"suspects": suspects_per_doc},
            ) as mock_extract,
        ):
            result = sync_patient_from_hie(
                tenant_id="tenant-1",
                raf_patient_id=42,
                network="commonwell",
            )

        assert result["documents_fetched"] == 3
        assert result["suspects_extracted"] == 3  # 1 suspect * 3 docs
        assert result["documents_skipped"] == 0
        assert mock_mark.call_count == 3
        assert mock_extract.call_count == 3
        mock_upsert.assert_called_once()

    def test_sync_skips_already_processed_docs(self):
        from app.services.hie.sync import sync_patient_from_hie

        mock_adapter = self._mock_adapter_for_sync(n_docs=3)
        demo = {"first_name": "John", "last_name": "Doe", "dob": "1960-01-01",
                "sex": "male", "mbi": None}

        # All 3 docs already processed
        with (
            patch("app.services.hie.sync._get_adapter", return_value=mock_adapter),
            patch("app.services.hie.sync._fetch_patient_demographics", return_value=demo),
            patch("app.services.hie.sync._upsert_hie_match"),
            patch("app.services.hie.sync._log_hie_query"),
            patch("app.services.hie.sync._is_document_processed", return_value=True),
            patch("app.services.hie.sync._mark_document_processed") as mock_mark,
            patch("app.services.hie.sync.extract_from_document") as mock_extract,
        ):
            result = sync_patient_from_hie(
                tenant_id="tenant-1",
                raf_patient_id=42,
                network="commonwell",
            )

        assert result["documents_skipped"] == 3
        assert result["documents_fetched"] == 0
        assert mock_mark.call_count == 0
        assert mock_extract.call_count == 0

    def test_sync_returns_network_not_configured(self):
        from app.services.hie.sync import sync_patient_from_hie

        mock_adapter = MagicMock()
        mock_adapter.is_configured = MagicMock(return_value=False)

        with patch("app.services.hie.sync._get_adapter", return_value=mock_adapter):
            result = sync_patient_from_hie(
                tenant_id="tenant-1",
                raf_patient_id=42,
                network="commonwell",
            )

        assert result["status"] == "network_not_configured"

    def test_sync_handles_no_patient_found(self):
        from app.services.hie.sync import sync_patient_from_hie

        mock_adapter = MagicMock()
        mock_adapter.is_configured = MagicMock(return_value=True)

        with (
            patch("app.services.hie.sync._get_adapter", return_value=mock_adapter),
            patch("app.services.hie.sync._fetch_patient_demographics", return_value=None),
        ):
            result = sync_patient_from_hie(
                tenant_id="tenant-1",
                raf_patient_id=9999,
                network="commonwell",
            )

        assert "patient_not_found" in result["errors"]
