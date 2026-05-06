"""
Import a UMLS RRF subset (or simulated data) into the knowledge graph, and/or
run the bootstrap top-HCC seed.

Usage
-----

    # Just seed the top 20 HCCs and their immediate clinical neighborhood
    python -m backend.scripts.import_umls_subset --seed-top-hccs

    # Import concepts from a UMLS-style CSV
    python -m backend.scripts.import_umls_subset --csv /path/to/umls_subset.csv

    # Both at once
    python -m backend.scripts.import_umls_subset --csv ... --seed-top-hccs

CSV format
----------
Expected columns (header required, extras ignored):

    ontology,code,preferred_label,definition,semantic_type

``ontology`` must be one of: umls, snomed, icd10, hcc, atc, rxnorm, loinc,
custom. Rows with unknown ontology are skipped with a warning.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

# Allow running as a script directly (python backend/scripts/import_umls_subset.py)
# in addition to the recommended ``python -m backend.scripts.import_umls_subset``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.knowledge_graph.kg_repository import (  # noqa: E402
    bulk_upsert_concepts,
    stats,
)
from app.services.knowledge_graph.kg_schema import ONTOLOGIES, Concept  # noqa: E402
from app.services.knowledge_graph.seed_top_hccs import seed_top_hccs  # noqa: E402

logger = logging.getLogger("kg.import_umls_subset")


def _read_csv(path: Path) -> list[Concept]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    out: list[Concept] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):  # header on line 1
            ontology = (row.get("ontology") or "").strip().lower()
            code = (row.get("code") or "").strip()
            label = (row.get("preferred_label") or row.get("label") or "").strip()
            if not ontology or not code or not label:
                logger.warning("Row %d: missing ontology/code/label, skipping", i)
                continue
            if ontology not in ONTOLOGIES:
                logger.warning(
                    "Row %d: unknown ontology %r, skipping", i, ontology
                )
                continue
            out.append(
                Concept(
                    ontology=ontology,
                    code=code,
                    preferred_label=label,
                    definition=(row.get("definition") or "").strip() or None,
                    semantic_type=(row.get("semantic_type") or "").strip() or None,
                    metadata={"source": f"csv:{path.name}"},
                )
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import UMLS subset / bootstrap top HCCs into the knowledge graph."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to a UMLS-style CSV (ontology,code,preferred_label,definition,semantic_type).",
    )
    parser.add_argument(
        "--seed-top-hccs",
        action="store_true",
        help="Run the bootstrap top-20 HCC seed.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.csv and not args.seed_top_hccs:
        parser.error("Pass --csv PATH or --seed-top-hccs (or both).")

    summary: dict[str, object] = {}

    if args.csv:
        concepts = _read_csv(args.csv)
        logger.info("CSV %s: parsed %d concepts", args.csv, len(concepts))
        bulk_upsert_concepts(concepts)
        summary["csv_concepts_inserted"] = len(concepts)

    if args.seed_top_hccs:
        seed_summary = seed_top_hccs()
        logger.info(
            "Top-HCC seed: %d concepts, %d edges (%d skipped). HCCs: %s",
            seed_summary["concepts_inserted"],
            seed_summary["edges_inserted"],
            seed_summary["edges_skipped"],
            ", ".join(seed_summary["hccs_covered"]),
        )
        summary["seed"] = seed_summary

    summary["stats_after"] = stats()
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
