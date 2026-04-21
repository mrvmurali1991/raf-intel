#!/usr/bin/env python3
"""CI gate: reconcile every supported (model, payment_year) combo against
CMS reference CSVs and exit non-zero on any coefficient drift > epsilon.

Usage:
    python backend/scripts/check_cms_reconciliation.py

Exit codes:
    0 — all combos reconcile cleanly (or are SOURCE_PENDING and skipped)
    1 — at least one combo has coefficient drift above epsilon

Wired into .github/workflows/dx-hardening.yml as a dedicated job so the gate
blocks every PR targeting main/server.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repository's backend package importable when run as a standalone script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.raf.reconcile import (  # noqa: E402
    EPSILON,
    list_supported_combos,
    reconcile_coefficients,
)


def main() -> int:
    combos = list_supported_combos()
    if not combos:
        print("ERROR: no (model, year) combos registered in reconcile.py", file=sys.stderr)
        return 1

    print(f"CMS reconciliation gate — epsilon={EPSILON}")
    print(f"Checking {len(combos)} combos: {combos}")
    print("=" * 72)

    overall_ok = True
    reports = []

    for model, year in combos:
        report = reconcile_coefficients(model, year)
        reports.append(report)

        status = "OK" if report.ok else ("SKIP (source pending)" if report.source_pending else "FAIL")
        print(
            f"[{status:>20}] model={model} year={year} "
            f"checked={report.checked_count} diffs={len(report.diffs)}"
        )

        if report.notes:
            for note in report.notes:
                print(f"    note: {note}")

        if report.diffs:
            overall_ok = False
            for d in report.diffs:
                print(
                    f"    DRIFT  kind={d.kind} key={d.key} "
                    f"ref={d.reference_value} lib={d.library_value} delta={d.delta}"
                )

    print("=" * 72)
    if overall_ok:
        print("PASS: all registered (model, year) combos reconcile within epsilon.")
        return 0

    print("FAIL: coefficient drift detected. See above.", file=sys.stderr)
    # Also emit a machine-readable blob so CI logs can be grepped easily.
    print("REPORT_JSON=" + json.dumps([r.as_dict() for r in reports]), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
