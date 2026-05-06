"""
CLI entry point for the KG-first accuracy benchmark.

Usage:
    python -m scripts.run_kg_benchmark \\
        --fixtures backend/app/services/evaluation/fixtures/extended_charts.json \\
        --mode kg-first \\
        --out-json eval_results.json \\
        --out-md eval_results.md

If --mode is `all` the script runs all three modes (`llm-only`, `kg-first`,
`hybrid`) and writes a single Markdown report comparing them.

By default the LLM caller is the deterministic `mock_gemini_caller`, which
reads each fixture's `llm_mock` field. To attach to a live Gemini path,
pass `--live-gemini`; the script then imports `app.services.skill_pipeline`
and uses the production wiring (requires GOOGLE_API_KEY).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make sure `app.*` is importable when this is run as `python -m scripts.run_kg_benchmark`
HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation import kg_benchmark  # noqa: E402


def _live_gemini_caller(chart):
    """Adapter that calls the production skill_pipeline.run_pipeline.

    Returns a list of {icd10, hcc, confidence, source, evidence_type}
    so the benchmark consumes it identically to the mock caller.
    """
    from app.services.skill_pipeline import run_pipeline
    from app.services.hccinfhir_utils import lookup_hcc

    result = run_pipeline(
        clinical_note=chart.get("note_text") or "",
        patient_age=(chart.get("demographics") or {}).get("age"),
        patient_sex=(chart.get("demographics") or {}).get("sex"),
        medications=[m.get("drug") for m in (chart.get("medications") or []) if m.get("drug")],
        problem_list=chart.get("problem_list") or [],
    )
    out = []
    for d in (result or {}).get("diagnoses", []):
        icd = d.get("icd10") or d.get("code") or ""
        hcc_info = lookup_hcc(icd) if icd else {"hcc_codes": []}
        for hcc in hcc_info.get("hcc_codes") or []:
            out.append({
                "icd10": icd, "hcc": hcc,
                "confidence": float(d.get("confidence", 0.7)),
                "source": "llm", "evidence_type": "llm",
            })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KG-first accuracy benchmark")
    p.add_argument("--fixtures", required=True, help="Path to fixture JSON file")
    p.add_argument(
        "--mode",
        choices=("kg-first", "llm-only", "hybrid", "all"),
        default="kg-first",
    )
    p.add_argument("--out-json", help="Write detailed JSON results here")
    p.add_argument("--out-md", help="Write formatted Markdown report here")
    p.add_argument(
        "--live-gemini",
        action="store_true",
        help="Use the production Gemini path instead of the deterministic mock",
    )
    p.add_argument(
        "--headline-mode",
        default="kg-first",
        help="Mode used for the executive-summary numbers in the Markdown report",
    )
    args = p.parse_args(argv)

    caller = _live_gemini_caller if args.live_gemini else None

    modes = ("kg-first", "llm-only", "hybrid") if args.mode == "all" else (args.mode,)
    results: dict[str, dict] = {}
    for m in modes:
        print(f"[run_kg_benchmark] running mode={m} fixtures={args.fixtures}", file=sys.stderr)
        results[m] = kg_benchmark.run_kg_benchmark(args.fixtures, mode=m, gemini_caller=caller)

    headline = args.headline_mode if args.headline_mode in results else next(iter(results))

    # Pretty stdout summary
    for m, r in results.items():
        print(
            f"  mode={m:<10s} P={r['precision']:.3f} R={r['recall']:.3f} "
            f"F1={r['f1']:.3f} (TP={r['true_positives']} FP={r['false_positives']} "
            f"FN={r['false_negatives']}, charts={r['charts_processed']}, "
            f"runtime={r['runtime_seconds']:.2f}s)",
            file=sys.stderr,
        )

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(
            {"results_by_mode": results, "headline_mode": headline}, indent=2,
        ))
        print(f"[run_kg_benchmark] JSON -> {args.out_json}", file=sys.stderr)

    if args.out_md:
        # Always include all three lines in the comparison if available;
        # if a mode wasn't run, it's simply omitted.
        # Load fixture count for the header
        fixtures = kg_benchmark.load_fixtures(args.fixtures)
        md = kg_benchmark.render_markdown_report(
            fixture_path=args.fixtures,
            fixture_count=len(fixtures),
            results_by_mode=results,
            mock_mode=not args.live_gemini,
            headline_mode=headline,
        )
        Path(args.out_md).write_text(md)
        print(f"[run_kg_benchmark] Markdown -> {args.out_md}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
