"""
tests/test_provider_scorecard.py — provider scorecard shape + N+1 regression tests.

Locks in the public response shape for `calculate_provider_scorecard` and
`calculate_hcc_performance` so that the recent batched-aggregate rewrite
(consolidating six panel-level COUNT round-trips into two conditional
aggregates) cannot silently change keys, types, or query-count budget.

The frontend consumes these responses with strict TypeScript types; any
key drift would break the provider detail page. We also assert the query
budget stays at the post-optimization counts (calculate_hcc_performance =
2 round-trips, calculate_provider_scorecard <= 9) so a future contributor
cannot accidentally re-introduce an N+1 without the test going red.

All database calls are stubbed via unittest.mock — no live MySQL required.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Cursor fake — records every execute() call so we can count round-trips.
# ---------------------------------------------------------------------------

class _RecordingCursor:
    """Minimal cursor stub. Each test plants a sequence of fetchall/fetchone
    payloads; the cursor pops the next one each time the service calls
    fetchall() or fetchone(). Every execute() bumps the query counter."""

    def __init__(self, scripted: list[dict[str, Any]]) -> None:
        self._scripted = list(scripted)
        self._next: dict[str, Any] | None = None
        self.executed: list[str] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple | list | None = None) -> None:
        self.executed.append(sql.strip().split("\n", 1)[0][:120])
        # Pop the next scripted payload so fetch* sees it.
        self._next = self._scripted.pop(0) if self._scripted else {}

    def fetchall(self) -> list[dict[str, Any]]:
        payload = (self._next or {}).get("rows", [])
        return list(payload)

    def fetchone(self) -> dict[str, Any] | None:
        payload = (self._next or {}).get("row")
        return payload


@contextmanager
def _cursor_cm(cursor: _RecordingCursor):
    yield cursor


# ---------------------------------------------------------------------------
# Fixtures: scripted DB responses for a 2-patient, 3-HCC panel.
# ---------------------------------------------------------------------------

@pytest.fixture
def hcc_perf_script() -> list[dict[str, Any]]:
    """Scripted responses for calculate_hcc_performance.

    Order matches the post-optimization query sequence:
      1. panel patient_ids
      2. unioned coded + suspect aggregate (rows shape)
    """
    return [
        # 1. panel
        {"rows": [{"patient_id": 101}, {"patient_id": 102}]},
        # 2. unioned coded+suspect aggregates
        {
            "rows": [
                {"src": "coded", "hcc_code": "HCC18", "cnt": 2},
                {"src": "coded", "hcc_code": "HCC19", "cnt": 1},
                {"src": "suspect", "hcc_code": "HCC22", "cnt": 1},
            ]
        },
    ]


@pytest.fixture
def scorecard_script() -> list[dict[str, Any]]:
    """Scripted responses for calculate_provider_scorecard.

    Order matches the post-optimization query sequence:
      1. panel
      2. raf_scores latest per patient
      3. hcc counts (curr + prior + recaptured) — single conditional aggregate
      4. suspect counts (open / accepted / dismissed / total_confidence)
      5. MEAT avg
      6. _calculate_percentile_rank → SELECT average_raf
      7. INSERT snapshot
      8. SELECT * FROM providers WHERE id = %s   (via get_provider)
    """
    return [
        # 1. panel
        {"rows": [{"patient_id": 101}, {"patient_id": 102}]},
        # 2. raf_scores
        {
            "rows": [
                {"patient_id": 101, "final_raf": 1.234},
                {"patient_id": 102, "final_raf": 0.987},
            ]
        },
        # 3. hcc counts (combined)
        {"row": {"coded_curr": 5, "coded_prior": 4, "recaptured": 3}},
        # 4. suspect counts (combined)
        {
            "row": {
                "open_suspect_hccs": 2,
                "s_open": 3,
                "s_accepted": 1,
                "s_dismissed": 0,
                "total_confidence": 1.6,
            }
        },
        # 5. MEAT avg
        {"row": {"avg_meat": 0.85}},
        # 6. percentile rank — needs >=2 scores for a real percentile
        {"rows": [{"average_raf": 0.9}, {"average_raf": 1.1}, {"average_raf": 1.3}]},
        # 7. INSERT snapshot — no fetch
        {},
        # 8. get_provider
        {
            "row": {
                "id": 1,
                "first_name": "Test",
                "last_name": "Provider",
                "full_name": "Test Provider",
                "specialty": "Internal Medicine",
                "specialty_category": "PCP",
                "practice_name": None,
                "npi": "1234567890",
                "email": "test@example.com",
                "credential": "MD",
                "openemr_user_id": None,
                "phone": None,
                "status": "active",
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        },
    ]


# ---------------------------------------------------------------------------
# calculate_hcc_performance: shape + query-count regression.
# ---------------------------------------------------------------------------

def test_calculate_hcc_performance_shape_and_query_count(hcc_perf_script) -> None:
    """Locks the per-HCC row shape and asserts the post-optimization
    query budget (panel fetch + one unioned aggregate = 2 round-trips)."""
    from app.services import provider_service

    cursor = _RecordingCursor(hcc_perf_script)

    with patch.object(provider_service, "raf_cursor", lambda: _cursor_cm(cursor)):
        result = provider_service.calculate_hcc_performance(
            provider_id=1, year=2026, tenant_id=1
        )

    # --- query budget: was 3 (panel + coded + suspects), now 2.
    assert len(cursor.executed) == 2, (
        f"calculate_hcc_performance must use 2 queries (panel + unioned aggregate); "
        f"got {len(cursor.executed)}: {cursor.executed}"
    )

    # --- response shape: list of dicts with the exact keys the frontend reads.
    assert isinstance(result, list)
    assert len(result) == 3  # HCC18, HCC19, HCC22

    expected_keys = {
        "hcc_code",
        "hcc_label",
        "coded_patients",
        "open_suspects",
        "possible_patients",
        "capture_rate",
        "missed_patients",
        "revenue_impact",
    }
    for row in result:
        assert set(row.keys()) == expected_keys, (
            f"per-HCC row keys drifted: {set(row.keys()) ^ expected_keys}"
        )
        assert isinstance(row["hcc_code"], str)
        assert isinstance(row["hcc_label"], str)
        assert isinstance(row["coded_patients"], int)
        assert isinstance(row["open_suspects"], int)
        assert isinstance(row["possible_patients"], int)
        assert row["capture_rate"] is None or isinstance(row["capture_rate"], float)
        assert isinstance(row["missed_patients"], int)
        assert isinstance(row["revenue_impact"], float)

    # --- math: HCC18 has 2 coded / 0 suspects → capture_rate = 1.0
    by_code = {r["hcc_code"]: r for r in result}
    assert by_code["HCC18"]["coded_patients"] == 2
    assert by_code["HCC18"]["open_suspects"] == 0
    assert by_code["HCC18"]["capture_rate"] == 1.0

    # HCC22 has 0 coded / 1 suspect → capture_rate = 0.0
    assert by_code["HCC22"]["coded_patients"] == 0
    assert by_code["HCC22"]["open_suspects"] == 1
    assert by_code["HCC22"]["capture_rate"] == 0.0


def test_calculate_hcc_performance_empty_panel_returns_empty_list() -> None:
    """Empty panel must short-circuit (single panel query, no aggregates)."""
    from app.services import provider_service

    cursor = _RecordingCursor([{"rows": []}])  # empty panel

    with patch.object(provider_service, "raf_cursor", lambda: _cursor_cm(cursor)):
        result = provider_service.calculate_hcc_performance(
            provider_id=1, year=2026, tenant_id=1
        )

    assert result == []
    assert len(cursor.executed) == 1


# ---------------------------------------------------------------------------
# calculate_provider_scorecard: shape + query-count regression.
# ---------------------------------------------------------------------------

def test_calculate_provider_scorecard_shape_and_query_count(scorecard_script) -> None:
    """Locks the scorecard dict shape and asserts the post-optimization
    query budget. Was 12 round-trips, now 8 (one large conditional
    aggregate replaces 4 separate COUNT-DISTINCT queries; one suspect
    aggregate replaces 3 separate suspect queries)."""
    from app.services import provider_service

    cursor = _RecordingCursor(scorecard_script)

    with patch.object(provider_service, "raf_cursor", lambda: _cursor_cm(cursor)):
        result = provider_service.calculate_provider_scorecard(
            provider_id=1, year=2026, tenant_id=1
        )

    # --- query budget: was 12, now <= 9 (snapshot insert + provider lookup
    # are unavoidable; HCC and suspect aggregates are now consolidated).
    assert len(cursor.executed) <= 9, (
        f"calculate_provider_scorecard query budget exceeded "
        f"(post-optimization target <= 9, got {len(cursor.executed)}): {cursor.executed}"
    )

    # --- response shape: every key the frontend (and snapshot loader)
    # reads must remain. This is the contract the wrapping router merges
    # via **scorecard_data into the GET /scorecard response.
    expected_keys = {
        "provider_id",
        "provider_name",
        "measurement_year",
        "total_patients",
        "patients_with_scores",
        "average_raf",
        "hcc_capture_rate",
        "recapture_rate",
        "suspects_open",
        "suspects_accepted",
        "suspects_dismissed",
        "revenue_opportunity",
        "meat_completeness_avg",
        "documentation_quality_score",
        "percentile_rank",
        "calculated_at",
    }
    assert set(result.keys()) == expected_keys, (
        f"scorecard keys drifted: extra={set(result.keys()) - expected_keys} "
        f"missing={expected_keys - set(result.keys())}"
    )

    # --- types
    assert isinstance(result["provider_id"], int)
    assert isinstance(result["provider_name"], str)
    assert result["measurement_year"] == 2026
    assert result["total_patients"] == 2
    assert result["patients_with_scores"] == 2
    assert isinstance(result["average_raf"], float)
    # hcc_capture_rate = coded_curr / (coded_curr + open_suspect_hccs) = 5/(5+2)
    assert result["hcc_capture_rate"] == pytest.approx(5 / 7, abs=1e-4)
    # recapture_rate = recaptured / coded_prior = 3/4
    assert result["recapture_rate"] == pytest.approx(0.75, abs=1e-4)
    assert result["suspects_open"] == 3
    assert result["suspects_accepted"] == 1
    assert result["suspects_dismissed"] == 0
    assert isinstance(result["revenue_opportunity"], float)
    assert result["meat_completeness_avg"] == pytest.approx(0.85, abs=1e-4)
    assert isinstance(result["documentation_quality_score"], float)


def test_calculate_provider_scorecard_empty_panel_returns_empty_scorecard() -> None:
    """Empty panel returns _empty_scorecard with no aggregate queries fired."""
    from app.services import provider_service

    cursor = _RecordingCursor([
        {"rows": []},  # empty panel
        # _empty_scorecard calls get_provider, which fires one SELECT.
        {"row": {
            "id": 1, "first_name": "X", "last_name": "Y",
            "full_name": "X Y", "specialty": "", "specialty_category": None,
            "practice_name": None, "npi": "", "email": "",
            "credential": None, "openemr_user_id": None, "phone": None,
            "status": "active", "created_at": "", "updated_at": "",
        }},
    ])

    with patch.object(provider_service, "raf_cursor", lambda: _cursor_cm(cursor)):
        result = provider_service.calculate_provider_scorecard(
            provider_id=1, year=2026, tenant_id=1
        )

    # Only panel query + get_provider; no aggregates.
    assert len(cursor.executed) == 2
    assert result["total_patients"] == 0
    assert result["patients_with_scores"] == 0
    assert result["hcc_capture_rate"] is None
