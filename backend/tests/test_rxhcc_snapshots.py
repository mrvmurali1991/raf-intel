"""RxHCC (Part D) coefficient lock — V05 and V08.

Medicare Part D prescription-drug bids use a separate CMS risk-adjustment
model family (RxHCC) with its own coefficient tables. Even if the
RAF engine currently consumes only CMS-HCC (Part C) values, RxHCC
coefficients ship in the same ``hccinfhir`` package and any drift in
them is a silent signal that the pinned version moved.

This harness locks:

- V05 RxHCC table (legacy — used for prior payment years).
- V08 RxHCC table (current — CY2026 payment year).
- Structural prefix hygiene (RX_, rx_ce, rx_cf, rx_ci, rx_cn families).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir", reason="hccinfhir not installed")

from hccinfhir.defaults import coefficients_default  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _current_rxhcc_coefs(model_name: str) -> dict[str, float]:
    return {
        k[0]: round(float(v), 6)
        for k, v in coefficients_default.items()
        if k[1] == model_name
    }


# ---------------------------------------------------------------------------
# V05 (legacy RxHCC)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rxhcc_v05_fixture() -> dict:
    path = _FIXTURES / "rxhcc_v05_coefficient_snapshot.json"
    assert path.exists(), f"missing fixture: {path}"
    return json.loads(path.read_text())


def test_rxhcc_v05_count_matches_snapshot(rxhcc_v05_fixture: dict) -> None:
    current = _current_rxhcc_coefs("RxHCC Model V05")
    assert len(current) == rxhcc_v05_fixture["coefficient_count"], (
        f"RxHCC V05 count drifted: "
        f"snapshot={rxhcc_v05_fixture['coefficient_count']}, "
        f"current={len(current)}"
    )


def test_rxhcc_v05_coefficients_have_not_drifted(rxhcc_v05_fixture: dict) -> None:
    current = _current_rxhcc_coefs("RxHCC Model V05")
    expected = rxhcc_v05_fixture["coefficients"]
    drifted = [
        (k, v, current.get(k))
        for k, v in expected.items()
        if current.get(k) != v
    ]
    assert not drifted, (
        f"{len(drifted)} RxHCC V05 coefficients drifted. First 10: "
        f"{drifted[:10]}"
    )


# ---------------------------------------------------------------------------
# V08 (current RxHCC — PY2026)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rxhcc_v08_fixture() -> dict:
    path = _FIXTURES / "rxhcc_v08_coefficient_snapshot.json"
    assert path.exists(), f"missing fixture: {path}"
    return json.loads(path.read_text())


def test_rxhcc_v08_count_matches_snapshot(rxhcc_v08_fixture: dict) -> None:
    current = _current_rxhcc_coefs("RxHCC Model V08")
    assert len(current) == rxhcc_v08_fixture["coefficient_count"], (
        f"RxHCC V08 count drifted: "
        f"snapshot={rxhcc_v08_fixture['coefficient_count']}, "
        f"current={len(current)}"
    )


def test_rxhcc_v08_coefficients_have_not_drifted(rxhcc_v08_fixture: dict) -> None:
    current = _current_rxhcc_coefs("RxHCC Model V08")
    expected = rxhcc_v08_fixture["coefficients"]
    drifted = [
        (k, v, current.get(k))
        for k, v in expected.items()
        if current.get(k) != v
    ]
    assert not drifted, (
        f"{len(drifted)} RxHCC V08 coefficients drifted. First 10: "
        f"{drifted[:10]}"
    )


def test_rxhcc_v08_has_required_prefix_families(rxhcc_v08_fixture: dict) -> None:
    """RxHCC tables segment by continuing/new enrollee × low-income × LTI.

    hccinfhir ships V08 with two top-level segments that split further:
      - rx_ce_*  continuing enrollees
          * lowaged / lownoaged / nolowaged / nolownoaged   (low-income × aged crosses)
          * lti  long-term institutional
      - rx_ne_*  new enrollees
          * lo / nolo / lti                                (low-income / LTI)

    We assert the top-level families and at least one low-income and LTI
    sub-segment exist, so a silent re-shape of hccinfhir upstream fails fast.
    """
    keys = set(rxhcc_v08_fixture["coefficients"].keys())
    top_level = ("rx_ce_", "rx_ne_")
    for p in top_level:
        assert any(k.startswith(p) for k in keys), (
            f"RxHCC V08 missing top-level {p!r} family"
        )
    assert any(k.startswith("rx_ce_lti_") for k in keys), (
        "RxHCC V08 missing long-term institutional (rx_ce_lti_)"
    )
    assert any(k.startswith("rx_ne_lo_") or k.startswith("rx_ne_nolo_") for k in keys), (
        "RxHCC V08 missing new-enrollee low-income split (rx_ne_lo_/rx_ne_nolo_)"
    )
