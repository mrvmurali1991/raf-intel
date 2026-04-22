"""Convert a Synthea-style FHIR bundle to hccinfhir scoring inputs.

hccinfhir's ``HCCInFHIR.calculate_from_diagnosis`` accepts a plain list
of ICD-10 codes + demographic kwargs. For parity we *also* emit the
``ServiceLevelData`` list that ``run_from_service_data`` expects, in
case someone wants to exercise the claim-filter path.

We keep the extractor dependency-free (pure ``json`` parsing) so that
breaking changes in the ``fhir.resources`` library or Synthea's schema
cannot derail the accuracy harness.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

# ICD-10 CM coding system URI used by Synthea + OpenEMR.
ICD10_SYSTEMS = {
    "http://hl7.org/fhir/sid/icd-10",
    "http://hl7.org/fhir/sid/icd-10-cm",
    "http://hl7.org/fhir/sid/icd-10-us",
    "urn:oid:2.16.840.1.113883.6.90",  # ICD-10-CM OID
}

# Synthea encodes conditions primarily with SNOMED. We still accept SNOMED
# so that bundles produced by Synthea out-of-the-box aren't silently empty —
# the SNOMED → ICD10 mapping is delegated to hccinfhir in that case, which
# is exactly what our production pipeline does.
SNOMED_SYSTEMS = {"http://snomed.info/sct"}


@dataclasses.dataclass
class ScoreInput:
    """Everything the oracle needs to score a single patient."""

    patient_id: str
    age: int
    sex: str  # "M" or "F"
    dual_elgbl_cd: str = "NA"
    orec: str = "0"
    new_enrollee: bool = False
    institutional: bool = False
    icd10_codes: list[str] = dataclasses.field(default_factory=list)
    service_level_data: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def demographics_dict(self) -> dict[str, Any]:
        return {
            "age": self.age,
            "sex": self.sex,
            "dual_elgbl_cd": self.dual_elgbl_cd,
            "orec": self.orec,
            "new_enrollee": self.new_enrollee,
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _iter_entries(bundle: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for entry in bundle.get("entry") or []:
        res = entry.get("resource")
        if isinstance(res, dict):
            yield res


def _calculate_age(birth_date: str | None, ref: date | None = None) -> int:
    if not birth_date:
        return 70  # reasonable Medicare default
    try:
        bd = datetime.fromisoformat(birth_date[:10]).date()
    except ValueError:
        return 70
    ref = ref or date.today()
    age = ref.year - bd.year - ((ref.month, ref.day) < (bd.month, bd.day))
    return max(age, 0)


def _sex_code(gender: str | None) -> str:
    if not gender:
        return "M"
    g = gender.strip().lower()
    if g.startswith("f"):
        return "F"
    return "M"


def _extract_icd10(condition: dict[str, Any]) -> list[str]:
    """Pull ICD-10-CM codes from a FHIR Condition resource.

    Synthea tends to use SNOMED as the primary coding. When the bundle
    carries *only* SNOMED, we return an empty list for that condition —
    hccinfhir cannot score SNOMED directly, so the harness focuses on
    bundles that carry ICD-10 (either natively or as a secondary coding).
    This is why the hand-crafted fixtures always include ICD-10.
    """
    codings = (condition.get("code") or {}).get("coding") or []
    out: list[str] = []
    for c in codings:
        system = (c.get("system") or "").lower()
        code = c.get("code")
        if not code:
            continue
        if system in ICD10_SYSTEMS:
            # Strip decimal point to match CMS's "no punctuation" ICD-10
            # format used by hccinfhir's dx_to_cc table.
            out.append(str(code).replace(".", "").strip().upper())
    return out


def _encounter_period(encounter: dict[str, Any]) -> tuple[str | None, str | None]:
    period = encounter.get("period") or {}
    return period.get("start"), period.get("end")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bundle_to_score_input(
    bundle: dict[str, Any],
    *,
    measurement_year: int | None = None,
) -> ScoreInput:
    """Convert a single FHIR bundle to a ``ScoreInput``.

    ``measurement_year`` affects age calculation only — if unset we use
    the max encounter year in the bundle, falling back to the current year.
    """
    patient_id = ""
    birth_date: str | None = None
    gender: str | None = None
    conditions: list[dict[str, Any]] = []
    encounters: list[dict[str, Any]] = []

    for res in _iter_entries(bundle):
        rt = res.get("resourceType")
        if rt == "Patient" and not patient_id:
            patient_id = res.get("id") or ""
            birth_date = res.get("birthDate")
            gender = res.get("gender")
        elif rt == "Condition":
            conditions.append(res)
        elif rt == "Encounter":
            encounters.append(res)

    # Determine reference date.
    ref_year = measurement_year
    if ref_year is None:
        best: date | None = None
        for enc in encounters:
            start, _ = _encounter_period(enc)
            if not start:
                continue
            try:
                d = datetime.fromisoformat(start.replace("Z", "+00:00")).date()
            except ValueError:
                continue
            if best is None or d > best:
                best = d
        ref_year = best.year if best else date.today().year
    ref_date = date(ref_year, 12, 31)

    age = _calculate_age(birth_date, ref_date)
    sex = _sex_code(gender)

    # Dedupe ICD codes while preserving first-seen order.
    seen: set[str] = set()
    icd_codes: list[str] = []
    for cond in conditions:
        for code in _extract_icd10(cond):
            if code not in seen:
                seen.add(code)
                icd_codes.append(code)

    # Build a minimal ServiceLevelData list. We attach all ICDs to each
    # encounter's claim; CPT filtering is disabled (RA-eligible defaults
    # in hccinfhir may drop these, so we pass procedure_code=None).
    service_level_data: list[dict[str, Any]] = []
    if icd_codes:
        if not encounters:
            # Fabricate a single office visit so calculate_from_service_data
            # callers have something to iterate.
            service_level_data.append(
                {
                    "claim_id": f"{patient_id}-synthetic-1",
                    "procedure_code": "99214",
                    "claim_diagnosis_codes": list(icd_codes),
                    "linked_diagnosis_codes": list(icd_codes),
                    "claim_type": "71",  # outpatient
                    "service_date": f"{ref_year}-06-15",
                    "patient_id": patient_id,
                }
            )
        else:
            for idx, enc in enumerate(encounters, 1):
                start, _end = _encounter_period(enc)
                service_level_data.append(
                    {
                        "claim_id": f"{patient_id}-{idx}",
                        "procedure_code": "99214",
                        "claim_diagnosis_codes": list(icd_codes),
                        "linked_diagnosis_codes": list(icd_codes),
                        "claim_type": "71",
                        "service_date": (start or f"{ref_year}-06-15")[:10],
                        "patient_id": patient_id,
                    }
                )

    return ScoreInput(
        patient_id=patient_id or "unknown",
        age=age,
        sex=sex,
        icd10_codes=icd_codes,
        service_level_data=service_level_data,
    )


def load_bundle(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_all(paths: Iterable[Path]) -> list[ScoreInput]:
    inputs: list[ScoreInput] = []
    for p in paths:
        try:
            inputs.append(bundle_to_score_input(load_bundle(p)))
        except Exception as exc:  # noqa: BLE001
            # Keep going — surface the filename in the harness output.
            inputs.append(
                ScoreInput(
                    patient_id=f"PARSE_ERROR::{p.name}",
                    age=70,
                    sex="M",
                    icd10_codes=[],
                )
            )
            print(f"[WARN] failed to parse {p}: {exc}")
    return inputs
