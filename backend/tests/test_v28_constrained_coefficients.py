"""V28 constrained-coefficient invariants.

The CMS-HCC V28 model deliberately flattens (“constrains”) the coefficients of
certain disease families so that every HCC in the family carries the same
payment weight regardless of complication severity. Two families are known to
be constrained in the PY2026 specification:

* Diabetes (excluding pancreas transplant status HCC 35): HCCs 36, 37, 38
* CHF (specific sub-group): HCCs 224, 225, 226

This test locks those invariants in place so we catch silent drift if
``hccinfhir`` is upgraded, if a future patch overrides coefficients, or if a
downstream config accidentally reintroduces V24-style differential weights.

Sources:
- CMS CY2026 Final Rate Announcement, Attachment VI (V28 model coefficients).
- AAPC Knowledge Center, "CMS-HCC Model V28" (2024), diabetes-constrained note.
- CodingIntel, "HCC Coding: V24 to V28", CHF-constrained group discussion.
- hccinfhir==0.1.5 defaults.coefficients_default, PY2026 snapshot.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skipif(
    pytest.importorskip("hccinfhir", reason="hccinfhir not installed") is None,
    reason="hccinfhir not installed",
)

from hccinfhir.defaults import coefficients_default  # noqa: E402

V28 = "CMS-HCC Model V28"

# Segments CMS publishes for non-ESRD community/institutional scoring.
V28_SEGMENTS = ("cna", "cnd", "cfa", "cfd", "cpa", "cpd", "ins")

# (HCC number, family label) groups that MUST share a single coefficient
# within each segment.
CONSTRAINED_GROUPS: dict[str, list[int]] = {
    "diabetes": [36, 37, 38],
    "chf": [224, 225, 226],
}


def _coef(segment: str, hcc: int) -> float | None:
    return coefficients_default.get((f"{segment}_hcc{hcc}", V28))


@pytest.mark.parametrize("segment", V28_SEGMENTS)
@pytest.mark.parametrize("family,hcc_codes", list(CONSTRAINED_GROUPS.items()))
def test_v28_constrained_family_shares_single_coefficient(
    segment: str, family: str, hcc_codes: list[int]
) -> None:
    """All HCCs in a constrained family share one coefficient per segment."""
    values = {hcc: _coef(segment, hcc) for hcc in hcc_codes}
    present = {hcc: v for hcc, v in values.items() if v is not None}
    if not present:
        pytest.skip(
            f"V28 {family} coefficients not present in hccinfhir for {segment}"
        )
    unique = set(present.values())
    assert len(unique) == 1, (
        f"V28 {family} constraint violated in segment {segment}: "
        f"expected identical coefficients across HCCs {hcc_codes}, got {values}"
    )


def test_v28_diabetes_cna_coefficient_matches_cms_2026() -> None:
    """Pinned CMS PY2026 diabetes CNA coefficient.

    Per CMS CY2026 Final Rate Announcement the community non-dual aged
    coefficient for the constrained diabetes group (HCC 36/37/38) is 0.166.
    If hccinfhir drifts from this value, payment RAFs silently shift; this
    assertion forces the drift into daylight.
    """
    value = _coef("cna", 36)
    assert value is not None, "V28 CNA HCC36 coefficient missing from hccinfhir"
    assert value == pytest.approx(0.166, abs=1e-4), (
        f"V28 diabetes CNA coefficient drifted: expected 0.166, got {value}"
    )


def test_v28_pancreas_transplant_hcc35_is_differentiated() -> None:
    """HCC 35 (pancreas transplant status) must NOT be constrained.

    V28 keeps HCC 35 at a materially higher coefficient than the
    constrained diabetes group. If HCC 35 ever collapses to the same value
    as HCC 36/37/38, the pancreas-transplant differential is broken.
    """
    hcc35 = _coef("cna", 35)
    hcc36 = _coef("cna", 36)
    assert hcc35 is not None and hcc36 is not None
    assert hcc35 > hcc36 * 3, (
        f"V28 HCC 35 (pancreas transplant) must dominate HCC 36: "
        f"got hcc35={hcc35}, hcc36={hcc36}"
    )


def test_v28_chf_constrained_group_present() -> None:
    """CHF constrained subgroup (HCC 224/225/226) must be present in V28.

    We skip earlier because the constrained-family test is parameterized,
    but this spot-check ensures at least the community-non-dual-aged
    coefficients exist and are non-zero.
    """
    values = [_coef("cna", hcc) for hcc in (224, 225, 226)]
    assert all(v is not None and v > 0 for v in values), (
        f"V28 CHF constrained HCCs must exist with positive coefficients; "
        f"got {values}"
    )
