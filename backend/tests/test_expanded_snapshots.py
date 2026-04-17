"""Snapshot audits for ICD→HCC mapping, V22 legacy, and ESRD V24 coefficients.

Purpose
-------
Iteration 7 locked V28 coefficients. This iteration closes the remaining
coefficient-provider trust gaps:

- Gap #3: ICD→HCC mapping table (7,903 codes for V28). Any change to
  which ICDs map to which HCCs is a billing-impacting event that must be
  reviewed against CMS's Final Rate Announcement CY2026 dx-to-cc file.
- Gap #4: V22 legacy coefficients (930 values). PACE PY2026 is 90% V22 +
  10% V28 — we must lock V22 or PACE payments are unverifiable.
- Gap #5: ESRD V24 coefficients (902 values). ESRD beneficiaries run a
  dedicated model with DI_/GC_ prefixes — separate from standard V24.

Each fixture carries its own hccinfhir version pin; drift in any of the
three tables fails fast in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir", reason="hccinfhir not installed")

from hccinfhir.defaults import coefficients_default, dx_to_cc_default  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# V28 ICD → HCC mapping
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def v28_mapping_fixture() -> dict:
    path = _FIXTURES / "v28_icd_mapping_snapshot.json"
    assert path.exists(), f"missing: {path}"
    return json.loads(path.read_text())


def _current_v28_mapping() -> dict[str, list[str]]:
    return {
        icd: sorted(hccs)
        for (icd, model), hccs in dx_to_cc_default.items()
        if model == "CMS-HCC Model V28"
    }


def test_v28_icd_count_matches_snapshot(v28_mapping_fixture: dict) -> None:
    current = _current_v28_mapping()
    assert len(current) == v28_mapping_fixture["icd_count"], (
        f"V28 ICD count drifted: snapshot={v28_mapping_fixture['icd_count']}, "
        f"current={len(current)}"
    )


def test_v28_icd_mapping_has_not_drifted(v28_mapping_fixture: dict) -> None:
    current = _current_v28_mapping()
    expected = v28_mapping_fixture["mapping"]
    drifted: list[tuple[str, list[str], list[str]]] = []
    missing: list[str] = []
    for icd, exp_hccs in expected.items():
        if icd not in current:
            missing.append(icd)
            continue
        if current[icd] != exp_hccs:
            drifted.append((icd, exp_hccs, current[icd]))
    assert not missing, (
        f"{len(missing)} ICDs removed since snapshot: {missing[:10]}..."
    )
    assert not drifted, (
        f"{len(drifted)} ICDs re-mapped since snapshot: first 10 diffs = "
        f"{drifted[:10]}"
    )


def test_v28_critical_icds_map_correctly(v28_mapping_fixture: dict) -> None:
    """Spot-check high-value diagnoses used in clinical tests."""
    mapping = v28_mapping_fixture["mapping"]
    # E11.9 (DM without complications) → HCC 38
    assert "E119" in mapping and "38" in mapping["E119"], (
        f"E119 should map to HCC 38; got {mapping.get('E119')}"
    )
    # I50.22 (acute-on-chronic HF) → HCC 226
    assert "I5022" in mapping and "226" in mapping["I5022"], (
        f"I5022 should map to HCC 226; got {mapping.get('I5022')}"
    )
    # N18.3 (CKD stage 3) → HCC 329
    if "N183" in mapping:
        assert "329" in mapping["N183"], (
            f"N183 should map to HCC 329; got {mapping.get('N183')}"
        )


# ---------------------------------------------------------------------------
# V22 legacy (PACE)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def v22_fixture() -> dict:
    path = _FIXTURES / "v22_coefficient_snapshot.json"
    assert path.exists(), f"missing: {path}"
    return json.loads(path.read_text())


def _current_v22_coefs() -> dict[str, float]:
    return {
        k[0]: round(float(v), 6)
        for k, v in coefficients_default.items()
        if k[1] == "CMS-HCC Model V22"
    }


def test_v22_count_matches_snapshot(v22_fixture: dict) -> None:
    current = _current_v22_coefs()
    assert len(current) == v22_fixture["coefficient_count"]


def test_v22_coefficients_have_not_drifted(v22_fixture: dict) -> None:
    current = _current_v22_coefs()
    expected = v22_fixture["coefficients"]
    drifted = [
        (k, v, current.get(k))
        for k, v in expected.items()
        if current.get(k) != v
    ]
    assert not drifted, (
        f"{len(drifted)} V22 coefficients drifted. First 10: {drifted[:10]}"
    )


# ---------------------------------------------------------------------------
# ESRD V24
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def esrd_v24_fixture() -> dict:
    path = _FIXTURES / "esrd_v24_coefficient_snapshot.json"
    assert path.exists(), f"missing: {path}"
    return json.loads(path.read_text())


def _current_esrd_v24_coefs() -> dict[str, float]:
    return {
        k[0]: round(float(v), 6)
        for k, v in coefficients_default.items()
        if k[1] == "CMS-HCC ESRD Model V24"
    }


def test_esrd_v24_count_matches_snapshot(esrd_v24_fixture: dict) -> None:
    current = _current_esrd_v24_coefs()
    assert len(current) == esrd_v24_fixture["coefficient_count"]


def test_esrd_v24_coefficients_have_not_drifted(esrd_v24_fixture: dict) -> None:
    current = _current_esrd_v24_coefs()
    expected = esrd_v24_fixture["coefficients"]
    drifted = [
        (k, v, current.get(k))
        for k, v in expected.items()
        if current.get(k) != v
    ]
    assert not drifted, (
        f"{len(drifted)} ESRD V24 coefficients drifted. First 10: {drifted[:10]}"
    )


def test_esrd_v24_has_required_prefixes(esrd_v24_fixture: dict) -> None:
    """ESRD V24 must carry at minimum DI_ (dialysis) and FG*_ (functioning graft) prefixes.

    hccinfhir uses ``fgc``/``fgi``/``fga``/``fgn``-style prefixes for the
    functioning-graft segments.  The precise prefix set expands over payment
    years — we just assert that both the dialysis and graft families are
    represented.
    """
    keys = esrd_v24_fixture["coefficients"].keys()
    di_count = sum(1 for k in keys if k.startswith("di_"))
    fg_count = sum(
        1 for k in keys if k.startswith(("fg", "gfa_", "gfn_", "gi_", "gne_"))
    )
    assert di_count > 0, "ESRD V24 must contain DI_ (dialysis) coefficients"
    assert fg_count > 0, (
        "ESRD V24 must contain functioning-graft prefixes (fg*/g*)"
    )
