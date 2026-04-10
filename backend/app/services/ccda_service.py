"""
C-CDA / CCD Document Service
=============================
Parses Consolidated Clinical Document Architecture (C-CDA) XML documents and
extracts structured clinical data into the raf_intelligence database.

Supported C-CDA sections
-------------------------
  - Problems          (templateId 2.16.840.1.113883.10.20.22.2.5.1)
  - Medications       (templateId 2.16.840.1.113883.10.20.22.2.1.1)
  - Results / Labs    (templateId 2.16.840.1.113883.10.20.22.2.3.1)
  - Encounters        (templateId 2.16.840.1.113883.10.20.22.2.22.1)
  - Procedures        (templateId 2.16.840.1.113883.10.20.22.2.7.1)
  - Vital Signs       (templateId 2.16.840.1.113883.10.20.22.2.4.1)

SNOMED → ICD-10 crosswalk
--------------------------
A lightweight in-process mapping covers the most common RAF-relevant SNOMED
codes.  When a SNOMED code is not found in the local map the service falls
back to the snomed_icd10_crosswalk database table (if it exists); failing that
the icd10_code column is left NULL and the problem is stored under its SNOMED
code only.

ICD-10 → HCC mapping
----------------------
Uses the hcc_icd10_crosswalk table already present in the raf_intelligence
schema (populated by 001_fhir_integration.sql).

C-CDA Export
------------
generate_ccda_export() builds a minimal but structurally valid CCD document
for a patient using data from ccda_problems, ccda_medications, and
ccda_results tables.  The output is a UTF-8 encoded XML string.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CDA XML namespace map — ElementTree requires the full URI in {uri}tag form.
_NS = {
    "cda":  "urn:hl7-org:v3",
    "xsi":  "http://www.w3.org/2001/XMLSchema-instance",
    "sdtc": "urn:hl7-org:sdtc",
}

# Section templateIds used to identify sections by their template root.
_SECTION_TEMPLATES = {
    "problems":    "2.16.840.1.113883.10.20.22.2.5.1",
    "medications": "2.16.840.1.113883.10.20.22.2.1.1",
    "results":     "2.16.840.1.113883.10.20.22.2.3.1",
    "encounters":  "2.16.840.1.113883.10.20.22.2.22.1",
    "procedures":  "2.16.840.1.113883.10.20.22.2.7.1",
    "vitals":      "2.16.840.1.113883.10.20.22.2.4.1",
}

# NPI OID used to extract NPI values from id elements
_NPI_OID = "2.16.840.1.113883.4.6"

# Max XML file size accepted for parsing (20 MB)
MAX_CCDA_SIZE_BYTES = 20 * 1024 * 1024

# Project root — two levels above /backend/app/services/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CCDA_UPLOADS_BASE = _PROJECT_ROOT / "uploads" / "ccda"

# ---------------------------------------------------------------------------
# Lightweight SNOMED → ICD-10 crosswalk (top RAF-relevant codes)
# ---------------------------------------------------------------------------
# This covers conditions that frequently appear in CCDs and map to HCC
# categories.  Full crosswalk should be loaded from the database at runtime
# via _snomed_to_icd10_db().
_SNOMED_ICD10_MAP: dict[str, str] = {
    # Diabetes
    "44054006":  "E11.9",   # Type 2 diabetes mellitus
    "73211009":  "E11.9",   # Diabetes mellitus
    "46635009":  "E10.9",   # Type 1 diabetes mellitus
    "314771006": "E11.65",  # DM2 with hyperglycaemia
    # Heart failure
    "84114007":  "I50.9",   # Heart failure
    "48447003":  "I50.9",   # Chronic heart failure
    "82523003":  "I50.1",   # Left heart failure
    # COPD / Respiratory
    "13645005":  "J44.1",   # COPD
    "195967001": "J45.909", # Asthma
    # CKD
    "709044004": "N18.9",   # Chronic kidney disease
    "431855005": "N18.1",   # CKD stage 1
    "431856006": "N18.2",   # CKD stage 2
    "433144002": "N18.3",   # CKD stage 3
    "431857002": "N18.4",   # CKD stage 4
    "433146000": "N18.5",   # CKD stage 5
    # CAD / MI
    "53741008":  "I25.10",  # CAD
    "57054005":  "I21.9",   # Acute MI
    "22298006":  "I21.9",   # MI
    # Stroke / CVA
    "230690007": "I63.9",   # Cerebral infarction
    "266257000": "I63.9",   # TIA/stroke
    # Cancer (general)
    "363346000": "C80.1",   # Malignant neoplasm
    # Depression
    "370143000": "F32.9",   # Major depressive disorder
    "35489007":  "F32.9",   # Depressive disorder
    # Atrial fibrillation
    "49436004":  "I48.91",  # Atrial fibrillation
    # Hypertension
    "38341003":  "I10",     # Hypertension
    "59621000":  "I10",     # Essential hypertension
    # Hyperlipidemia
    "55822004":  "E78.5",   # Hyperlipidemia
    "13644009":  "E78.00",  # Hypercholesterolemia
    # Obesity
    "414916001": "E66.9",   # Obesity
    "238131007": "E66.01",  # Morbid obesity
    # Peripheral vascular disease
    "400047006": "I73.9",   # PVD
    # Rheumatoid arthritis
    "69896004":  "M06.9",   # RA
}


def _snomed_to_icd10(snomed_code: str) -> str | None:
    """Return ICD-10 code for a SNOMED CT code.

    Checks the in-process map first, then queries the database.
    Returns None when no mapping is found.
    """
    if not snomed_code:
        return None

    # 1. Fast in-process lookup
    icd10 = _SNOMED_ICD10_MAP.get(snomed_code)
    if icd10:
        return icd10

    # 2. Database lookup (table may not exist in all deployments)
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT icd10_code FROM snomed_icd10_crosswalk "
                "WHERE snomed_code = %s LIMIT 1",
                (snomed_code,),
            )
            row = cur.fetchone()
            if row:
                return row["icd10_code"]
    except Exception:
        # Table does not exist or query failed — degrade gracefully
        pass

    return None


def _icd10_to_hcc(icd10_code: str) -> tuple[str | None, str | None]:
    """Return (hcc_code, hcc_description) for an ICD-10 code using the
    hcc_icd10_crosswalk table.  Returns (None, None) on miss."""
    if not icd10_code:
        return None, None
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT hcc_code, hcc_description "
                "FROM hcc_icd10_crosswalk "
                "WHERE icd10_code = %s "
                "ORDER BY model_year DESC LIMIT 1",
                (icd10_code,),
            )
            row = cur.fetchone()
            if row:
                return str(row["hcc_code"]), row.get("hcc_description")
    except Exception as exc:
        logger.debug("HCC crosswalk lookup failed for %s: %s", icd10_code, exc)
    return None, None


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _cda(tag: str) -> str:
    """Return fully-qualified CDA element name for ElementTree."""
    return f"{{urn:hl7-org:v3}}{tag}"


def _attr(element: ET.Element | None, attr: str, default: str = "") -> str:
    if element is None:
        return default
    return element.get(attr, default)


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    t = element.text
    if t:
        return t.strip() or None
    return None


def _parse_cda_date(value: str | None) -> date | None:
    """Parse CDA effectiveTime value attribute (yyyymmdd[HHMMSS±ZZZZ]) to date."""
    if not value:
        return None
    # Strip everything after the 8-character date portion
    value = value[:8]
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _find_section(root: ET.Element, template_id: str) -> ET.Element | None:
    """Locate a CDA section by its templateId root attribute."""
    for section in root.iter(_cda("section")):
        for tid in section.findall(_cda("templateId")):
            if tid.get("root") == template_id:
                return section
    return None


def _display_name(code_elem: ET.Element | None) -> str:
    """Extract displayName from a CDA code element."""
    if code_elem is None:
        return ""
    dn = code_elem.get("displayName", "")
    if dn:
        return dn
    orig = code_elem.find(_cda("originalText"))
    if orig is not None:
        return _text(orig) or ""
    return ""


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

def _parse_problems(section: ET.Element) -> list[dict]:
    """Extract problem list entries from a CDA Problems section."""
    problems: list[dict] = []

    for act in section.iter(_cda("act")):
        # Each problem act contains an observation
        for obs in act.iter(_cda("observation")):
            # Ignore non-problem observations
            mood = obs.get("moodCode", "")
            if mood not in ("EVN", ""):
                continue

            # Status
            status_elem = obs.find(f".//{_cda('statusCode')}")
            raw_status = _attr(status_elem, "code", "active").lower()
            if raw_status in ("completed",):
                status = "resolved"
            elif raw_status in ("aborted", "cancelled", "nullified", "obsolete"):
                status = "inactive"
            else:
                status = "active"

            # Value element carries the diagnosis code
            value_elem = obs.find(_cda("value"))
            snomed_code: str | None = None
            icd10_code: str | None = None
            problem_name: str = "Unknown problem"

            if value_elem is not None:
                code_system = value_elem.get("codeSystem", "")
                raw_code = value_elem.get("code", "")
                problem_name = _display_name(value_elem) or raw_code

                # 2.16.840.1.113883.6.96 = SNOMED CT
                if code_system == "2.16.840.1.113883.6.96":
                    snomed_code = raw_code
                    icd10_code = _snomed_to_icd10(snomed_code)
                # 2.16.840.1.113883.6.90 = ICD-10-CM
                elif code_system == "2.16.840.1.113883.6.90":
                    icd10_code = raw_code.replace(".", "")

                # Translation element may carry ICD-10 even when primary is SNOMED
                for trans in value_elem.findall(_cda("translation")):
                    if trans.get("codeSystem") == "2.16.840.1.113883.6.90":
                        icd10_code = trans.get("code", "").replace(".", "")
                        break

            # Effective time (onset / resolution)
            eff = obs.find(_cda("effectiveTime"))
            onset_date: date | None = None
            resolved_date: date | None = None
            if eff is not None:
                low = eff.find(_cda("low"))
                high = eff.find(_cda("high"))
                onset_date = _parse_cda_date(_attr(low, "value") if low is not None else _attr(eff, "value"))
                if high is not None and not high.get("nullFlavor"):
                    resolved_date = _parse_cda_date(_attr(high, "value"))

            # HCC mapping
            hcc_code, hcc_desc = _icd10_to_hcc(icd10_code) if icd10_code else (None, None)

            problems.append({
                "snomed_code": snomed_code,
                "icd10_code": icd10_code,
                "problem_name": problem_name,
                "onset_date": onset_date,
                "resolved_date": resolved_date,
                "status": status,
                "hcc_code": hcc_code,
                "hcc_description": hcc_desc,
                "source_section": "problems",
            })

    return problems


def _parse_medications(section: ET.Element) -> list[dict]:
    """Extract medication entries from a CDA Medications section."""
    medications: list[dict] = []

    for sub_act in section.iter(_cda("substanceAdministration")):
        # Medication name
        consumable = sub_act.find(f".//{_cda('manufacturedMaterial')}")
        code_elem = consumable.find(_cda("code")) if consumable is not None else None
        rxnorm_code: str | None = None
        medication_name: str = "Unknown medication"

        if code_elem is not None:
            cs = code_elem.get("codeSystem", "")
            # 2.16.840.1.113883.6.88 = RxNorm
            if cs == "2.16.840.1.113883.6.88":
                rxnorm_code = code_elem.get("code")
            medication_name = _display_name(code_elem) or medication_name

        if medication_name == "Unknown medication" and consumable is not None:
            name_elem = consumable.find(_cda("name"))
            if name_elem is not None:
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

        # Frequency (period-based effectiveTime)
        frequency: str | None = None
        for eff in sub_act.findall(_cda("effectiveTime")):
            period = eff.find(_cda("period"))
            if period is not None:
                pval = period.get("value", "")
                punit = period.get("unit", "")
                frequency = f"every {pval} {punit}".strip() if pval else None
                break
            # Institution-specified timing text
            inst = eff.find(_cda("institutionSpecified"))
            if inst is not None and inst.get("value") == "true":
                frequency = "as directed"
                break

        # Dates from effectiveTime/low / high
        start_date: date | None = None
        end_date: date | None = None
        for eff in sub_act.findall(_cda("effectiveTime")):
            low = eff.find(_cda("low"))
            high = eff.find(_cda("high"))
            if low is not None:
                start_date = _parse_cda_date(_attr(low, "value"))
            if high is not None and not high.get("nullFlavor"):
                end_date = _parse_cda_date(_attr(high, "value"))
            if start_date or end_date:
                break

        # Status
        status_elem = sub_act.find(f".//{_cda('statusCode')}")
        med_status = _attr(status_elem, "code", "active")

        # Prescriber NPI
        prescriber_npi: str | None = None
        for performer in sub_act.iter(_cda("performer")):
            for id_elem in performer.iter(_cda("id")):
                if id_elem.get("root") == _NPI_OID:
                    prescriber_npi = id_elem.get("extension")
                    break

        medications.append({
            "rxnorm_code": rxnorm_code,
            "medication_name": medication_name,
            "dose": dose,
            "route": route,
            "frequency": frequency,
            "start_date": start_date,
            "end_date": end_date,
            "status": med_status,
            "prescriber_npi": prescriber_npi,
        })

    return medications


def _parse_results(section: ET.Element) -> list[dict]:
    """Extract lab/diagnostic results from a CDA Results section."""
    results: list[dict] = []

    for organizer in section.iter(_cda("organizer")):
        for obs in organizer.iter(_cda("observation")):
            code_elem = obs.find(_cda("code"))
            loinc_code: str | None = None
            test_name: str = "Unknown test"

            if code_elem is not None:
                cs = code_elem.get("codeSystem", "")
                # 2.16.840.1.113883.6.1 = LOINC
                if cs == "2.16.840.1.113883.6.1":
                    loinc_code = code_elem.get("code")
                test_name = _display_name(code_elem) or test_name

            # Value
            value_elem = obs.find(_cda("value"))
            value_text: str | None = None
            value_numeric: float | None = None
            unit: str | None = None

            if value_elem is not None:
                xsi_type = value_elem.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
                if "PQ" in xsi_type or value_elem.get("unit"):
                    raw_val = value_elem.get("value", "")
                    unit = value_elem.get("unit")
                    try:
                        value_numeric = float(raw_val)
                        value_text = f"{raw_val} {unit or ''}".strip()
                    except (ValueError, TypeError):
                        value_text = raw_val or None
                else:
                    value_text = _attr(value_elem, "displayName") or _text(value_elem)

            # Reference range
            ref_range: str | None = None
            rr = obs.find(_cda("referenceRange"))
            if rr is not None:
                obs_range = rr.find(f".//{_cda('observationRange')}")
                if obs_range is not None:
                    text_elem = obs_range.find(_cda("text"))
                    ref_range = _text(text_elem)
                    if not ref_range:
                        val_rr = obs_range.find(_cda("value"))
                        if val_rr is not None:
                            low_rr = val_rr.find(_cda("low"))
                            high_rr = val_rr.find(_cda("high"))
                            lv = _attr(low_rr, "value") if low_rr is not None else ""
                            hv = _attr(high_rr, "value") if high_rr is not None else ""
                            if lv or hv:
                                ref_range = f"{lv} - {hv}".strip(" -")

            # Abnormal flag
            interp_elem = obs.find(_cda("interpretationCode"))
            abnormal_flag: str | None = None
            if interp_elem is not None:
                abnormal_flag = interp_elem.get("code")

            # Result date
            eff = obs.find(_cda("effectiveTime"))
            result_date: date | None = None
            if eff is not None:
                result_date = _parse_cda_date(_attr(eff, "value") or _attr(eff.find(_cda("low")) or ET.Element("x"), "value"))

            if test_name == "Unknown test" and loinc_code is None:
                continue  # Skip noise entries

            results.append({
                "loinc_code": loinc_code,
                "test_name": test_name,
                "value_text": value_text,
                "value_numeric": value_numeric,
                "unit": unit,
                "reference_range": ref_range,
                "abnormal_flag": abnormal_flag,
                "result_date": result_date,
            })

    return results


def _parse_encounters(section: ET.Element) -> list[dict]:
    """Extract encounter summaries (stored in parsed_data only, no child table)."""
    encounters: list[dict] = []
    for enc in section.iter(_cda("encounter")):
        code_elem = enc.find(_cda("code"))
        enc_type = _attr(code_elem, "displayName") if code_elem is not None else "Encounter"
        eff = enc.find(_cda("effectiveTime"))
        enc_date: date | None = None
        if eff is not None:
            enc_date = _parse_cda_date(_attr(eff, "value"))
        encounters.append({
            "type": enc_type,
            "date": enc_date.isoformat() if enc_date else None,
        })
    return encounters


def _parse_procedures(section: ET.Element) -> list[dict]:
    """Extract procedures (stored in parsed_data only, no child table)."""
    procedures: list[dict] = []
    for proc in section.iter(_cda("procedure")):
        code_elem = proc.find(_cda("code"))
        proc_name = _attr(code_elem, "displayName") if code_elem is not None else "Procedure"
        cpt_code = code_elem.get("code") if code_elem is not None else None
        eff = proc.find(_cda("effectiveTime"))
        proc_date: date | None = None
        if eff is not None:
            proc_date = _parse_cda_date(_attr(eff, "value"))
        procedures.append({
            "name": proc_name,
            "cpt_code": cpt_code,
            "date": proc_date.isoformat() if proc_date else None,
        })
    return procedures


def _parse_vitals(section: ET.Element) -> list[dict]:
    """Extract vital signs (stored in parsed_data only, no child table)."""
    vitals: list[dict] = []
    for organizer in section.iter(_cda("organizer")):
        for obs in organizer.iter(_cda("observation")):
            code_elem = obs.find(_cda("code"))
            vital_name = _attr(code_elem, "displayName") if code_elem is not None else "Vital"
            loinc = code_elem.get("code") if code_elem is not None else None
            val_elem = obs.find(_cda("value"))
            value: str | None = None
            unit: str | None = None
            if val_elem is not None:
                value = val_elem.get("value")
                unit = val_elem.get("unit")
            eff = obs.find(_cda("effectiveTime"))
            obs_date: date | None = None
            if eff is not None:
                obs_date = _parse_cda_date(_attr(eff, "value"))
            vitals.append({
                "name": vital_name,
                "loinc_code": loinc,
                "value": value,
                "unit": unit,
                "date": obs_date.isoformat() if obs_date else None,
            })
    return vitals


# ---------------------------------------------------------------------------
# Document header parser
# ---------------------------------------------------------------------------

def _parse_header(root: ET.Element) -> dict[str, Any]:
    """Extract author, custodian, document date from the CDA header."""
    result: dict[str, Any] = {
        "doc_date": None,
        "author_name": None,
        "author_npi": None,
        "custodian_org": None,
        "document_type": "ccd",
    }

    # Effective time
    eff = root.find(_cda("effectiveTime"))
    if eff is not None:
        result["doc_date"] = _parse_cda_date(_attr(eff, "value"))

    # Document type from LOINC code
    code_elem = root.find(_cda("code"))
    if code_elem is not None:
        loinc = code_elem.get("code", "")
        # LOINC 34133-9 = CCD, 11490-0 = Discharge summary, 57133-1 = Referral
        # 11506-3 = Progress note, 34117-2 = H&P
        _loinc_type_map = {
            "34133-9": "ccd",
            "11490-0": "discharge_summary",
            "57133-1": "referral",
            "11506-3": "progress_note",
            "34117-2": "history_physical",
        }
        result["document_type"] = _loinc_type_map.get(loinc, "ccd")

    # Author
    for author in root.findall(_cda("author")):
        assigned = author.find(f".//{_cda('assignedPerson')}")
        if assigned is None:
            assigned = author.find(f".//{_cda('assignedAuthoringDevice')}")
        if assigned is not None:
            name_elem = assigned.find(f".//{_cda('name')}")
            if name_elem is not None:
                given = _text(name_elem.find(_cda("given"))) or ""
                family = _text(name_elem.find(_cda("family"))) or ""
                result["author_name"] = f"{given} {family}".strip() or _text(name_elem)
        # NPI from assignedAuthor/id
        ae = author.find(_cda("assignedAuthor"))
        if ae is not None:
            for id_elem in ae.findall(_cda("id")):
                if id_elem.get("root") == _NPI_OID:
                    result["author_npi"] = id_elem.get("extension")
                    break
        if result["author_name"]:
            break

    # Custodian
    cust = root.find(f".//{_cda('custodianOrganization')}")
    if cust is not None:
        name_elem = cust.find(_cda("name"))
        result["custodian_org"] = _text(name_elem)

    return result


# ---------------------------------------------------------------------------
# Document validation
# ---------------------------------------------------------------------------

def validate_ccda_xml(xml_bytes: bytes) -> tuple[bool, str]:
    """Perform structural validation of a C-CDA XML document.

    Returns (is_valid, error_message).  Validation is intentionally lenient
    (structural, not schema-strict) to handle real-world documents from
    various EHR vendors that may deviate from the published templates.
    """
    if len(xml_bytes) > MAX_CCDA_SIZE_BYTES:
        return False, f"File exceeds maximum size of {MAX_CCDA_SIZE_BYTES // 1024 // 1024} MB"

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        return False, f"XML parse error: {exc}"

    # Must be a ClinicalDocument in the HL7 v3 namespace
    if root.tag != _cda("ClinicalDocument"):
        return False, (
            f"Root element is {root.tag!r}; expected "
            f"{{urn:hl7-org:v3}}ClinicalDocument"
        )

    # Must have a templateId
    tids = root.findall(_cda("templateId"))
    if not tids:
        return False, "No templateId elements found in ClinicalDocument header"

    return True, ""


# ---------------------------------------------------------------------------
# Core parse entry point
# ---------------------------------------------------------------------------

def parse_ccda_document(ccda_id: int) -> dict[str, Any]:
    """Parse a stored C-CDA document and persist extracted data.

    Reads the file from ccda_documents.file_path, parses all recognised
    sections, writes child rows to ccda_problems / ccda_medications /
    ccda_results, and updates the ccda_documents row with parsed_data and
    status = 'parsed'.

    Returns a summary dict with counts per section.
    """
    # Load document record
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, patient_id, file_path, tenant_id, status "
            "FROM ccda_documents WHERE id = %s",
            (ccda_id,),
        )
        doc = cur.fetchone()

    if not doc:
        raise ValueError(f"C-CDA document {ccda_id} not found")

    if doc["status"] == "parsing":
        raise RuntimeError(f"Document {ccda_id} is already being parsed")

    # Mark as parsing
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE ccda_documents SET status = 'parsing', updated_at = NOW() WHERE id = %s",
            (ccda_id,),
        )

    patient_id: int | None = doc["patient_id"]
    tenant_id: str = doc["tenant_id"]

    try:
        # Read the XML file
        file_path = doc["file_path"]
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"XML file not found at {file_path}")

        with open(file_path, "rb") as fh:
            xml_bytes = fh.read()

        # Validate
        valid, err_msg = validate_ccda_xml(xml_bytes)
        if not valid:
            raise ValueError(f"Validation failed: {err_msg}")

        # Parse tree
        root = ET.fromstring(xml_bytes)

        # Header
        header = _parse_header(root)

        # Section data
        problems: list[dict] = []
        medications: list[dict] = []
        results: list[dict] = []
        encounters: list[dict] = []
        procedures: list[dict] = []
        vitals: list[dict] = []

        problems_section = _find_section(root, _SECTION_TEMPLATES["problems"])
        if problems_section is not None:
            problems = _parse_problems(problems_section)

        medications_section = _find_section(root, _SECTION_TEMPLATES["medications"])
        if medications_section is not None:
            medications = _parse_medications(medications_section)

        results_section = _find_section(root, _SECTION_TEMPLATES["results"])
        if results_section is not None:
            results = _parse_results(results_section)

        encounters_section = _find_section(root, _SECTION_TEMPLATES["encounters"])
        if encounters_section is not None:
            encounters = _parse_encounters(encounters_section)

        procedures_section = _find_section(root, _SECTION_TEMPLATES["procedures"])
        if procedures_section is not None:
            procedures = _parse_procedures(procedures_section)

        vitals_section = _find_section(root, _SECTION_TEMPLATES["vitals"])
        if vitals_section is not None:
            vitals = _parse_vitals(vitals_section)

        # Persist child rows
        _persist_problems(ccda_id, patient_id, tenant_id, problems)
        _persist_medications(ccda_id, patient_id, tenant_id, medications)
        _persist_results(ccda_id, patient_id, tenant_id, results)

        # Build parsed_data summary
        parsed_data = {
            "problems_count": len(problems),
            "medications_count": len(medications),
            "results_count": len(results),
            "encounters_count": len(encounters),
            "procedures_count": len(procedures),
            "vitals_count": len(vitals),
            "encounters": encounters,
            "procedures": procedures,
            "vitals": vitals,
        }

        # Update header fields and mark parsed
        with raf_cursor() as cur:
            cur.execute(
                """UPDATE ccda_documents SET
                    status = 'parsed',
                    doc_date = %s,
                    author_name = %s,
                    author_npi = %s,
                    custodian_org = %s,
                    document_type = %s,
                    parsed_data = %s,
                    error_message = NULL,
                    updated_at = NOW()
                WHERE id = %s""",
                (
                    header.get("doc_date"),
                    header.get("author_name"),
                    header.get("author_npi"),
                    header.get("custodian_org"),
                    header.get("document_type"),
                    json.dumps(parsed_data),
                    ccda_id,
                ),
            )

        logger.info(
            "C-CDA %d parsed: %d problems, %d medications, %d results",
            ccda_id, len(problems), len(medications), len(results),
        )

        return {
            "ccda_id": ccda_id,
            "status": "parsed",
            **parsed_data,
        }

    except Exception as exc:
        error_msg = str(exc)
        logger.error("C-CDA parse failed for document %d: %s", ccda_id, error_msg, exc_info=True)
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE ccda_documents SET status = 'error', error_message = %s, updated_at = NOW() WHERE id = %s",
                (error_msg[:2000], ccda_id),
            )
        raise


# ---------------------------------------------------------------------------
# Child-table persistence helpers
# ---------------------------------------------------------------------------

def _persist_problems(
    ccda_id: int,
    patient_id: int | None,
    tenant_id: str,
    problems: list[dict],
) -> None:
    if not problems:
        return
    with raf_cursor() as cur:
        # Clear any previous parse results for this document
        cur.execute("DELETE FROM ccda_problems WHERE ccda_id = %s", (ccda_id,))
        cur.executemany(
            """INSERT INTO ccda_problems
               (ccda_id, patient_id, icd10_code, snomed_code, problem_name,
                onset_date, resolved_date, status, hcc_code, hcc_description,
                source_section, tenant_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [
                (
                    ccda_id,
                    patient_id,
                    p.get("icd10_code"),
                    p.get("snomed_code"),
                    p.get("problem_name", ""),
                    p.get("onset_date"),
                    p.get("resolved_date"),
                    p.get("status", "active"),
                    p.get("hcc_code"),
                    p.get("hcc_description"),
                    p.get("source_section"),
                    tenant_id,
                )
                for p in problems
            ],
        )


