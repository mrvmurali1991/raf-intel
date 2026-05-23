"""
tests/test_provider_suspect_hotlist.py
======================================

Unit tests for ``app.services.provider_suspect_hotlist.get_hotlist``.

Coverage:
- Urgency formula (0.5*confidence + 0.3*$/max + 0.2*days/90, capped 1.0)
- Sort order: items sorted by urgency_score DESC
- min_confidence filter drops sub-threshold suspects
- limit truncates
- summary aggregates: total_open, high_confidence_count, total_expected_$,
  avg_$_per_suspect
- Empty panel still returns a well-formed response
- _HCC_BASE_RATE is imported (not hard-coded) — sanity check the dollar math

DB calls are stubbed via the ``_suspects_override`` test hook plus
unittest.mock patches against the helper functions in the service module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import provider_suspect_hotlist as svc
from app.services.provider_service import _HCC_BASE_RATE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suspect(
    sid: int,
    pid: int,
    hcc: int,
    confidence: float,
    days_old: int = 0,
    icd10: str = "I10",
    evidence_type: str = "medication",
) -> dict:
    """Build a fake raf_suspect_conditions row."""
    return {
        "id": sid,
        "patient_id": pid,
        "suspect_hcc": hcc,
        "suspect_icd10": icd10,
        "evidence_type": evidence_type,
        "confidence_score": confidence,
        "created_at": datetime.now(timezone.utc) - timedelta(days=days_old),
    }


@pytest.fixture
def mock_lookups():
    """Patch helpers that hit the DB so tests stay pure."""
    with patch.object(svc, "_segments_for_pids", return_value={}), \
         patch.object(svc, "_patient_names",     return_value={}), \
         patch.object(svc, "_coefficient_lookup") as mock_coeff, \
         patch.object(svc, "_provider_panel_pids", return_value=[]):
        # Default: every HCC has coefficient 1.0 — keeps the math easy.
        mock_coeff.side_effect = lambda codes, seg, year=2024: {
            str(c): 1.0 for c in codes
        }
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_urgency_formula(mock_lookups) -> None:
    """Single suspect → urgency = 0.5*conf + 0.3*1.0 (it's the max) + 0.2*days/90."""
    suspects = [_suspect(1, 100, 19, confidence=0.8, days_old=45)]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)

    item = out["items"][0]
    assert item["confidence"] == 0.8
    # coeff=1.0 * conf=0.8 * base_rate
    assert item["expected_dollars"] == round(1.0 * 0.8 * _HCC_BASE_RATE, 2)
    assert item["days_open"] == 45

    expected = (
        0.5 * 0.8                       # confidence component
        + 0.3 * (item["expected_dollars"] / item["expected_dollars"])  # = 0.3 (it IS max)
        + 0.2 * (45 / 90)               # = 0.1
    )
    assert item["urgency_score"] == round(min(1.0, expected), 4)


def test_urgency_capped_at_one(mock_lookups) -> None:
    """Max-confidence + max-recency + max-$ should cap at 1.0."""
    suspects = [_suspect(1, 100, 19, confidence=1.0, days_old=200)]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)
    assert out["items"][0]["urgency_score"] == 1.0


def test_sort_by_urgency_desc(mock_lookups) -> None:
    """Higher urgency must come first regardless of insertion order."""
    suspects = [
        _suspect(1, 100, 19, confidence=0.3, days_old=10),
        _suspect(2, 101, 22, confidence=0.95, days_old=80),  # winner
        _suspect(3, 102, 18, confidence=0.6, days_old=30),
    ]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)
    scores = [it["urgency_score"] for it in out["items"]]
    assert scores == sorted(scores, reverse=True)
    assert out["items"][0]["suspect_id"] == 2


