"""CMS-cited factor tests — per-value, source-anchored audit.

Each test ties a specific numeric value in the coefficients manifest to the
CMS Final Rate Announcement row that publishes it. Unlike the parity tests
(which just check manifest ⇔ code agreement), these tests check that the
manifest values themselves match CMS-published truth.

If CMS changes a factor for a new payment year, the failing test tells you
*which* citation needs reconfirmation, not just "something drifted".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MANIFEST = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "raf"
        / "coefficients_manifest.json"
    ).read_text()
)


class TestNormalizationFactors:
    """CMS normalization factors by model × payment year.

    Source: CY2026 Final Rate Announcement, "Normalization Factors" section.
    """

    def test_v28_py2026_equals_published(self) -> None:
        assert MANIFEST["normalization_factors"]["v28"]["2026"] == 1.067, (
            "CMS CY2026 Final Rate Announcement publishes V28 normalization "
            "factor = 1.067 (for the 2024 CMS-HCC model)."
        )

    def test_v24_py2026_equals_published(self) -> None:
        assert MANIFEST["normalization_factors"]["v24"]["2026"] == 1.153, (
            "CMS CY2026 Final Rate Announcement retains V24 normalization "
            "factor = 1.153 (for the 2020 CMS-HCC model)."
        )

    def test_v22_legacy_py2026_equals_published(self) -> None:
        assert MANIFEST["normalization_factors"]["v22_legacy_2017"]["2026"] == 1.187, (
            "CMS CY2026 Final Rate Announcement retains legacy 2017 CMS-HCC "
            "model normalization factor = 1.187 (used for PACE blend leg)."
        )

    def test_every_model_cites_its_source(self) -> None:
        for model, data in MANIFEST["normalization_factors"].items():
            assert "source" in data, (
                f"normalization_factors[{model}] missing 'source' citation"
            )
            assert "CMS" in data["source"], (
                f"normalization_factors[{model}].source must reference CMS"
            )


class TestMACIFactors:
    """MACI (Minimum Allowable Coding Intensity) adjustment.

    Source: Social Security Act §1853(a)(1)(C)(ii)(II) — statutory 5.9%
    minimum. CMS has maintained the floor every year since PY2018.
    """

    def test_v28_maci_py2026_is_statutory_minimum(self) -> None:
        assert MANIFEST["maci_factors"]["v28"]["2026"] == 0.059, (
            "MACI for CY2026 must be 5.9% (statutory floor, CMS-confirmed)."
        )

    def test_v24_maci_py2026_is_statutory_minimum(self) -> None:
        assert MANIFEST["maci_factors"]["v24"]["2026"] == 0.059

    def test_maci_cites_statutory_authority(self) -> None:
        source = MANIFEST["maci_factors"]["v28"]["source"]
        assert "1853" in source or "Social Security" in source, (
            f"V28 MACI must cite statutory authority (SSA §1853); got {source!r}"
        )


class TestBlendWeights:
    """CMS transition blending between V24 and V28 (non-PACE)."""

    def test_py2024_is_67_33(self) -> None:
        w = MANIFEST["blend_weights"]["non_pace"]["2024"]
        assert w["v24"] == 0.67 and w["v28"] == 0.33, (
            "CMS CY2024 Final Rate Announcement: 67% V24 + 33% V28."
        )

    def test_py2025_is_33_67(self) -> None:
        w = MANIFEST["blend_weights"]["non_pace"]["2025"]
        assert w["v24"] == 0.33 and w["v28"] == 0.67, (
            "CMS CY2025 Final Rate Announcement: 33% V24 + 67% V28."
        )

    def test_py2026_is_pure_v28(self) -> None:
        w = MANIFEST["blend_weights"]["non_pace"]["2026"]
        assert w["v24"] == 0.0 and w["v28"] == 1.0, (
            "CMS CY2026 Final Rate Announcement: 100% V28 (no blend)."
        )

    def test_weights_sum_to_one(self) -> None:
        for year, w in MANIFEST["blend_weights"]["non_pace"].items():
            if not year.isdigit():
                continue
            total = w["v24"] + w["v28"]
            assert total == pytest.approx(1.0, abs=1e-9), (
                f"non_pace {year}: v24+v28={total}, must sum to 1.0"
            )


class TestPACEBlendWeights:
    """PACE has a separate (slower) V28 transition schedule."""

    def test_py2026_is_90_legacy_10_v28(self) -> None:
        w = MANIFEST["blend_weights"]["pace"]["2026"]
        assert w["legacy_2017"] == 0.90 and w["v28"] == 0.10, (
            "CMS CY2026 Final Rate Announcement: PACE 90% legacy + 10% V28."
        )

    def test_pre_2026_is_pure_legacy(self) -> None:
        for year in ("2024", "2025"):
            w = MANIFEST["blend_weights"]["pace"][year]
            assert w["legacy_2017"] == 1.0 and w["v28"] == 0.0, (
                f"PACE {year}: must be 100% legacy 2017."
            )

    def test_pace_weights_sum_to_one(self) -> None:
        for year, w in MANIFEST["blend_weights"]["pace"].items():
            if not year.isdigit():
                continue
            total = w["legacy_2017"] + w["v28"]
            assert total == pytest.approx(1.0, abs=1e-9), (
                f"pace {year}: legacy+v28={total}, must sum to 1.0"
            )


class TestStructuralFacts:
    """CMS-published V28 structural counts (HCCs, disease families, ICDs)."""

    def test_v28_has_115_hccs(self) -> None:
        assert MANIFEST["v28_structural_facts"]["hcc_category_count"] == 115, (
            "CMS CY2026 defines V28 with 115 HCC categories (down from V24's 86)."
        )

    def test_v28_has_26_disease_families(self) -> None:
        assert MANIFEST["v28_structural_facts"]["disease_family_count"] == 26

    def test_v28_icd_count_is_in_documented_range(self) -> None:
        count = MANIFEST["v28_structural_facts"]["valid_icd10_count"]
        # CMS publishes ~7,770–7,903 (the exact number drifts slightly with
        # ICD-10-CM revisions each October).
        assert 7500 <= count <= 8000, (
            f"V28 ICD count {count} outside documented 7.5k–8k range"
        )
