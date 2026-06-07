"""
C-CDA XML Parser — Direct Trust inbound extraction layer
=========================================================
Provides a lightweight, stdlib-only ``parse_ccda_xml(xml_bytes)`` function
that extracts structured clinical data from a Consolidated Clinical Document
Architecture (C-CDA / CCD) XML document and returns a plain dict suitable
for downstream persistence and HCC suspect routing.

Design decisions
----------------
- Uses ``defusedxml.ElementTree`` to guard against XXE attacks on untrusted
  inbound payloads (drop-in replacement for ``xml.etree.ElementTree``).
- Delegates ICD-10 → HCC crosswalk to the existing ``hcc_icd10_crosswalk``
  table via ``app.db.raf_cursor``.  Falls back gracefully when the DB is
  unavailable (unit-test context).
- All date values are returned as ISO-8601 strings (``str | None``) so the
  dict is directly JSON-serialisable.
- S/MIME verification is deliberately outside scope here; the caller
  (``routers/direct_inbound.py``) validates trust anchors before invoking
  this module.

Sections parsed
---------------
  problems    → ICD-10 code + onset date + HCC mapping
  medications → RxNorm code + dose
  results     → LOINC code + value + date
  encounters  → start, end, encounter type, provider NPI
  allergies   → substance, reaction, severity

``defusedxml.ElementTree`` is used instead of ``xml.etree.ElementTree`` to
block XXE, billion-laughs, and quadratic-blowup attacks on untrusted
inbound payloads received from external EHRs.
"""
from __future__ import annotations

import logging
import defusedxml.ElementTree as ET
from xml.etree.ElementTree import Element as _ETElement  # safe: only used for sentinel construction, never for parsing
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CDA namespace
# ---------------------------------------------------------------------------

_CDA_NS = "urn:hl7-org:v3"


def _cda(tag: str) -> str:
    """Return ``{urn:hl7-org:v3}tag`` for ElementTree lookups."""
    return f"{{{_CDA_NS}}}{tag}"


# Allergy severity SNOMED → human label map
_SEVERITY_MAP: dict[str, str] = {
    "255604002": "mild",
    "6736007":   "moderate",
    "24484000":  "severe",
    "399166001": "fatal",
}

# Section template IDs (C-CDA R2.1)
_TMPL_PROBLEMS    = "2.16.840.1.113883.10.20.22.2.5.1"
_TMPL_MEDICATIONS = "2.16.840.1.113883.10.20.22.2.1.1"
_TMPL_RESULTS     = "2.16.840.1.113883.10.20.22.2.3.1"
_TMPL_ENCOUNTERS  = "2.16.840.1.113883.10.20.22.2.22.1"
_TMPL_ALLERGIES   = "2.16.840.1.113883.10.20.22.2.6.1"

# OID constants
_OID_NPI       = "2.16.840.1.113883.4.6"
_OID_SNOMED    = "2.16.840.1.113883.6.96"
_OID_ICD10CM   = "2.16.840.1.113883.6.90"
_OID_RXNORM    = "2.16.840.1.113883.6.88"
_OID_LOINC     = "2.16.840.1.113883.6.1"

# Max bytes accepted (20 MB)
_MAX_BYTES = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _attr(elem: ET.Element | None, name: str, default: str = "") -> str:
    if elem is None:
        return default
    return elem.get(name, default)


def _text(elem: ET.Element | None) -> str | None:
    if elem is None:
        return None
    t = (elem.text or "").strip()
    return t or None


def _parse_date(value: str | None) -> str | None:
    """Parse CDA yyyymmdd[HHmmss±zzzz] date value to ISO date string."""
    if not value:
        return None
    raw = value[:8]
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _find_section(root: ET.Element, template_id: str) -> ET.Element | None:
    """Locate a CDA section by templateId/@root."""
    for section in root.iter(_cda("section")):
        for tid in section.findall(_cda("templateId")):
            if tid.get("root") == template_id:
                return section
    return None


