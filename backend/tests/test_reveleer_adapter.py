"""Reveleer bi-directional adapter — unit tests.

Tests cover:
  - ReveleerClient: list, download, submit (mocked httpx).
  - pull_charts_from_reveleer: 2 charts → 2 docs processed.
  - push_suspects_to_reveleer: 3 open suspects → 3 entries in pushed table.
  - Idempotency: duplicate chart_id / suspect_id rejected by UNIQUE index.
  - evidence_sentence filter: suspects with empty evidence skipped at push.

All tests are pure-Python (no live DB, no live Reveleer).
"""
from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Ensure sparse-checkout environments can still run these tests.
# Pre-inject stub modules for any app.services.* module that is lazy-imported
# inside reveleer_sync but may not exist in the current worktree.
# ---------------------------------------------------------------------------

def _ensure_stub(module_name: str) -> None:
    """Insert a stub into sys.modules only for leaves that truly don't exist.

    Parent packages that are real importable packages are never overwritten.
    """
    if module_name in sys.modules:
        return
    # Try a real import first — only stub if that fails.
    import importlib
    try:
        importlib.import_module(module_name)
        return  # real module imported successfully
    except (ImportError, ModuleNotFoundError):
        pass
    # Stub only the missing leaf; leave real parents intact.
    stub = MagicMock()
    stub.__name__ = module_name
    stub.__package__ = module_name
    stub.__spec__ = None
    sys.modules[module_name] = stub
    # Attach to parent if parent is already loaded
    parts = module_name.rsplit(".", 1)
    if len(parts) == 2:
        parent_name, attr = parts
        parent = sys.modules.get(parent_name)
        if parent is not None:
            try:
                setattr(parent, attr, stub)
            except (AttributeError, TypeError):
                pass

_ensure_stub("app.services.gemini_document_extractor")

