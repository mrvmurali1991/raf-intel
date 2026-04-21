#!/usr/bin/env python3
"""
Fit per-source confidence calibrators and persist them.

NOT run in CI.  Invoke manually, review diffs on the joblib artifacts,
commit as part of a release.

Usage::

    # Fit from the shipped bootstrap CSV (synthetic labels):
    python backend/scripts/fit_calibrators.py

    # Fit from a real labelled export (columns: source,raw_score,label):
    python backend/scripts/fit_calibrators.py \\
        --input path/to/chart_review_labels.csv

    # Force Platt (default is isotonic when >=500 rows, Platt otherwise):
    python backend/scripts/fit_calibrators.py --method platt
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running as a script without installing the backend package.
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import numpy as np  # noqa: E402

# Import submodules directly so we do not trigger the broader
# ``app.services.raf`` package __init__ (which pulls in hccinfhir and
# requires a full runtime install).  The calibration module is a leaf
# subpackage and fits cleanly without the rest of the RAF calculator.
from app.services.raf.calibration.bootstrap import (  # noqa: E402
    DEFAULT_CSV_PATH,
    class_balance,
    read_csv,
)
from app.services.raf.calibration.calibrator import (  # noqa: E402
    IsotonicCalibrator,
    PlattCalibrator,
)
from app.services.raf.calibration.persistence import (  # noqa: E402
    CANONICAL_SOURCES,
    _normalise_source,
    save_calibrator,
)

logger = logging.getLogger("fit_calibrators")


def _choose_method(n: int, method_flag: str | None) -> str:
    if method_flag:
        return method_flag
    # Isotonic needs many samples to avoid overfit; Platt is the safer
    # choice for small datasets.
    return "isotonic" if n >= 500 else "platt"


def _fit_one(source: str, raws: np.ndarray, labels: np.ndarray, method: str):
    if method == "platt":
        cal = PlattCalibrator().fit(raws, labels)
    elif method == "isotonic":
        cal = IsotonicCalibrator().fit(raws, labels)
    else:
        raise ValueError(f"unknown method: {method}")
    save_calibrator(source, cal)
    return cal


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="CSV with columns source,raw_score,label. "
        "Defaults to the shipped bootstrap set.",
    )
    parser.add_argument(
        "--method",
        choices=("platt", "isotonic"),
        default=None,
        help="Force a method. Default: isotonic if >=500 rows, else Platt.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        logger.error("input CSV not found: %s", args.input)
        return 2

    rows = read_csv(args.input)
    if not rows:
        logger.error("input CSV %s has no rows", args.input)
        return 2

    balance = class_balance(rows)
    logger.info("class balance: %s", balance)

    by_src: dict[str, list] = {s: [] for s in CANONICAL_SOURCES}
    for r in rows:
        by_src.setdefault(_normalise_source(r.source), []).append(r)

    had_any = False
    for src, src_rows in by_src.items():
        if not src_rows:
            logger.warning("no rows for source=%s — skipping fit", src)
            continue
        raws = np.asarray([r.raw_score for r in src_rows], dtype=float)
        labels = np.asarray([r.label for r in src_rows], dtype=int)
        method = _choose_method(len(src_rows), args.method)
        logger.info(
            "fitting source=%s method=%s n=%d pos=%d",
            src,
            method,
            len(src_rows),
            int(labels.sum()),
        )
        _fit_one(src, raws, labels, method)
        had_any = True

    if not had_any:
        logger.error("no fits performed — check input CSV contents")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
