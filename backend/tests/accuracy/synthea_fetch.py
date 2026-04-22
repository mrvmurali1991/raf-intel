"""Fetch / generate Synthea Medicare FHIR bundles for the accuracy harness.

Strategy (in order of preference):

1. If bundles already exist under ``fixtures/synthea_bundles/*.json``
   (including the hand-crafted ``hand/*.json``), reuse them — the harness
   is idempotent.
2. Attempt to generate 50 Medicare-aged patients locally with Synthea
   (``git clone https://github.com/synthetichealth/synthea``,
   ``./run_synthea -p 50 --exporter.fhir.export true --generate.only_live_patients true``).
   This requires Java + ~3 minutes of runtime. Skipped if Synthea is not
   reachable or Java is missing.
3. Fall back to the hand-crafted 20 bundles under
   ``fixtures/synthea_bundles/hand/*.json``. These cover the HCC
   hierarchies explicitly requested by the spec
   (diabetes + neuropathy, CHF + cardiomyopathy, CKD + ESRD,
    cancer + metastasis) plus a handful of single-condition controls.

This module never blocks the harness — if every strategy fails, it
raises a clear message telling the reader to commit the hand fixtures.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

LOG = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
FIXTURE_DIR = HERE / "fixtures" / "synthea_bundles"
HAND_DIR = FIXTURE_DIR / "hand"


def _existing_bundles() -> List[Path]:
    """Return all *.json bundles already on disk (real + hand)."""
    if not FIXTURE_DIR.exists():
        return []
    out: list[Path] = []
    for p in FIXTURE_DIR.rglob("*.json"):
        if p.is_file():
            out.append(p)
    return sorted(out)


def _try_generate_with_synthea(population: int = 50) -> bool:
    """Clone + run Synthea locally. Returns True on success.

    Fails fast (returns False) if Java/git/network is unavailable or if
    the clone/run takes longer than a reasonable upper bound.
    """
    if shutil.which("java") is None:
        LOG.info("Synthea skipped: java not on PATH")
        return False
    if shutil.which("git") is None:
        LOG.info("Synthea skipped: git not on PATH")
        return False

    work_dir = HERE / ".synthea_workdir"
    synthea_dir = work_dir / "synthea"
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        if not synthea_dir.exists():
            LOG.info("Cloning Synthea into %s", synthea_dir)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "https://github.com/synthetichealth/synthea",
                    str(synthea_dir),
                ],
                check=True,
                timeout=120,
            )
        # Minimal run: Medicare-aged population, FHIR bundles only.
        LOG.info("Running Synthea for %d patients (may take several minutes)...", population)
        subprocess.run(
            [
                "./run_synthea",
                "-p",
                str(population),
                "--exporter.fhir.export",
                "true",
                "--exporter.hospital.fhir.export",
                "false",
                "--exporter.practitioner.fhir.export",
                "false",
                "--generate.only_live_patients",
                "true",
                "--generate.default_population.age_min",
                "65",
            ],
            cwd=str(synthea_dir),
            check=True,
            timeout=600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        LOG.warning("Synthea run failed: %s", exc)
        return False

    # Copy FHIR output into our fixture directory.
    fhir_out = synthea_dir / "output" / "fhir"
    if not fhir_out.exists():
        LOG.warning("Synthea finished but produced no FHIR output at %s", fhir_out)
        return False
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in fhir_out.glob("*.json"):
        # Synthea emits 3 non-patient bundles (hospitalInformation,
        # practitionerInformation, ...) — skip them.
        name = src.name.lower()
        if name.startswith(("hospital", "practitioner")):
            continue
        dst = FIXTURE_DIR / src.name
        shutil.copy2(src, dst)
        copied += 1
    LOG.info("Copied %d Synthea bundles into %s", copied, FIXTURE_DIR)
    return copied > 0


def ensure_bundles(min_count: int = 20, try_synthea: bool = False) -> List[Path]:
    """Return at least ``min_count`` FHIR bundles, generating if needed.

    Preference order:
      1. Existing bundles on disk.
      2. Local Synthea run (only if ``try_synthea=True`` — off by default
         because it pulls a multi-MB repo and needs Java).
      3. Hand-crafted fixtures (always committed to the repo).
    """
    existing = _existing_bundles()
    if len(existing) >= min_count:
        return existing

    if try_synthea and os.environ.get("RAF_ACCURACY_RUN_SYNTHEA", "") == "1":
        if _try_generate_with_synthea(population=max(min_count, 50)):
            return _existing_bundles()

    # Final fallback: hand-crafted bundles only.
    hand = sorted(HAND_DIR.glob("*.json"))
    if not hand:
        raise RuntimeError(
            "No Synthea bundles found and no hand-crafted fixtures either. "
            f"Populate {HAND_DIR} or set RAF_ACCURACY_RUN_SYNTHEA=1 to run Synthea."
        )
    return hand


if __name__ == "__main__":  # pragma: no cover - manual invocation
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bundles = ensure_bundles(min_count=20, try_synthea=True)
    print(f"Ready: {len(bundles)} bundles available.")
    for b in bundles[:5]:
        print("  ", b.relative_to(HERE))
    if len(bundles) > 5:
        print(f"  ... and {len(bundles) - 5} more")

    # Emit a tiny index file for consumers that don't want to re-scan.
    index = FIXTURE_DIR / "_index.json"
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps([str(b.relative_to(HERE)) for b in bundles], indent=2))
