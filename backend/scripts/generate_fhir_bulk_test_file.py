#!/usr/bin/env python3
"""
Generate a synthetic FHIR NDJSON file for testing the bulk ingest pipeline.

Usage:
    python -m backend.scripts.generate_fhir_bulk_test_file \\
        --patients 1000 \\
        --conditions-per-patient 5 \\
        --out /tmp/fhir_bulk_demo.ndjson

The file contains ``patients`` Patient resources followed by
``patients × conditions-per-patient`` Condition resources, each Condition's
``subject.reference`` pointing back to one of the Patients.

The generator lives in :mod:`app.services.bulk_ingest_service` so unit
tests and curl-driven manual verification both use the same source.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure ``backend/`` is on sys.path when invoked as a script.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.bulk_ingest_service import generate_synthetic_ndjson


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic FHIR NDJSON.")
    ap.add_argument("--patients", type=int, default=1000)
    ap.add_argument("--conditions-per-patient", type=int, default=5)
    ap.add_argument("--out", type=Path, default=Path("/tmp/fhir_bulk_demo.ndjson"))
    args = ap.parse_args()

    blob = generate_synthetic_ndjson(
        patient_count=args.patients,
        conditions_per_patient=args.conditions_per_patient,
    )
    args.out.write_bytes(blob)
    print(
        f"Wrote {args.out} — {args.patients} Patients, "
        f"{args.patients * args.conditions_per_patient} Conditions, "
        f"{len(blob):,} bytes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
