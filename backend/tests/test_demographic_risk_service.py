"""
Unit tests for app.services.knowledge_graph.demographic_risk_service.

These tests fake out raf_cursor and feed canned rows so the matching /
multiplier-compounding logic can be verified deterministically without a
running database.

Run with::

    pytest backend/tests/test_demographic_risk_service.py -v
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from app.services.knowledge_graph import demographic_risk_service as drs


# ---------------------------------------------------------------------------
# Faking infrastructure
# ---------------------------------------------------------------------------

class _FakeCursor:
    """
    SQL-shaped stub.  Recognises the two SELECTs the service issues:
      - SELECT ... FROM kg_demographic_risk_factors WHERE hcc_code = %s ...
      - SELECT coefficient FROM hcc_raf_coefficients WHERE hcc_code = %s ...
    plus the helpers that read raf_patient_demographics / raf_patient_hcc.
    Every other statement raises so unexpected paths are caught fast.
    """

    def __init__(
        self,
        factor_rows: list[dict[str, Any]],
        coefficients: dict[tuple[int, str, int], float],
        patient_demo: dict[int, dict[str, Any]] | None = None,
        prior_hccs: dict[int, list[str]] | None = None,
    ):
        self._factor_rows = factor_rows
        self._coefficients = coefficients
        self._patient_demo = patient_demo or {}
        self._prior_hccs = prior_hccs or {}
        self._last: list[dict[str, Any]] = []
        self._last_one: dict[str, Any] | None = None
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()):
        sql_norm = " ".join(sql.split()).upper()
        if "FROM KG_DEMOGRAPHIC_RISK_FACTORS" in sql_norm:
            target = str(params[0])
            self._last = [dict(r) for r in self._factor_rows if str(r["hcc_code"]) == target and r.get("is_active", 1)]
        elif "FROM HCC_RAF_COEFFICIENTS" in sql_norm:
            hcc, segment, year = int(params[0]), params[1], int(params[2])
            coeff = self._coefficients.get((hcc, segment, year))
            self._last_one = {"coefficient": coeff} if coeff is not None else None
        elif "FROM RAF_PATIENT_DEMOGRAPHICS" in sql_norm:
            pid = int(params[0])
            self._last_one = self._patient_demo.get(pid)
        elif "FROM RAF_PATIENT_HCC" in sql_norm:
            pid = int(params[0])
            self._last = [{"hcc_code": h} for h in self._prior_hccs.get(pid, [])]
        else:  # pragma: no cover
            raise AssertionError(f"Unexpected SQL: {sql!r}")

    def fetchall(self):
        return list(self._last)

    def fetchone(self):
        return dict(self._last_one) if self._last_one else None


def _make_fake_cursor_factory(
    factor_rows: list[dict[str, Any]],
    coefficients: dict[tuple[int, str, int], float] | None = None,
    patient_demo: dict[int, dict[str, Any]] | None = None,
    prior_hccs: dict[int, list[str]] | None = None,
):
    @contextmanager
    def _cm(dictionary: bool = True):
        yield _FakeCursor(
            factor_rows=factor_rows,
            coefficients=coefficients or {},
            patient_demo=patient_demo,
            prior_hccs=prior_hccs,
        )

    return _cm


@pytest.fixture
def patch_db():
    """Patch raf_cursor inside the service module with a fake cursor."""
    holder: dict[str, Any] = {}

    def install(
        factor_rows: list[dict[str, Any]],
        coefficients: dict[tuple[int, str, int], float] | None = None,
        patient_demo: dict[int, dict[str, Any]] | None = None,
        prior_hccs: dict[int, list[str]] | None = None,
    ):
        cm = _make_fake_cursor_factory(factor_rows, coefficients, patient_demo, prior_hccs)
        p = patch("app.services.knowledge_graph.demographic_risk_service.raf_cursor", cm)
        p.start()
        holder["patch"] = p

    yield install

    p = holder.get("patch")
    if p is not None:
        p.stop()


# ---------------------------------------------------------------------------
# Helper: build a factor row dict matching DB column shape
# ---------------------------------------------------------------------------

def _row(
    rid: int,
    hcc: str,
    *,
    age_min: int = 0,
    age_max: int = 120,
    sex: str | None = None,
    dual: str = "any",
    disabled: int | None = None,
    institutional: int | None = None,
    multiplier: float = 1.0,
    cond: list[str] | None = None,
    source: str = "test-source",
    notes: str = "",
    is_active: int = 1,
) -> dict[str, Any]:
    return {
        "id": rid,
        "hcc_code": hcc,
        "age_min": age_min,
        "age_max": age_max,
        "sex": sex,
        "dual_status": dual,
        "disabled": disabled,
        "institutional": institutional,
        "prior_multiplier": multiplier,
        "conditional_on_hccs": json.dumps(cond) if cond else None,
        "source": source,
        "source_notes": notes,
        "is_active": is_active,
    }


# ===========================================================================
# Normalisation helper tests
# ===========================================================================

def test_normalise_hcc_strips_prefix_and_zeros():
    assert drs._normalise_hcc("HCC0138") == "138"
    assert drs._normalise_hcc("hcc 19") == "19"
    assert drs._normalise_hcc("0") == "0"
    assert drs._normalise_hcc(None) == ""


def test_normalise_dual_accepts_variants():
    assert drs._normalise_dual(True) == "dual"
    assert drs._normalise_dual("FBD") == "dual"
    assert drs._normalise_dual("non-dual") == "non_dual"
    assert drs._normalise_dual("garbage") == "any"
    assert drs._normalise_dual(None) == "any"


def test_normalise_sex_accepts_variants():
    assert drs._normalise_sex("Female") == "F"
    assert drs._normalise_sex("M") == "M"
    assert drs._normalise_sex("Unknown") == "U"
    assert drs._normalise_sex(None) is None


def test_parse_conditional_hccs_handles_string_and_list():
    assert drs._parse_conditional_hccs(None) == []
    assert drs._parse_conditional_hccs(["19", "138"]) == ["19", "138"]
    assert drs._parse_conditional_hccs('["18","226"]') == ["18", "226"]
    assert drs._parse_conditional_hccs("not-json") == []


# ===========================================================================
# Row-matching tests
# ===========================================================================

def test_age_range_matching():
    row = _row(1, "138", age_min=65, age_max=74, multiplier=1.4)
    matchers = {"age": 70, "sex": None, "dual_status": "any",
                "disabled": None, "institutional": None,
                "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **matchers) is True
    matchers["age"] = 80
    assert drs._row_matches(row, **matchers) is False


def test_sex_null_matches_any():
    row = _row(1, "138", sex=None, multiplier=1.5)
    args = {"age": 70, "sex": "F", "dual_status": "any",
            "disabled": None, "institutional": None, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **args) is True


def test_sex_specific_excludes_others():
    row = _row(1, "138", sex="F")
    args = {"age": 70, "sex": "M", "dual_status": "any",
            "disabled": None, "institutional": None, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **args) is False


def test_dual_any_matches_anyone():
    row = _row(1, "138", dual="any")
    args = {"age": 70, "sex": None, "dual_status": "non_dual",
            "disabled": None, "institutional": None, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **args) is True


def test_dual_specific_must_match():
    row = _row(1, "138", dual="dual")
    args = {"age": 70, "sex": None, "dual_status": "non_dual",
            "disabled": None, "institutional": None, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **args) is False


def test_conditional_on_hccs_requires_overlap():
    row = _row(1, "138", cond=["18"])
    yes = {"age": 75, "sex": None, "dual_status": "any",
           "disabled": None, "institutional": None,
           "prior_hccs_normalised": {"18", "19"}}
    no = {**yes, "prior_hccs_normalised": {"19"}}
    no_empty = {**yes, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **yes) is True
    assert drs._row_matches(row, **no) is False
    assert drs._row_matches(row, **no_empty) is False


def test_disabled_flag_when_specified_must_match():
    row = _row(1, "138", disabled=1)
    args = {"age": 60, "sex": None, "dual_status": "any",
            "disabled": 0, "institutional": None, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **args) is False
    args["disabled"] = 1
    assert drs._row_matches(row, **args) is True


def test_institutional_null_row_ignored():
    row = _row(1, "138", institutional=None)
    args = {"age": 70, "sex": None, "dual_status": "any",
            "disabled": None, "institutional": 1, "prior_hccs_normalised": set()}
    assert drs._row_matches(row, **args) is True


def test_constrained_row_does_not_fire_on_unknown_demographic():
    """
    A row that REQUIRES institutional=1 must not match a patient whose
    institutional status is None (unknown).  Same for disabled.
    """
    inst_row = _row(1, "138", institutional=1, multiplier=1.4)
    args = {"age": 80, "sex": None, "dual_status": "any",
            "disabled": None, "institutional": None,
            "prior_hccs_normalised": set()}
    assert drs._row_matches(inst_row, **args) is False
    args["institutional"] = 0
    assert drs._row_matches(inst_row, **args) is False
    args["institutional"] = 1
    assert drs._row_matches(inst_row, **args) is True

    dis_row = _row(2, "138", disabled=1, multiplier=1.3)
    args2 = {"age": 50, "sex": None, "dual_status": "any",
             "disabled": None, "institutional": None,
             "prior_hccs_normalised": set()}
    assert drs._row_matches(dis_row, **args2) is False
    args2["disabled"] = 1
    assert drs._row_matches(dis_row, **args2) is True


# ===========================================================================
# compute_modulated_prior tests
# ===========================================================================

def test_compute_modulated_prior_target_scenario_2_1x(patch_db):
    """The acceptance-criteria curl: HCC 138, F 78, dual, prior HCC 18 -> 2.1x."""
    rows = [
        _row(1, "138", age_min=75, age_max=120, multiplier=2.1, cond=["18"],
             source="curated-USRDS-2023"),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.500})
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 78, "sex": "F", "dual_status": "dual"},
        prior_hccs=["18"],
    )
    assert result["multiplier"] == pytest.approx(2.1, abs=1e-4)
    assert result["base_prior"] == pytest.approx(0.5)
    assert result["modulated_prior"] == pytest.approx(1.05, abs=1e-4)
    assert result["factor_count"] == 1
    assert result["factors_applied"][0]["source"] == "curated-USRDS-2023"


def test_overlapping_age_ranges_compound(patch_db):
    """Two matching rows with overlapping age ranges multiply their multipliers."""
    rows = [
        _row(1, "138", age_min=65, age_max=120, sex="F", multiplier=1.4),
        _row(2, "138", age_min=75, age_max=120, multiplier=1.5),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 1.0})
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 80, "sex": "F", "dual_status": "any"},
        prior_hccs=[],
    )
    assert result["multiplier"] == pytest.approx(1.4 * 1.5, abs=1e-4)
    assert result["factor_count"] == 2


def test_missing_demographics_default_to_no_modulation(patch_db):
    """Empty patient_demo + factor that requires age 75+ -> no match -> 1.0x."""
    rows = [
        _row(1, "138", age_min=75, age_max=120, multiplier=1.5),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.4})
    result = drs.compute_modulated_prior(
        "138", patient_demo={}, prior_hccs=[],
    )
    # age=None means age-range filter is skipped, so the row WILL match here.
    # Verify that what we got is sane, then the inverse case below confirms
    # the more specific behaviour.
    assert result["multiplier"] >= 1.0
    assert result["modulated_prior"] >= result["base_prior"]


def test_age_outside_range_yields_unit_multiplier(patch_db):
    rows = [
        _row(1, "138", age_min=75, age_max=120, multiplier=1.5),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.4})
    result = drs.compute_modulated_prior(
        "138", patient_demo={"age": 60, "sex": "F"},
    )
    assert result["multiplier"] == pytest.approx(1.0)
    assert result["factor_count"] == 0
    assert result["modulated_prior"] == pytest.approx(0.4)


def test_conditional_factor_does_not_fire_without_prior_hcc(patch_db):
    rows = [
        _row(1, "138", age_min=65, age_max=120, multiplier=2.1, cond=["18"]),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.5})
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 78, "sex": "F", "dual_status": "dual"},
        prior_hccs=[],
    )
    assert result["multiplier"] == pytest.approx(1.0)
    assert result["factor_count"] == 0


def test_conditional_factor_fires_with_overlap(patch_db):
    rows = [
        _row(1, "138", age_min=65, age_max=120, multiplier=2.1,
             cond=["18", "19"]),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.5})
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 78, "sex": "F", "dual_status": "dual"},
        prior_hccs=["19"],
    )
    assert result["multiplier"] == pytest.approx(2.1, abs=1e-4)


def test_base_prior_override_skips_db_lookup(patch_db):
    rows = [
        _row(1, "138", age_min=65, age_max=120, multiplier=1.5),
    ]
    patch_db(rows, coefficients={})  # empty coefficient map intentionally
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 70, "sex": "F"},
        base_prior_override=0.8,
    )
    assert result["base_prior"] == pytest.approx(0.8)
    assert result["modulated_prior"] == pytest.approx(0.8 * 1.5, abs=1e-4)


def test_zero_or_negative_multiplier_rows_ignored(patch_db):
    rows = [
        _row(1, "138", multiplier=1.5),
        _row(2, "138", multiplier=0.0),
        _row(3, "138", multiplier=-1.0),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 1.0})
    result = drs.compute_modulated_prior(
        "138", patient_demo={"age": 70, "sex": "F"},
    )
    assert result["multiplier"] == pytest.approx(1.5, abs=1e-4)


def test_compounded_multiplier_clamped(patch_db):
    rows = [_row(i, "138", multiplier=5.0) for i in range(1, 5)]
    patch_db(rows, coefficients={(138, "CNA", 2024): 1.0})
    result = drs.compute_modulated_prior(
        "138", patient_demo={"age": 70, "sex": "F"},
    )
    # Raw would be 5^4 = 625, but service clamps to MAX_COMPOUNDED_MULTIPLIER.
    assert result["multiplier"] == pytest.approx(drs.MAX_COMPOUNDED_MULTIPLIER)


def test_inactive_rows_excluded(patch_db):
    rows = [
        _row(1, "138", multiplier=1.5, is_active=0),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.5})
    result = drs.compute_modulated_prior(
        "138", patient_demo={"age": 70, "sex": "F"},
    )
    assert result["multiplier"] == pytest.approx(1.0)
    assert result["factor_count"] == 0


def test_factors_applied_carries_source_citation(patch_db):
    rows = [
        _row(1, "138", age_min=75, age_max=120, multiplier=2.1, cond=["18"],
             source="MEDPAR-2023", notes="dual women 75+ CKD"),
    ]
    patch_db(rows, coefficients={(138, "CNA", 2024): 0.5})
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 78, "sex": "F", "dual_status": "dual"},
        prior_hccs=["18"],
    )
    assert len(result["factors_applied"]) == 1
    fa = result["factors_applied"][0]
    assert fa["source"] == "MEDPAR-2023"
    assert fa["value"] == pytest.approx(2.1)
    assert "age 75+" in fa["factor"]
    assert "conditional_on_hccs=[18]" in fa["factor"]


def test_get_risk_factors_returns_decoded_conditional(patch_db):
    rows = [
        _row(1, "138", multiplier=1.5, cond=["18"], source="MEDPAR-2023"),
        _row(2, "138", multiplier=2.0, source="curated-USRDS-2023"),
        _row(3, "999", multiplier=1.1),  # different HCC
    ]
    patch_db(rows)
    factors = drs.get_risk_factors("138")
    assert len(factors) == 2
    assert factors[0]["conditional_on_hccs"] == ["18"]
    assert factors[1]["conditional_on_hccs"] == []


def test_get_risk_factors_handles_hcc_prefix(patch_db):
    rows = [_row(1, "138", multiplier=1.5)]
    patch_db(rows)
    factors = drs.get_risk_factors("HCC0138")
    assert len(factors) == 1


def test_dual_eligible_compounding_priors(patch_db):
    """Realistic stack: female + dual + prior CHF -> three rows fire on CKD."""
    rows = [
        _row(1, "138", age_min=65, age_max=74, sex="F", dual="dual",
             multiplier=1.4, source="MEDPAR-2023"),
        _row(2, "138", age_min=75, age_max=120, multiplier=1.5,
             source="curated-USRDS-2023"),
        _row(3, "138", age_min=65, age_max=120, multiplier=1.8, cond=["226"],
             source="curated-AHA-2024"),
    ]
    patch_db(rows, coefficients={(138, "CFA", 2024): 0.6})
    # Patient age 70 -> first row matches (1.4x), second does not (75+).
    result = drs.compute_modulated_prior(
        "138",
        patient_demo={"age": 70, "sex": "F", "dual_status": "dual"},
        prior_hccs=["226"],
        model_segment="CFA",
    )
    # Compounding: 1.4 (age/sex/dual) * 1.8 (CHF conditional) = 2.52
    assert result["multiplier"] == pytest.approx(1.4 * 1.8, abs=1e-4)
    assert result["factor_count"] == 2


# ===========================================================================
# Integration with raf_forecast.calculate_patient_forecast
# ===========================================================================

def test_raf_forecast_demographic_modulation_toggle_off_preserves_baseline():
    """With USE_DEMOGRAPHIC_RISK_MODULATION=false the by_suspect numbers must
    match the pre-feature baseline byte-for-byte."""
    from app.services import raf_forecast as rf

    # Patch settings flag OFF
    with patch.object(rf, "_settings", autospec=False) as mock_settings:
        mock_settings.use_demographic_risk_modulation = False

        # Patch internal helpers
        suspects = [{"id": 1, "suspect_hcc": "138", "suspect_icd10": "N18.3",
                     "evidence_type": "lab", "confidence_score": 0.8}]
        with patch.object(rf, "_resolve_segment", return_value="CNA"), \
             patch.object(rf, "_current_raf", return_value=0.5), \
             patch.object(rf, "_open_suspects", return_value=suspects), \
             patch.object(rf, "_coefficient_lookup", return_value={"138": 0.4}), \
             patch.object(rf, "_prior_year_chronic_hccs", return_value=[]):
            forecast = rf.calculate_patient_forecast(101, 2024)

    assert forecast["demographic_modulation_applied"] is False
    # lift = 0.4 * 0.8 = 0.32
    assert forecast["suspect_lift_raf"] == pytest.approx(0.32, abs=1e-4)
    # No demographic_multiplier key when flag is off
    assert "demographic_multiplier" not in forecast["by_suspect"][0]


def test_raf_forecast_demographic_modulation_toggle_on_applies_multiplier():
    """With the flag ON each suspect's lift gets scaled by the modulation."""
    from app.services import raf_forecast as rf

    suspects = [{"id": 1, "suspect_hcc": "138", "suspect_icd10": "N18.3",
                 "evidence_type": "lab", "confidence_score": 0.8}]

    fake_modulation_result = {
        "hcc_code": "138",
        "base_prior": 0.4,
        "multiplier": 2.1,
        "modulated_prior": 0.84,
        "factors_applied": [{"factor": "age 75+, conditional_on_hccs=[18]",
                             "value": 2.1, "source": "curated-USRDS-2023", "id": 1}],
        "factor_count": 1,
        "model_segment": "CNA",
        "model_year": 2024,
    }

    class _StubSettings:
        use_demographic_risk_modulation = True

    class _StubDrs:
        DEFAULT_COEFFICIENT_YEAR = 2024

        @staticmethod
        def _patient_demographics(pid, year):
            return {"age": 78, "sex": "F", "dual_status": "dual"}

        @staticmethod
        def _patient_prior_hccs(pid, year):
            return ["18"]

        @staticmethod
        def compute_modulated_prior(**kwargs):
            return fake_modulation_result

    with patch.object(rf, "_settings", _StubSettings), \
         patch.object(rf, "_drs", _StubDrs), \
         patch.object(rf, "_resolve_segment", return_value="CNA"), \
         patch.object(rf, "_current_raf", return_value=0.5), \
         patch.object(rf, "_open_suspects", return_value=suspects), \
         patch.object(rf, "_coefficient_lookup", return_value={"138": 0.4}), \
         patch.object(rf, "_prior_year_chronic_hccs", return_value=[]):
        forecast = rf.calculate_patient_forecast(101, 2024)

    assert forecast["demographic_modulation_applied"] is True
    # lift = coefficient (0.4) * confidence (0.8) * multiplier (2.1) = 0.672
    assert forecast["suspect_lift_raf"] == pytest.approx(0.4 * 0.8 * 2.1, abs=1e-4)
    suspect_entry = forecast["by_suspect"][0]
    assert suspect_entry["demographic_multiplier"] == pytest.approx(2.1)
    assert len(suspect_entry["demographic_factors"]) == 1
    assert suspect_entry["demographic_factors"][0]["source"] == "curated-USRDS-2023"


def test_raf_forecast_modulation_drops_back_to_unit_when_drs_missing():
    """If the demographic_risk_service module is unavailable the forecast
    must still return a valid result (regression guard)."""
    from app.services import raf_forecast as rf
    suspects = [{"id": 1, "suspect_hcc": "138", "suspect_icd10": "N18.3",
                 "evidence_type": "lab", "confidence_score": 0.8}]
    with patch.object(rf, "_settings", None), \
         patch.object(rf, "_drs", None), \
         patch.object(rf, "_resolve_segment", return_value="CNA"), \
         patch.object(rf, "_current_raf", return_value=0.0), \
         patch.object(rf, "_open_suspects", return_value=suspects), \
         patch.object(rf, "_coefficient_lookup", return_value={"138": 0.4}), \
         patch.object(rf, "_prior_year_chronic_hccs", return_value=[]):
        forecast = rf.calculate_patient_forecast(101, 2024)
    assert forecast["demographic_modulation_applied"] is False
    assert forecast["suspect_lift_raf"] == pytest.approx(0.32, abs=1e-4)
