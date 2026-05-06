"""
tests/test_recapture_campaign_service.py
=========================================

Unit tests for the recapture campaign service.  All DB calls are patched —
no MySQL is touched.  These tests cover the four behaviours called out in
the task spec:

    1. filter_criteria → SQL WHERE translation
    2. round-robin distribution
    3. kanban bucketing
    4. closure_rate / recaptured_revenue aggregation
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services import recapture_campaign_service as svc


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _ScriptedCursor:
    """Cursor mock that returns a pre-recorded sequence of fetch results.

    The service code interleaves ``execute()`` and ``fetchall()`` /
    ``fetchone()`` calls; we use a queue of replies indexed by call order.
    """

    def __init__(self, replies: list[Any], rowcount: int = 0):
        self._replies = list(replies)
        self._idx = 0
        self.rowcount = rowcount
        self.lastrowid = 1
        self.executed: list[tuple[str, Any]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    # The service interleaves execute + fetch — we just play back the replies.
    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, batch):
        self.executemany_calls.append((sql, list(batch)))
        # Simulate INSERT IGNORE: count = len(batch) by default.
        self.rowcount = len(batch)

    def _next(self):
        if self._idx >= len(self._replies):
            return None
        v = self._replies[self._idx]
        self._idx += 1
        return v

    def fetchone(self):
        v = self._next()
        if isinstance(v, list):
            # Caller expected fetchall but we've queued a list — degrade.
            return v[0] if v else None
        return v

    def fetchall(self):
        v = self._next()
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


def _patch_cursor(cursor: _ScriptedCursor):
    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor
    return _cm


# ---------------------------------------------------------------------------
# 1. filter_criteria → SQL fragment
# ---------------------------------------------------------------------------


class TestBuildFilterClause:
    def test_empty_returns_no_fragment(self):
        clause, params = svc._build_filter_clause({})
        assert clause == ""
        assert params == []

    def test_hcc_codes_translates_to_in_list(self):
        clause, params = svc._build_filter_clause({"hcc_codes": ["18", "19"]})
        assert "rg.hcc_code IN" in clause
        assert params == ["18", "19"]

    def test_min_revenue_filter(self):
        clause, params = svc._build_filter_clause({"min_revenue": 5000})
        assert "rg.revenue_impact >= %s" in clause
        assert params == [5000.0]

    def test_max_age_days_filter(self):
        clause, params = svc._build_filter_clause({"max_age_days": 90})
        assert "INTERVAL %s DAY" in clause
        assert params == [90]

    def test_combined_filters(self):
        clause, params = svc._build_filter_clause(
            {"hcc_codes": ["19"], "min_revenue": 5000, "max_age_days": 30}
        )
        # Order: hcc_codes, min_revenue, max_age_days
        assert clause.count("AND") == 3  # leading AND + 2 between fragments
        assert params == ["19", 5000.0, 30]

    def test_unknown_keys_ignored(self):
        clause, params = svc._build_filter_clause({"foo": "bar", "min_revenue": 100})
        assert "foo" not in clause
        assert params == [100.0]


# ---------------------------------------------------------------------------
# 2. preview_filter
# ---------------------------------------------------------------------------


def test_preview_filter_returns_count_and_breakdown():
    cursor = _ScriptedCursor(
        replies=[
            {"matched_gaps": 16, "total_revenue_at_risk": 48000},  # head row
            [  # by_hcc rows
                {"hcc_code": "19", "gap_count": 16, "revenue": 48000},
            ],
        ]
    )
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        out = svc.preview_filter(tenant_id="1", filter_criteria={"hcc_codes": ["19"]})

    assert out["matched_gaps"] == 16
    assert out["total_revenue_at_risk"] == 48000.0
    assert out["by_hcc"] == [{"hcc_code": "19", "count": 16, "revenue": 48000.0}]


# ---------------------------------------------------------------------------
# 3. round_robin distribution
# ---------------------------------------------------------------------------


class TestRoundRobin:
    def test_even_distribution(self):
        out = svc._round_robin([1, 2, 3, 4, 5, 6], buckets=2)
        assert out == [[1, 3, 5], [2, 4, 6]]

    def test_uneven_distribution(self):
        out = svc._round_robin([1, 2, 3, 4, 5], buckets=2)
        assert out == [[1, 3, 5], [2, 4]]

    def test_more_buckets_than_items(self):
        out = svc._round_robin([1, 2], buckets=3)
        assert out == [[1], [2], []]


# ---------------------------------------------------------------------------
# 4. assign_gaps_to_coders — round-robin against 16 gaps / 2 coders
# ---------------------------------------------------------------------------


def test_assign_gaps_round_robin_balances_two_coders():
    """16 open gaps assigned to 2 coders → 8 per coder."""
    gap_ids = list(range(1, 17))
    gaps = [
        {"id": gid, "patient_id": "p", "hcc_code": "19", "icd10_code": "E11.9",
         "provider_npi": "111", "revenue_impact": 3000.0, "created_at": None}
        for gid in gap_ids
    ]
    cursor = _ScriptedCursor(
        replies=[
            # fetch_campaign
            {"id": 7, "tenant_id": "1", "filter_criteria": '{"hcc_codes":["19"]}',
             "status": "draft"},
            # _select_matching_open_gaps
            gaps,
        ]
    )

    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        result = svc.assign_gaps_to_coders(
            campaign_id=7,
            coder_ids=[101, 202],
            distribution="round_robin",
            tenant_id="1",
        )

    assert result["assigned"] == 16
    assert result["total_matched"] == 16
    assert result["per_coder"] == [
        {"coder_id": 101, "count": 8},
        {"coder_id": 202, "count": 8},
    ]
    # Verify INSERT batch was actually written
    assert len(cursor.executemany_calls) == 1
    _, batch = cursor.executemany_calls[0]
    assert len(batch) == 16
    # Each row: (campaign_id, coder_id, gap_id)
    coder_101_gaps = [r[2] for r in batch if r[1] == 101]
    coder_202_gaps = [r[2] for r in batch if r[1] == 202]
    assert len(coder_101_gaps) == 8
    assert len(coder_202_gaps) == 8


def test_assign_rejects_unknown_distribution():
    with pytest.raises(ValueError, match="Invalid distribution"):
        svc.assign_gaps_to_coders(campaign_id=1, coder_ids=[1], distribution="bogus")


def test_assign_rejects_empty_coder_list():
    with pytest.raises(ValueError, match="At least one coder_id"):
        svc.assign_gaps_to_coders(campaign_id=1, coder_ids=[])


# ---------------------------------------------------------------------------
# 5. mark_assignment closure_rate aggregation
# ---------------------------------------------------------------------------


def test_mark_assignment_closes_gap_and_rolls_up_stats():
    """Mark 5 of 16 assignments closed → closure_rate=31.25, recaptured=$15,000."""
    cursor = _ScriptedCursor(
        replies=[
            # fetch (assignment + tenant)
            {"id": 50, "campaign_id": 7, "coder_id": 101, "gap_id": 99,
             "status": "in_progress", "tenant_id": "1"},
            # post-update assignment fetch
            {"id": 50, "campaign_id": 7, "coder_id": 101, "gap_id": 99,
             "status": "closed", "closed_at": None, "notes": None,
             "created_at": None, "updated_at": None},
            # rollup for auto-complete
            {"still_open": 11, "total": 16},
            # _compute_campaign_stats
            {"total_gaps": 16, "assigned_count": 5, "in_progress_count": 6,
             "closed_count": 5, "dismissed_count": 0,
             "recaptured_revenue": 15000, "at_risk_revenue": 33000},
        ]
    )
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        out = svc.mark_assignment(
            assignment_id=50, status="closed", coder_id=101
        )

    assert out["status"] == "closed"
    stats = out["campaign_stats"]
    assert stats["total_gaps"] == 16
    assert stats["closed"] == 5
    assert stats["closure_rate"] == 31.25
    assert stats["recaptured_revenue"] == 15000.0


def test_mark_assignment_rejects_unknown_status():
    with pytest.raises(ValueError, match="Invalid status"):
        svc.mark_assignment(assignment_id=1, status="exploded")


def test_mark_assignment_enforces_coder_ownership():
    cursor = _ScriptedCursor(
        replies=[
            {"id": 1, "campaign_id": 7, "coder_id": 101, "gap_id": 99,
             "status": "assigned", "tenant_id": "1"},
        ]
    )
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        with pytest.raises(PermissionError):
            svc.mark_assignment(assignment_id=1, status="closed", coder_id=999)


# ---------------------------------------------------------------------------
# 6. Kanban bucketing
# ---------------------------------------------------------------------------


def test_get_campaign_kanban_groups_by_status():
    rows = [
        {"assignment_id": 1, "campaign_id": 7, "coder_id": 101, "gap_id": 11,
         "assignment_status": "assigned", "closed_at": None, "notes": None,
         "assigned_at": None, "assignment_updated_at": None,
         "patient_id": "p1", "hcc_code": "19", "icd10_code": "E11.9",
         "prior_year": 2025, "current_year": 2026, "revenue_impact": 3000,
         "last_encounter_date": None, "provider_npi": "111",
         "gap_status": "open", "coder_name": "Alice A", "coder_email": "a@x"},
        {"assignment_id": 2, "campaign_id": 7, "coder_id": 101, "gap_id": 12,
         "assignment_status": "in_progress", "closed_at": None, "notes": None,
         "assigned_at": None, "assignment_updated_at": None,
         "patient_id": "p2", "hcc_code": "19", "icd10_code": "E11.9",
         "prior_year": 2025, "current_year": 2026, "revenue_impact": 3000,
         "last_encounter_date": None, "provider_npi": "111",
         "gap_status": "open", "coder_name": "Alice A", "coder_email": "a@x"},
        {"assignment_id": 3, "campaign_id": 7, "coder_id": 202, "gap_id": 13,
         "assignment_status": "closed", "closed_at": None, "notes": None,
         "assigned_at": None, "assignment_updated_at": None,
         "patient_id": "p3", "hcc_code": "19", "icd10_code": "E11.9",
         "prior_year": 2025, "current_year": 2026, "revenue_impact": 3000,
         "last_encounter_date": None, "provider_npi": "111",
         "gap_status": "recaptured", "coder_name": "Bob B", "coder_email": "b@x"},
        {"assignment_id": 4, "campaign_id": 7, "coder_id": 202, "gap_id": 14,
         "assignment_status": "dismissed", "closed_at": None, "notes": None,
         "assigned_at": None, "assignment_updated_at": None,
         "patient_id": "p4", "hcc_code": "19", "icd10_code": "E11.9",
         "prior_year": 2025, "current_year": 2026, "revenue_impact": 3000,
         "last_encounter_date": None, "provider_npi": "111",
         "gap_status": "dismissed", "coder_name": "Bob B", "coder_email": "b@x"},
    ]

    # First call inside get_campaign() → row + tenant check
    # Then _compute_campaign_stats() → 1 stats row
    # Then the kanban SELECT → list of row dicts above
    cursor = _ScriptedCursor(
        replies=[
            # get_campaign fetchone
            {"id": 7, "tenant_id": "1", "name": "C", "description": None,
             "status": "active", "filter_criteria": "{}",
             "target_close_date": None, "created_by": "u",
             "created_at": None, "updated_at": None},
            # _compute_campaign_stats
            {"total_gaps": 4, "assigned_count": 1, "in_progress_count": 1,
             "closed_count": 1, "dismissed_count": 1,
             "recaptured_revenue": 3000, "at_risk_revenue": 6000},
            # kanban rows
            rows,
        ]
    )
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        out = svc.get_campaign_kanban(campaign_id=7, tenant_id="1")

    buckets = out["buckets"]
    assert len(buckets["assigned"]) == 1
    assert len(buckets["in_progress"]) == 1
    assert len(buckets["closed"]) == 1
    assert len(buckets["dismissed"]) == 1
    # Stats are passed through
    assert out["stats"]["closure_rate"] == 25.0


# ---------------------------------------------------------------------------
# 7. Closure rate aggregation in list_campaigns
# ---------------------------------------------------------------------------


def test_list_campaigns_computes_closure_rate():
    cursor = _ScriptedCursor(
        replies=[
            [{
                "id": 1, "tenant_id": "1", "name": "Q1", "description": None,
                "status": "active", "filter_criteria": "{}",
                "target_close_date": None, "created_by": "u",
                "created_at": None, "updated_at": None,
                "total_gaps": 16, "closed_count": 5, "in_progress_count": 6,
                "dismissed_count": 0,
                "recaptured_revenue": 15000, "at_risk_revenue": 33000,
            }],
        ]
    )
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        out = svc.list_campaigns(tenant_id="1")

    assert len(out) == 1
    stats = out[0]["stats"]
    assert stats["total_gaps"] == 16
    assert stats["closed"] == 5
    assert stats["closure_rate"] == 31.25
    assert stats["recaptured_revenue"] == 15000.0


def test_list_campaigns_handles_zero_total():
    cursor = _ScriptedCursor(
        replies=[
            [{
                "id": 1, "tenant_id": "1", "name": "Q1", "description": None,
                "status": "draft", "filter_criteria": "{}",
                "target_close_date": None, "created_by": "u",
                "created_at": None, "updated_at": None,
                "total_gaps": 0, "closed_count": 0, "in_progress_count": 0,
                "dismissed_count": 0,
                "recaptured_revenue": 0, "at_risk_revenue": 0,
            }],
        ]
    )
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        out = svc.list_campaigns(tenant_id="1")

    assert out[0]["stats"]["closure_rate"] == 0.0


# ---------------------------------------------------------------------------
# 8. create_campaign happy path
# ---------------------------------------------------------------------------


def test_create_campaign_persists_and_returns_row():
    cursor = _ScriptedCursor(
        replies=[
            # post-insert SELECT
            {"id": 99, "tenant_id": "1", "name": "Q1", "description": None,
             "status": "draft", "filter_criteria": '{"hcc_codes":["19"]}',
             "target_close_date": None, "created_by": "u@x",
             "created_at": None, "updated_at": None},
        ],
    )
    cursor.lastrowid = 99
    with patch.object(svc, "raf_cursor", _patch_cursor(cursor)):
        out = svc.create_campaign(
            tenant_id="1",
            name="Q1",
            filter_criteria={"hcc_codes": ["19"]},
            created_by="u@x",
        )
    assert out["id"] == 99
    assert out["filter_criteria"] == {"hcc_codes": ["19"]}


def test_create_campaign_rejects_blank_name():
    with pytest.raises(ValueError, match="name is required"):
        svc.create_campaign(tenant_id="1", name="   ")


# ---------------------------------------------------------------------------
# 9. _parse_filter_criteria — robustness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, {}),
        ("", {}),
        ("{}", {}),
        ('{"a":1}', {"a": 1}),
        (b'{"a":2}', {"a": 2}),
        ({"already": "dict"}, {"already": "dict"}),
        ("not-json", {}),
    ],
)
def test_parse_filter_criteria(raw, expected):
    assert svc._parse_filter_criteria(raw) == expected