def _persist_medications(
    ccda_id: int,
    patient_id: int | None,
    tenant_id: str,
    medications: list[dict],
) -> None:
    if not medications:
        return
    with raf_cursor() as cur:
        cur.execute("DELETE FROM ccda_medications WHERE ccda_id = %s", (ccda_id,))
        cur.executemany(
            """INSERT INTO ccda_medications
               (ccda_id, patient_id, rxnorm_code, medication_name, dose, route,
                frequency, start_date, end_date, status, prescriber_npi, tenant_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [
                (
                    ccda_id,
                    patient_id,
                    m.get("rxnorm_code"),
                    m.get("medication_name", ""),
                    m.get("dose"),
                    m.get("route"),
                    m.get("frequency"),
                    m.get("start_date"),
                    m.get("end_date"),
                    m.get("status", "active"),
                    m.get("prescriber_npi"),
                    tenant_id,
                )
                for m in medications
            ],
        )


def _persist_results(
    ccda_id: int,
    patient_id: int | None,
    tenant_id: str,
    results: list[dict],
) -> None:
    if not results:
        return
    with raf_cursor() as cur:
        cur.execute("DELETE FROM ccda_results WHERE ccda_id = %s", (ccda_id,))
        cur.executemany(
            """INSERT INTO ccda_results
               (ccda_id, patient_id, loinc_code, test_name, value_text,
                value_numeric, unit, reference_range, abnormal_flag,
                result_date, tenant_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [
                (
                    ccda_id,
                    patient_id,
                    r.get("loinc_code"),
                    r.get("test_name", ""),
                    r.get("value_text"),
                    r.get("value_numeric"),
                    r.get("unit"),
                    r.get("reference_range"),
                    r.get("abnormal_flag"),
                    r.get("result_date"),
                    tenant_id,
                )
                for r in results
            ],
        )


# ---------------------------------------------------------------------------
# Document storage
# ---------------------------------------------------------------------------

def store_ccda_upload(
    tenant_id: str,
    patient_id: int | None,
    xml_bytes: bytes,
    original_filename: str,
    source: str = "upload",
) -> dict[str, Any]:
    """Validate and store an uploaded C-CDA XML file.

    Returns a dict with success, ccda_id, and error (on failure).
    """
    # Basic validation before writing to disk
    valid, err_msg = validate_ccda_xml(xml_bytes)
    if not valid:
        return {"success": False, "error": err_msg}

    # Persist file to disk
    CCDA_UPLOADS_BASE.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.xml"
    tenant_dir = CCDA_UPLOADS_BASE / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    file_path = tenant_dir / unique_name
    file_path.write_bytes(xml_bytes)

    # Parse header metadata eagerly for the DB record
    try:
        root = ET.fromstring(xml_bytes)
        header = _parse_header(root)
    except Exception:
        header = {"document_type": "ccd", "doc_date": None, "author_name": None,
                  "author_npi": None, "custodian_org": None}

    # Insert DB record
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO ccda_documents
               (patient_id, document_type, source, original_filename, file_path,
                file_size, doc_date, author_name, author_npi, custodian_org,
                status, tenant_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'uploaded', %s)""",
            (
                patient_id,
                header.get("document_type", "ccd"),
                source,
                original_filename,
                str(file_path),
                len(xml_bytes),
                header.get("doc_date"),
                header.get("author_name"),
                header.get("author_npi"),
                header.get("custodian_org"),
                tenant_id,
            ),
        )
        ccda_id = cur.lastrowid

    return {
        "success": True,
        "ccda_id": ccda_id,
        "document_type": header.get("document_type", "ccd"),
        "file_path": str(file_path),
        "file_size": len(xml_bytes),
    }


# ---------------------------------------------------------------------------
# Query helpers used by the router
# ---------------------------------------------------------------------------

def get_ccda_document(ccda_id: int, tenant_id: str) -> dict | None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM ccda_documents WHERE id = %s AND tenant_id = %s",
            (ccda_id, tenant_id),
        )
        return cur.fetchone()


def list_ccda_documents(
    tenant_id: str,
    patient_id: int | None = None,
    status: str | None = None,
    document_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    clauses = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if patient_id is not None:
        clauses.append("patient_id = %s")
        params.append(patient_id)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if document_type:
        clauses.append("document_type = %s")
        params.append(document_type)

    where = " AND ".join(clauses)

    with raf_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM ccda_documents WHERE {where}", params)
        total = cur.fetchone()["cnt"]

        cur.execute(
            f"SELECT * FROM ccda_documents WHERE {where} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return rows, total


def get_ccda_problems(ccda_id: int, tenant_id: str) -> list[dict]:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT p.* FROM ccda_problems p "
            "JOIN ccda_documents d ON d.id = p.ccda_id "
            "WHERE p.ccda_id = %s AND d.tenant_id = %s "
            "ORDER BY p.status, p.onset_date DESC",
            (ccda_id, tenant_id),
        )
        return cur.fetchall()


def get_ccda_medications(ccda_id: int, tenant_id: str) -> list[dict]:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT m.* FROM ccda_medications m "
            "JOIN ccda_documents d ON d.id = m.ccda_id "
            "WHERE m.ccda_id = %s AND d.tenant_id = %s "
            "ORDER BY m.status, m.start_date DESC",
            (ccda_id, tenant_id),
        )
        return cur.fetchall()


def get_ccda_results(ccda_id: int, tenant_id: str) -> list[dict]:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT r.* FROM ccda_results r "
            "JOIN ccda_documents d ON d.id = r.ccda_id "
            "WHERE r.ccda_id = %s AND d.tenant_id = %s "
            "ORDER BY r.result_date DESC",
            (ccda_id, tenant_id),
        )
        return cur.fetchall()


def get_ccda_hcc_impact(ccda_id: int, tenant_id: str) -> list[dict]:
    """Return all distinct HCC codes found in the problem list for a document."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT p.hcc_code, p.hcc_description, "
            "COUNT(*) AS supporting_conditions, "
            "GROUP_CONCAT(DISTINCT p.icd10_code ORDER BY p.icd10_code SEPARATOR ', ') AS icd10_codes "
            "FROM ccda_problems p "
            "JOIN ccda_documents d ON d.id = p.ccda_id "
            "WHERE p.ccda_id = %s AND d.tenant_id = %s "
            "AND p.hcc_code IS NOT NULL "
            "GROUP BY p.hcc_code, p.hcc_description "
            "ORDER BY p.hcc_code",
            (ccda_id, tenant_id),
        )
        return cur.fetchall()