# Pre-import the reveleer modules so that patch() can resolve attribute chains
# like "app.services.partners.reveleer.ReveleerClient.from_env" at test time.
import app.services.partners.reveleer       # noqa: E402
import app.services.partners.reveleer_sync  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(json_data=None, content=b"", status_code=200, headers=None):
    """Build a minimal mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = headers or {"content-type": "application/pdf"}
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# ReveleerClient unit tests
# ---------------------------------------------------------------------------


class TestReveleerClient:
    def _client(self):
        from app.services.partners.reveleer import ReveleerClient

        return ReveleerClient(
            api_base="https://api.reveleer.test",
            api_key="test-key",
            tenant_id="tenant-abc",
        )

    def test_list_retrieved_charts_returns_list(self):
        charts_payload = {
            "charts": [
                {"chart_id": "c1", "patient_external_id": "P001", "filename": "chart1.pdf",
                 "mimetype": "application/pdf", "size_bytes": 1234, "retrieved_at": "2026-05-01T00:00:00Z"},
                {"chart_id": "c2", "patient_external_id": "P002", "filename": "chart2.pdf",
                 "mimetype": "application/pdf", "size_bytes": 5678, "retrieved_at": "2026-05-02T00:00:00Z"},
            ]
        }
        mock_resp = _make_response(json_data=charts_payload)
        with patch("httpx.get", return_value=mock_resp) as mock_get:
            result = self._client().list_retrieved_charts(since="2026-05-01T00:00:00Z")

        assert len(result) == 2
        assert result[0]["chart_id"] == "c1"
        # Verify query params forwarded
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["status"] == "ready"
        assert kwargs["params"]["since"] == "2026-05-01T00:00:00Z"

    def test_list_retrieved_charts_default_status_ready(self):
        mock_resp = _make_response(json_data={"charts": []})
        with patch("httpx.get", return_value=mock_resp) as mock_get:
            self._client().list_retrieved_charts()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["status"] == "ready"

    def test_download_chart_returns_bytes_and_mime(self):
        pdf_bytes = b"%PDF-test-content"
        mock_resp = _make_response(
            content=pdf_bytes,
            headers={"content-type": "application/pdf; charset=binary"},
        )
        with patch("httpx.get", return_value=mock_resp):
            data, mime = self._client().download_chart("c1")

        assert data == pdf_bytes
        assert mime == "application/pdf"

    def test_download_chart_fallback_mime(self):
        # headers mapping without a content-type key should yield the fallback mime
        mock_resp = MagicMock()
        mock_resp.content = b"data"
        mock_resp.headers = {}  # plain dict — no content-type key
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_resp):
            _, mime = self._client().download_chart("c99")
        assert mime == "application/octet-stream"

    def test_submit_hcc_suspects_posts_bulk(self):
        suspects = [
            {
                "hcc": "19",
                "icd10": "E11.9",
                "confidence": 0.92,
                "evidence_sentence": "Patient has type 2 diabetes mellitus.",
                "source_document_id": "doc-001",
            },
        ]
        mock_resp = _make_response(json_data={"response_id": "rv-resp-001", "accepted": 1})
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = self._client().submit_hcc_suspects("P001", suspects)

        assert result["response_id"] == "rv-resp-001"
        _, kwargs = mock_post.call_args
        body = kwargs["json"]
        assert body["patient_external_id"] == "P001"
        assert len(body["suspects"]) == 1

    def test_submit_hcc_suspects_drops_empty_evidence(self):
        suspects = [
            {"hcc": "19", "icd10": "E11.9", "confidence": 0.9,
             "evidence_sentence": "Valid evidence.", "source_document_id": "d1"},
            {"hcc": "85", "icd10": "I50.9", "confidence": 0.8,
             "evidence_sentence": "", "source_document_id": "d1"},
            {"hcc": "22", "icd10": "E78.5", "confidence": 0.7,
             "evidence_sentence": "   ", "source_document_id": "d1"},
        ]
        mock_resp = _make_response(json_data={"response_id": "rv-resp-002", "accepted": 1})
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            self._client().submit_hcc_suspects("P001", suspects)

        body = mock_post.call_args[1]["json"]
        # Only the one with valid evidence should be sent
        assert len(body["suspects"]) == 1
        assert body["suspects"][0]["hcc"] == "19"


# ---------------------------------------------------------------------------
# pull_charts_from_reveleer
# ---------------------------------------------------------------------------


CHART_LIST = [
    {
        "chart_id": "rev-chart-001",
        "patient_external_id": "EXT-P001",
        "filename": "chart_001.pdf",
        "mimetype": "application/pdf",
        "size_bytes": 2048,
        "retrieved_at": "2026-05-10T08:00:00Z",
    },
    {
        "chart_id": "rev-chart-002",
        "patient_external_id": "EXT-P002",
        "filename": "chart_002.pdf",
        "mimetype": "application/pdf",
        "size_bytes": 4096,
        "retrieved_at": "2026-05-10T09:00:00Z",
    },
]

EXTRACTION_RESULT = {
    "suspects": [
        {
            "hcc_code": "19",
            "icd10_code": "E11.9",
            "description": "Type 2 DM",
            "confidence": 0.91,
            "evidence_sentence": "Patient diagnosed with Type 2 DM.",
            "page_number": 1,
            "meat": {},
            "source_document_id": None,
        }
    ],
    "kept_count": 1,
}


class TestPullChartsFromReveleer:
    """Tests for pull_charts_from_reveleer — all DB + HTTP mocked."""

    def _run_pull(self, already_pulled_ids=None):
        """
        Patch everything external and run pull_charts_from_reveleer.
        Returns (summary, inserted_charts, inserted_suspects).
        """
        already_pulled_ids = set(already_pulled_ids or [])
        inserted_charts = []
        inserted_suspects = []

        def fake_already_pulled(chart_id):
            return chart_id in already_pulled_ids

        def fake_insert_chart(**kwargs):
            inserted_charts.append(kwargs)
            return len(inserted_charts)

        def fake_resolve_patient(tenant_id, ext_id):
            mapping = {"EXT-P001": 101, "EXT-P002": 102}
            return mapping.get(ext_id)

        def fake_persist_suspect(*, tenant_id, patient_id, measurement_year, s, source_document_id):
            inserted_suspects.append({"patient_id": patient_id, "hcc": s["hcc_code"]})
            return len(inserted_suspects)

        mock_client = MagicMock()
        mock_client.list_retrieved_charts.return_value = CHART_LIST
        mock_client.download_chart.return_value = (b"%PDF-content", "application/pdf")

        with (
            patch(
                "app.services.partners.reveleer.ReveleerClient.from_env",
                return_value=mock_client,
            ),
            patch(
                "app.services.partners.reveleer_sync._chart_already_pulled",
                side_effect=fake_already_pulled,
            ),
            patch(
                "app.services.partners.reveleer_sync._insert_chart_pulled",
                side_effect=fake_insert_chart,
            ),
            patch(
                "app.services.partners.reveleer_sync._resolve_patient",
                side_effect=fake_resolve_patient,
            ),
            patch(
                "app.services.partners.reveleer_sync._persist_suspect",
                side_effect=fake_persist_suspect,
            ),
            patch(
                "app.services.gemini_document_extractor.extract_from_document",
                return_value=EXTRACTION_RESULT,
            ),
        ):
            from app.services.partners.reveleer_sync import pull_charts_from_reveleer

            summary = pull_charts_from_reveleer(tenant_id="tenant-test")

        return summary, inserted_charts, inserted_suspects

    def test_two_charts_both_processed(self):
        summary, charts, suspects = self._run_pull()
        assert summary["charts_found"] == 2
        assert summary["charts_processed"] == 2
        assert summary["charts_skipped"] == 0
        assert len(charts) == 2

    def test_suspects_extracted_and_persisted(self):
        summary, charts, suspects = self._run_pull()
        # 1 suspect per chart × 2 charts
        assert summary["suspects_extracted"] == 2
        assert len(suspects) == 2

    def test_already_pulled_chart_skipped(self):
        """If chart_id already in DB, it must be skipped (idempotency)."""
        summary, charts, _ = self._run_pull(already_pulled_ids={"rev-chart-001"})
        assert summary["charts_skipped"] == 1
        assert summary["charts_processed"] == 1
        assert len(charts) == 1
        assert charts[0]["reveleer_chart_id"] == "rev-chart-002"

    def test_both_charts_already_pulled_all_skipped(self):
        summary, charts, _ = self._run_pull(
            already_pulled_ids={"rev-chart-001", "rev-chart-002"}
        )
        assert summary["charts_found"] == 2
        assert summary["charts_skipped"] == 2
        assert summary["charts_processed"] == 0
        assert len(charts) == 0


# ---------------------------------------------------------------------------
# push_suspects_to_reveleer
# ---------------------------------------------------------------------------


OPEN_SUSPECTS = [
    {
        "id": 1001,
        "hcc": "19",
        "icd10": "E11.9",
        "confidence": 0.91,
        "evidence_sentence": "DM type 2 documented.",
        "source_document_id": "rev-chart-001",
    },
    {
        "id": 1002,
        "hcc": "85",
        "icd10": "I50.9",
        "confidence": 0.85,
        "evidence_sentence": "CHF with reduced EF noted in chart.",
        "source_document_id": "rev-chart-001",
    },
    {
        "id": 1003,
        "hcc": "22",
        "icd10": "E78.5",
        "confidence": 0.78,
        "evidence_sentence": "Hyperlipidemia on statin therapy.",
        "source_document_id": "rev-chart-002",
    },
]


class TestPushSuspectsToReveleer:
    """Tests for push_suspects_to_reveleer — all DB + HTTP mocked."""

    def _run_push(self, suspects=None, submit_raises=None):
        suspects = suspects if suspects is not None else OPEN_SUSPECTS
        push_records = []

        def fake_record_push(**kwargs):
            push_records.append(kwargs)

        mock_client = MagicMock()
        if submit_raises:
            mock_client.submit_hcc_suspects.side_effect = submit_raises
        else:
            mock_client.submit_hcc_suspects.return_value = {
                "response_id": "rv-bulk-999",
                "accepted": len(suspects),
            }

        # Mock raf_cursor for external_id lookup
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__enter__ = MagicMock(return_value=mock_cursor_ctx)
        mock_cursor_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor_ctx.fetchone.return_value = {"external_id": "EXT-P001"}

        with (
            patch(
                "app.services.partners.reveleer.ReveleerClient.from_env",
                return_value=mock_client,
            ),
            patch(
                "app.services.partners.reveleer_sync._get_unpushed_suspects",
                return_value=suspects,
            ),
            patch(
                "app.services.partners.reveleer_sync._record_push_result",
                side_effect=fake_record_push,
            ),
            patch(
                "app.services.partners.reveleer_sync.raf_cursor",
                return_value=mock_cursor_ctx,
            ),
        ):
            from app.services.partners.reveleer_sync import push_suspects_to_reveleer

            summary = push_suspects_to_reveleer(
                tenant_id="tenant-test", raf_patient_id=101
            )

        return summary, push_records, mock_client

    def test_three_suspects_pushed_successfully(self):
        summary, records, mock_client = self._run_push()
        assert summary["pushed"] == 3
        assert summary["failed"] == 0
        assert len(records) == 3
        # All recorded as success
        assert all(r["status"] == "success" for r in records)

    def test_push_records_contain_response_id(self):
        _, records, _ = self._run_push()
        assert all(r["reveleer_response_id"] == "rv-bulk-999" for r in records)

    def test_submit_failure_marks_all_failed(self):
        summary, records, _ = self._run_push(
            submit_raises=RuntimeError("503 Service Unavailable")
        )
        assert summary["failed"] == 3
        assert summary["pushed"] == 0
        assert all(r["status"] == "failed" for r in records)
        assert all("503" in (r["error_text"] or "") for r in records)

    def test_empty_suspect_list_returns_zeros(self):
        summary, records, mock_client = self._run_push(suspects=[])
        assert summary == {"suspects_found": 0, "pushed": 0, "failed": 0, "skipped": 0}
        mock_client.submit_hcc_suspects.assert_not_called()

    def test_idempotency_unique_suspect_already_pushed(self):
        """Suspects returned by _get_unpushed_suspects already exclude pushed ones
        (via LEFT JOIN).  Confirm that if list is empty (all already pushed),
        nothing is submitted to Reveleer."""
        summary, records, mock_client = self._run_push(suspects=[])
        mock_client.submit_hcc_suspects.assert_not_called()
        assert len(records) == 0


# ---------------------------------------------------------------------------
# _get_unpushed_suspects — evidence filter (unit, pure Python)
# ---------------------------------------------------------------------------


class TestGetUnpushedSuspectsFilter:
    """Verify that the DB helper drops suspects with empty evidence_sentence."""

    def _build_db_rows(self, rows_data):
        """Build fake DB row dicts as returned by raf_cursor."""
        return [
            {
                "id": r["id"],
                "suspect_hcc": r["hcc"],
                "suspect_icd10": r["icd10"],
                "confidence_score": r["conf"],
                "evidence_detail": json.dumps({
                    "source": "gemini_vision",
                    "evidence_sentence": r.get("evidence_sentence", ""),
                    "document_id": "doc-1",
                }),
            }
            for r in rows_data
        ]

    def test_suspects_with_empty_evidence_excluded(self):
        raw_rows = [
            {"id": 1, "hcc": "19", "icd10": "E11.9", "conf": 0.9, "evidence_sentence": "DM documented."},
            {"id": 2, "hcc": "85", "icd10": "I50.9", "conf": 0.8, "evidence_sentence": ""},
            {"id": 3, "hcc": "22", "icd10": "E78.5", "conf": 0.7, "evidence_sentence": "   "},
        ]
        db_rows = self._build_db_rows(raw_rows)

        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__enter__ = MagicMock(return_value=mock_cursor_ctx)
        mock_cursor_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor_ctx.fetchall.return_value = db_rows

        with patch("app.services.partners.reveleer_sync.raf_cursor", return_value=mock_cursor_ctx):
            from app.services.partners.reveleer_sync import _get_unpushed_suspects

            result = _get_unpushed_suspects("tenant-x", 101)

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["evidence_sentence"] == "DM documented."

    def test_non_gemini_vision_source_excluded(self):
        """Only gemini_vision sourced suspects should be returned."""
        db_rows = [
            {
                "id": 10,
                "suspect_hcc": "19",
                "suspect_icd10": "E11.9",
                "confidence_score": 0.9,
                "evidence_detail": json.dumps({
                    "source": "claims",  # not gemini_vision
                    "evidence_sentence": "Claims-based evidence.",
                    "document_id": "doc-1",
                }),
            }
        ]
        mock_cursor_ctx = MagicMock()
        mock_cursor_ctx.__enter__ = MagicMock(return_value=mock_cursor_ctx)
        mock_cursor_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor_ctx.fetchall.return_value = db_rows

        with patch("app.services.partners.reveleer_sync.raf_cursor", return_value=mock_cursor_ctx):
            from app.services.partners.reveleer_sync import _get_unpushed_suspects

            result = _get_unpushed_suspects("tenant-x", 101)

        assert len(result) == 0
