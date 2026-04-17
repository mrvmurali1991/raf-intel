"""V28 interaction-term enumeration & lock.

V28 ships 25 interaction / special-population coefficients that fire
on specific disease-crosses (HF × chronic lung, HF × HCC 238), on
origin-of-entry status (originally-disabled-aged premium), and on
institutional × disabled × disease-family combinations.

These are high-dollar coefficients — a single wrong row can shift
RAF by 0.1-0.5 on an institutional disabled beneficiary. This
harness locks every one of them byte-for-byte.

Grouped by family so a failure points at which CMS table drifted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir")

from hccinfhir.defaults import coefficients_default  # noqa: E402

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "v28_interaction_coefficients.json"
)


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(_FIXTURE.read_text())


def _current_v28() -> dict[str, float]:
    return {
        k[0]: round(float(v), 6)
        for k, v in coefficients_default.items()
        if k[1] == "CMS-HCC Model V28"
    }


class TestInteractionCount:
    def test_interaction_count_matches_snapshot(self, bundle: dict) -> None:
        current = _current_v28()
        sensed = [
            k for k in current
            if k.lower().count("hcc") >= 2
            or any(tok in k.lower() for tok in (
                "_hf_chr_lung_", "_hf_hcc238_", "originallydisabled",
                "ins_disabled_", "ltimcaid",
            ))
        ]
        assert len(sensed) == bundle["interaction_count"], (
            f"V28 interaction count drifted: snapshot="
            f"{bundle['interaction_count']}, live={len(sensed)}"
        )


class TestHFChronicLungFamily:
    """HF × chronic lung interaction — must be present in all 7 segments."""

    @pytest.mark.parametrize("segment", ["cfa", "cfd", "cna", "cnd", "cpa", "cpd", "ins"])
    def test_each_segment_has_value(self, bundle: dict, segment: str) -> None:
        key = f"{segment}_hf_chr_lung_v28"
        current = _current_v28()
        snap = bundle["interaction_groups"]["hf_chr_lung_v28"]["coefficients"]
        assert key in snap, f"snapshot missing {key}"
        assert current.get(key) == snap[key], (
            f"{key}: snapshot={snap[key]}, live={current.get(key)}"
        )


class TestHFHCC238Family:
    """V28 HF × HCC 238 is defined on the 6 non-institutional segments only."""

    @pytest.mark.parametrize("segment", ["cfa", "cfd", "cna", "cnd", "cpa", "cpd"])
    def test_each_segment_has_value(self, bundle: dict, segment: str) -> None:
        key = f"{segment}_hf_hcc238_v28"
        current = _current_v28()
        snap = bundle["interaction_groups"]["hf_hcc238_v28"]["coefficients"]
        assert key in snap, f"snapshot missing {key}"
        assert current.get(key) == snap[key]


class TestOriginallyDisabledFamily:
    """OREC=1 premium must carry both male & female for each segment."""

    @pytest.mark.parametrize(
        "segment, sex",
        [
            ("cfa", "female"), ("cfa", "male"),
            ("cna", "female"), ("cna", "male"),
            ("cpa", "female"), ("cpa", "male"),
        ],
    )
    def test_each_segment_sex_pair_locked(
        self, bundle: dict, segment: str, sex: str
    ) -> None:
        key = f"{segment}_originallydisabled_{sex}"
        current = _current_v28()
        snap = bundle["interaction_groups"]["originally_disabled"]["coefficients"]
        assert key in snap, f"snapshot missing {key}"
        assert current.get(key) == snap[key]


class TestInstitutionalDisabledFamily:
    @pytest.mark.parametrize(
        "family", ["cancer", "chr_lung", "hf", "neuro", "ulcer"]
    )
    def test_each_family_locked(self, bundle: dict, family: str) -> None:
        key = f"ins_disabled_{family}_v28"
        current = _current_v28()
        snap = bundle["interaction_groups"]["institutional_disabled"]["coefficients"]
        assert key in snap, f"snapshot missing {key}"
        assert current.get(key) == snap[key]


class TestInstitutionalOtherFamily:
    def test_hf_chr_lung_and_ltimcaid_locked(self, bundle: dict) -> None:
        current = _current_v28()
        snap = bundle["interaction_groups"]["institutional_other"]["coefficients"]
        for key in ("ins_hf_chr_lung_v28", "ins_ltimcaid"):
            assert key in snap, f"snapshot missing {key}"
            assert current.get(key) == snap[key]


class TestExhaustiveLock:
    """Every interaction value in the snapshot must match live exactly."""

    def test_no_interaction_value_has_drifted(self, bundle: dict) -> None:
        current = _current_v28()
        drifted = [
            (k, v, current.get(k))
            for k, v in bundle["all_interactions"].items()
            if current.get(k) != v
        ]
        assert not drifted, (
            f"{len(drifted)} V28 interaction coefficients drifted. "
            f"First 10: {drifted[:10]}"
        )


class TestStructuralSanity:
    """All interaction coefficients must be positive (they are additive premiums)."""

    def test_every_interaction_is_non_negative(self, bundle: dict) -> None:
        negatives = {
            k: v for k, v in bundle["all_interactions"].items() if v < 0
        }
        assert not negatives, (
            f"V28 interaction coefficients should be non-negative premiums; "
            f"found negatives: {negatives}"
        )

    def test_institutional_disabled_dominates_standard(self, bundle: dict) -> None:
        """INS × disabled × HF should exceed CNA × HF × chronic lung —
        institutional disabled is the highest-acuity track."""
        c = bundle["all_interactions"]
        ins_disabled_hf = c["ins_disabled_hf_v28"]
        cna_hf_chr_lung = c["cna_hf_chr_lung_v28"]
        assert ins_disabled_hf > cna_hf_chr_lung, (
            f"Institutional disabled HF ({ins_disabled_hf}) must exceed "
            f"CNA HF×chronic-lung ({cna_hf_chr_lung}) — acuity ordering"
        )
