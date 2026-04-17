"""Full V28 coefficient snapshot audit.

Why this exists
---------------
Without CMS's Python reference software (still internal to CMS as of
2026-04-17), we rely on `hccinfhir` as a *cached copy* of CMS coefficients.
This test turns that dependency into something auditable: every V28
coefficient shipped with the pinned hccinfhir version is checkpointed into a
JSON fixture, and this test asserts current coefficients exactly match the
fixture.

Effect on upgrade path
----------------------
- `pip install -U hccinfhir` → if any V28 coefficient drifts, this test
  fails loudly with a per-key diff.
- The engineer regenerates the fixture **only after** comparing the new
  values against the CMS Final Rate Announcement Excel for the target
  payment year (URL in fixture metadata).
- That comparison is the direct CMS audit; the fixture locks the result.

So although we cannot yet reconcile against CMS Python reference software,
we CAN reconcile against CMS's published coefficient *tables* — this fixture
is the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir", reason="hccinfhir not installed")

from hccinfhir.defaults import coefficients_default  # noqa: E402

_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "v28_coefficient_snapshot.json"
)


@pytest.fixture(scope="module")
def snapshot() -> dict:
    assert _FIXTURE_PATH.exists(), f"fixture missing: {_FIXTURE_PATH}"
    return json.loads(_FIXTURE_PATH.read_text())


def _current_v28_coefficients() -> dict[str, float]:
    return {
        k: round(float(v), 6)
        for (k, model), v in coefficients_default.items()
        if "V28" in model
    }


def test_coefficient_count_matches_snapshot(snapshot: dict) -> None:
    current = _current_v28_coefficients()
    assert len(current) == snapshot["coefficient_count"], (
        f"V28 coefficient count drifted: snapshot={snapshot['coefficient_count']}, "
        f"current={len(current)}. hccinfhir upgraded? Regenerate fixture only "
        f"after CMS Final Rate Announcement cross-check."
    )


def test_every_snapshot_key_present_with_matching_value(snapshot: dict) -> None:
    current = _current_v28_coefficients()
    expected = snapshot["coefficients"]
    drifted: list[tuple[str, float, float]] = []
    missing: list[str] = []
    for key, exp_val in expected.items():
        if key not in current:
            missing.append(key)
            continue
        if current[key] != exp_val:
            drifted.append((key, exp_val, current[key]))
    assert not missing, (
        f"{len(missing)} V28 coefficients removed since snapshot: "
        f"{sorted(missing)[:10]}..."
    )
    assert not drifted, (
        f"{len(drifted)} V28 coefficient values drifted since snapshot. "
        f"First 10 diffs: {drifted[:10]}"
    )


def test_no_new_coefficients_without_snapshot_refresh(snapshot: dict) -> None:
    current = _current_v28_coefficients()
    expected = snapshot["coefficients"]
    added = sorted(set(current) - set(expected))
    assert not added, (
        f"{len(added)} V28 coefficients NEW since snapshot (not in fixture): "
        f"{added[:10]}... Review against CMS Final Rate Announcement and "
        f"regenerate fixture."
    )


def test_constrained_families_match_cms_published_values(snapshot: dict) -> None:
    """Spot-check CMS Final Rate Announcement PY2026 published constrained values.

    CMS publishes the constrained-family coefficients explicitly in the Final
    Rate Announcement. These are the canonical reference values — if these
    don't match, the whole snapshot is suspect.
    """
    coeffs = snapshot["coefficients"]
    # Diabetes family: HCCs 36/37/38 share constrained CNA value 0.166
    for hcc in ("36", "37", "38"):
        key = f"cna_hcc{hcc}"
        assert coeffs[key] == pytest.approx(0.166, abs=1e-3), (
            f"CMS CY2026 Final Rate Announcement: cna_hcc{hcc}=0.166, "
            f"snapshot has {coeffs[key]}"
        )
    # CHF family: HCCs 224/225/226 share constrained CNA value 0.360
    for hcc in ("224", "225", "226"):
        key = f"cna_hcc{hcc}"
        assert coeffs[key] == pytest.approx(0.360, abs=1e-3), (
            f"CMS CY2026 Final Rate Announcement: cna_hcc{hcc}=0.360, "
            f"snapshot has {coeffs[key]}"
        )


def test_snapshot_metadata_is_self_describing(snapshot: dict) -> None:
    assert snapshot["model_name"] == "CMS-HCC Model V28"
    assert snapshot["coefficient_source"].startswith("hccinfhir==")
    assert snapshot["payment_year"] == "2026"
    assert "cms.gov" in snapshot["cms_source_url"]
    assert snapshot["coefficient_count"] > 1000, (
        "V28 snapshot should have >1000 coefficients (HCC × 7 segments + "
        "interactions + NE tables)"
    )


def test_every_segment_has_full_hcc_coverage(snapshot: dict) -> None:
    """All 7 payment segments must carry a coefficient for every V28 HCC."""
    coeffs = snapshot["coefficients"]
    segments = ["cna", "cnd", "cfa", "cfd", "cpa", "cpd", "ins"]
    per_segment_hccs: dict[str, set[str]] = {s: set() for s in segments}
    for key in coeffs:
        if "_hcc" not in key:
            continue
        seg, hcc = key.split("_hcc", 1)
        if seg in per_segment_hccs:
            per_segment_hccs[seg].add(hcc)
    counts = {s: len(per_segment_hccs[s]) for s in segments}
    # All 7 segments must have the same HCC count (CMS guarantees parity).
    distinct = set(counts.values())
    assert len(distinct) == 1, (
        f"V28 segments must carry identical HCC coverage; got {counts}"
    )
    assert next(iter(distinct)) >= 115, (
        f"Each segment must carry ≥115 HCCs (V28 defines 115); got {counts}"
    )
