"""
tests/test_recapture_close_service.py — Smart Close + Bulk Close + Reopen +
Orphan Attribution test suite for ``app.services.recapture_close_service``.

All DB calls are mocked via unittest.mock — no MySQL required.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.recapture_close_service import (
    attribute_orphan_gaps,
    bulk_close,
    get_close_history,
    reopen_gap,
    smart_close,
)


# ---------------------------------------------------------------------------
# Cursor harness — multi-step replay so we can simulate
#   1) SELECT gap            (fetchone)
#   2) UPDATE gap             (rowcount=1)
#   3) SELECT existing HCC   (fetchone -> None or row)
#   4) INSERT IGNORE HCC     (rowcount=1)
# in a single ``with raf_cursor()`` block.
# ---------------------------------------------------------------------------


def _scripted_cursor(steps):
    """Build a cursor whose execute()/fetchone()/fetchall()/rowcount step
    through a scripted sequence.

    Each step is a dict:
        - "fetchone": value returned by the next fetchone()
        - "fetchall": value returned by the next fetchall()
        - "rowcount": value of cursor.rowcount after the next execute()

    The cursor records every execute() call into ``cursor.execute_calls``.
    """
    cursor = MagicMock()
    cursor.execute_calls = []
    state = {"i": 0}

    def _on_execute(sql, params=None):
        cursor.execute_calls.append((sql, params))
        idx = state["i"]
        if idx < len(steps):
            step = steps[idx]
            cursor.fetchone.return_value = step.get("fetchone")
            cursor.fetchall.return_value = step.get("fetchall", [])
            cursor.rowcount = step.get("rowcount", 0)
        state["i"] += 1

    cursor.execute.side_effect = _on_execute

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


# ===========================================================================
# 1. attribute_orphan_gaps
# ===========================================================================


class TestAttributeOrphanGaps:
    def test_updates_orphan_with_panel_provider(self):
        candidates = [
            {"gap_id": 10, "patient_id": 100, "provider_npi": "1234567890"},
            {"gap_id": 11, "patient_id": 101, "provider_npi": None},
        ]
        steps = [
            {"fetchall": candidates},   # SELECT candidates
            {"rowcount": 1},            # UPDATE gap_id=10
            {"fetchone": {"c": 1}},     # COUNT remaining orphans
        ]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = attribute_orphan_gaps(tenant_id="1")

        assert result["checked"] == 2
        assert result["updated"] == 1
        assert result["still_orphan"] == 1

    def test_no_panel_match_leaves_orphan(self):
        candidates = [{"gap_id": 50, "patient_id": 700, "provider_npi": None}]
        steps = [
            {"fetchall": candidates},
            {"fetchone": {"c": 1}},
        ]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = attribute_orphan_gaps(tenant_id="1")
        assert result["updated"] == 0
        assert result["still_orphan"] == 1

    def test_zero_orphans(self):
        steps = [
            {"fetchall": []},
            {"fetchone": {"c": 0}},
        ]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = attribute_orphan_gaps(tenant_id="1")
        assert result == {"checked": 0, "updated": 0, "still_orphan": 0}

    def test_first_provider_wins_when_multiple(self):
        # Two panel rows for same gap, only one with NPI; we should pick that one.
        candidates = [
            {"gap_id": 9, "patient_id": 5, "provider_npi": None},
            {"gap_id": 9, "patient_id": 5, "provider_npi": "9876543210"},
        ]
        steps = [
            {"fetchall": candidates},
            {"rowcount": 1},
            {"fetchone": {"c": 0}},
        ]
        cm, cursor = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = attribute_orphan_gaps(tenant_id="1")
        # One UPDATE call against the gap with the NPI that was found.
        assert result["updated"] == 1
        update_call = [c for c in cursor.execute_calls if "UPDATE" in c[0]][0]
        assert update_call[1] == ("9876543210", 9)


# ===========================================================================
# 2. smart_close — transactional close + raf_patient_hcc write-through
# ===========================================================================


class TestSmartClose:
    GAP = {
        "id": 1, "patient_id": 100, "tenant_id": "1",
        "hcc_code": "85", "icd10_code": "I50.9",
        "prior_year": 2025, "current_year": 2026,
        "status": "open", "provider_npi": "1234567890",
    }

    def test_close_writes_evidence_and_inserts_hcc(self):
        steps = [
            {"fetchone": dict(self.GAP)},   # SELECT gap
            {"rowcount": 1},                # UPDATE recapture_gaps
            {"fetchone": None},             # SELECT existing raf_patient_hcc -> None
            {"rowcount": 1},                # INSERT IGNORE raf_patient_hcc
        ]
        cm, cursor = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = smart_close(
                gap_id=1,
                closed_by="dr@raf.health",
                evidence_phrase="Patient has CHF NYHA II, on metoprolol, BNP 450.",
                meat_element="m",  # lowercased — should be normalized
                write_to_raf_hcc=True,
                tenant_id="1",
                measurement_year=2026,
            )

        assert result["status"] == "recaptured"
        assert result["raf_hcc_inserted"] is True
        assert result["raf_hcc_already_present"] is False
        assert result["measurement_year"] == 2026

        # Inspect the UPDATE call for evidence + meat normalisation.
        update_call = next(c for c in cursor.execute_calls if "UPDATE recapture_gaps" in c[0])
        params = update_call[1]
        # update params: (now, closed_by, evidence, meat, gap_id)
        assert params[1] == "dr@raf.health"
        assert "CHF" in params[2]
        assert params[3] == "M"          # normalized to upper
        assert params[4] == 1

    def test_close_skips_hcc_when_already_present(self):
        steps = [
            {"fetchone": dict(self.GAP)},
            {"rowcount": 1},
            {"fetchone": {"id": 99}},   # raf_patient_hcc already there
        ]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = smart_close(
                gap_id=1,
                closed_by="dr@raf.health",
                evidence_phrase="evidence",
                meat_element="A",
                write_to_raf_hcc=True,
                tenant_id="1",
            )
        assert result["raf_hcc_inserted"] is False
        assert result["raf_hcc_already_present"] is True

    def test_close_skips_hcc_when_flag_disabled(self):
        steps = [
            {"fetchone": dict(self.GAP)},
            {"rowcount": 1},
        ]
        cm, cursor = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = smart_close(
                gap_id=1,
                closed_by="x",
                evidence_phrase="ok",
                meat_element=None,
                write_to_raf_hcc=False,
                tenant_id="1",
            )
        assert result["raf_hcc_inserted"] is False
        assert result["raf_hcc_already_present"] is False
        # No INSERT or HCC SELECT should have been executed
        sqls = [c[0] for c in cursor.execute_calls]
        assert not any("raf_patient_hcc" in s for s in sqls)

    def test_close_raises_when_gap_missing(self):
        steps = [{"fetchone": None}]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            with pytest.raises(ValueError, match="not found"):
                smart_close(
                    gap_id=999,
                    closed_by="x",
                    evidence_phrase="evidence",
                    tenant_id="1",
                )

    def test_close_requires_evidence(self):
        with pytest.raises(ValueError, match="evidence_phrase"):
            smart_close(gap_id=1, closed_by="x", evidence_phrase="", tenant_id="1")

    def test_close_requires_closed_by(self):
        with pytest.raises(ValueError, match="closed_by"):
            smart_close(gap_id=1, closed_by="", evidence_phrase="ok", tenant_id="1")

    def test_close_rejects_invalid_meat_element(self):
        with pytest.raises(ValueError, match="meat_element"):
            smart_close(
                gap_id=1, closed_by="x",
                evidence_phrase="ok", meat_element="Z", tenant_id="1",
            )

    def test_close_succeeds_even_if_hcc_insert_blows_up(self):
        # Simulate an INSERT exception. The close still succeeds.
        steps = [
            {"fetchone": dict(self.GAP)},
            {"rowcount": 1},
            {"fetchone": None},
        ]
        cm, cursor = _scripted_cursor(steps)

        original_side_effect = cursor.execute.side_effect

        def _raise_on_insert(sql, params=None):
            if "INSERT IGNORE INTO raf_patient_hcc" in sql:
                cursor.execute_calls.append((sql, params))
                raise RuntimeError("schema mismatch")
            return original_side_effect(sql, params)

        cursor.execute.side_effect = _raise_on_insert
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = smart_close(
                gap_id=1,
                closed_by="x",
                evidence_phrase="ok",
                write_to_raf_hcc=True,
                tenant_id="1",
            )
        assert result["status"] == "recaptured"
        assert result["raf_hcc_inserted"] is False


# ===========================================================================
# 3. bulk_close
# ===========================================================================


class TestBulkClose:
    def test_bulk_closes_all_supplied_gaps(self):
        # Patch smart_close so we don't need to script multi-step cursors per id.
        with patch(
            "app.services.recapture_close_service.smart_close",
            side_effect=lambda **kw: {
                "gap_id": kw["gap_id"], "status": "recaptured",
                "raf_hcc_inserted": True, "raf_hcc_already_present": False,
                "measurement_year": 2026,
            },
        ) as mock_close:
            result = bulk_close(
                gap_ids=[1, 2, 3],
                closed_by="dr@raf.health",
                evidence_phrase="Documented in today's note",
                meat_element="T",
                write_to_raf_hcc=True,
                tenant_id="1",
            )
        assert result["closed"] == 3
        assert result["raf_hcc_inserted"] == 3
        assert result["errors"] == []
        assert mock_close.call_count == 3

    def test_bulk_collects_errors_and_continues(self):
        def _fake(gap_id, **kw):
            if gap_id == 2:
                raise ValueError(f"Gap {gap_id} not found")
            return {
                "gap_id": gap_id, "status": "recaptured",
                "raf_hcc_inserted": False, "raf_hcc_already_present": True,
                "measurement_year": 2026,
            }

        with patch(
            "app.services.recapture_close_service.smart_close", side_effect=_fake,
        ):
            result = bulk_close(
                gap_ids=[1, 2, 3],
                closed_by="x",
                evidence_phrase="ok",
                tenant_id="1",
            )
        assert result["closed"] == 2
        assert len(result["errors"]) == 1
        assert result["errors"][0]["gap_id"] == 2

    def test_bulk_empty_input(self):
        result = bulk_close(
            gap_ids=[], closed_by="x", evidence_phrase="ok", tenant_id="1",
        )
        assert result == {
            "closed": 0, "raf_hcc_inserted": 0, "errors": [], "results": [],
        }


# ===========================================================================
# 4. reopen_gap
# ===========================================================================


class TestReopenGap:
    def test_reopen_clears_close_audit(self):
        steps = [
            {"fetchone": {"id": 1, "tenant_id": "1", "status": "recaptured"}},
            {"rowcount": 1},
        ]
        cm, cursor = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = reopen_gap(
                gap_id=1, reopened_by="dr@raf.health",
                reason="MEAT failed audit", tenant_id="1",
            )
        assert result == {"gap_id": 1, "status": "open"}
        update_call = next(c for c in cursor.execute_calls if "UPDATE" in c[0])
        # params: (now, reopened_by, reason, gap_id)
        assert update_call[1][1] == "dr@raf.health"
        assert update_call[1][2] == "MEAT failed audit"
        assert update_call[1][3] == 1

    def test_reopen_missing_gap(self):
        steps = [{"fetchone": None}]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            with pytest.raises(ValueError, match="not found"):
                reopen_gap(gap_id=99, reopened_by="x", reason="why", tenant_id="1")

    def test_reopen_requires_reason(self):
        with pytest.raises(ValueError, match="reason"):
            reopen_gap(gap_id=1, reopened_by="x", reason="", tenant_id="1")

    def test_reopen_requires_reopened_by(self):
        with pytest.raises(ValueError, match="reopened_by"):
            reopen_gap(gap_id=1, reopened_by="", reason="why", tenant_id="1")


# ===========================================================================
# 5. get_close_history
# ===========================================================================


class TestCloseHistory:
    def test_returns_recently_closed_gaps(self):
        rows = [
            {
                "id": 1, "patient_id": 100, "tenant_id": "1", "hcc_code": "85",
                "icd10_code": "I50.9", "prior_year": 2025, "current_year": 2026,
                "status": "recaptured", "provider_npi": "111", "revenue_impact": 3000,
                "resolved_at": datetime(2026, 5, 1, 12, 0),
                "resolved_by": "dr@raf.health",
                "evidence_phrase": "BNP 800; on furosemide",
                "meat_element": "M",
                "reopened_at": None, "reopened_by": None,
                "patient_name": "Jane Doe",
            }
        ]
        steps = [{"fetchall": rows}]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = get_close_history(tenant_id="1", year=2026, limit=50)
        assert len(result) == 1
        assert result[0]["resolved_by"] == "dr@raf.health"
        assert result[0]["patient_name"] == "Jane Doe"
        # ISO-formatted datetime
        assert isinstance(result[0]["resolved_at"], str)

    def test_empty_history(self):
        steps = [{"fetchall": []}]
        cm, _ = _scripted_cursor(steps)
        with patch("app.services.recapture_close_service.raf_cursor", cm):
            result = get_close_history(tenant_id="1")
        assert result == []
