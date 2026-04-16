"""
ai_pipeline/hcc_mapper.py
=========================

ICD-10 -> HCC mapper for the AI pipeline with age/sex/ESRD gate validation.

Authoritative CMS-HCC semantics already live in ``hcc_mapping_service`` (which
wraps ``hccinfhir``). This module layers two pipeline-specific concerns on
top of that canonical source:

  1. Demographic gate validation (age_min / age_max / sex / esrd_only).
     ``hccinfhir`` does not enforce these at the single-code lookup level;
     the pipeline must refuse to surface HCCs that are demographically
     invalid for the member.

  2. A curated CSV override layer (``data/hcc_v24.csv`` / ``data/hcc_v28.csv``)
     so analysts can hand-tune top-frequency mappings, add new codes ahead
     of a ``hccinfhir`` release, or pin labels for the UI without waiting
     on an upstream version bump.

CSV lookups take precedence. If the ICD-10 code is not in the CSV we fall
through to ``hcc_mapping_service.map_icd10_to_hcc``.

Public API
----------
map_icd_to_hcc(icd10, age, sex, model, *, has_esrd=False) -> HCCMapping | None
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

ModelVersion = Literal["V24", "V28"]

_DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class HCCMapping:
    icd10: str
    hcc: str
    label: str
    model: str
    source: str  # "csv" | "hccinfhir"
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    sex: Optional[str] = None  # "M" | "F" | None
    esrd_only: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_int(v: str) -> Optional[int]:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _parse_bool(v: str) -> bool:
    return (v or "").strip().lower() in {"1", "true", "t", "yes", "y"}


@lru_cache(maxsize=1)
def _load_csv(model: ModelVersion) -> dict[str, dict]:
    """Load and index the CSV for a given model version.

    Returns a dict keyed by normalized ICD-10 (uppercase, no dot). A single
    ICD-10 can only map to one HCC per model version in this curated layer.
    """
    by_icd: dict[str, dict] = {}
    # Both CSVs carry both model columns so we read both files and prefer
    # V28-specific file entries when model == "V28".
    files = [_DATA_DIR / "hcc_v24.csv"]
    if model == "V28":
        files.append(_DATA_DIR / "hcc_v28.csv")

    hcc_col = "hcc_v24" if model == "V24" else "hcc_v28"

    for path in files:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(
                (line for line in fh if not line.lstrip().startswith("#"))
            )
            for row in reader:
                icd = (row.get("icd10") or "").strip().upper().replace(".", "")
                hcc_val = (row.get(hcc_col) or "").strip()
                if not icd or not hcc_val:
                    continue
                by_icd[icd] = {
                    "icd10": icd,
                    "hcc": hcc_val,
                    "label": (row.get("hcc_label") or "").strip(),
                    "age_min": _parse_int(row.get("age_min", "")),
                    "age_max": _parse_int(row.get("age_max", "")),
                    "sex": ((row.get("sex") or "").strip().upper() or None),
                    "esrd_only": _parse_bool(row.get("esrd_only", "")),
                }
    return by_icd


def _gates_pass(
    row: dict,
    age: Optional[int],
    sex: Optional[str],
    has_esrd: bool,
) -> tuple[bool, str]:
    sex_norm = (sex or "").strip().upper() or None
    if row.get("age_min") is not None and age is not None and age < row["age_min"]:
        return False, f"age<{row['age_min']}"
    if row.get("age_max") is not None and age is not None and age > row["age_max"]:
        return False, f"age>{row['age_max']}"
    if row.get("sex") and sex_norm and sex_norm != row["sex"]:
        return False, f"sex!={row['sex']}"
    if row.get("esrd_only") and not has_esrd:
        return False, "esrd_required"
    return True, ""


def map_icd_to_hcc(
    icd10: str,
    age: Optional[int],
    sex: Optional[str],
    model: ModelVersion = "V28",
    *,
    has_esrd: bool = False,
) -> Optional[HCCMapping]:
    """Map an ICD-10 code to a CMS-HCC category, applying demographic gates.

    Returns None if the code does not map or if a gate rejects the candidate.
    """
    if not icd10:
        return None
    if model not in ("V24", "V28"):
        raise ValueError(f"Unsupported model version: {model}")

    key = icd10.strip().upper().replace(".", "")
    csv_index = _load_csv(model)
    row = csv_index.get(key)

    if row:
        ok, reason = _gates_pass(row, age, sex, has_esrd)
        if not ok:
            logger.debug("hcc_mapper gate reject %s %s: %s", key, model, reason)
            return None
        return HCCMapping(
            icd10=key,
            hcc=str(row["hcc"]),
            label=row["label"],
            model=model,
            source="csv",
            age_min=row.get("age_min"),
            age_max=row.get("age_max"),
            sex=row.get("sex"),
            esrd_only=row.get("esrd_only", False),
        )

    # Fallback: canonical hccinfhir mapping (no gate metadata available).
    try:
        from app.services.hcc_mapping_service import map_icd10_to_hcc as _canonical
    except Exception:  # pragma: no cover - import safety
        return None

    try:
        canon = _canonical(key, model)
    except Exception as exc:
        logger.warning("hcc_mapper fallback error for %s/%s: %s", key, model, exc)
        return None
    if not canon:
        return None

    hcc = canon.get("hcc") or canon.get("hcc_category")
    if not hcc:
        return None
    return HCCMapping(
        icd10=key,
        hcc=str(hcc),
        label=canon.get("label") or canon.get("hcc_label") or "",
        model=model,
        source="hccinfhir",
    )


__all__ = ["HCCMapping", "map_icd_to_hcc"]
