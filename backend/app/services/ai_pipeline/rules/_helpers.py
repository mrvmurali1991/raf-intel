"""Bundle-inspection helpers shared across rule modules.

``bundle`` is the PatientContextBundle dict from Agent 4.  Expected
(best-effort) shape::

    {
      "labs":        [{"id","loinc","name","value","unit","date"}, ...],
      "medications": [{"id","rxnorm","name","class","active"}, ...],
      "vitals":      [{"id","type","value","unit","date"}, ...],
      "problem_list":[{"icd10","description","active"}, ...],
      "prior_hccs":  [{"hcc","icd10","year"}, ...],
    }

All helpers are defensive — missing keys return empty iterables.
"""
from __future__ import annotations

from typing import Iterable


def labs(bundle: dict, *names: str, loincs: tuple[str, ...] = ()) -> list[dict]:
    names_l = {n.lower() for n in names}
    out: list[dict] = []
    for lab in bundle.get("labs") or []:
        name = str(lab.get("name", "")).lower()
        loinc = str(lab.get("loinc", ""))
        if names_l and any(n in name for n in names_l):
            out.append(lab)
        elif loincs and loinc in loincs:
            out.append(lab)
    return out


def latest_lab(bundle: dict, *names: str, loincs: tuple[str, ...] = ()) -> dict | None:
    matches = labs(bundle, *names, loincs=loincs)
    if not matches:
        return None
    return max(matches, key=lambda r: str(r.get("date", "")))


def lab_values_above(bundle: dict, threshold: float, *names: str, min_count: int = 1) -> list[dict]:
    hits = [l for l in labs(bundle, *names) if _num(l.get("value")) is not None and _num(l.get("value")) >= threshold]
    return hits if len(hits) >= min_count else []


def lab_values_below(bundle: dict, threshold: float, *names: str, min_count: int = 1) -> list[dict]:
    hits = [l for l in labs(bundle, *names) if _num(l.get("value")) is not None and _num(l.get("value")) <= threshold]
    return hits if len(hits) >= min_count else []


def has_med(bundle: dict, *keywords: str) -> dict | None:
    kws = {k.lower() for k in keywords}
    for med in bundle.get("medications") or []:
        if not med.get("active", True):
            continue
        name = str(med.get("name", "")).lower()
        cls = str(med.get("class", "")).lower()
        if any(k in name or k in cls for k in kws):
            return med
    return None


def has_icd_prefix(bundle: dict, *prefixes: str) -> bool:
    active = [p for p in (bundle.get("problem_list") or []) if p.get("active", True)]
    for p in active:
        code = str(p.get("icd10", "")).upper()
        if any(code.startswith(pref.upper()) for pref in prefixes):
            return True
    return False


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evidence_from_labs(rows: Iterable[dict]):
    from ..suspect_schema import SupportingEvidence
    return [
        SupportingEvidence(
            type="lab",
            ref_id=str(r.get("id") or r.get("loinc") or r.get("name", "")),
            value=f"{r.get('name','?')}={r.get('value')} {r.get('unit','')} on {r.get('date','?')}",
        )
        for r in rows
    ]


def evidence_from_med(med: dict):
    from ..suspect_schema import SupportingEvidence
    return SupportingEvidence(
        type="med",
        ref_id=str(med.get("id") or med.get("rxnorm") or med.get("name", "")),
        value=str(med.get("name", "?")),
    )