def delete_ccda_document(ccda_id: int, tenant_id: str) -> bool:
    """Delete a document record and its file from disk."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT file_path FROM ccda_documents WHERE id = %s AND tenant_id = %s",
            (ccda_id, tenant_id),
        )
        row = cur.fetchone()

    if not row:
        return False

    # Remove file from disk
    try:
        fp = Path(row["file_path"])
        if fp.is_file():
            fp.unlink()
    except OSError as exc:
        logger.warning("Could not delete C-CDA file %s: %s", row["file_path"], exc)

    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM ccda_documents WHERE id = %s AND tenant_id = %s",
            (ccda_id, tenant_id),
        )

    return True


# ---------------------------------------------------------------------------
# C-CDA Export
# ---------------------------------------------------------------------------

def generate_ccda_export(patient_id: int, tenant_id: str) -> str:
    """Generate a minimal but valid CCD XML document for a patient.

    Pulls data from ccda_problems, ccda_medications, and ccda_results for the
    most recent C-CDA documents on file for the patient.  The generated XML
    is a skeleton CCD conformant to HITSP C32 / HL7 CCD Release 1.

    Returns the XML as a UTF-8 string.
    """
    # Fetch patient demographics from OpenEMR if available
    patient_name = "Unknown Patient"
    patient_dob: str = ""
    try:
        from app.db import openemr_cursor
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT fname, lname, DOB FROM patient_data WHERE pid = %s LIMIT 1",
                (patient_id,),
            )
            row = cur.fetchone()
            if row:
                patient_name = f"{row.get('fname', '')} {row.get('lname', '')}".strip()
                patient_dob = str(row.get("DOB", "")).replace("-", "")
    except Exception as exc:
        logger.warning("Could not load patient demographics for export: %s", exc)

    # Collect problems, medications, results
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM ccda_problems WHERE patient_id = %s AND tenant_id = %s "
            "ORDER BY status, onset_date DESC",
            (patient_id, tenant_id),
        )
        problems = cur.fetchall()

        cur.execute(
            "SELECT * FROM ccda_medications WHERE patient_id = %s AND tenant_id = %s "
            "ORDER BY status, start_date DESC",
            (patient_id, tenant_id),
        )
        medications = cur.fetchall()

        cur.execute(
            "SELECT * FROM ccda_results WHERE patient_id = %s AND tenant_id = %s "
            "ORDER BY result_date DESC LIMIT 50",
            (patient_id, tenant_id),
        )
        results = cur.fetchall()

    now_str = datetime.utcnow().strftime("%Y%m%d%H%M%S+0000")
    doc_id = str(uuid.uuid4())

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<ClinicalDocument xmlns="urn:hl7-org:v3"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '  xsi:schemaLocation="urn:hl7-org:v3 CDA.xsd">',
        '',
        '  <!-- RAF Intelligence C-CDA Export -->',
        '  <realmCode code="US"/>',
        '  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>',
        '  <templateId root="2.16.840.1.113883.10.20.22.1.1"/>',
        '  <templateId root="2.16.840.1.113883.10.20.22.1.2"/>',
        f'  <id root="{doc_id}"/>',
        '  <code code="34133-9" codeSystem="2.16.840.1.113883.6.1"',
        '    displayName="Summarization of Episode Note"/>',
        f'  <title>Continuity of Care Document — {patient_name}</title>',
        f'  <effectiveTime value="{now_str}"/>',
        '  <confidentialityCode code="N" codeSystem="2.16.840.1.113883.5.25"/>',
        '  <languageCode code="en-US"/>',
        '',
        '  <recordTarget>',
        '    <patientRole>',
        f'      <id root="2.16.840.1.113883.4.1" extension="{patient_id}"/>',
        '      <patient>',
        f'        <name><given>{patient_name.split()[0] if patient_name else ""}</given>'
        f'<family>{patient_name.split()[-1] if patient_name else ""}</family></name>',
        f'        <birthTime value="{patient_dob}"/>',
        '      </patient>',
        '    </patientRole>',
        '  </recordTarget>',
        '',
        '  <author>',
        f'    <time value="{now_str}"/>',
        '    <assignedAuthor>',
        '      <id root="2.16.840.1.113883.3.999" extension="raf-intelligence"/>',
        '      <assignedAuthoringDevice>',
        '        <softwareName>RAF Intelligence Export</softwareName>',
        '      </assignedAuthoringDevice>',
        '    </assignedAuthor>',
        '  </author>',
        '',
        '  <component>',
        '    <structuredBody>',
    ]

    # ---- Problems section ----
    lines += [
        '',
        '      <!-- Problems Section -->',
        '      <component><section>',
        '        <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>',
        '        <code code="11450-4" codeSystem="2.16.840.1.113883.6.1"',
        '          displayName="Problem List"/>',
        '        <title>Problems</title>',
        '        <text>',
        '          <table border="1"><thead><tr>',
        '            <th>Problem</th><th>Status</th><th>Onset</th><th>ICD-10</th><th>HCC</th>',
        '          </tr></thead><tbody>',
    ]
    for p in problems:
        lines.append(
            f'            <tr><td>{_xml_escape(str(p.get("problem_name", "")))}</td>'
            f'<td>{p.get("status", "")}</td>'
            f'<td>{p.get("onset_date") or ""}</td>'
            f'<td>{p.get("icd10_code") or ""}</td>'
            f'<td>{p.get("hcc_code") or ""}</td></tr>'
        )
    lines += [
        '          </tbody></table>',
        '        </text>',
    ]
    for p in problems:
        icd10 = p.get("icd10_code") or ""
        snomed = p.get("snomed_code") or ""
        prob_name = _xml_escape(str(p.get("problem_name", "")))
        onset = str(p.get("onset_date") or "").replace("-", "")
        status_map = {"active": "active", "resolved": "completed", "inactive": "aborted"}
        cda_status = status_map.get(p.get("status", "active"), "active")
        lines += [
            '        <entry typeCode="DRIV"><act classCode="ACT" moodCode="EVN">',
            '          <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>',
            '          <entryRelationship typeCode="SUBJ"><observation classCode="OBS" moodCode="EVN">',
            '            <templateId root="2.16.840.1.113883.10.20.22.4.4"/>',
            f'            <statusCode code="{cda_status}"/>',
        ]
        if onset:
            lines.append(f'            <effectiveTime><low value="{onset}"/></effectiveTime>')
        if icd10:
            lines.append(
                f'            <value xsi:type="CD" code="{icd10}" '
                f'codeSystem="2.16.840.1.113883.6.90" displayName="{prob_name}"/>'
            )
        elif snomed:
            lines.append(
                f'            <value xsi:type="CD" code="{snomed}" '
                f'codeSystem="2.16.840.1.113883.6.96" displayName="{prob_name}"/>'
            )
        lines += [
            '          </observation></entryRelationship>',
            '        </act></entry>',
        ]
    lines.append('      </section></component>')

    # ---- Medications section ----
    lines += [
        '',
        '      <!-- Medications Section -->',
        '      <component><section>',
        '        <templateId root="2.16.840.1.113883.10.20.22.2.1.1"/>',
        '        <code code="10160-0" codeSystem="2.16.840.1.113883.6.1"',
        '          displayName="History of Medication Use"/>',
        '        <title>Medications</title>',
        '        <text>',
        '          <table border="1"><thead><tr>',
        '            <th>Medication</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Status</th>',
        '          </tr></thead><tbody>',
    ]
    for m in medications:
        lines.append(
            f'            <tr><td>{_xml_escape(str(m.get("medication_name", "")))}</td>'
            f'<td>{m.get("dose") or ""}</td>'
            f'<td>{m.get("route") or ""}</td>'
            f'<td>{m.get("frequency") or ""}</td>'
            f'<td>{m.get("status") or ""}</td></tr>'
        )
    lines += [
        '          </tbody></table>',
        '        </text>',
    ]
    for m in medications:
        rxnorm = m.get("rxnorm_code") or ""
        med_name = _xml_escape(str(m.get("medication_name", "")))
        lines += [
            '        <entry typeCode="DRIV">',
            '          <substanceAdministration classCode="SBADM" moodCode="EVN">',
            '            <templateId root="2.16.840.1.113883.10.20.22.4.16"/>',
            '            <consumable><manufacturedProduct>',
            '              <templateId root="2.16.840.1.113883.10.20.22.4.23"/>',
            '              <manufacturedMaterial>',
        ]
        if rxnorm:
            lines.append(
                f'                <code code="{rxnorm}" codeSystem="2.16.840.1.113883.6.88"'
                f' displayName="{med_name}"/>'
            )
        else:
            lines.append(f'                <name>{med_name}</name>')
        lines += [
            '              </manufacturedMaterial>',
            '            </manufacturedProduct></consumable>',
            '          </substanceAdministration>',
            '        </entry>',
        ]
    lines.append('      </section></component>')

    # ---- Results section ----
    lines += [
        '',
        '      <!-- Results Section -->',
        '      <component><section>',
        '        <templateId root="2.16.840.1.113883.10.20.22.2.3.1"/>',
        '        <code code="30954-2" codeSystem="2.16.840.1.113883.6.1"',
        '          displayName="Relevant Diagnostic Tests and/or Laboratory Data"/>',
        '        <title>Results</title>',
        '        <text>',
        '          <table border="1"><thead><tr>',
        '            <th>Test</th><th>Value</th><th>Unit</th><th>Reference Range</th><th>Date</th>',
        '          </tr></thead><tbody>',
    ]
    for r in results:
        lines.append(
            f'            <tr><td>{_xml_escape(str(r.get("test_name", "")))}</td>'
            f'<td>{r.get("value_text") or r.get("value_numeric") or ""}</td>'
            f'<td>{r.get("unit") or ""}</td>'
            f'<td>{r.get("reference_range") or ""}</td>'
            f'<td>{r.get("result_date") or ""}</td></tr>'
        )
    lines += [
        '          </tbody></table>',
        '        </text>',
    ]
    lines.append('      </section></component>')

    # Close document
    lines += [
        '',
        '    </structuredBody>',
        '  </component>',
        '</ClinicalDocument>',
    ]

    return "\n".join(lines)


def _xml_escape(s: str) -> str:
    """Escape special XML characters in a text value."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )
