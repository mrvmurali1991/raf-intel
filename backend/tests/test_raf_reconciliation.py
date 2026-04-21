"""Tests for app.services.raf.reconcile — CMS reference cross-checks.

Covers:
  (a) reference CSV loads for every supported (model, year) combo
  (b) a deliberate edit to the reference CSV triggers a diff report
  (c) independent hierarchy trimming matches CMS trumping rules
      (classic example: HCC 17 suppresses HCC 18/19 under both V24 and V28)
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir", reason="hccinfhir not installed")

from app.services.raf.reconcile import (  # noqa: E402
    EPSILON,
    HierarchyMismatchError,
    ReconciliationReport,
    _independent_trim,
    _load_hierarchy_csv,
    list_supported_combos,
    reconcile_coefficients,
    validate_hierarchy,
)


# ---------------------------------------------------------------------------
# (a) Reference CSVs load cleanly and reconcile to hccinfhir
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("combo", list_supported_combos())
def test_reference_csv_loads_and_reconciles(combo: tuple[str, int]) -> None:
    """Every registered (model, year) reference CSV reconciles within epsilon."""
    model, year = combo
    report = reconcile_coefficients(model, year)
    assert isinstance(report, ReconciliationReport)
    assert report.checked_count > 0, f"CSV {report.reference_csv} produced zero rows"
    assert report.ok, (
        f"Reference CSV drift for {model}/{year}: "
        f"{[d.as_dict() for d in report.diffs]} notes={report.notes}"
    )


def test_epsilon_is_tight() -> None:
    """Sanity check the epsilon — must be small enough to catch real drift."""
    assert EPSILON <= 0.0005, (
        f"EPSILON={EPSILON} is too loose; CMS-published coefficients have "
        f"3-digit precision so a tight tolerance is required."
    )


# ---------------------------------------------------------------------------
# (b) Deliberate CSV edit triggers a diff report
# ---------------------------------------------------------------------------


def test_deliberate_csv_edit_triggers_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the reconcile module at a synthetic CSV with a wrong value and
    assert we get a non-empty diff report."""
    from app.services.raf import reconcile as rc

    # Build a synthetic CSV with one intentionally-wrong HCC coefficient.
    fake_csv = tmp_path / "v28_synthetic.csv"
    fake_csv.write_text(
        "# synthetic — deliberately wrong\n"
        "kind,key,value,label\n"
        'hcc,17,999.999,"intentionally wrong — should trigger diff"\n'
        'hcc,18,2.341,"correct V28 CNA value"\n'
    )

    # Patch the registry so "V28/9999" resolves to our synthetic file.
    monkeypatch.setitem(rc._COEFFICIENT_FILES, ("V28", 9999), fake_csv.name)
    monkeypatch.setattr(rc, "_COEFF_DIR", tmp_path)

    report = rc.reconcile_coefficients("V28", 9999)

    assert not report.ok, "Expected diff report to be non-ok with wrong value"
    assert report.checked_count == 2, "Expected both rows to be checked"
    assert len(report.diffs) == 1, (
        f"Expected exactly one diff, got {len(report.diffs)}: "
        f"{[d.as_dict() for d in report.diffs]}"
    )
    diff = report.diffs[0]
    assert diff.key == "17"
    assert diff.reference_value == pytest.approx(999.999)
    assert diff.library_value == pytest.approx(4.209, abs=1e-3)
    assert diff.delta is not None and diff.delta > 100


# ---------------------------------------------------------------------------
# (c) Hierarchy trim: HCC 17 suppresses HCC 18/19 (V24) and 18..23 (V28)
# ---------------------------------------------------------------------------


def test_hierarchy_trim_v24_hcc17_suppresses_hcc18_and_19() -> None:
    """CMS V24 rule: HCC 17 (Diabetes with Acute Complications) trumps
    HCC 18 (Chronic Complications) and HCC 19 (without Complication)."""
    pairs = _load_hierarchy_csv(
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "raf" / "cms_reference"
        / "hierarchy" / "v24_hierarchy.csv"
    )
    # Sanity check the rules we rely on are in the CSV
    assert (17, 18) in pairs
    assert (17, 19) in pairs

    trimmed = _independent_trim([17, 18, 19, 96], pairs)
    assert trimmed == [17, 96], (
        f"V24 trim should drop 18, 19 when 17 is present; got {trimmed}"
    )


def test_hierarchy_trim_v28_hcc17_suppresses_18_through_23() -> None:
    """CMS V28 expanded cancer family: HCC 17 trumps HCCs 18..23."""
    pairs = _load_hierarchy_csv(
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "raf" / "cms_reference"
        / "hierarchy" / "v28_hierarchy.csv"
    )
    for child in (18, 19, 20, 21, 22, 23):
        assert (17, child) in pairs, f"V28 CSV missing rule (17, {child})"

    trimmed = _independent_trim([17, 18, 19, 20, 21, 22, 23, 37], pairs)
    assert trimmed == [17, 37], (
        f"V28 trim should drop 18-23 when 17 is present; got {trimmed}"
    )


def test_validate_hierarchy_passes_on_trimmed_input() -> None:
    """Properly pre-trimmed input should round-trip without raising."""
    # hccinfhir has already suppressed 18/19: only 17 remains.
    out = validate_hierarchy([17], "V24")
    assert out == [17]

    out = validate_hierarchy([17, 37, 111], "V28")
    assert out == [17, 37, 111]


def test_validate_hierarchy_raises_on_library_divergence() -> None:
    """If hccinfhir forgot to trim a child HCC, validate_hierarchy must raise.

    Example: input claims both 17 and 18 are active — CMS rules require 18 to
    be dropped; failure to do so is a billing safety defect.
    """
    with pytest.raises(HierarchyMismatchError) as exc:
        validate_hierarchy([17, 18], "V24")
    assert "18" in str(exc.value)

    with pytest.raises(HierarchyMismatchError) as exc:
        validate_hierarchy([17, 23], "V28")
    assert "23" in str(exc.value)


# ---------------------------------------------------------------------------
# (d) Hierarchy CSVs themselves are syntactically valid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["V24", "V28"])
def test_hierarchy_csv_is_well_formed(model: str) -> None:
    path = (
        Path(__file__).resolve().parent.parent
        / "app" / "services" / "raf" / "cms_reference"
        / "hierarchy" / f"{model.lower()}_hierarchy.csv"
    )
    assert path.exists(), f"Missing hierarchy CSV for {model}"

    with path.open() as f:
        data_lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(data_lines)
    header = reader.fieldnames or []
    assert header == ["hcc_parent", "hcc_child"], (
        f"{path} header should be [hcc_parent, hcc_child], got {header}"
    )
    rows = list(reader)
    assert len(rows) > 0, f"{path} has no rows"
    for r in rows:
        # Every cell must be an integer
        int(r["hcc_parent"])
        int(r["hcc_child"])