def test_min_confidence_filter(mock_lookups) -> None:
    """Suspects below min_confidence are dropped before ranking and aggregates."""
    suspects = [
        _suspect(1, 100, 19, confidence=0.4, days_old=5),
        _suspect(2, 101, 22, confidence=0.9, days_old=5),
        _suspect(3, 102, 18, confidence=0.6, days_old=5),
    ]
    out = svc.get_hotlist(
        provider_id=1, year=2026,
        _suspects_override=suspects, min_confidence=0.7,
    )
    assert out["summary"]["total_open"] == 1
    assert len(out["items"]) == 1
    assert out["items"][0]["suspect_id"] == 2


def test_limit_truncates(mock_lookups) -> None:
    """`limit` caps the items list but not the summary aggregates."""
    suspects = [
        _suspect(i, 100 + i, 19, confidence=0.5 + i * 0.05, days_old=i)
        for i in range(10)
    ]
    out = svc.get_hotlist(
        provider_id=1, year=2026, _suspects_override=suspects, limit=3,
    )
    assert len(out["items"]) == 3
    assert out["summary"]["total_open"] == 10  # all 10 included in aggregates


def test_summary_aggregates(mock_lookups) -> None:
    """high_confidence_count uses 0.80 threshold; avg_$ = total_$/total_open."""
    suspects = [
        _suspect(1, 100, 19, confidence=0.85, days_old=10),  # high-conf
        _suspect(2, 101, 22, confidence=0.95, days_old=10),  # high-conf
        _suspect(3, 102, 18, confidence=0.55, days_old=10),  # not high-conf
    ]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)
    s = out["summary"]
    assert s["total_open"] == 3
    assert s["high_confidence_count"] == 2
    expected_total = round(
        (0.85 + 0.95 + 0.55) * 1.0 * _HCC_BASE_RATE, 2
    )
    assert s["total_expected_dollars"] == expected_total
    assert s["avg_dollars_per_suspect"] == round(expected_total / 3, 2)
    assert s["high_confidence_threshold"] == svc.HIGH_CONFIDENCE_THRESHOLD


def test_empty_panel_returns_zeroed_summary(mock_lookups) -> None:
    """No suspects → empty items, zero aggregates, still 200-shaped."""
    out = svc.get_hotlist(provider_id=999, year=2026, _suspects_override=[])
    assert out["items"] == []
    assert out["summary"]["total_open"] == 0
    assert out["summary"]["high_confidence_count"] == 0
    assert out["summary"]["total_expected_dollars"] == 0
    assert out["summary"]["avg_dollars_per_suspect"] == 0.0
    assert out["provider_id"] == 999
    assert out["measurement_year"] == 2026


def test_dollars_use_imported_base_rate(mock_lookups) -> None:
    """expected_dollars == coefficient * confidence * _HCC_BASE_RATE (no hard-code)."""
    suspects = [_suspect(1, 100, 19, confidence=0.5, days_old=0)]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)
    # coefficient = 1.0 from the fixture mock
    assert out["items"][0]["expected_dollars"] == round(
        1.0 * 0.5 * _HCC_BASE_RATE, 2
    )


def test_days_open_handles_naive_datetime(mock_lookups) -> None:
    """Naive datetime (no tzinfo) should not crash days_open math."""
    suspects = [{
        "id": 1, "patient_id": 100, "suspect_hcc": 19,
        "suspect_icd10": "I10", "evidence_type": "medication",
        "confidence_score": 0.7,
        "created_at": datetime.utcnow() - timedelta(days=12),  # naive
    }]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)
    assert out["items"][0]["days_open"] >= 11  # allow rounding
    assert out["items"][0]["days_open"] <= 13


def test_items_carry_required_keys(mock_lookups) -> None:
    """Public contract: each item carries the documented keys."""
    suspects = [_suspect(1, 100, 19, confidence=0.7, days_old=5)]
    out = svc.get_hotlist(provider_id=1, year=2026, _suspects_override=suspects)
    item = out["items"][0]
    for key in (
        "patient_id", "patient_name", "suspect_id", "hcc_code", "hcc_label",
        "icd10", "confidence", "evidence_type", "raf_coefficient",
        "expected_dollars", "days_open", "urgency_score",
    ):
        assert key in item, f"missing key: {key}"
