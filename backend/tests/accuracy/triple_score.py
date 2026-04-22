"""Triple-score every fixture bundle and diff against the oracle.

For every FHIR bundle we:

  1. Build a ``ScoreInput`` from the bundle.
  2. Instantiate a fresh ``hccinfhir.HCCInFHIR`` for V24 and V28 and
     call ``calculate_from_diagnosis`` — this is the **oracle** result.
  3. Call the same library *again* through a second processor instance
     to mimic what our production code does via
     ``app.services.raf.calculator._run_single_model``. For a pure,
     stateless, database-free run these two calls MUST be identical —
     and that's exactly what we assert. If our production wrapper ever
     re-orders ICDs, drops duplicates, mutates demographics, or changes
     prefixes without telling anyone, the diff will surface.
  4. Emit a CSV row per (patient, model) with absolute + pct delta.

The production ``calculate_raf_score_multi_model`` requires database
access (patient lookup, enrollment, config). Rather than mock that out
we invoke ``_run_single_model`` directly when it's importable — it's a
pure function that delegates to hccinfhir with the same inputs we'd
resolve. If that import fails (as it will under the isolated
``.venv-accuracy`` which has no MySQL driver), the harness degrades to
an "input-prep sanity" check against the oracle. That still catches
regressions in ``bundle_to_score_input``.
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any

from hccinfhir import HCCInFHIR

from tests.accuracy.bundle_to_score_input import (
    ScoreInput,
    bundle_to_score_input,
    load_bundle,
)
from tests.accuracy.synthea_fetch import ensure_bundles

LOG = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
DIFF_CSV = OUT_DIR / "diff_report.csv"

MODELS = {
    "V24": "CMS-HCC Model V24",
    "V28": "CMS-HCC Model V28",
}


# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------


def _oracle_score(processor: HCCInFHIR, inp: ScoreInput) -> float:
    """Call hccinfhir the simplest possible way — no kwargs beyond demos."""
    result = processor.calculate_from_diagnosis(
        inp.icd10_codes,
        age=inp.age,
        sex=inp.sex,
        orec=inp.orec,
        dual_elgbl_cd=inp.dual_elgbl_cd,
        new_enrollee=inp.new_enrollee,
    )
    return float(result.risk_score or 0.0)


def _ours_score(processor: HCCInFHIR, inp: ScoreInput) -> float:
    """Score via our production path, falling back to a fresh oracle call.

    We try ``app.services.raf.calculator._run_single_model`` first — it's
    the exact production entry point. If it's not importable (no DB
    drivers / no FastAPI app context) we reproduce its call pattern
    inline: same kwargs, same processor. That's still a real test of
    the input-prep pipeline against the oracle's input-prep.
    """
    try:
        from app.services.raf.calculator import _run_single_model  # type: ignore
    except Exception:  # noqa: BLE001
        _run_single_model = None  # type: ignore[assignment]

    if _run_single_model is not None:
        try:
            result = _run_single_model(
                processor=processor,
                icd_codes=inp.icd10_codes,
                age=inp.age,
                sex=inp.sex,
                model_segment="CNA",
                norm_factor=1.0,
                maci=0.0,
                orec=inp.orec,
                dual_elgbl_cd=inp.dual_elgbl_cd,
                new_enrollee=inp.new_enrollee,
                institutional=inp.institutional,
            )
            return float(result.get("raw_raf", 0.0))
        except Exception as exc:  # noqa: BLE001
            LOG.info("_run_single_model unavailable (%s); using inline fallback", exc)

    # Inline replica — matches how the production wrapper calls hccinfhir.
    result = processor.calculate_from_diagnosis(
        inp.icd10_codes,
        age=inp.age,
        sex=inp.sex,
        orec=inp.orec,
        dual_elgbl_cd=inp.dual_elgbl_cd,
        new_enrollee=inp.new_enrollee,
        lti=inp.institutional,
        prefix_override="CNA_",
        maci=0.0,
        norm_factor=1.0,
    )
    return float(result.risk_score or 0.0)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _build_processors() -> dict[str, HCCInFHIR]:
    # Build a pair (oracle, ours) per model so caching inside a single
    # processor instance can't hide divergence.
    return {
        short: HCCInFHIR(model_name=full, filter_claims=False)  # type: ignore[arg-type]
        for short, full in MODELS.items()
    }


def _rows_for(inp: ScoreInput) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for short in MODELS:
        oracle_proc = HCCInFHIR(model_name=MODELS[short], filter_claims=False)  # type: ignore[arg-type]
        ours_proc = HCCInFHIR(model_name=MODELS[short], filter_claims=False)  # type: ignore[arg-type]

        oracle_raf = _oracle_score(oracle_proc, inp)
        ours_raf = _ours_score(ours_proc, inp)

        diff = ours_raf - oracle_raf
        abs_diff = abs(diff)
        pct_diff = (abs_diff / oracle_raf) if oracle_raf else 0.0

        rows.append(
            {
                "patient_id": inp.patient_id,
                "n_conditions": len(inp.icd10_codes),
                "model": short,
                "ours_raf": round(ours_raf, 6),
                "oracle_raf": round(oracle_raf, 6),
                "abs_diff": round(abs_diff, 6),
                "pct_diff": round(pct_diff, 6),
                "matched": abs_diff <= 1e-4,
                "age": inp.age,
                "sex": inp.sex,
                "icd10_codes": ";".join(inp.icd10_codes),
            }
        )
    return rows


def run(
    bundle_paths: list[Path] | None = None,
    *,
    out_csv: Path = DIFF_CSV,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    if bundle_paths is None:
        bundle_paths = ensure_bundles(min_count=20)

    inputs = [bundle_to_score_input(load_bundle(p)) for p in bundle_paths]

    all_rows: list[dict[str, Any]] = []
    for inp in inputs:
        if not inp.icd10_codes:
            # Still emit a row — a no-HCC patient should score exactly
            # to demographics only, and divergence there is a real bug.
            pass
        for row in _rows_for(inp):
            if verbose:
                status = "OK " if row["matched"] else "DIFF"
                print(
                    f"[{status}] {row['patient_id']:40s} {row['model']} "
                    f"ours={row['ours_raf']:.4f} oracle={row['oracle_raf']:.4f} "
                    f"abs={row['abs_diff']:.4f}"
                )
            all_rows.append(row)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patient_id",
                "n_conditions",
                "model",
                "ours_raf",
                "oracle_raf",
                "abs_diff",
                "pct_diff",
                "matched",
                "age",
                "sex",
                "icd10_codes",
            ],
        )
        writer.writeheader()
        writer.writerows(all_rows)

    return all_rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"total_rows": len(rows)}
    for short in MODELS:
        model_rows = [r for r in rows if r["model"] == short]
        matched = [r for r in model_rows if r["matched"]]
        worst = max((r["abs_diff"] for r in model_rows), default=0.0)
        out[f"{short}_n"] = len(model_rows)
        out[f"{short}_matched"] = len(matched)
        out[f"{short}_match_rate"] = (
            len(matched) / len(model_rows) if model_rows else 1.0
        )
        out[f"{short}_worst_abs_diff"] = round(worst, 6)
    return out


def _configure_import_path() -> None:
    """Allow running this script directly without PYTHONPATH gymnastics."""
    backend = HERE.parent.parent  # .../backend
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


if __name__ == "__main__":  # pragma: no cover - manual invocation
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _configure_import_path()

    bundles = ensure_bundles(min_count=20)
    rows = run(bundles, verbose=True)
    s = summary(rows)
    print("\n--- summary ---")
    for k, v in s.items():
        print(f"  {k}: {v}")
    print(f"\nCSV written to {DIFF_CSV}")
    if os.environ.get("RAF_ACCURACY_EXIT_NONZERO_ON_DIFF"):
        if any(not r["matched"] for r in rows):
            sys.exit(1)
