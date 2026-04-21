"""Parity between the version-locked coefficients manifest and the live code.

Any drift between :file:`app/services/raf/coefficients_manifest.json` and the
Python tables in :mod:`app.services.raf.blend_weights` is a hard failure.

The manifest is the single source of truth for CMS-published factors; the
Python tables are performance-oriented hot paths. Tests here guarantee they
never diverge silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services.raf.blend_weights import (
    _BLEND_WEIGHTS,
    _MACI_FACTORS_V24,
    _MACI_FACTORS_V28,
    _NORM_FACTORS_V22,
    _NORM_FACTORS_V24,
    _NORM_FACTORS_V28,
    _PACE_BLEND_WEIGHTS,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "raf"
    / "coefficients_manifest.json"
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"manifest missing: {MANIFEST_PATH}"
    return json.loads(MANIFEST_PATH.read_text())


def _year_map(obj: dict, weight_key: str) -> dict[int, float]:
    """Extract {year: weight} from a blend-weights section."""
    out: dict[int, float] = {}
    for k, v in obj.items():
        if not k.isdigit():
            continue
        out[int(k)] = v[weight_key]
    return out


def test_non_pace_blend_weights_match_manifest(manifest: dict) -> None:
    v24 = _year_map(manifest["blend_weights"]["non_pace"], "v24")
    v28 = _year_map(manifest["blend_weights"]["non_pace"], "v28")
    for year in v24:
        assert _BLEND_WEIGHTS[year] == pytest.approx((v24[year], v28[year])), (
            f"Non-PACE blend drift for PY{year}: "
            f"code={_BLEND_WEIGHTS[year]}, manifest=({v24[year]}, {v28[year]})"
        )


def test_pace_blend_weights_match_manifest(manifest: dict) -> None:
    legacy = _year_map(manifest["blend_weights"]["pace"], "legacy_2017")
    v28 = _year_map(manifest["blend_weights"]["pace"], "v28")
    for year in legacy:
        assert _PACE_BLEND_WEIGHTS[year] == pytest.approx(
            (legacy[year], v28[year])
        ), (
            f"PACE blend drift for PY{year}: "
            f"code={_PACE_BLEND_WEIGHTS[year]}, "
            f"manifest=({legacy[year]}, {v28[year]})"
        )


@pytest.mark.parametrize(
    "table_key,code_table",
    [
        ("v28", _NORM_FACTORS_V28),
        ("v24", _NORM_FACTORS_V24),
        ("v22_legacy_2017", _NORM_FACTORS_V22),
    ],
)
def test_normalization_factors_match_manifest(
    manifest: dict, table_key: str, code_table: dict[int, float]
) -> None:
    section = manifest["normalization_factors"][table_key]
    for k, expected in section.items():
        if not k.isdigit():
            continue
        year = int(k)
        assert code_table[year] == pytest.approx(expected), (
            f"Normalization drift ({table_key}, PY{year}): "
            f"code={code_table[year]}, manifest={expected}"
        )


@pytest.mark.parametrize(
    "table_key,code_table",
    [("v28", _MACI_FACTORS_V28), ("v24", _MACI_FACTORS_V24)],
)
def test_maci_factors_match_manifest(
    manifest: dict, table_key: str, code_table: dict[int, float]
) -> None:
    section = manifest["maci_factors"][table_key]
    for k, expected in section.items():
        if not k.isdigit():
            continue
        year = int(k)
        assert code_table[year] == pytest.approx(expected), (
            f"MACI drift ({table_key}, PY{year}): "
            f"code={code_table[year]}, manifest={expected}"
        )


def test_py2026_is_pure_v28_non_pace(manifest: dict) -> None:
    """PY2026 is the terminal year of the V24→V28 transition for non-PACE MA."""
    assert _BLEND_WEIGHTS[2026] == (0.0, 1.0)
    non_pace_2026 = manifest["blend_weights"]["non_pace"]["2026"]
    assert non_pace_2026["v24"] == 0.0
    assert non_pace_2026["v28"] == 1.0


def test_py2026_pace_is_90_10_blend(manifest: dict) -> None:
    """PACE CY2026 uses 90% legacy 2017 + 10% V28 per CMS CY2026 Rate Announcement."""
    assert _PACE_BLEND_WEIGHTS[2026] == pytest.approx((0.90, 0.10))
    pace_2026 = manifest["blend_weights"]["pace"]["2026"]
    assert pace_2026["legacy_2017"] == pytest.approx(0.90)
    assert pace_2026["v28"] == pytest.approx(0.10)


def test_manifest_structural_facts_match_v28_spec(manifest: dict) -> None:
    """V28 structural facts locked to the CMS CY2026 Final Rate Announcement."""
    facts = manifest["v28_structural_facts"]
    assert facts["hcc_category_count"] == 115
    assert facts["disease_family_count"] == 26
    assert facts["valid_icd10_count"] == 7770
