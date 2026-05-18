"""
Unit tests for app.services.fhir_bulk_export_client

Uses unittest.mock to patch httpx calls — no network, no DB.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.fhir_bulk_export_client import (
    BulkExportKickoffError,
    BulkExportTimeoutError,
    DEFAULT_TYPES,
    download_manifest_files,
    kickoff_group_export,
    kickoff_patient_export,
    poll_export,
)


# ---------------------------------------------------------------------------
# Minimal stub adapter (mirrors OpenEMRFhirAdapter interface)
# ---------------------------------------------------------------------------


class _StubAdapter:
    base_url = "https://fhir.example.com/fhir"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-token"}


ADAPTER = _StubAdapter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, headers: dict | None = None, json_body=None, content: bytes | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if json_body is not None:
        resp.json.return_value = json_body
    if content is not None:
        resp.content = content
    else:
        resp.content = b""
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# kickoff_group_export
# ---------------------------------------------------------------------------


class TestKickoffGroupExport:
    def test_returns_content_location_on_202(self):
        polling_url = "https://fhir.example.com/fhir/__bulk_status/abc123"
        mock_resp = _mock_response(
            202,
            headers={"Content-Location": polling_url},
        )
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = kickoff_group_export(ADAPTER, group_id="G1")

        assert result == polling_url
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "/Group/G1/$export" in call_kwargs.args[0]

    def test_raises_on_non_202(self):
        mock_resp = _mock_response(403)
        mock_resp.text = "Forbidden"
        with patch("httpx.post", return_value=mock_resp):
            with pytest.raises(BulkExportKickoffError, match="403"):
                kickoff_group_export(ADAPTER, group_id="G1")

    def test_raises_when_no_content_location(self):
        mock_resp = _mock_response(202, headers={})
        with patch("httpx.post", return_value=mock_resp):
            with pytest.raises(BulkExportKickoffError, match="Content-Location"):
                kickoff_group_export(ADAPTER)

    def test_since_param_is_url_encoded(self):
        """The _since param must appear in the request params as-is."""
        since_value = "2025-01-01T00:00:00+00:00"
        polling_url = "https://fhir.example.com/fhir/__bulk_status/xyz"
        mock_resp = _mock_response(
            202, headers={"Content-Location": polling_url}
        )
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            kickoff_group_export(ADAPTER, since=since_value)

        call_kwargs = mock_post.call_args
        params = call_kwargs.kwargs.get("params") or {}
        assert params.get("_since") == since_value

    def test_default_group_id_fallback(self):
        """When group_id is None the URL should use 'all'."""
        polling_url = "https://fhir.example.com/fhir/__bulk_status/def"
        mock_resp = _mock_response(202, headers={"Content-Location": polling_url})
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            kickoff_group_export(ADAPTER)

        url_called = mock_post.call_args.args[0]
        assert "/Group/all/$export" in url_called

    def test_types_encoded_in_params(self):
        polling_url = "https://fhir.example.com/fhir/__bulk_status/t1"
        mock_resp = _mock_response(202, headers={"Content-Location": polling_url})
        custom_types = ("Patient", "Condition")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            kickoff_group_export(ADAPTER, types=custom_types)

        params = mock_post.call_args.kwargs.get("params") or {}
        assert "Patient" in params["_type"]
        assert "Condition" in params["_type"]


# ---------------------------------------------------------------------------
# kickoff_patient_export
# ---------------------------------------------------------------------------


class TestKickoffPatientExport:
    def test_returns_polling_url(self):
        polling_url = "https://fhir.example.com/fhir/__bulk_status/patient1"
        mock_resp = _mock_response(
            202, headers={"Content-Location": polling_url}
        )
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = kickoff_patient_export(ADAPTER, patient_id="P42")

        assert result == polling_url
        url_called = mock_post.call_args.args[0]
        assert "/Patient/P42/$export" in url_called

    def test_since_param_forwarded(self):
        since = "2024-06-01T00:00:00Z"
        polling_url = "https://fhir.example.com/fhir/__bulk_status/patient2"
        mock_resp = _mock_response(202, headers={"Content-Location": polling_url})
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            kickoff_patient_export(ADAPTER, patient_id="P1", since=since)

        params = mock_post.call_args.kwargs.get("params") or {}
        assert params.get("_since") == since


# ---------------------------------------------------------------------------
# poll_export
# ---------------------------------------------------------------------------


class TestPollExport:
    POLLING_URL = "https://fhir.example.com/fhir/__bulk_status/abc"
    MANIFEST = {
        "transactionTime": "2025-01-02T00:00:00Z",
        "request": POLLING_URL,
        "requiresAccessToken": True,
        "output": [
            {"type": "Patient", "url": "https://fhir.example.com/bulk/patients.ndjson"},
        ],
    }

    def test_polls_202_then_200_returns_manifest(self):
        """First call returns 202 (in-progress); second call returns 200 with manifest."""
        in_progress = _mock_response(202, headers={"Retry-After": "0"})
        complete = _mock_response(200, json_body=self.MANIFEST)

        with patch("httpx.get", side_effect=[in_progress, complete]):
            with patch("time.sleep"):  # don't actually sleep in tests
                result = poll_export(ADAPTER, self.POLLING_URL, max_wait_seconds=60)

        assert result == self.MANIFEST

    def test_raises_timeout_error(self):
        """If the export never completes within max_wait_seconds, raise BulkExportTimeoutError."""
        in_progress = _mock_response(202, headers={"Retry-After": "0"})

        # poll_export calls time.monotonic() multiple times:
        #   1. deadline = time.monotonic() + max_wait_seconds  (start)
        #   2. remaining = deadline - time.monotonic()          (first loop check)
        #   3. sleep_for = min(..., remaining - 0.1)            (sleep calc — same call)
        #   4. time.monotonic() - elapsed_start                 (elapsed in error msg)
        # Supply enough values so the second check shows budget is exhausted.
        monotonic_values = [0.0, 700.0, 700.0, 700.0, 700.0]
        with patch("httpx.get", return_value=in_progress):
            with patch("time.sleep"):
                with patch("time.monotonic", side_effect=monotonic_values):
                    with pytest.raises(BulkExportTimeoutError):
                        poll_export(ADAPTER, self.POLLING_URL, max_wait_seconds=600)

    def test_honors_retry_after_header(self):
        """Retry-After header value should be used as the sleep duration."""
        in_progress = _mock_response(202, headers={"Retry-After": "5"})
        complete = _mock_response(200, json_body=self.MANIFEST)

        sleep_calls: list[float] = []

        def _fake_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with patch("httpx.get", side_effect=[in_progress, complete]):
            with patch("time.sleep", side_effect=_fake_sleep):
                poll_export(ADAPTER, self.POLLING_URL, max_wait_seconds=60)

        # First sleep should use Retry-After=5 (capped by min(5, 30, remaining))
        assert sleep_calls[0] == pytest.approx(5.0, abs=1.0)

    def test_raises_on_error_status(self):
        """Non-202/200 status during polling should raise BulkExportKickoffError."""
        error_resp = _mock_response(500)
        error_resp.text = "Internal Server Error"

        with patch("httpx.get", return_value=error_resp):
            with pytest.raises(BulkExportKickoffError, match="500"):
                poll_export(ADAPTER, self.POLLING_URL, max_wait_seconds=60)


# ---------------------------------------------------------------------------
# download_manifest_files
# ---------------------------------------------------------------------------


class TestDownloadManifestFiles:
    def _make_ndjson(self, resources: list[dict]) -> bytes:
        return b"\n".join(json.dumps(r).encode() for r in resources)

    def test_yields_all_resources(self):
        """Three NDJSON lines should produce three (type, dict) tuples."""
        resources = [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Patient", "id": "p2"},
            {"resourceType": "Patient", "id": "p3"},
        ]
        ndjson_bytes = self._make_ndjson(resources)
        manifest = {
            "output": [
                {"type": "Patient", "url": "https://fhir.example.com/bulk/p.ndjson"}
            ]
        }
        mock_resp = _mock_response(200, content=ndjson_bytes)

        with patch("httpx.get", return_value=mock_resp):
            results = list(download_manifest_files(ADAPTER, manifest))

        assert len(results) == 3
        for i, (rtype, rdict) in enumerate(results):
            assert rtype == "Patient"
            assert rdict["id"] == f"p{i + 1}"

    def test_gzip_decompression(self):
        """Gzip-compressed NDJSON should be transparently decompressed."""
        import gzip

        resources = [{"resourceType": "Condition", "id": "c1"}]
        ndjson_bytes = self._make_ndjson(resources)
        compressed = gzip.compress(ndjson_bytes)

        manifest = {
            "output": [
                {
                    "type": "Condition",
                    "url": "https://fhir.example.com/bulk/c.ndjson.gz",
                }
            ]
        }
        mock_resp = _mock_response(200, content=compressed)

        with patch("httpx.get", return_value=mock_resp):
            results = list(download_manifest_files(ADAPTER, manifest))

        assert len(results) == 1
        rtype, rdict = results[0]
        assert rtype == "Condition"
        assert rdict["id"] == "c1"

    def test_skips_malformed_lines(self):
        """A malformed JSON line should be skipped; valid lines still yielded."""
        bad_ndjson = b'{"resourceType":"Patient","id":"p1"}\nnot-json\n{"resourceType":"Patient","id":"p2"}\n'
        manifest = {
            "output": [
                {"type": "Patient", "url": "https://fhir.example.com/bulk/mixed.ndjson"}
            ]
        }
        mock_resp = _mock_response(200, content=bad_ndjson)

        with patch("httpx.get", return_value=mock_resp):
            results = list(download_manifest_files(ADAPTER, manifest))

        assert len(results) == 2

    def test_multiple_output_files(self):
        """Manifest with two output entries should yield rows from both."""
        patient_ndjson = self._make_ndjson([{"resourceType": "Patient", "id": "p1"}])
        condition_ndjson = self._make_ndjson([{"resourceType": "Condition", "id": "c1"}])

        manifest = {
            "output": [
                {"type": "Patient", "url": "https://fhir.example.com/bulk/p.ndjson"},
                {"type": "Condition", "url": "https://fhir.example.com/bulk/c.ndjson"},
            ]
        }

        responses = [
            _mock_response(200, content=patient_ndjson),
            _mock_response(200, content=condition_ndjson),
        ]

        with patch("httpx.get", side_effect=responses):
            results = list(download_manifest_files(ADAPTER, manifest))

        assert len(results) == 2
        types = {r[0] for r in results}
        assert types == {"Patient", "Condition"}

    def test_empty_manifest_yields_nothing(self):
        manifest = {"output": []}
        results = list(download_manifest_files(ADAPTER, manifest))
        assert results == []

    def test_missing_output_key_yields_nothing(self):
        manifest = {}
        results = list(download_manifest_files(ADAPTER, manifest))
        assert results == []