def _display_name(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    dn = elem.get("displayName", "")
    if dn:
        return dn
    orig = elem.find(_cda("originalText"))
    return _text(orig) or ""


# ---------------------------------------------------------------------------
# ICD-10 → HCC crosswalk (DB-backed, degrades gracefully)
# ---------------------------------------------------------------------------

def _icd10_to_hcc(icd10: str) -> tuple[str | None, str | None]:
    """Return (hcc_code, hcc_description) from ``hcc_icd10_crosswalk``.

    Returns ``(None, None)`` when:
    - ``icd10`` is empty / None.
    - The table is not populated or the DB is unavailable (unit-test context).
    """
    if not icd10:
        return None, None
    try:
        from app.db import raf_cursor  # deferred import keeps module test-friendly
        with raf_cursor() as cur:
            cur.execute(
                "SELECT hcc_code, hcc_description "
                "FROM hcc_icd10_crosswalk "
                "WHERE icd10_code = %s "
                "ORDER BY model_year DESC LIMIT 1",
                (icd10,),
            )
            row = cur.fetchone()
            if row:
                return str(row["hcc_code"]), row.get("hcc_description")
    except Exception as exc:
        logger.debug("HCC crosswalk lookup skipped for %s: %s", icd10, exc)
    return None, None


# ---------------------------------------------------------------------------
# Patient identifier extraction
# ---------------------------------------------------------------------------

def _extract_patient_identifiers(root: ET.Element) -> dict[str, Any]:
    """Extract MRN, SSN, DOB, name, sex from the CDA recordTarget."""
    identifiers: dict[str, Any] = {
        "mrn": None,
        "ssn": None,
        "first_name": None,
        "last_name": None,
        "date_of_birth": None,
        "gender": None,
        "additional_ids": [],
    }

    record_target = root.find(_cda("recordTarget"))
    if record_target is None:
        return identifiers

    patient_role = record_target.find(_cda("patientRole"))
    if patient_role is None:
        return identifiers

    # IDs
    for id_elem in patient_role.findall(_cda("id")):
        root_oid = id_elem.get("root", "")
        ext = id_elem.get("extension", "")
        # Common MRN OIDs — 2.16.840.1.113883.4.1 = SSN
        if root_oid == "2.16.840.1.113883.4.1":
            identifiers["ssn"] = ext
        elif ext:
            if identifiers["mrn"] is None:
                identifiers["mrn"] = ext
            else:
                identifiers["additional_ids"].append({"root": root_oid, "extension": ext})

    # Patient demographics
    patient = patient_role.find(_cda("patient"))
    if patient is not None:
        name_elem = patient.find(_cda("name"))
        if name_elem is not None:
            given = _text(name_elem.find(_cda("given"))) or ""
            family = _text(name_elem.find(_cda("family"))) or ""
            identifiers["first_name"] = given or None
            identifiers["last_name"] = family or None

        birth_time = patient.find(_cda("birthTime"))
        if birth_time is not None:
            identifiers["date_of_birth"] = _parse_date(_attr(birth_time, "value"))

        admin_gender = patient.find(_cda("administrativeGenderCode"))
        if admin_gender is not None:
            code = admin_gender.get("code", "")
            identifiers["gender"] = {"M": "male", "F": "female"}.get(code, code.lower() or None)

    return identifiers


# ---------------------------------------------------------------------------
# Section: Problems
# ---------------------------------------------------------------------------

def _parse_problems(section: ET.Element) -> list[dict]:
    problems: list[dict] = []

    for act in section.iter(_cda("act")):
        for obs in act.iter(_cda("observation")):
            if obs.get("moodCode", "") not in ("EVN", ""):
                continue

            # Status
            status_elem = obs.find(f".//{_cda('statusCode')}")
            raw_status = _attr(status_elem, "code", "active").lower()
            if raw_status == "completed":
                status = "resolved"
            elif raw_status in ("aborted", "cancelled", "nullified", "obsolete"):
                status = "inactive"
            else:
                status = "active"

            # Code
            value_elem = obs.find(_cda("value"))
            snomed_code: str | None = None
            icd10_code: str | None = None
            problem_name: str = "Unknown problem"

            if value_elem is not None:
                cs = value_elem.get("codeSystem", "")
                raw_code = value_elem.get("code", "")
                problem_name = _display_name(value_elem) or raw_code

                if cs == _OID_SNOMED:
                    snomed_code = raw_code
                elif cs == _OID_ICD10CM:
                    icd10_code = raw_code.replace(".", "")

                # Translation may carry ICD-10 even when primary is SNOMED
                for trans in value_elem.findall(_cda("translation")):
                    if trans.get("codeSystem") == _OID_ICD10CM:
                        icd10_code = trans.get("code", "").replace(".", "")
                        break

            # Onset / resolved dates
            eff = obs.find(_cda("effectiveTime"))
            onset_date: str | None = None
            resolved_date: str | None = None
            if eff is not None:
                low = eff.find(_cda("low"))
                high = eff.find(_cda("high"))
                onset_date = _parse_date(
                    _attr(low, "value") if low is not None else _attr(eff, "value")
                )
                if high is not None and not high.get("nullFlavor"):
                    resolved_date = _parse_date(_attr(high, "value"))

            # HCC mapping
            hcc_code, hcc_description = _icd10_to_hcc(icd10_code) if icd10_code else (None, None)

            problems.append({
                "snomed_code": snomed_code,
                "icd10_code": icd10_code,
                "problem_name": problem_name,
                "onset_date": onset_date,
                "resolved_date": resolved_date,
                "status": status,
                "hcc_code": hcc_code,
                "hcc_description": hcc_description,
            })

    return problems


# ---------------------------------------------------------------------------
# Section: Medications
# ---------------------------------------------------------------------------

def _parse_medications(section: ET.Element) -> list[dict]:
    medications: list[dict] = []

    for sub_act in section.iter(_cda("substanceAdministration")):
        consumable = sub_act.find(f".//{_cda('manufacturedMaterial')}")
        code_elem = consumable.find(_cda("code")) if consumable is not None else None

        rxnorm_code: str | None = None
        medication_name: str = "Unknown medication"

        if code_elem is not None:
            cs = code_elem.get("codeSystem", "")
            if cs == _OID_RXNORM:
                rxnorm_code = code_elem.get("code")
            medication_name = _display_name(code_elem) or medication_name

        if medication_name == "Unknown medication" and consumable is not None:
            name_elem = consumable.find(_cda("name"))
            medication_name = _text(name_elem) or medication_name

        # Dose
        dose_qty = sub_act.find(_cda("doseQuantity"))
        dose: str | None = None
        if dose_qty is not None:
            val = dose_qty.get("value", "")
            unit = dose_qty.get("unit", "")
            dose = f"{val} {unit}".strip() if val else None

        # Route
        route_elem = sub_act.find(_cda("routeCode"))
        route: str | None = _attr(route_elem, "displayName") if route_elem is not None else None

        # Status
        status_elem = sub_act.find(f".//{_cda('statusCode')}")
        med_status = _attr(status_elem, "code", "active")

        medications.append({
            "rxnorm_code": rxnorm_code,
            "medication_name": medication_name,
            "dose": dose,
            "route": route,
            "status": med_status,
        })

    return medications


# ---------------------------------------------------------------------------
# Section: Results (labs)
# ---------------------------------------------------------------------------

def _parse_results(section: ET.Element) -> list[dict]:
    results: list[dict] = []

    for organizer in section.iter(_cda("organizer")):
        for obs in organizer.iter(_cda("observation")):
            code_elem = obs.find(_cda("code"))
            loinc_code: str | None = None
            test_name: str = "Unknown test"

            if code_elem is not None:
                cs = code_elem.get("codeSystem", "")
                if cs == _OID_LOINC:
                    loinc_code = code_elem.get("code")
                test_name = _display_name(code_elem) or test_name

            # Value
            value_elem = obs.find(_cda("value"))
            value_text: str | None = None
            unit: str | None = None

            if value_elem is not None:
                xsi_type = value_elem.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
                if "PQ" in xsi_type or value_elem.get("unit"):
                    raw_val = value_elem.get("value", "")
                    unit = value_elem.get("unit")
                    value_text = f"{raw_val} {unit or ''}".strip() if raw_val else None
                else:
                    value_text = _attr(value_elem, "displayName") or _text(value_elem)

            # Result date
            eff = obs.find(_cda("effectiveTime"))
            result_date: str | None = None
            if eff is not None:
                result_date = _parse_date(
                    _attr(eff, "value") or _attr(eff.find(_cda("low")) or _ETElement("x"), "value")
                )

            if test_name == "Unknown test" and loinc_code is None:
                continue  # skip noise

            results.append({
                "loinc_code": loinc_code,
                "test_name": test_name,
                "value": value_text,
                "unit": unit,
                "result_date": result_date,
            })

    return results


# ---------------------------------------------------------------------------
# Section: Encounters
# ---------------------------------------------------------------------------

def _parse_encounters(section: ET.Element) -> list[dict]:
    encounters: list[dict] = []

    for enc in section.iter(_cda("encounter")):
        code_elem = enc.find(_cda("code"))
        enc_type = _attr(code_elem, "displayName") if code_elem is not None else "Encounter"

        eff = enc.find(_cda("effectiveTime"))
        start_date: str | None = None
        end_date: str | None = None
        if eff is not None:
            low = eff.find(_cda("low"))
            high = eff.find(_cda("high"))
            start_date = _parse_date(
                _attr(low, "value") if low is not None else _attr(eff, "value")
            )
            if high is not None and not high.get("nullFlavor"):
                end_date = _parse_date(_attr(high, "value"))

        # Provider NPI
        provider_npi: str | None = None
        for performer in enc.iter(_cda("performer")):
            for id_elem in performer.iter(_cda("id")):
                if id_elem.get("root") == _OID_NPI:
                    provider_npi = id_elem.get("extension")
                    break

        encounters.append({
            "type": enc_type,
            "start_date": start_date,
            "end_date": end_date,
            "provider_npi": provider_npi,
        })

    return encounters


# ---------------------------------------------------------------------------
# Section: Allergies
# ---------------------------------------------------------------------------

def _parse_allergies(section: ET.Element) -> list[dict]:
    allergies: list[dict] = []

    for act in section.iter(_cda("act")):
        for obs in act.iter(_cda("observation")):
            # Allergy observation classCode check
            if obs.get("classCode") not in ("OBS", ""):
                continue

            # Substance (participant / playingEntity)
            substance: str | None = None
            for participant in obs.iter(_cda("participant")):
                playing = participant.find(f".//{_cda('playingEntity')}")
                if playing is not None:
                    code_elem = playing.find(_cda("code"))
                    substance = _display_name(code_elem) or _text(playing.find(_cda("name")))
                    if substance:
                        break

            # Reaction
            reaction: str | None = None
            severity: str | None = None
            for ent_rel in obs.iter(_cda("entryRelationship")):
                inner_obs = ent_rel.find(_cda("observation"))
                if inner_obs is None:
                    continue
                tid_elems = inner_obs.findall(_cda("templateId"))
                roots = {t.get("root") for t in tid_elems}
                # Reaction template 2.16.840.1.113883.10.20.22.4.9
                if "2.16.840.1.113883.10.20.22.4.9" in roots:
                    val = inner_obs.find(_cda("value"))
                    reaction = _display_name(val) if val is not None else None
                # Severity template 2.16.840.1.113883.10.20.22.4.8
                if "2.16.840.1.113883.10.20.22.4.8" in roots:
                    val = inner_obs.find(_cda("value"))
                    if val is not None:
                        snomed_sev = val.get("code", "")
                        severity = _SEVERITY_MAP.get(snomed_sev, _display_name(val) or None)

            if substance or reaction:
                allergies.append({
                    "substance": substance,
                    "reaction": reaction,
                    "severity": severity,
                })

    return allergies


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_ccda_xml(xml_bytes: bytes) -> dict[str, Any]:
    """Parse a C-CDA XML document and return a structured dict.

    Parameters
    ----------
    xml_bytes:
        Raw bytes of the C-CDA XML document.  Must be <= 20 MB.

    Returns
    -------
    dict with keys:
        ``patient``          — identifiers (MRN, SSN, name, DOB, gender)
        ``problems``         — list of {icd10_code, onset_date, hcc_code, ...}
        ``medications``      — list of {rxnorm_code, dose, ...}
        ``results``          — list of {loinc_code, value, result_date, ...}
        ``encounters``       — list of {type, start_date, end_date, provider_npi}
        ``allergies``        — list of {substance, reaction, severity}
        ``hcc_suspects``     — deduplicated list of HCC codes found in problems
        ``parse_warnings``   — non-fatal issues encountered during parsing

    Raises
    ------
    ValueError
        If ``xml_bytes`` exceeds 20 MB or cannot be parsed as XML.
    """
    if len(xml_bytes) > _MAX_BYTES:
        raise ValueError(
            f"C-CDA document exceeds maximum size ({_MAX_BYTES // 1024 // 1024} MB)"
        )

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc

    warnings: list[str] = []

    # Validate root element
    if root.tag != _cda("ClinicalDocument"):
        warnings.append(
            f"Root element {root.tag!r} is not ClinicalDocument — "
            "document may parse with reduced fidelity"
        )

    # Patient identifiers
    patient = _extract_patient_identifiers(root)

    # Sections
    problems_section   = _find_section(root, _TMPL_PROBLEMS)
    medications_section = _find_section(root, _TMPL_MEDICATIONS)
    results_section    = _find_section(root, _TMPL_RESULTS)
    encounters_section = _find_section(root, _TMPL_ENCOUNTERS)
    allergies_section  = _find_section(root, _TMPL_ALLERGIES)

    problems   = _parse_problems(problems_section)   if problems_section   else []
    medications = _parse_medications(medications_section) if medications_section else []
    results    = _parse_results(results_section)     if results_section    else []
    encounters = _parse_encounters(encounters_section) if encounters_section else []
    allergies  = _parse_allergies(allergies_section) if allergies_section  else []

    if not problems_section:
        warnings.append("Problems section not found")
    if not medications_section:
        warnings.append("Medications section not found")
    if not results_section:
        warnings.append("Results section not found")

    # Deduplicated HCC suspect list (non-null HCC codes from problems)
    hcc_suspects: list[str] = list(
        dict.fromkeys(
            p["hcc_code"] for p in problems if p.get("hcc_code")
        )
    )

    return {
        "patient": patient,
        "problems": problems,
        "medications": medications,
        "results": results,
        "encounters": encounters,
        "allergies": allergies,
        "hcc_suspects": hcc_suspects,
        "parse_warnings": warnings,
    }
