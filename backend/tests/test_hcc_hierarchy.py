"""
tests/test_hcc_hierarchy.py — HCC hierarchy / trumping logic test suite.

Tests cover:
- Pure-logic apply_hierarchy() function (no I/O)
- Diabetes chain: HCC 17 trumps 18 and 19; HCC 18 trumps 19
- Non-related HCCs never trump each other
- Full multi-family hierarchy application on a patient with many HCCs
- Edge cases: single HCC, empty list, unknown codes, idempotency
- DB-aware apply_hierarchy_to_patient() using mocked raf_cursor
- apply_hierarchy_to_all_patients() batch path

All tests run entirely in-process.  No database required.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.services.hcc_hierarchy import (
    _ALL_TRUMPED_BY,
    _V24_TRUMPED_BY,
    _V28_TRUMPED_BY,
    _build_lookup,
    apply_hierarchy,
    apply_hierarchy_to_all_patients,
    apply_hierarchy_to_patient,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hcc_records(*codes: int) -> list[dict]:
    """Build minimal HCC record dicts for testing."""
    return [{"id": i + 1, "hcc_code": code, "patient_id": 1} for i, code in enumerate(codes)]


def _make_cursor_cm(rows: list[dict] | None = None, rowcount: int = 1):
    """Return a context-manager mock that yields a cursor returning *rows*."""
    cursor = MagicMock()
    cursor.fetchall.return_value = list(rows or [])
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.rowcount = rowcount

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


# ===========================================================================
# 1. Lookup table construction
# ===========================================================================

class TestBuildLookup:
    def test_diabetes_chain_v24_hcc18_trumped_by_17(self) -> None:
        """HCC 18 should be trumped by HCC 17 in V24."""
        assert 17 in _V24_TRUMPED_BY[18]

    def test_diabetes_chain_v24_hcc19_trumped_by_17_and_18(self) -> None:
        """HCC 19 should be trumped by both 17 and 18 in V24."""
        assert 17 in _V24_TRUMPED_BY[19]
        assert 18 in _V24_TRUMPED_BY[19]

    def test_hcc17_not_in_trumped_by(self) -> None:
        """HCC 17 is the most severe in its chain — nothing trumps it."""
        assert 17 not in _V24_TRUMPED_BY

    def test_v28_diabetes_chain_hcc36_trumped_by_35(self) -> None:
        """V28 diabetes chain: HCC 36 trumped by 35."""
        assert 35 in _V28_TRUMPED_BY[36]

    def test_v28_renal_chain_hcc327_trumped_by_326(self) -> None:
        assert 326 in _V28_TRUMPED_BY[327]

    def test_custom_chain_build(self) -> None:
        chains = [(10, 20, 30)]
        lookup = _build_lookup(chains)
        assert 10 in lookup[20]
        assert 10 in lookup[30]
        assert 20 in lookup[30]
        assert 10 not in lookup  # most-severe, never trumped

    def test_cancer_chain_v24_hcc9_trumped_by_8(self) -> None:
        assert 8 in _V24_TRUMPED_BY[9]

    def test_all_trumped_by_covers_both_v24_and_v28(self) -> None:
        """Combined lookup includes HCC 18 (V24) and HCC 36 (V28)."""
        assert 18 in _ALL_TRUMPED_BY
        assert 36 in _ALL_TRUMPED_BY


# ===========================================================================
# 2. apply_hierarchy — diabetes chain (V24)
# ===========================================================================

class TestApplyHierarchyDiabetes:
    """HCC 17 (acute) > 18 (chronic) > 19 (without complications)."""

    def test_17_trumps_18(self) -> None:
        records = _hcc_records(17, 18)
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[17]["is_trumped"] is False
        assert by_code[18]["is_trumped"] is True
        assert by_code[18]["trumped_by_hcc"] == "17"

    def test_17_trumps_19(self) -> None:
        records = _hcc_records(17, 19)
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[19]["is_trumped"] is True
        assert by_code[19]["trumped_by_hcc"] == "17"

    def test_18_trumps_19(self) -> None:
        """When only 18 and 19 are present (no 17), 18 still trumps 19."""
        records = _hcc_records(18, 19)
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[18]["is_trumped"] is False
        assert by_code[19]["is_trumped"] is True
        assert by_code[19]["trumped_by_hcc"] == "18"

    def test_17_18_19_all_present(self) -> None:
        """With all three: only 17 is active; 18 and 19 are both trumped."""
        records = _hcc_records(17, 18, 19)
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[17]["is_trumped"] is False
        assert by_code[18]["is_trumped"] is True
        assert by_code[19]["is_trumped"] is True

    def test_only_hcc19_present_not_trumped(self) -> None:
        """If only the least-severe diabetes HCC is present, it is not trumped."""
        records = _hcc_records(19)
        apply_hierarchy(records, model_version="V24")
        assert records[0]["is_trumped"] is False
        assert records[0]["trumped_by_hcc"] is None

    def test_trumped_by_points_to_lowest_severe(self) -> None:
        """When 17 and 18 are present, HCC 19 is reported as trumped by 17 (most severe)."""
        records = _hcc_records(17, 18, 19)
        apply_hierarchy(records, model_version="V24")
        hcc19 = next(r for r in records if r["hcc_code"] == 19)
        assert hcc19["trumped_by_hcc"] == "17"


# ===========================================================================
# 3. Non-related HCCs do not trump each other
# ===========================================================================

class TestNonRelatedHCCs:
    def test_diabetes_and_chf_independent(self) -> None:
        """HCC 17 (diabetes) and HCC 85 (CHF) are in different chains — no trumping."""
        records = _hcc_records(17, 85)
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[17]["is_trumped"] is False
        assert by_code[85]["is_trumped"] is False

    def test_renal_and_cancer_independent(self) -> None:
        records = _hcc_records(8, 134)
        apply_hierarchy(records, model_version="V24")
        for r in records:
            assert r["is_trumped"] is False

    def test_three_unrelated_hccs(self) -> None:
        """Three HCCs from completely different families — none trumped."""
        records = _hcc_records(17, 85, 111)  # diabetes, CHF, COPD
        apply_hierarchy(records, model_version="V24")
        for r in records:
            assert r["is_trumped"] is False

    def test_neurological_and_cardiac_independent(self) -> None:
        records = _hcc_records(70, 85)
        apply_hierarchy(records, model_version="V24")
        for r in records:
            assert r["is_trumped"] is False


# ===========================================================================
# 4. Full hierarchy application on a patient with multiple HCCs
# ===========================================================================

class TestFullHierarchyApplication:
    def test_multi_family_patient(self) -> None:
        """Patient with HCCs from several families — only intra-family trumping fires."""
        # Families: cancer (8,9), diabetes (17,18), renal (134,135), COPD (111,112)
        records = _hcc_records(8, 9, 17, 18, 134, 135, 111, 112)
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}

        # Cancer family: 8 trumps 9
        assert by_code[8]["is_trumped"] is False
        assert by_code[9]["is_trumped"] is True
        assert by_code[9]["trumped_by_hcc"] == "8"

        # Diabetes family: 17 trumps 18
        assert by_code[17]["is_trumped"] is False
        assert by_code[18]["is_trumped"] is True

        # Renal family: 134 trumps 135
        assert by_code[134]["is_trumped"] is False
        assert by_code[135]["is_trumped"] is True

        # COPD family: 111 trumps 112
        assert by_code[111]["is_trumped"] is False
        assert by_code[112]["is_trumped"] is True

    def test_active_hcc_count_after_hierarchy(self) -> None:
        """Only non-trumped HCCs should contribute to a real RAF score."""
        records = _hcc_records(17, 18, 19, 85, 86, 87)
        apply_hierarchy(records, model_version="V24")
        active = [r for r in records if not r["is_trumped"]]
        # Per V24: 17 survives; 18,19 trumped. 85 survives; 86,87 trumped.
        assert len(active) == 2

    def test_idempotency(self) -> None:
        """Calling apply_hierarchy twice yields the same result."""
        records = _hcc_records(17, 18, 19)
        apply_hierarchy(records, model_version="V24")
        first_pass = [(r["hcc_code"], r["is_trumped"], r["trumped_by_hcc"]) for r in records]
        apply_hierarchy(records, model_version="V24")
        second_pass = [(r["hcc_code"], r["is_trumped"], r["trumped_by_hcc"]) for r in records]
        assert first_pass == second_pass

    def test_empty_list_is_safe(self) -> None:
        result = apply_hierarchy([], model_version="V24")
        assert result == []

    def test_single_hcc_never_trumped(self) -> None:
        records = _hcc_records(18)
        apply_hierarchy(records, model_version="V24")
        assert records[0]["is_trumped"] is False

    def test_hcc_code_as_string(self) -> None:
        """hcc_code stored as string (common from DB) should still work."""
        records = [
            {"id": 1, "hcc_code": "17", "patient_id": 1},
            {"id": 2, "hcc_code": "18", "patient_id": 1},
        ]
        apply_hierarchy(records, model_version="V24")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code["18"]["is_trumped"] is True

    def test_unknown_hcc_code_skipped_gracefully(self) -> None:
        records = [
            {"id": 1, "hcc_code": "not-a-number", "patient_id": 1},
            {"id": 2, "hcc_code": 17, "patient_id": 1},
        ]
        # Should not raise
        result = apply_hierarchy(records, model_version="V24")
        assert result is records  # same list returned


# ===========================================================================
# 5. model_version routing
# ===========================================================================

class TestModelVersionRouting:
    def test_v28_diabetes_chain_applied_correctly(self) -> None:
        """V28 diabetes uses HCC 35/36/37 — V24 chain should not fire for 35."""
        records = _hcc_records(35, 36, 37)
        apply_hierarchy(records, model_version="V28")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[35]["is_trumped"] is False
        assert by_code[36]["is_trumped"] is True
        assert by_code[37]["is_trumped"] is True

    def test_none_model_version_uses_combined(self) -> None:
        """None model_version uses combined V24+V28 — both chain sets apply."""
        records = _hcc_records(17, 18)  # V24 diabetes
        apply_hierarchy(records, model_version=None)
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[18]["is_trumped"] is True

    def test_unknown_model_version_falls_back_to_combined(self) -> None:
        records = _hcc_records(17, 18)
        apply_hierarchy(records, model_version="V99_FUTURE")
        by_code = {r["hcc_code"]: r for r in records}
        assert by_code[18]["is_trumped"] is True


# ===========================================================================
# 6. DB-aware: apply_hierarchy_to_patient (mocked cursor)
# ===========================================================================

class TestApplyHierarchyToPatient:
    def _db_rows(self, *codes: int) -> list[dict]:
        return [
            {"id": i + 10, "hcc_code": code, "is_trumped": 0, "trumped_by_hcc": None}
            for i, code in enumerate(codes)
        ]

    def test_no_rows_returns_zero_counts(self) -> None:
        cm, _ = _make_cursor_cm(rows=[])
        with patch("app.services.hcc_hierarchy.raf_cursor", cm):
            result = apply_hierarchy_to_patient(
                patient_id=1, measurement_year=2026, tenant_id="1"
            )
        assert result["total"] == 0
        assert result["trumped"] == 0
        assert result["updated"] == 0

    def test_diabetes_trumping_persisted(self) -> None:
        rows = self._db_rows(17, 18, 19)
        cm, cursor = _make_cursor_cm(rows=rows)
        with patch("app.services.hcc_hierarchy.raf_cursor", cm):
            result = apply_hierarchy_to_patient(
                patient_id=1, measurement_year=2026, tenant_id="1", model_version="V24"
            )
        assert result["total"] == 3
        assert result["trumped"] == 2
        assert result["not_trumped"] == 1

    def test_error_counter_increments_on_db_failure(self) -> None:
        rows = self._db_rows(17, 18)
        # First call (SELECT) works; UPDATE calls raise
        call_count = {"n": 0}

        @contextmanager
        def _patchy(*args, **kwargs):
            cur = MagicMock()
            if call_count["n"] == 0:
                cur.fetchall.return_value = rows
            else:
                cur.execute.side_effect = RuntimeError("DB write failed")
            call_count["n"] += 1
            yield cur

        with patch("app.services.hcc_hierarchy.raf_cursor", _patchy):
            result = apply_hierarchy_to_patient(
                patient_id=1, measurement_year=2026, tenant_id="1"
            )
        # At least one error should have been recorded
        assert result["errors"] > 0


# ===========================================================================
# 7. DB-aware: apply_hierarchy_to_all_patients (mocked cursor)
# ===========================================================================

class TestApplyHierarchyToAllPatients:
    def test_empty_patient_list_returns_zeros(self) -> None:
        cm, _ = _make_cursor_cm(rows=[])
        with patch("app.services.hcc_hierarchy.raf_cursor", cm):
            result = apply_hierarchy_to_all_patients(measurement_year=2026, tenant_id="1")
        assert result["patients"] == 0
        assert result["total_hccs"] == 0

    def test_aggregate_across_two_patients(self) -> None:
        """Two patients each with a diabetes pair → 2 total trumped HCCs."""
        patient_list = [{"patient_id": 1}, {"patient_id": 2}]
        hcc_rows_p1 = [
            {"id": 1, "hcc_code": 17, "is_trumped": 0, "trumped_by_hcc": None},
            {"id": 2, "hcc_code": 18, "is_trumped": 0, "trumped_by_hcc": None},
        ]
        hcc_rows_p2 = [
            {"id": 3, "hcc_code": 17, "is_trumped": 0, "trumped_by_hcc": None},
            {"id": 4, "hcc_code": 18, "is_trumped": 0, "trumped_by_hcc": None},
        ]

        call_counter = {"n": 0}

        @contextmanager
        def _multi_cursor(*args, **kwargs):
            cur = MagicMock()
            n = call_counter["n"]
            call_counter["n"] += 1
            if n == 0:
                # First call: DISTINCT patient IDs
                cur.fetchall.return_value = patient_list
            elif n % 3 == 1:
                # Per-patient SELECT: alternate patient HCC rows
                pid_idx = (n - 1) // 3
                cur.fetchall.return_value = hcc_rows_p1 if pid_idx == 0 else hcc_rows_p2
            else:
                cur.fetchall.return_value = []
            yield cur

        with patch("app.services.hcc_hierarchy.raf_cursor", _multi_cursor):
            result = apply_hierarchy_to_all_patients(
                measurement_year=2026, tenant_id="1", model_version="V24"
            )
        assert result["patients"] == 2
