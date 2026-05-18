"""
Unit tests for the Inovalon EROND adapter.

All external HTTP calls and DB writes are mocked — no live network or DB
connection required.

Coverage:
  - OAuth2 token fetch + in-process caching
  - Token expiry → automatic re-fetch
  - pull_patient_record / get_pull_status / download_bundle happy path
  - ingest_patient_from_inovalon:
      * 2 Conditions (ICD→HCC cross-walk) → 2 suspects persisted
      * 1 DocumentReference → Gemini vision routed
      * 3 Observations (LOINC) → 3 observations stored
  - Idempotency: duplicate pull_id skipped
  - Credentials check with no env vars → {configured: false}
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build FHIR resources as NDJSON lines
# ---------------------------------------------------------------------------

def _condition(icd10: str) -> dict:
    return {
        "resourceType": "Condition",
        "id": f"cond-{icd10}",
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": icd10,
                }
            ]
        },
    }


def _document_ref(url: str) -> dict:
    return {
        "resourceType": "DocumentReference",
        "id": "docref-1",
        "content": [
            {
                "attachment": {
                    "url": url,
                    "contentType": "application/pdf",
                }
            }
        ],
    }


def _observation(loinc: str, value: float, units: str, obs_at: str) -> dict:
    return {
        "resourceType": "Observation",
        "id": f"obs-{loinc}",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": loinc,
                }
            ]
        },
        "valueQuantity": {"value": value, "unit": units},
        "effectiveDateTime": obs_at,
    }


def _make_bundle_bytes(*resources) -> bytes:
    return b"\n".join(json.dumps(r).encode() for r in resources)


# ---------------------------------------------------------------------------
# InovalonClient unit tests
# ---------------------------------------------------------------------------

class TestInovalonClientToken:
    """Test OAuth2 token acquisition and caching."""

    def _make_client(self):
        from app.services.partners.inovalon import InovalonClient
        return InovalonClient(
            api_base="https://api.inovalon.test",
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_url="https://api.inovalon.test/oauth2/token",
        )

    def _mock_token_response(self, access_token="tok123", expires_in=3600):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": access_token,
            "expires_in": expires_in,
            "token_type": "Bearer",
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_token_fetched_on_first_call(self):
        client = self._make_client()
        mock_resp = self._mock_token_response()
        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http_client):
            token = client._token()

        assert token == "tok123"
        assert mock_http_client.post.call_count == 1

    def test_token_cached_on_second_call(self):
        client = self._make_client()
        mock_resp = self._mock_token_response()
        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http_client):
            client._token()
            client._token()  # second call — should use cache

        assert mock_http_client.post.call_count == 1  # only one real HTTP call

    def test_expired_token_triggers_refetch(self):
        client = self._make_client()
        # Seed the cache with an already-expired token (expires_at in the past)
        client._token_cache = {
            "access_token": "old-token",
            "expires_at": time.time() - 10,  # already expired
        }
        mock_resp = self._mock_token_response(access_token="new-token")
        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http_client):
            token = client._token()

        assert token == "new-token"
        assert mock_http_client.post.call_count == 1

    def test_token_within_buffer_triggers_refetch(self):
        """Token expiring within 60 s should be refreshed proactively."""
        from app.services.partners.inovalon import _TOKEN_REFRESH_BUFFER_S

        client = self._make_client()
        client._token_cache = {
            "access_token": "nearly-expired",
            # expires_at is exactly at the refresh-buffer boundary
            "expires_at": time.time() + _TOKEN_REFRESH_BUFFER_S - 5,
        }
        mock_resp = self._mock_token_response(access_token="fresh-token")
        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http_client):
            token = client._token()

        assert token == "fresh-token"


class TestInovalonClientAPIs:
    """Test pull_patient_record, get_pull_status, download_bundle."""

    def _make_client_with_cached_token(self):
        from app.services.partners.inovalon import InovalonClient
        client = InovalonClient(
            api_base="https://api.inovalon.test",
            client_id="cid",
            client_secret="csec",
        )
        client._token_cache = {
            "access_token": "cached-tok",
            "expires_at": time.time() + 3600,
        }
        return client

    def test_pull_patient_record(self):
        client = self._make_client_with_cached_token()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "pull_id": "pull-abc-123",
            "status": "submitted",
            "submitted_at": "2026-05-18T12:00:00Z",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http):
            result = client.pull_patient_record(
                {"first_name": "Jane", "last_name": "Doe", "dob": "1960-01-15"}
            )

        assert result["pull_id"] == "pull-abc-123"
        assert result["status"] == "submitted"

    def test_get_pull_status(self):
        client = self._make_client_with_cached_token()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "completed",
            "resources_returned": {"Condition": 2, "Observation": 3},
            "bundle_size_bytes": 4096,
            "completed_at": "2026-05-18T12:05:00Z",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http):
            result = client.get_pull_status("pull-abc-123")

        assert result["status"] == "completed"
        assert result["resources_returned"]["Condition"] == 2

    def test_download_bundle(self):
        client = self._make_client_with_cached_token()
        mock_resp = MagicMock()
        mock_resp.content = b'{"resourceType":"Condition"}\n'
        mock_resp.raise_for_status = MagicMock()
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_http):
            data = client.download_bundle("pull-abc-123")

        assert b"Condition" in data


# ---------------------------------------------------------------------------
# Credentials check
# ---------------------------------------------------------------------------

class TestCredentialsCheck:
    def test_no_env_returns_not_configured(self, monkeypatch):
        monkeypatch.delenv("INOVALON_API_BASE", raising=False)
        monkeypatch.delenv("INOVALON_CLIENT_ID", raising=False)
        monkeypatch.delenv("INOVALON_CLIENT_SECRET", raising=False)

        from app.services.partners.inovalon import InovalonClient
        client = InovalonClient()
        assert client.is_configured is False

    def test_all_env_set_returns_configured(self, monkeypatch):
        monkeypatch.setenv("INOVALON_API_BASE", "https://api.inovalon.test")
        monkeypatch.setenv("INOVALON_CLIENT_ID", "cid")
        monkeypatch.setenv("INOVALON_CLIENT_SECRET", "csec")

        from app.services.partners.inovalon import InovalonClient
        client = InovalonClient()
        assert client.is_configured is True


# ---------------------------------------------------------------------------
# ingest_patient_from_inovalon integration tests (all DB + HTTP mocked)
# ---------------------------------------------------------------------------

SAMPLE_BUNDLE = _make_bundle_bytes(
    _condition("E1165"),        # Type 2 DM w/ hyperglycemia → HCC 18/19 range
    _condition("I5020"),        # Systolic heart failure → HCC 85
    _document_ref("https://api.inovalon.test/binary/doc-1"),
    _observation("2160-0", 1.1, "mg/dL", "2026-01-10T09:00:00"),   # Creatinine
    _observation("718-7", 12.5, "g/dL", "2026-01-10T09:00:00"),    # Hemoglobin
    _observation("2345-7", 95.0, "mg/dL", "2026-01-10T09:00:00"),  # Glucose
)


class TestIngestPatientFromInovalon:
    """Full pipeline: 2 conditions, 1 doc, 3 observations."""

    def _patch_all(self, tmp_pull_id="pull-xyz-999", pull_status="completed"):
        """Return a context-manager stack that patches all external calls."""
        # We'll set up patches one by one and apply them in the test.
        return tmp_pull_id, pull_status

    def test_full_pipeline_creates_suspects_docs_and_observations(self):
        from app.services.partners.inovalon_ingest import ingest_patient_from_inovalon

        demographics = {
            "id": 42,
            "first_name": "Jane",
            "last_name": "Doe",
            "date_of_birth": "1960-01-15",
            "gender": "F",
            "member_id": "MEM001",
        }

        # --- mock _get_patient_demographics ---
        with patch(
            "app.services.partners.inovalon_ingest._get_patient_demographics",
            return_value=demographics,
        ):
            # --- mock InovalonClient ---
            mock_client = MagicMock()
            mock_client.is_configured = True
            mock_client.pull_patient_record.return_value = {
                "pull_id": "pull-xyz-999",
                "status": "submitted",
                "submitted_at": "2026-05-18T12:00:00Z",
            }
            mock_client.get_pull_status.return_value = {
                "status": "completed",
                "resources_returned": {"Condition": 2, "Observation": 3, "DocumentReference": 1},
                "bundle_size_bytes": len(SAMPLE_BUNDLE),
                "completed_at": "2026-05-18T12:05:00Z",
            }
            mock_client.download_bundle.return_value = SAMPLE_BUNDLE
            mock_client.fetch_binary.return_value = (b"%PDF-1.4 mock", "application/pdf")

            with patch(
                "app.services.partners.inovalon_ingest.InovalonClient",
                return_value=mock_client,
            ):
                # --- mock DB operations ---
                suspects_inserted: list[tuple] = []
                observations_inserted: list[tuple] = []

                def fake_raf_cursor():
                    """Context manager that records inserts via lastrowid."""
                    from contextlib import contextmanager

                    @contextmanager
                    def _ctx():
                        cur = MagicMock()
                        cur.lastrowid = 1
                        cur.fetchone.return_value = None  # no existing pull_id

                        original_execute = cur.execute

                        def track_execute(sql, params=None):
                            sql_upper = sql.strip().upper()
                            if "INSERT INTO RAF_SUSPECT_CONDITIONS" in sql_upper:
                                suspects_inserted.append(params)
                                cur.lastrowid += 1
                            elif "INSERT INTO RAF_EXTERNAL_OBSERVATIONS" in sql_upper:
                                observations_inserted.append(params)
                            elif "LAST_INSERT_ID" in sql_upper:
                                cur.fetchone.return_value = {"lid": cur.lastrowid}
                            return original_execute(sql, params)

                        cur.execute = track_execute
                        yield cur

                    return _ctx()

                with patch(
                    "app.services.partners.inovalon_ingest.raf_cursor",
                    side_effect=fake_raf_cursor,
                ):
                    # Also need to mock lookup_hcc to return valid HCC mappings
                    with patch(
                        "app.services.partners.inovalon_ingest.lookup_hcc",
                        side_effect=lambda icd: {
                            "maps_to_hcc": True,
                            "hcc_codes": ["19"],
                            "hcc_details": [{"label": "Diabetes"}],
                        },
                    ):
                        # Mock gemini extract — patch at the source module since
                        # inovalon_ingest imports it lazily inside the function.
                        with patch(
                            "app.services.gemini_document_extractor.extract_from_document",
                            return_value={"suspects": [{"hcc_code": "19", "icd10_code": "E1165", "confidence": 0.9, "evidence_sentence": "dx diabetes"}]},
                        ):
                            result = ingest_patient_from_inovalon(
                                tenant_id="tenant-test",
                                raf_patient_id=42,
                            )

        assert result["status"] == "completed"
        assert result["pull_id"] == "pull-xyz-999"
        assert result["suspects_created"] == 2, (
            f"Expected 2 suspects, got {result['suspects_created']}"
        )
        assert result["docs_routed"] == 1, (
            f"Expected 1 doc routed, got {result['docs_routed']}"
        )
        assert result["observations_stored"] == 3, (
            f"Expected 3 observations, got {result['observations_stored']}"
        )

    def test_idempotent_skips_duplicate_pull_id(self):
        """If inovalon_pull_id already in DB the ingestion must be skipped."""
        from app.services.partners.inovalon_ingest import ingest_patient_from_inovalon

        demographics = {
            "id": 7,
            "first_name": "Bob",
            "last_name": "Smith",
            "date_of_birth": "1955-05-05",
            "gender": "M",
            "member_id": "MEM007",
        }

        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.pull_patient_record.return_value = {
            "pull_id": "pull-already-exists",
            "status": "submitted",
            "submitted_at": "2026-05-18T10:00:00Z",
        }

        with patch(
            "app.services.partners.inovalon_ingest._get_patient_demographics",
            return_value=demographics,
        ):
            with patch(
                "app.services.partners.inovalon_ingest.InovalonClient",
                return_value=mock_client,
            ):
                from contextlib import contextmanager

                def fake_cursor_with_existing_pull():
                    @contextmanager
                    def _ctx():
                        cur = MagicMock()
                        cur.lastrowid = 99
                        # Simulate existing pull_id row returned by SELECT
                        cur.fetchone.return_value = {"id": 99}
                        yield cur

                    return _ctx()

                with patch(
                    "app.services.partners.inovalon_ingest.raf_cursor",
                    side_effect=fake_cursor_with_existing_pull,
                ):
                    result = ingest_patient_from_inovalon(
                        tenant_id="tenant-test",
                        raf_patient_id=7,
                    )

        assert result["status"] == "skipped"
        # Should not have called download_bundle since we skipped early
        mock_client.download_bundle.assert_not_called()

    def test_unconfigured_client_returns_error(self, monkeypatch):
        monkeypatch.delenv("INOVALON_API_BASE", raising=False)
        monkeypatch.delenv("INOVALON_CLIENT_ID", raising=False)
        monkeypatch.delenv("INOVALON_CLIENT_SECRET", raising=False)

        from app.services.partners.inovalon_ingest import ingest_patient_from_inovalon

        result = ingest_patient_from_inovalon(
            tenant_id="tenant-test",
            raf_patient_id=1,
        )
        assert result["status"] == "error"
        assert "not configured" in result.get("error", "").lower()

    def test_missing_patient_returns_error(self):
        from app.services.partners.inovalon_ingest import ingest_patient_from_inovalon

        mock_client = MagicMock()
        mock_client.is_configured = True

        with patch(
            "app.services.partners.inovalon_ingest.InovalonClient",
            return_value=mock_client,
        ):
            with patch(
                "app.services.partners.inovalon_ingest._get_patient_demographics",
                return_value=None,
            ):
                result = ingest_patient_from_inovalon(
                    tenant_id="tenant-test",
                    raf_patient_id=9999,
                )

        assert result["status"] == "error"
        assert "not found" in result.get("error", "").lower()
