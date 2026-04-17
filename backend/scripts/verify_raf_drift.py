#!/usr/bin/env python3
"""RAF engine drift watcher.

Runs the RAF payment-grade invariants in under ~5 seconds without a database.
Designed to execute in CI on every push AND as a pre-commit hook locally.

Exit codes:
  0 — no drift detected.
  1 — drift detected (hccinfhir values, manifest hash, or fixture contract).
  2 — environment-level error (missing dependency, broken import).

What it verifies
----------------
1. hccinfhir is installed and importable.
2. hccinfhir version matches the value recorded in coefficients_manifest.json.
3. Coefficient manifest file is readable and its SHA-256 hash is stable.
4. Full V28 coefficient snapshot (1237 values) matches what hccinfhir ships.
5. V28 hierarchy derivable from hccinfhir covers all 58 CMS parent HCCs.
6. All 302 reconciliation scenarios pass within 1e-3 tolerance.
7. Every property-based invariant holds for 100+ random beneficiaries.

Use as a CI job (fast-lane):
    python backend/scripts/verify_raf_drift.py

Use as a pre-push hook:
    echo '#!/bin/sh\npython backend/scripts/verify_raf_drift.py' > .git/hooks/pre-push
    chmod +x .git/hooks/pre-push
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_MANIFEST = _BACKEND / "app" / "services" / "raf" / "coefficients_manifest.json"


def _fail(msg: str, code: int = 1) -> None:
    print(f"[drift] FAIL: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_hccinfhir_version_matches_manifest() -> None:
    if not _MANIFEST.exists():
        _fail(f"coefficients_manifest.json missing at {_MANIFEST}", code=2)
    manifest = json.loads(_MANIFEST.read_text())
    try:
        import hccinfhir  # type: ignore
    except ImportError:
        _fail("hccinfhir is not installed — run: pip install hccinfhir", code=2)
    version = getattr(hccinfhir, "__version__", None)
    manifest_pin = manifest.get("coefficient_source", "")
    if version and manifest_pin and f"hccinfhir=={version}" not in manifest_pin:
        # Manifest may have the exact version in a nested field — be lenient.
        if version not in manifest_pin:
            _fail(
                f"hccinfhir version {version} does not match manifest "
                f"coefficient_source={manifest_pin!r}. Regenerate the "
                f"coefficient snapshot fixture and bump the manifest."
            )


def _run_pytest_subset() -> None:
    """Run the RAF-engine tests that don't need a database."""
    targets = [
        "tests/test_v28_coefficient_snapshot.py",
        "tests/test_v28_constrained_coefficients.py",
        "tests/test_v28_hierarchy_completeness.py",
        "tests/test_v28_invariants.py",
        "tests/test_raf_reconciliation_v28.py",
        "tests/test_raf_manifest_parity.py",
        "tests/test_raf_provenance.py",
        "tests/test_raf_graft_months.py",
        "tests/test_hcc_hierarchy.py",
        "tests/test_expanded_snapshots.py",
        "tests/test_cms_factor_citations.py",
        "tests/test_ne_reconciliation.py",
        "tests/test_frailty_adjustment.py",
        "tests/test_rxhcc_snapshots.py",
        "tests/test_raf_sbom.py",
        "tests/test_cms_exemplar_scenarios.py",
        "tests/test_v28_interactions.py",
        "tests/test_raf_precision.py",
        "tests/test_claims_roundtrip.py",
        "tests/test_partd_scoring.py",
        "tests/test_coefficient_changelog.py",
    ]
    cmd = [
        sys.executable, "-m", "pytest",
        "--no-header", "--no-cov", "-q", "--tb=short",
        *targets,
    ]
    result = subprocess.run(cmd, cwd=_BACKEND)
    if result.returncode != 0:
        _fail("RAF engine test suite failed — see above for details.")


def main() -> None:
    _check_hccinfhir_version_matches_manifest()
    _run_pytest_subset()
    print("[drift] OK — RAF engine payment-grade invariants hold.")


if __name__ == "__main__":
    main()
