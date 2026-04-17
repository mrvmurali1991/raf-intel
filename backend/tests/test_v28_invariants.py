"""Property-based invariants for the V28 RAF engine.

Parametrized/example-driven tests check specific cases. These tests use
Hypothesis to assert *structural* properties that must hold for *every*
beneficiary shape the engine can see.  If the engine ever produces an output
that violates one of these properties, Hypothesis will shrink to the
minimal counter-example and print it.

Invariants covered
------------------
1. Monotone-in-HCCs: adding a recognised HCC never *decreases* risk score.
2. Dual-status monotonicity: for the same HCC, CFA ≥ CNA and CFD ≥ CND
   (full-dual pays ≥ non-dual for the same demographics) — a CMS rate
   rule, not a coincidence.
3. Hierarchy dominance: when a parent + descendant are both coded, only
   the parent's coefficient should remain after hierarchy — score must
   equal the score of the parent alone.
4. Demographic-only for new enrollees: NE scores must equal their
   demographic_score (no HCC contribution).
5. Non-negativity: no risk component (risk_score, demographic, hcc) is
   ever negative.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

pytest.importorskip("hccinfhir")

from hccinfhir import HCCInFHIR, Demographics  # noqa: E402

_proc = HCCInFHIR(model_name="CMS-HCC Model V28")


# A small set of ICDs that are known to map to distinct HCCs in V28.  Using
# a curated pool keeps Hypothesis fast and avoids over-sampling non-HCC codes.
_HCC_POOL: list[str] = [
    "E119",   # DM → HCC 38
    "I5022",  # acute-on-chronic HF → HCC 226
    "N184",   # CKD stage 4 → HCC 329
    "J441",   # COPD → HCC 111
    "B20",    # HIV → HCC 1
    "G20",    # Parkinson → HCC 78
    "F0281",  # Dementia moderate → HCC 180
    "M8666",  # Bone/joint infection → HCC 85
    "A419",   # Sepsis → HCC 383
    "E10329", # Type1 DM w/ retinopathy → HCC 35
]

_AGE_STRATEGY = st.integers(min_value=65, max_value=94)
_SEX_STRATEGY = st.sampled_from(["M", "F"])
_DUAL_STRATEGY = st.sampled_from(["NA", "02", "03"])  # non-dual / full-dual / partial-dual
_ICD_SUBSET = st.lists(
    st.sampled_from(_HCC_POOL), min_size=0, max_size=5, unique=True
)


def _demo(age: int, sex: str, dual: str, new_enrollee: bool = False) -> Demographics:
    return Demographics(age=age, sex=sex, dual_elgbl_cd=dual, orec="0", new_enrollee=new_enrollee)


def _score(age: int, sex: str, dual: str, codes: list[str]) -> float:
    r = _proc.calculate_from_diagnosis(
        diagnosis_codes=codes, demographics=_demo(age, sex, dual)
    )
    return float(r.risk_score)


# ---------------------------------------------------------------------------
# Invariant 1: non-negativity
# ---------------------------------------------------------------------------
@given(age=_AGE_STRATEGY, sex=_SEX_STRATEGY, dual=_DUAL_STRATEGY, codes=_ICD_SUBSET)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_no_score_component_is_negative(
    age: int, sex: str, dual: str, codes: list[str]
) -> None:
    r = _proc.calculate_from_diagnosis(
        diagnosis_codes=codes, demographics=_demo(age, sex, dual)
    )
    assert r.risk_score >= 0.0, f"risk_score={r.risk_score}"
    assert r.risk_score_demographics >= 0.0, f"demo={r.risk_score_demographics}"
    assert r.risk_score_hcc >= 0.0, f"hcc={r.risk_score_hcc}"


# ---------------------------------------------------------------------------
# Invariant 2: monotone in HCCs — adding a recognised code never decreases score
# ---------------------------------------------------------------------------
@given(
    age=_AGE_STRATEGY,
    sex=_SEX_STRATEGY,
    dual=_DUAL_STRATEGY,
    base=st.lists(st.sampled_from(_HCC_POOL), min_size=0, max_size=3, unique=True),
    add=st.sampled_from(_HCC_POOL),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_adding_hcc_never_decreases_score(
    age: int, sex: str, dual: str, base: list[str], add: str
) -> None:
    before = _score(age, sex, dual, base)
    after = _score(age, sex, dual, list(set(base + [add])))
    # Tolerance for rounding within hccinfhir normalisation pipeline.
    assert after + 1e-6 >= before, (
        f"Adding {add} decreased score: before={before}, after={after}, "
        f"base={base}"
    )


# ---------------------------------------------------------------------------
# Invariant 3: dual-status monotonicity at the same demographic
# For the same HCC and same demographics, CFA ≥ CNA and CFD ≥ CND.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", _HCC_POOL)
@pytest.mark.parametrize(
    "age,sex",
    [(72, "F"), (68, "M"), (80, "F"), (55, "M")],
)
def test_full_dual_score_gte_non_dual_same_hcc(
    code: str, age: int, sex: str
) -> None:
    non_dual = _score(age, sex, "NA", [code])
    full_dual = _score(age, sex, "02", [code])
    assert full_dual + 1e-6 >= non_dual, (
        f"Full-dual < non-dual for {code} at ({age},{sex}): "
        f"CFA/CFD={full_dual}, CNA/CND={non_dual}"
    )


# ---------------------------------------------------------------------------
# Invariant 4: new-enrollee score equals demographic_score (no HCC)
# ---------------------------------------------------------------------------
@given(age=_AGE_STRATEGY, sex=_SEX_STRATEGY, dual=_DUAL_STRATEGY)
@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_new_enrollee_score_is_demographic_only(
    age: int, sex: str, dual: str
) -> None:
    r = _proc.calculate_from_diagnosis(
        diagnosis_codes=[], demographics=_demo(age, sex, dual, new_enrollee=True)
    )
    assert r.risk_score == pytest.approx(r.risk_score_demographics, abs=1e-6)
    assert r.risk_score_hcc == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Invariant 5: hierarchy dominance — adding a descendant (when parent is
# already present) does not duplicate-pay.  Per CMS hierarchy, HCC 37 trumps
# HCC 38; coding both E1022 (→ HCC 37) and E119 (→ HCC 38) must score as
# HCC 37 alone, not HCC 37 + HCC 38.
# ---------------------------------------------------------------------------
def test_hierarchy_parent_dominates_child_v28_diabetes() -> None:
    demo = _demo(72, "F", "NA")
    parent_only = _proc.calculate_from_diagnosis(
        diagnosis_codes=["E1022"], demographics=demo
    )
    parent_plus_child = _proc.calculate_from_diagnosis(
        diagnosis_codes=["E1022", "E119"], demographics=demo
    )
    # HCC 37 and HCC 38 share the same constrained coefficient (0.166) so
    # the per-HCC list will shrink from 2 entries to 1, and the score is
    # identical — both payments would otherwise double-count the same
    # underlying condition.
    parent_only_hccs = {h.hcc for h in (parent_only.hcc_details or [])}
    combined_hccs = {h.hcc for h in (parent_plus_child.hcc_details or [])}
    assert combined_hccs == parent_only_hccs, (
        f"Hierarchy did not collapse diabetes family: parent_only={parent_only_hccs}, "
        f"parent+child={combined_hccs}"
    )
    assert parent_plus_child.risk_score_hcc == pytest.approx(
        parent_only.risk_score_hcc, abs=1e-6
    )


# ---------------------------------------------------------------------------
# Invariant 6: empty ICD list → demographic score only
# ---------------------------------------------------------------------------
@given(age=_AGE_STRATEGY, sex=_SEX_STRATEGY, dual=_DUAL_STRATEGY)
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_no_icd_no_disease_score(
    age: int, sex: str, dual: str
) -> None:
    r = _proc.calculate_from_diagnosis(
        diagnosis_codes=[], demographics=_demo(age, sex, dual)
    )
    assert r.risk_score_hcc == pytest.approx(0.0, abs=1e-6)
    assert r.risk_score == pytest.approx(r.risk_score_demographics, abs=1e-6)
