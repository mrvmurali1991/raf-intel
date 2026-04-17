"""V28 hierarchy completeness vs. CMS / hccinfhir bundled tables.

Purpose
-------
Before this test existed, the V28 hierarchy chain list in
``app.services.hcc_hierarchy`` was maintained by hand and had silent gaps
(e.g. missing 17→23 cancer chain, missing 276→280 chain, missing 379→383
chain).  Any gap is a direct billing defect: a more-severe HCC fails to
dominate a less-severe sibling, and both coefficients get paid — which is
exactly the kind of pattern RADV audits flag.

The test asserts that, for every V28 trump relationship CMS publishes
(shipped with ``hccinfhir.defaults.hierarchies_default``), our module's
derived ``_V28_TRUMPED_BY`` lookup contains the same relationship.

When CMS updates V28 for a new payment year the hccinfhir package is
version-bumped and this test locks the new table into the codebase
automatically — no hand-editing of chain tuples required.
"""

from __future__ import annotations

import pytest

pytest.importorskip("hccinfhir")

from hccinfhir.defaults import hierarchies_default  # noqa: E402

from app.services.hcc_hierarchy import (  # noqa: E402
    V28_HIERARCHY_CHAINS,
    _V28_TRUMPED_BY,
)


def _cms_v28_trump_pairs() -> set[tuple[int, int]]:
    """Return every (parent_trumps_child) pair from the CMS V28 table."""
    pairs: set[tuple[int, int]] = set()
    for (hcc, model), trumped in hierarchies_default.items():
        if "V28" not in model:
            continue
        try:
            parent = int(hcc)
        except (TypeError, ValueError):
            continue
        for child in trumped:
            try:
                pairs.add((parent, int(child)))
            except (TypeError, ValueError):
                continue
    return pairs


def test_every_cms_v28_pair_is_represented() -> None:
    cms_pairs = _cms_v28_trump_pairs()
    assert cms_pairs, "hccinfhir V28 hierarchy table is empty — package broken?"

    missing: list[tuple[int, int]] = []
    for parent, child in cms_pairs:
        if parent not in _V28_TRUMPED_BY.get(child, []):
            missing.append((parent, child))
    assert not missing, (
        f"V28 hierarchy is missing {len(missing)} CMS-defined trump pairs: "
        f"{sorted(missing)[:10]}..."
    )


def test_we_do_not_invent_non_cms_trump_pairs() -> None:
    """Every pair we claim must be backed by CMS — no over-reach."""
    cms_pairs = _cms_v28_trump_pairs()
    extra: list[tuple[int, int]] = []
    for child, parents in _V28_TRUMPED_BY.items():
        for parent in parents:
            if (parent, child) not in cms_pairs:
                extra.append((parent, child))
    assert not extra, (
        f"V28 hierarchy contains {len(extra)} pairs not in CMS table: "
        f"{sorted(extra)[:10]}..."
    )


def test_critical_families_are_present() -> None:
    """Spot-check the families that were previously missing or incomplete."""
    # Cancer: HCC 17 must dominate all of 18-23.
    for child in (18, 19, 20, 21, 22, 23):
        assert 17 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 17 must trump {child} (cancer family)"
        )
    # CHF: HCC 221 must dominate 222-227.
    for child in (222, 223, 224, 225, 226, 227):
        assert 221 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 221 must trump {child} (CHF family)"
        )
    # Renal: HCC 326 must dominate 327-329.
    for child in (327, 328, 329):
        assert 326 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 326 must trump {child} (renal family)"
        )
    # Diabetes: HCC 35 must dominate 36-38.
    for child in (36, 37, 38):
        assert 35 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 35 must trump {child} (diabetes family)"
        )
    # Substance use: HCC 135 must dominate 136-139.
    for child in (136, 137, 138, 139):
        assert 135 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 135 must trump {child} (substance family)"
        )
    # Psychiatric: HCC 151 must dominate 152-155.
    for child in (152, 153, 154, 155):
        assert 151 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 151 must trump {child} (psychiatric family)"
        )
    # Liver: HCC 276 must dominate 277-280.
    for child in (277, 278, 279, 280):
        assert 276 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 276 must trump {child} (liver family)"
        )
    # Sepsis / infection: HCC 379 must dominate 380-383.
    for child in (380, 381, 382, 383):
        assert 379 in _V28_TRUMPED_BY.get(child, []), (
            f"HCC 379 must trump {child} (sepsis family)"
        )


def test_chains_populated_from_hccinfhir_at_import() -> None:
    """Sanity: we're not silently falling back to the minimal hard-coded list."""
    # The fallback has 12 chains.  Derived-from-hccinfhir yields ~139 pairs.
    assert len(V28_HIERARCHY_CHAINS) > 50, (
        f"V28 chains unexpectedly short ({len(V28_HIERARCHY_CHAINS)}) — "
        "probable fallback to hard-coded list; hccinfhir import may be broken."
    )


def test_every_v28_trumped_hcc_has_at_least_one_trumper() -> None:
    """No orphaned entries — every child in the lookup must list a parent."""
    for child, parents in _V28_TRUMPED_BY.items():
        assert parents, f"HCC {child} has empty trumper list — malformed lookup"
