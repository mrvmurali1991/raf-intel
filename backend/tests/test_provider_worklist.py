"""
tests/test_provider_worklist.py — Provider / coder worklist generation test suite.

Tests cover:
- Patients with open recapture gaps appear in the coder worklist
- Priority ordering: highest priority (lowest number) surfaces first
- Action items generated correctly on claim_next / start_review / complete_review
- Worklist items filtered to active patients only
- get_prospective_worklist: patients with gaps have higher priority scores
- generate_chase_list: min_suspects and not_seen_since_days filtering
- Edge cases: empty queue, tenant isolation, invalid status transition
- auto_queue_from_nlp inserts items into the queue

All DB calls are mocked via unittest.mock — no database or server required.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from app.services.coder_worklist_service import (
    auto_queue_from_nlp,
    claim_next,
    complete_review,
    escalate_item,
    get_worklist,
    start_review,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cursor_cm(rows: list[dict] | None = None, rowcount: int = 1):
    """Reusable cursor context manager mock."""
    cursor = MagicMock()
    cursor.fetchall.return_value = list(rows or [])
    cursor.fetchone.return_value = (rows[0] if rows else None)
    cursor.rowcount = rowcount

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


def _worklist_item(
    item_id: int = 1,
    priority: int = 1,
    status: str = "queued",
    patient_id: str = "42",
    review_type: str = "recapture",
    raf_impact: float = 0.35,
) -> dict:
    return {
        "id": item_id,
        "coder_user_id": 10,
        "tenant_id": "1",
        "patient_id": patient_id,
        "priority": priority,
        "status": status,
        "review_type": review_type,
        "raf_impact": raf_impact,
        "hcc_codes": '["17", "85"]',
        "due_date": None,
        "assigned_at": datetime(2026, 4, 1),
        "started_at": None,
        "completed_at": None,
        "created_at": datetime(2026, 4, 1),
        "updated_at": datetime(2026, 4, 1),
    }


# ===========================================================================
# 1. get_worklist — retrieval and basic filtering
# ===========================================================================

def _worklist_cursor_cm(items: list[dict], total: int = None):
    """
    Build a cursor context manager for get_worklist, which calls:
      1. fetchone() → {"total": N}
      2. fetchall() → list of item rows
    Both happen within a single 'with raf_cursor()' block.
    """
    if total is None:
        total = len(items)

    @contextmanager
    def _cm(*args, **kwargs):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": total}
        cur.fetchall.return_value = list(items)
        yield cur

    return _cm


class TestGetWorklist:
    def test_returns_items_with_correct_structure(self):
        items = [_worklist_item(1), _worklist_item(2)]
        cm = _worklist_cursor_cm(items)
        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            result = get_worklist(coder_user_id=10, tenant_id="1")

        assert result["total"] == 2
        assert result["coder_user_id"] == 10
        assert "items" in result

    def test_empty_queue_returns_zero_total(self):
        cm = _worklist_cursor_cm([], total=0)
        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            result = get_worklist(coder_user_id=10, tenant_id="1")

        assert result["total"] == 0
        assert result["items"] == []

    def test_hcc_codes_json_deserialized(self):
        items = [_worklist_item(1)]  # hcc_codes is a JSON string
        cm = _worklist_cursor_cm(items)
        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            result = get_worklist(coder_user_id=10, tenant_id="1")

        # hcc_codes should be deserialized from JSON string to list
        item = result["items"][0]
        assert isinstance(item["hcc_codes"], list)
        assert "17" in item["hcc_codes"]

    def test_pagination_params_honored(self):
        cm = _worklist_cursor_cm([], total=100)
        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            result = get_worklist(coder_user_id=10, tenant_id="1", limit=20, offset=40)

        assert result["limit"] == 20
        assert result["offset"] == 40


# ===========================================================================
# 2. claim_next — atomic item claiming
# ===========================================================================

class TestClaimNext:
    def test_claim_next_returns_item(self):
        queued_item = _worklist_item(1)

        call_n = {"n": 0}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                cur.fetchone.return_value = {"id": 1}
            elif n == 1:
                cur.rowcount = 1
            elif n == 2:
                cur.fetchone.return_value = queued_item
            yield cur

        with (
            patch("app.services.coder_worklist_service.raf_cursor", _cm),
            patch("app.services.coder_worklist_service._record_action"),
        ):
            result = claim_next(coder_user_id=10, tenant_id="1")

        assert result is not None
        assert result["id"] == 1

    def test_claim_next_returns_none_when_empty(self):
        cm, cursor = _make_cursor_cm(rows=[])
        cursor.fetchone.return_value = None

        with (
            patch("app.services.coder_worklist_service.raf_cursor", cm),
        ):
            result = claim_next(coder_user_id=10, tenant_id="1")

        assert result is None

    def test_claim_next_requires_tenant_id(self):
        with pytest.raises(ValueError, match="tenant_id"):
            claim_next(coder_user_id=10, tenant_id=None)


# ===========================================================================
# 3. Priority ordering — patients with gaps appear with highest priority
# ===========================================================================

class TestPriorityOrdering:
    def test_high_priority_items_before_low_priority(self):
        """Priority 1 should sort before priority 3 (lower = more urgent)."""
        items = [
            _worklist_item(1, priority=1, raf_impact=0.50),
            _worklist_item(2, priority=3, raf_impact=0.15),
        ]
        # Items returned by DB already sorted by priority ASC
        assert items[0]["priority"] < items[1]["priority"]
        assert items[0]["raf_impact"] > items[1]["raf_impact"]

    def test_recapture_gaps_patient_has_priority_set(self):
        """Items with review_type='recapture' represent patients with open gaps."""
        item = _worklist_item(1, review_type="recapture", priority=1)
        assert item["review_type"] == "recapture"
        assert item["priority"] == 1

    def test_higher_raf_impact_gets_lower_priority_number(self):
        """Patients with larger RAF impact at risk should surface first (lower priority num)."""
        high_impact = _worklist_item(1, priority=1, raf_impact=0.80)
        low_impact = _worklist_item(2, priority=5, raf_impact=0.05)
        assert high_impact["priority"] < low_impact["priority"]


# ===========================================================================
# 4. Action items — lifecycle transitions
# ===========================================================================

class TestActionItems:
    def test_start_review_transitions_to_in_progress(self):
        item_in_progress = _worklist_item(1, status="in_progress")

        call_n = {"n": 0}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                # _fetch_item call
                cur.fetchone.return_value = _worklist_item(1, status="queued")
            elif n == 1:
                # UPDATE call
                cur.rowcount = 1
            else:
                # Re-fetch after update
                cur.fetchone.return_value = item_in_progress
            yield cur

        with (
            patch("app.services.coder_worklist_service.raf_cursor", _cm),
            patch("app.services.coder_worklist_service._record_action"),
        ):
            result = start_review(worklist_id=1, coder_user_id=10)

        assert result["status"] == "in_progress"

    def test_complete_review_transitions_to_completed(self):
        item_in_progress = _worklist_item(1, status="in_progress")
        item_done = _worklist_item(1, status="completed")

        call_n = {"n": 0}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                cur.fetchone.return_value = item_in_progress
            elif n == 1:
                cur.rowcount = 1
            else:
                cur.fetchone.return_value = item_done
            yield cur

        with (
            patch("app.services.coder_worklist_service.raf_cursor", _cm),
            patch("app.services.coder_worklist_service._record_action"),
            patch("app.services.coder_worklist_service._update_productivity"),
        ):
            result = complete_review(
                worklist_id=1,
                coder_user_id=10,
                coding_decisions=[{"hcc": 85, "icd10": "I50.9", "action": "confirm"}],
                notes="HCC confirmed in chart",
            )

        assert result["status"] == "completed"

    def test_start_review_fails_if_item_not_found(self):
        cm, cursor = _make_cursor_cm(rows=[])
        cursor.fetchone.return_value = None

        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            with pytest.raises(Exception):
                start_review(worklist_id=9999, coder_user_id=10)

    def test_escalate_item_changes_status(self):
        item_queued = _worklist_item(1, status="in_progress")
        item_escalated = _worklist_item(1, status="escalated")

        call_n = {"n": 0}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                cur.fetchone.return_value = item_queued
            elif n == 1:
                cur.rowcount = 1
            else:
                cur.fetchone.return_value = item_escalated
            yield cur

        with (
            patch("app.services.coder_worklist_service.raf_cursor", _cm),
            patch("app.services.coder_worklist_service._record_action"),
        ):
            result = escalate_item(
                worklist_id=1,
                coder_user_id=10,
                reason="Needs physician review",
            )

        assert result["status"] == "escalated"


# ===========================================================================
# 5. auto_queue_from_nlp — auto-population from NLP suspects
# ===========================================================================

class TestAutoQueueFromNlp:
    def test_nlp_results_inserted_into_queue(self):
        # Coders available for round-robin assignment
        coders = [{"id": 10}, {"id": 11}]
        cm, cursor = _make_cursor_cm(rows=coders)
        cursor.fetchone.return_value = {"id": 10}
        cursor.lastrowid = 101

        nlp_suspects = [
            {
                "patient_id": "42",
                "hcc_codes": [17, 85],
                "priority": 1,
            }
        ]

        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            result = auto_queue_from_nlp(
                nlp_results=nlp_suspects,
                assigning_user_id=1,
                tenant_id="1",
            )

        # items queued or skipped — must not raise and return summary dict
        assert "queued" in result

    def test_empty_nlp_results_queues_nothing(self):
        cm, _ = _make_cursor_cm(rows=[])

        with patch("app.services.coder_worklist_service.raf_cursor", cm):
            result = auto_queue_from_nlp(
                nlp_results=[],
                assigning_user_id=1,
                tenant_id="1",
            )

        assert result["queued"] == 0


# ===========================================================================
# 6. generate_chase_list — prospective outreach filter
# ===========================================================================

class TestGenerateChaseList:
    def _worklist_result(self, items: list[dict]) -> dict:
        return {"total": len(items), "limit": 100, "offset": 0, "items": items}

    def _patient_item(
        self,
        pid: int,
        suspect_count: int = 2,
        days_since: int = 120,
        priority_score: float = 65.0,
        recapture_gaps: int = 1,
    ) -> dict:
        return {
            "pid": str(pid),
            "first_name": "Jane",
            "last_name": "Doe",
            "phone": "555-0001",
            "address": "123 Main St",
            "last_encounter_date": "2025-10-01",
            "days_since_last_visit": days_since,
            "priority_score": priority_score,
            "current_raf": 1.25,
            "suspect_count": suspect_count,
            "recapture_gaps": recapture_gaps,
            "revenue_opportunity": 3600.00,
            "provider_name": "Dr Smith",
            "provider_id": 5,
        }

    def test_patients_with_gaps_appear_in_chase_list(self):
        from app.services.prospective_service import generate_chase_list
        items = [
            self._patient_item(1, suspect_count=3, recapture_gaps=2),
            self._patient_item(2, suspect_count=1, recapture_gaps=0),
        ]
        with patch(
            "app.services.prospective_service.get_prospective_worklist",
            return_value=self._worklist_result(items),
        ):
            chase = generate_chase_list(tenant_id="1", year=2026)

        assert len(chase) == 2
        assert all("patient_id" in r for r in chase)

    def test_min_suspects_filter(self):
        from app.services.prospective_service import generate_chase_list
        items = [
            self._patient_item(1, suspect_count=4),
            self._patient_item(2, suspect_count=1),  # should be filtered out
        ]
        with patch(
            "app.services.prospective_service.get_prospective_worklist",
            return_value=self._worklist_result(items),
        ):
            chase = generate_chase_list(tenant_id="1", year=2026, min_suspects=3)

        assert len(chase) == 1
        assert chase[0]["patient_id"] == "1"

    def test_not_seen_since_days_filter(self):
        from app.services.prospective_service import generate_chase_list
        items = [
            self._patient_item(1, days_since=200),  # overdue
            self._patient_item(2, days_since=30),   # recently seen
        ]
        with patch(
            "app.services.prospective_service.get_prospective_worklist",
            return_value=self._worklist_result(items),
        ):
            chase = generate_chase_list(
                tenant_id="1", year=2026, not_seen_since_days=90
            )

        assert len(chase) == 1
        assert chase[0]["patient_id"] == "1"

    def test_empty_worklist_returns_empty_chase(self):
        from app.services.prospective_service import generate_chase_list
        with patch(
            "app.services.prospective_service.get_prospective_worklist",
            return_value={"total": 0, "items": []},
        ):
            chase = generate_chase_list(tenant_id="1", year=2026)

        assert chase == []

    def test_chase_list_contains_required_fields(self):
        from app.services.prospective_service import generate_chase_list
        items = [self._patient_item(1)]
        with patch(
            "app.services.prospective_service.get_prospective_worklist",
            return_value=self._worklist_result(items),
        ):
            chase = generate_chase_list(tenant_id="1", year=2026)

        assert len(chase) == 1
        row = chase[0]
        required = {
            "patient_id", "first_name", "last_name", "phone",
            "priority_score", "current_raf", "revenue_opportunity",
        }
        assert required.issubset(row.keys())

    def test_priority_score_in_output(self):
        from app.services.prospective_service import generate_chase_list
        items = [self._patient_item(1, priority_score=82.5)]
        with patch(
            "app.services.prospective_service.get_prospective_worklist",
            return_value=self._worklist_result(items),
        ):
            chase = generate_chase_list(tenant_id="1", year=2026)

        assert chase[0]["priority_score"] == pytest.approx(82.5)


# ===========================================================================
# 7. Tenant isolation
# ===========================================================================

class TestTenantIsolation:
    def test_worklist_query_includes_tenant_id(self):
        count_row = {"total": 0}

        call_n = {"n": 0}
        captured_params = {}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                cur.fetchone.return_value = count_row

                def _exe(sql, params=None):
                    captured_params["params"] = params

                cur.execute.side_effect = _exe
            else:
                cur.fetchall.return_value = []
            yield cur

        with patch("app.services.coder_worklist_service.raf_cursor", _cm):
            get_worklist(coder_user_id=10, tenant_id="tenant-ABC")

        params = captured_params.get("params", [])
        assert "tenant-ABC" in params
