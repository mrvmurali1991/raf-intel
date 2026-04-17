"""CMS claims-file ingestion for the RAF engine.

Two formats are supported:

1. **RAPS detail-A records** (Risk Adjustment Processing System).
   The legacy CMS format used before 2016 and still consumed by some
   compliance reports. Each record is a fixed-field pipe-delimited
   line carrying one diagnosis cluster for one beneficiary.

2. **EDS encounter records** (Encounter Data System, post-2016).
   Modern CMS format sourced from 837 encounters. Modelled here as
   a line-oriented JSON ("JSONL") stream — each line is one encounter
   with a ``diagnosis_codes`` list.

Both parsers normalise into the same ``BeneficiaryClaims`` aggregate so
downstream code can feed either into the RAF engine without care about
provenance.

The format specs here are **simplified** for test-harness use. They
exercise the diagnosis → RAF code path end-to-end without us
implementing a full X12 837 parser. A real production ingestion would
replace these with a vendor parser (e.g. CMS's EDPPPS software).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Aggregate model
# ---------------------------------------------------------------------------

@dataclass
class BeneficiaryClaims:
    """All diagnoses for one beneficiary parsed out of a claims file."""

    beneficiary_id: str
    diagnosis_codes: list[str] = field(default_factory=list)
    encounter_count: int = 0
    source_format: str = ""

    def dedup_diagnoses(self) -> list[str]:
        """Return diagnosis codes de-duplicated, preserving first occurrence."""
        seen: set[str] = set()
        out: list[str] = []
        for d in self.diagnosis_codes:
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out


# ---------------------------------------------------------------------------
# Diagnosis-code normalisation
# ---------------------------------------------------------------------------

_ICD10_PATTERN = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](?:\.?[0-9A-Z]{0,4})?$")


def normalise_icd10(raw: str) -> str | None:
    """Strip dots/whitespace and validate ICD-10-CM shape.

    Returns the dotless code in upper case, or ``None`` if the input is
    not a plausible ICD-10-CM code.
    """
    if not raw:
        return None
    cleaned = raw.strip().upper().replace(".", "")
    if not cleaned:
        return None
    # Validate against ICD-10-CM shape: A00 … Z99.ABCD (up to 7 chars).
    if not _ICD10_PATTERN.match(cleaned):
        return None
    return cleaned


# ---------------------------------------------------------------------------
# RAPS parser
# ---------------------------------------------------------------------------

def parse_raps_line(line: str) -> tuple[str, list[str]] | None:
    """Parse one RAPS detail-A record into (beneficiary_id, diagnoses).

    Record layout (pipe-delimited, simplified):

        A|<hicn>|<patient_ctrl>|<from_date>|<thru_date>|<provider_type>|<dx1>|<dx2>|...

    The first field is ``A`` to mark a detail-A diagnosis cluster.
    Lines not starting with ``A|`` are ignored (headers, trailers).
    """
    if not line or not line.startswith("A|"):
        return None
    parts = [p.strip() for p in line.strip().split("|")]
    if len(parts) < 7:
        return None
    hicn = parts[1]
    if not hicn:
        return None
    dx_raw = parts[6:]
    dxs = [normalise_icd10(d) for d in dx_raw]
    return hicn, [d for d in dxs if d]


def parse_raps_file(content: str) -> list[BeneficiaryClaims]:
    """Parse a full RAPS file into per-beneficiary aggregates.

    Diagnoses from multiple records with the same HICN are folded into
    one ``BeneficiaryClaims`` aggregate (de-duplicated at retrieval).
    """
    by_bene: dict[str, BeneficiaryClaims] = {}
    for raw_line in content.splitlines():
        parsed = parse_raps_line(raw_line)
        if parsed is None:
            continue
        hicn, dxs = parsed
        bene = by_bene.setdefault(
            hicn, BeneficiaryClaims(beneficiary_id=hicn, source_format="RAPS")
        )
        bene.diagnosis_codes.extend(dxs)
        bene.encounter_count += 1
    return list(by_bene.values())


# ---------------------------------------------------------------------------
# EDS (JSONL) parser
# ---------------------------------------------------------------------------

def parse_eds_jsonl(content: str) -> list[BeneficiaryClaims]:
    """Parse EDS-style JSONL into per-beneficiary aggregates.

    Each line is a JSON object:

        {
          "beneficiary_id": "...",
          "encounter_id": "...",
          "service_date": "YYYY-MM-DD",
          "diagnosis_codes": ["E11.9", "I50.22"]
        }
    """
    by_bene: dict[str, BeneficiaryClaims] = {}
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        bene_id = record.get("beneficiary_id")
        if not bene_id:
            continue
        dx_raw = record.get("diagnosis_codes") or []
        dxs = [normalise_icd10(d) for d in dx_raw]
        dxs = [d for d in dxs if d]
        bene = by_bene.setdefault(
            bene_id, BeneficiaryClaims(beneficiary_id=bene_id, source_format="EDS")
        )
        bene.diagnosis_codes.extend(dxs)
        bene.encounter_count += 1
    return list(by_bene.values())


# ---------------------------------------------------------------------------
# Convenience: round-trip to an RAF score via hccinfhir
# ---------------------------------------------------------------------------

def score_beneficiary_claims(
    beneficiary: BeneficiaryClaims,
    *,
    age: int,
    sex: str,
    dual_elgbl_cd: str = "NA",
    orec: str = "0",
    new_enrollee: bool = False,
    model_name: str = "CMS-HCC Model V28",
) -> float:
    """End-to-end: BeneficiaryClaims → hccinfhir RAF score.

    Kept thin on purpose — just the round-trip for tests. Real
    integrations will go through ``calculator.calculate_raf_score``.
    """
    from hccinfhir import Demographics, HCCInFHIR

    demo = Demographics(
        age=age, sex=sex, dual_elgbl_cd=dual_elgbl_cd,
        orec=orec, new_enrollee=new_enrollee,
    )
    processor = HCCInFHIR(model_name=model_name)
    result = processor.calculate_from_diagnosis(
        diagnosis_codes=beneficiary.dedup_diagnoses(),
        demographics=demo,
    )
    return round(float(result.risk_score), 6)


__all__ = [
    "BeneficiaryClaims",
    "normalise_icd10",
    "parse_raps_line",
    "parse_raps_file",
    "parse_eds_jsonl",
    "score_beneficiary_claims",
]
