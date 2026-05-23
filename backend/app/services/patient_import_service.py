"""
Patient Bulk Import Service.

Supports two input formats:

1. **CSV** — flat spreadsheet, convenient for clinic onboarding.
   Columns cover USCDI v3 required demographic fields and map directly to
   the ``raf_intelligence.patients`` table.

2. **FHIR R4 Patient** — either a single ``Patient`` resource or a ``Bundle``
   whose entries are ``Patient`` resources. This is the interoperability
   standard mandated by CMS / ONC.

Both input paths converge on the same internal row dictionary, which is then
validated, deduplicated, and inserted by :func:`import_patients` into the
``raf_intelligence.patients`` table.

Public API
----------
  parse_patient_csv(file_bytes)         -> (rows, parse_errors)
  parse_fhir_patients(file_bytes)       -> (rows, parse_errors)
  validate_patient_row(row, line_num)   -> list[str]
  import_patients(rows, uploaded_by)    -> dict
  get_import_template()                 -> str         # CSV
  get_fhir_template()                   -> str         # JSON Bundle example
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
from datetime import date, datetime
from typing import Any

from app.db import raf_cursor

try:
    import openpyxl
except ImportError as _openpyxl_err:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]
    _openpyxl_import_error = _openpyxl_err
else:
    _openpyxl_import_error = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column definitions (superset covering USCDI v3)
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS: list[str] = ["first_name", "last_name", "dob", "sex"]

# Every column the CSV understands. Column names map directly to the
# ``patients`` table in the raf_intelligence database.
ALL_COLUMNS: list[str] = [
    # Core identity
    "first_name",
    "middle_name",
    "last_name",
    "previous_name",
    "dob",
    "sex",                # administrative/legal sex
    "birth_sex",          # sex recorded at birth (USCDI)
    "gender_identity",    # USCDI
    "sexual_orientation", # USCDI
    "pronouns",
    # Contact
    "ssn",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "zip",
    # Demographics (USCDI)
    "race",
    "ethnicity",
    "preferred_language",
    # Identifiers
    "mrn",
    "mbi",                # Medicare Beneficiary Identifier
    "insurance_type",
    # Emergency contact
    "emergency_contact_name",
    "emergency_contact_phone",
]

# Columns from ALL_COLUMNS that map directly to ``patients`` table columns.
# ``insurance_type`` is included — the new patients table has this column.
# ``_line`` and ``_source`` are internal parser metadata, not DB columns.
PATIENTS_TABLE_COLUMNS: set[str] = set(ALL_COLUMNS)

# ---------------------------------------------------------------------------
# Accepted value maps
# ---------------------------------------------------------------------------

_SEX_MAP: dict[str, str] = {
    "male": "Male", "m": "Male",
    "female": "Female", "f": "Female",
    "other": "Other", "o": "Other",
    "unknown": "Unknown", "u": "Unknown",
}

# FHIR Patient.gender -> our canonical sex values.
_FHIR_GENDER_MAP: dict[str, str] = {
    "male": "Male",
    "female": "Female",
    "other": "Other",
    "unknown": "Unknown",
}

_DOB_FORMATS: list[str] = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y%m%d",
]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_TEMPLATE_HEADER = ",".join(ALL_COLUMNS)
_TEMPLATE_EXAMPLE_VALUES: dict[str, str] = {
    "first_name": "Jane",
    "middle_name": "A",
    "last_name": "Doe",
    "previous_name": "",
    "dob": "1980-04-15",
    "sex": "Female",
    "birth_sex": "Female",
    "gender_identity": "identifies-as-female",
    "sexual_orientation": "not-disclosed",
    "pronouns": "she/her",
    "ssn": "",
    "phone": "555-867-5309",
    "email": "jane.doe@example.com",
    "address": "123 Main St",
    "city": "Springfield",
    "state": "IL",
    "zip": "62701",
    "race": "2106-3",        # White (CDC Race & Ethnicity Code Set)
    "ethnicity": "2186-5",   # Not Hispanic or Latino
    "preferred_language": "en",
    "mrn": "MRN00001",
    "mbi": "",
    "insurance_type": "Medicare",
    "emergency_contact_name": "John Doe (spouse)",
    "emergency_contact_phone": "555-111-2222",
}


def get_import_template() -> str:
    """Return a CSV template string with headers and one example row."""
    example_row = ",".join(
        _csv_escape(_TEMPLATE_EXAMPLE_VALUES.get(col, "")) for col in ALL_COLUMNS
    )
    return f"{_TEMPLATE_HEADER}\n{example_row}\n"


def _csv_escape(value: str) -> str:
    """Minimal CSV cell escaping for the template example row."""
    if any(c in value for c in [",", '"', "\n"]):
        return '"' + value.replace('"', '""') + '"'
    return value


def get_import_template_xlsx() -> bytes:
    """Return an Excel (.xlsx) template as bytes with headers, example row, and formatting."""
    if openpyxl is None:
        raise ImportError(
            "openpyxl is required for Excel support. "
            "Install it with: pip install openpyxl"
        ) from _openpyxl_import_error

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Patient Import"

    header_font = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    data_font = Font(name="Calibri", size=11)
    border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    for col_idx, col_name in enumerate(ALL_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border
        ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = max(len(col_name) + 4, 14)

    for col_idx, col_name in enumerate(ALL_COLUMNS, 1):
        val = _TEMPLATE_EXAMPLE_VALUES.get(col_name, "")
        cell = ws.cell(row=2, column=col_idx, value=val)
        cell.font = data_font
        cell.border = border

    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def get_fhir_template() -> str:
    """Return a minimal FHIR R4 Bundle (JSON) with one example Patient."""
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": [
                        {
                            "system": "http://hospital.example.org/mrn",
                            "value": "MRN00001",
                        }
                    ],
                    "name": [
                        {
                            "use": "official",
                            "family": "Doe",
                            "given": ["Jane", "A"],
                        }
                    ],
                    "telecom": [
                        {"system": "phone", "value": "555-867-5309", "use": "home"},
                        {"system": "email", "value": "jane.doe@example.com"},
                    ],
                    "gender": "female",
                    "birthDate": "1980-04-15",
                    "address": [
                        {
                            "line": ["123 Main St"],
                            "city": "Springfield",
                            "state": "IL",
                            "postalCode": "62701",
                            "country": "US",
                        }
                    ],
                    "communication": [
                        {
                            "language": {
                                "coding": [
                                    {
                                        "system": "urn:ietf:bcp:47",
                                        "code": "en",
                                        "display": "English",
                                    }
                                ]
                            },
                            "preferred": True,
                        }
                    ],
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
                            "extension": [
                                {
                                    "url": "ombCategory",
                                    "valueCoding": {
                                        "system": "urn:oid:2.16.840.1.113883.6.238",
                                        "code": "2106-3",
                                        "display": "White",
                                    },
                                }
                            ],
                        },
                        {
                            "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                            "extension": [
                                {
                                    "url": "ombCategory",
                                    "valueCoding": {
                                        "system": "urn:oid:2.16.840.1.113883.6.238",
                                        "code": "2186-5",
                                        "display": "Not Hispanic or Latino",
                                    },
                                }
                            ],
                        },
                        {
                            "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex",
                            "valueCode": "F",
                        },
                    ],
                }
            }
        ],
    }
    return json.dumps(bundle, indent=2)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _normalise_header(raw: str) -> str:
    """Strip whitespace, lowercase, replace spaces/hyphens with underscores.

    Also strips trailing markers like ``*`` (used for "required" in templates).
    """
    cleaned = raw.strip().lower().replace(" ", "_").replace("-", "_")
    # Remove trailing non-alphanumeric markers (e.g. "first_name_*" -> "first_name")
    return re.sub(r"[_*]+$", "", cleaned)


def parse_patient_csv(file_bytes: bytes) -> tuple[list[dict[str, str]], list[str]]:
    """Parse CSV bytes into (rows, parse_errors)."""
    parse_errors: list[str] = []
    rows: list[dict[str, str]] = []

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            return [], [f"Could not decode file: {exc}"]

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    if reader.fieldnames is None:
        return [], ["CSV file has no header row."]

    normalised_fields = [_normalise_header(f) for f in reader.fieldnames]

    missing_required = [col for col in REQUIRED_COLUMNS if col not in normalised_fields]
    if missing_required:
        return [], [
            f"Missing required column(s): {', '.join(missing_required)}. "
            f"Required columns: {', '.join(REQUIRED_COLUMNS)}"
        ]

    for line_num, raw_row in enumerate(reader, start=2):
        try:
            row: dict[str, str] = {
                _normalise_header(k): (v or "").strip()
                for k, v in raw_row.items()
                if k is not None
            }
            row["_line"] = str(line_num)
            row["_source"] = "csv"
            rows.append(row)
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            parse_errors.append(f"Row {line_num}: could not parse — {exc}")

    return rows, parse_errors


# ---------------------------------------------------------------------------
# XLSX parsing
# ---------------------------------------------------------------------------

def parse_patient_xlsx(file_bytes: bytes) -> tuple[list[dict[str, str]], list[str]]:
    """Parse Excel (.xlsx) bytes into (rows, parse_errors).

    Mirrors the return shape of :func:`parse_patient_csv`.  Reads the first
    worksheet and auto-detects the header row by scanning the first five rows
    for a cell whose normalised value is ``"first_name"``.  This accommodates
    template files that include a category / title row above the real header.
    """
    if openpyxl is None:
        raise ImportError(
            "openpyxl is required to parse .xlsx files. "
            f"Install it with: pip install openpyxl  (original error: {_openpyxl_import_error})"
        )

    parse_errors: list[str] = []
    rows: list[dict[str, str]] = []

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(file_bytes),
            read_only=True,
            data_only=True,
        )
    except Exception as exc:
        logger.debug("swallowed exception", exc_info=True)
        return [], [f"Could not open Excel file: {exc}"]

    sheet = workbook.worksheets[0]

    # Materialise all rows once so we can index by position without re-iterating
    # the read-only worksheet stream.
    all_rows = list(sheet.iter_rows(values_only=True))

    if not all_rows:
        return [], ["Excel file is empty."]

    # --- Find the header row (first 5 rows) -----------------------------------
    header_row_idx: int | None = None
    for scan_idx, scan_row in enumerate(all_rows[:5]):
        for cell_val in scan_row:
            if cell_val is not None and _normalise_header(str(cell_val)) == "first_name":
                header_row_idx = scan_idx
                break
        if header_row_idx is not None:
            break

    if header_row_idx is None:
        return [], [
            "Could not find a header row in the first 5 rows of the spreadsheet. "
            "Ensure the sheet contains a column named 'first_name'."
        ]

    raw_headers = all_rows[header_row_idx]
    normalised_headers = [
        _normalise_header(str(h)) if h is not None else "" for h in raw_headers
    ]

    # --- Check required columns -----------------------------------------------
    missing_required = [col for col in REQUIRED_COLUMNS if col not in normalised_headers]
    if missing_required:
        return [], [
            f"Missing required column(s): {', '.join(missing_required)}. "
            f"Required columns: {', '.join(REQUIRED_COLUMNS)}"
        ]

    # --- Parse data rows ------------------------------------------------------
    data_rows = all_rows[header_row_idx + 1:]

    for offset, raw_row in enumerate(data_rows):
        # 1-based spreadsheet row number (header_row_idx is 0-based; +1 for
        # header itself; +1 again because spreadsheet rows are 1-based).
        sheet_line = header_row_idx + offset + 2

        # Skip completely empty rows.
        if all(cell is None or str(cell).strip() == "" for cell in raw_row):
            continue

        row: dict[str, str] = {}
        try:
            for col_idx, header in enumerate(normalised_headers):
                if not header:
                    # Ignore columns with no header.
                    continue
                cell_val = raw_row[col_idx] if col_idx < len(raw_row) else None

                # Excel stores dates as datetime / date objects when the cell
                # has a date format applied.  Convert to canonical YYYY-MM-DD.
                if isinstance(cell_val, datetime) or isinstance(cell_val, date):
                    cell_str = cell_val.strftime("%Y-%m-%d")
                else:
                    cell_str = str(cell_val).strip() if cell_val is not None else ""

                row[header] = cell_str

            row["_line"] = str(sheet_line)
            row["_source"] = "xlsx"
            rows.append(row)
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            parse_errors.append(f"Row {sheet_line}: could not parse — {exc}")

    return rows, parse_errors


# ---------------------------------------------------------------------------
# FHIR parsing
# ---------------------------------------------------------------------------

_US_CORE_RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_US_CORE_ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
_US_CORE_BIRTHSEX_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"
_US_CORE_GENDER_IDENTITY_URL = (
    "http://hl7.org/fhir/us/core/StructureDefinition/us-core-genderIdentity"
)
_US_CORE_PRONOUNS_URL = (
    "http://hl7.org/fhir/us/core/StructureDefinition/us-core-pronouns"
)


def _fhir_extension(extensions: list[dict[str, Any]] | None, url: str) -> dict[str, Any] | None:
    if not extensions:
        return None
    for ext in extensions:
        if isinstance(ext, dict) and ext.get("url") == url:
            return ext
    return None


def _fhir_omb_code(ext: dict[str, Any] | None) -> str:
    """Pull the OMB category code from a us-core-race / us-core-ethnicity extension."""
    if not ext:
        return ""
    for child in ext.get("extension", []) or []:
        if child.get("url") == "ombCategory":
            coding = child.get("valueCoding") or {}
            return str(coding.get("code") or coding.get("display") or "")
    return ""


def _fhir_patient_to_row(
    patient: dict[str, Any],
    line_num: int,
) -> tuple[dict[str, str] | None, str | None]:
    """
    Convert a single FHIR Patient resource to our internal row format.
    Returns (row, None) on success, (None, error_message) on failure.
    """
    if not isinstance(patient, dict) or patient.get("resourceType") != "Patient":
        return None, f"Entry {line_num}: not a Patient resource."

    # Name
    names = patient.get("name") or []
    official = next(
        (n for n in names if isinstance(n, dict) and n.get("use") == "official"),
        None,
    ) or (names[0] if names and isinstance(names[0], dict) else {})

    given = official.get("given") or []
    first_name = given[0] if given else ""
    middle_name = " ".join(given[1:]) if len(given) > 1 else ""
    last_name = official.get("family") or ""

    # Previous name
    previous = next(
        (n for n in names if isinstance(n, dict) and n.get("use") == "old"),
        None,
    )
    previous_name = ""
    if previous:
        prev_given = previous.get("given") or []
        previous_name = " ".join(list(prev_given) + [previous.get("family") or ""]).strip()

    # Gender / DOB
    gender_raw = str(patient.get("gender") or "").lower()
    sex = _FHIR_GENDER_MAP.get(gender_raw, "")
    dob = str(patient.get("birthDate") or "")

    # --- DOB validation: must be a valid past date with age 0-120 -----------
    if dob:
        parsed_fhir_dob = _parse_dob(dob)
        if parsed_fhir_dob is None:
            return None, f"Entry {line_num}: birthDate {dob!r} is not a valid date."
        today = date.today()
        if parsed_fhir_dob > today:
            return None, f"Entry {line_num}: birthDate {dob!r} is in the future."
        age = (
            today.year
            - parsed_fhir_dob.year
            - ((today.month, today.day) < (parsed_fhir_dob.month, parsed_fhir_dob.day))
        )
        if age < 0 or age > 120:
            return (
                None,
                f"Entry {line_num}: birthDate {dob!r} yields implausible age {age} (must be 0-120).",
            )
        # Canonicalise to YYYY-MM-DD for downstream consumers.
        dob = parsed_fhir_dob.strftime("%Y-%m-%d")

    # Telecom
    phone = ""
    email = ""
    for t in patient.get("telecom") or []:
        if not isinstance(t, dict):
            continue
        system = (t.get("system") or "").lower()
        value = t.get("value") or ""
        if system == "phone" and not phone:
            phone = value
        elif system == "email" and not email:
            email = value

    # Address
    addresses = patient.get("address") or []
    first_addr = addresses[0] if addresses and isinstance(addresses[0], dict) else {}
    address_line = ""
    lines = first_addr.get("line") or []
    if lines:
        address_line = ", ".join(str(l) for l in lines)
    city = first_addr.get("city") or ""
    state = first_addr.get("state") or ""
    postal = first_addr.get("postalCode") or ""

    # Identifiers
    mrn = ""
    mbi = ""
    ssn = ""
    for ident in patient.get("identifier") or []:
        if not isinstance(ident, dict):
            continue
        system = (ident.get("system") or "").lower()
        type_coding = (ident.get("type") or {}).get("coding") or []
        type_code = (type_coding[0].get("code") if type_coding else "") or ""
        value = ident.get("value") or ""
        if "ssn" in system or type_code == "SS":
            ssn = ssn or value
        elif "mbi" in system or "medicare" in system:
            mbi = mbi or value
        elif "mrn" in system or type_code in {"MR", "MRN"} or not mrn:
            mrn = mrn or value

    # Communication / preferred language
    preferred_language = ""
    for comm in patient.get("communication") or []:
        if not isinstance(comm, dict):
            continue
        if comm.get("preferred") or not preferred_language:
            lang = comm.get("language") or {}
            coding = lang.get("coding") or []
            if coding:
                preferred_language = coding[0].get("code") or coding[0].get("display") or ""
            if comm.get("preferred"):
                break

    # Extensions (US Core)
    exts = patient.get("extension") or []
    race = _fhir_omb_code(_fhir_extension(exts, _US_CORE_RACE_URL))
    ethnicity = _fhir_omb_code(_fhir_extension(exts, _US_CORE_ETHNICITY_URL))

    birthsex_ext = _fhir_extension(exts, _US_CORE_BIRTHSEX_URL)
    birth_sex_code = str((birthsex_ext or {}).get("valueCode") or "").upper()
    birth_sex = {"M": "Male", "F": "Female"}.get(birth_sex_code, "")

    gender_identity_ext = _fhir_extension(exts, _US_CORE_GENDER_IDENTITY_URL)
    gender_identity = ""
    if gender_identity_ext:
        cc = gender_identity_ext.get("valueCodeableConcept") or {}
        coding = cc.get("coding") or []
        if coding:
            gender_identity = coding[0].get("display") or coding[0].get("code") or ""

    pronouns_ext = _fhir_extension(exts, _US_CORE_PRONOUNS_URL)
    pronouns = ""
    if pronouns_ext:
        cc = pronouns_ext.get("valueCodeableConcept") or {}
        coding = cc.get("coding") or []
        if coding:
            pronouns = coding[0].get("display") or coding[0].get("code") or ""

    # Emergency contact
    emergency_name = ""
    emergency_phone = ""
    contacts = patient.get("contact") or []
    if contacts and isinstance(contacts[0], dict):
        c0 = contacts[0]
        c_name = c0.get("name") or {}
        c_given = c_name.get("given") or []
        emergency_name = " ".join(list(c_given) + [c_name.get("family") or ""]).strip()
        for t in c0.get("telecom") or []:
            if isinstance(t, dict) and (t.get("system") or "").lower() == "phone":
                emergency_phone = t.get("value") or ""
                break

    row: dict[str, str] = {
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "previous_name": previous_name,
        "dob": dob,
        "sex": sex,
        "birth_sex": birth_sex,
        "gender_identity": gender_identity,
        "sexual_orientation": "",  # not commonly populated as a first-class field
        "pronouns": pronouns,
        "ssn": ssn,
        "phone": phone,
        "email": email,
        "address": address_line,
        "city": city,
        "state": state,
        "zip": postal,
        "race": race,
        "ethnicity": ethnicity,
        "preferred_language": preferred_language,
        "mrn": mrn,
        "mbi": mbi,
        "insurance_type": "",
        "emergency_contact_name": emergency_name,
        "emergency_contact_phone": emergency_phone,
        "_line": str(line_num),
        "_source": "fhir",
    }
    return row, None


def parse_fhir_patients(file_bytes: bytes) -> tuple[list[dict[str, str]], list[str]]:
    """
    Parse a FHIR R4 JSON payload.

    Accepts either:
      - a single ``Patient`` resource, or
      - a ``Bundle`` whose entries contain ``Patient`` resources.

    Returns (rows, parse_errors) in the same shape as :func:`parse_patient_csv`.
    """
    parse_errors: list[str] = []
    rows: list[dict[str, str]] = []

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            return [], [f"Could not decode file: {exc}"]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"Invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"]

    if not isinstance(payload, dict):
        return [], ["FHIR payload must be a JSON object (Patient or Bundle)."]

    resource_type = payload.get("resourceType")

    if resource_type == "Patient":
        row, err = _fhir_patient_to_row(payload, 1)
        if err:
            parse_errors.append(err)
        elif row:
            rows.append(row)
        return rows, parse_errors

    if resource_type == "Bundle":
        entries = payload.get("entry") or []
        if not isinstance(entries, list):
            return [], ["Bundle.entry must be an array."]
        for idx, entry in enumerate(entries, start=1):
            # Defensive: skip entries missing/invalid structure.
            if not isinstance(entry, dict):
                logger.warning("fhir_import: entry %d skipped — not a JSON object", idx)
                parse_errors.append(f"Entry {idx}: not a JSON object.")
                continue
            if "resource" not in entry:
                logger.warning("fhir_import: entry %d skipped — missing 'resource' key", idx)
                parse_errors.append(f"Entry {idx}: missing 'resource' key.")
                continue
            resource = entry.get("resource")
            if not isinstance(resource, dict):
                logger.warning("fhir_import: entry %d skipped — resource is not an object", idx)
                parse_errors.append(f"Entry {idx}: resource is not a JSON object.")
                continue
            entry_rt = resource.get("resourceType")
            if not entry_rt:
                logger.warning("fhir_import: entry %d skipped — resource missing resourceType", idx)
                parse_errors.append(f"Entry {idx}: resource missing 'resourceType'.")
                continue
            if entry_rt != "Patient":
                # Skip non-Patient resources silently — common in mixed bundles.
                logger.info(
                    "fhir_import: entry %d skipped — unexpected resourceType %r",
                    idx,
                    entry_rt,
                )
                continue
            row, err = _fhir_patient_to_row(resource, idx)
            if err:
                parse_errors.append(err)
            elif row:
                rows.append(row)
        if not rows and not parse_errors:
            parse_errors.append("Bundle contains no Patient resources.")
        return rows, parse_errors

    return [], [
        f"Unsupported resourceType {resource_type!r}. Expected 'Patient' or 'Bundle'."
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _parse_dob(raw: str) -> date | None:
    cleaned = raw.strip()
    for fmt in _DOB_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def validate_patient_row(row: dict[str, str], line_num: int) -> list[str]:
    """Validate a single parsed row. Returns list of error strings."""
    errors: list[str] = []
    prefix = f"Row {line_num}"

    for col in REQUIRED_COLUMNS:
        if not row.get(col, "").strip():
            errors.append(f"{prefix}: '{col}' is required but empty.")

    if errors:
        return errors

    dob_raw = row.get("dob", "")
    parsed_dob = _parse_dob(dob_raw)
    if parsed_dob is None:
        errors.append(
            f"{prefix}: 'dob' value {dob_raw!r} is not a recognised date. "
            "Use YYYY-MM-DD or MM/DD/YYYY."
        )
    elif parsed_dob > date.today():
        errors.append(f"{prefix}: 'dob' {dob_raw!r} is in the future.")
    elif parsed_dob.year < 1900:
        errors.append(f"{prefix}: 'dob' {dob_raw!r} — year before 1900 is unlikely.")

    sex_raw = row.get("sex", "").strip().lower()
    if sex_raw and sex_raw not in _SEX_MAP:
        errors.append(
            f"{prefix}: 'sex' value {row['sex']!r} is not recognised. "
            "Use Male, Female, Other, or Unknown."
        )

    email = row.get("email", "").strip()
    if email and not _EMAIL_RE.match(email):
        errors.append(f"{prefix}: 'email' value {email!r} does not look like a valid address.")

    zip_val = row.get("zip", "").strip()
    if zip_val and not re.match(r"^\d{5}(-\d{4})?$", zip_val):
        errors.append(f"{prefix}: 'zip' value {zip_val!r} should be 5 digits (or 5+4).")

    return errors


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

_PATIENTS_COLS_CACHE: set[str] | None = None
_PATIENTS_COLS_LOCK = threading.Lock()


def _get_patients_columns(cur: Any) -> set[str]:
    """Return the set of column names on ``patients`` table (cached)."""
    global _PATIENTS_COLS_CACHE
    with _PATIENTS_COLS_LOCK:
        if _PATIENTS_COLS_CACHE is not None:
            return _PATIENTS_COLS_CACHE
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'raf_intelligence'
              AND TABLE_NAME = 'patients'
            """
        )
        raw = cur.fetchall()
        cols = {
            (r["COLUMN_NAME"] if isinstance(r, dict) else r[0])
            for r in raw
        }
        _PATIENTS_COLS_CACHE = cols
        return cols


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _find_existing_patient(
    db: Any,
    ssn: str | None,
    mbi: str | None,
    dob: date | None,
    first_name: str | None,
    last_name: str | None,
    tenant_id: int,
) -> tuple[int | None, str | None]:
    """
    Look up an existing active patient by, in order:
      (a) MBI exact match,
      (b) SSN exact match,
      (c) (last_name, first_name, dob) exact match (case-insensitive names).

    Returns (patient_id, matched_field) if found, else (None, None).
    ``db`` is expected to be an open DB cursor.
    """
    if tenant_id is None:
        raise ValueError(
            "_find_existing_patient: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)

    # (a) MBI exact
    if mbi:
        mbi_clean = mbi.strip()
        if mbi_clean:
            db.execute(
                "SELECT id FROM patients WHERE mbi = %s AND is_active = 1 AND tenant_id = %s LIMIT 1",
                (mbi_clean, tid),
            )
            row = db.fetchone()
            if row is not None:
                pid = int(row["id"] if isinstance(row, dict) else row[0])
                return pid, "mbi"

    # (b) SSN exact
    if ssn:
        ssn_clean = ssn.strip()
        if ssn_clean:
            db.execute(
                "SELECT id FROM patients WHERE ssn = %s AND is_active = 1 AND tenant_id = %s LIMIT 1",
                (ssn_clean, tid),
            )
            row = db.fetchone()
            if row is not None:
                pid = int(row["id"] if isinstance(row, dict) else row[0])
                return pid, "ssn"

    # (c) (last_name, first_name, dob)
    if first_name and last_name and dob is not None:
        db.execute(
            """
            SELECT id FROM patients
            WHERE LOWER(last_name) = LOWER(%s)
              AND LOWER(first_name) = LOWER(%s)
              AND dob = %s
              AND is_active = 1
              AND tenant_id = %s
            LIMIT 1
            """,
            (last_name.strip(), first_name.strip(), dob.strftime("%Y-%m-%d"), tid),
        )
        row = db.fetchone()
        if row is not None:
            pid = int(row["id"] if isinstance(row, dict) else row[0])
            return pid, "name_dob"

    return None, None


def _find_existing_pid(
    cur: Any,
    first_name: str,
    last_name: str,
    dob: date,
    mrn: str | None,
    tenant_id: int,
) -> int | None:
    """Return the id of an existing patient record, or None if not found."""
    if tenant_id is None:
        raise ValueError(
            "_find_existing_pid: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)
    # Only match against ACTIVE patients — deactivated EMR patients don't count.
    if mrn:
        cur.execute(
            "SELECT id FROM patients WHERE mrn = %s AND is_active = 1 AND tenant_id = %s LIMIT 1",
            (mrn, tid),
        )
        row = cur.fetchone()
        if row is not None:
            return int(row["id"] if isinstance(row, dict) else row[0])

    # Fall back to name + DOB match.
    cur.execute(
        """
        SELECT id FROM patients
        WHERE LOWER(first_name) = LOWER(%s)
          AND LOWER(last_name) = LOWER(%s)
          AND dob = %s
          AND is_active = 1
          AND tenant_id = %s
        LIMIT 1
        """,
        (first_name, last_name, dob.strftime("%Y-%m-%d"), tid),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row["id"] if isinstance(row, dict) else row[0])
    return None


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_patients(
    rows: list[dict[str, str]],
    uploaded_by: str,
    on_duplicate: str = "skip",
    source: str = "csv",
    tenant_id: int | None = None,  # Will raise below if None
) -> dict[str, Any]:
    """
    Validate, deduplicate, and insert patients from parsed rows.

    Rows may come from CSV (:func:`parse_patient_csv`), Excel
    (:func:`parse_patient_xlsx`), or FHIR (:func:`parse_fhir_patients`) —
    all produce the same internal shape.

    Parameters
    ----------
    rows:
        Parsed row dicts.
    uploaded_by:
        Identifier of the user performing the import (stored in
        ``created_by`` / ``updated_by``).
    on_duplicate:
        ``"skip"`` (default) — leave existing records untouched and count them
        as ``duplicates_skipped``.
        ``"update"`` — overwrite non-empty, non-key fields on the existing
        record with values from the import row and count as ``updated``.
        ``"replace"`` — delete **all** existing patients first, then insert
        every row fresh.  Intended for demo / testing environments.
    source:
        Origin of the data: ``"csv"``, ``"excel"``, or ``"fhir"``.
        Stored in the ``source`` column of the ``patients`` table.
    """
    if tenant_id is None:
        raise ValueError(
            "import_patients: tenant_id is required — "
            "refusing to import patients without tenant scope (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)

    total_rows = len(rows)
    imported = 0
    updated = 0
    duplicates_skipped = 0
    deleted_count = 0
    error_details: list[str] = []

    # --- REPLACE mode: deactivate all existing EMR-sourced patients ---------
    # Instead of deleting, we mark EMR patients as inactive and disable the
    # active EMR connection. This is non-destructive — reactivating the EMR
    # connection later will restore those patients.
    if on_duplicate == "replace":
        try:
            with raf_cursor() as cur:
                # Count what will be deactivated (for the response).
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s",
                    (tid,),
                )
                result = cur.fetchone()
                deleted_count = result["cnt"] if isinstance(result, dict) else result[0]
                # Deactivate ALL currently active patients (EMR or prior CSV)
                # for this tenant only.
                cur.execute(
                    "UPDATE patients SET is_active = 0 WHERE is_active = 1 AND tenant_id = %s",
                    (tid,),
                )
                # Deactivate all currently active EMR connections for this
                # tenant so the app treats this as a CSV-only dataset until
                # the user reactivates.
                cur.execute(
                    "UPDATE emr_connections SET is_active = 0 WHERE is_active = 1 AND tenant_id = %s",
                    (tid,),
                )
                logger.info(
                    "patient_import: REPLACE mode — deactivated %d existing patients and EMR connections",
                    deleted_count,
                )
        except Exception as exc:
            logger.error("patient_import: REPLACE mode deactivation failed: %s", exc)
            return {
                "total_rows": total_rows,
                "imported": 0,
                "updated": 0,
                "deleted": 0,
                "duplicates_skipped": 0,
                "errors": 1,
                "error_details": [f"Failed to deactivate existing patients: {exc}"],
            }

    for row in rows:
        line_num = int(row.get("_line", 0))

        validation_errors = validate_patient_row(row, line_num)
        if validation_errors:
            error_details.extend(validation_errors)
            continue

        first_name = row["first_name"].strip()
        last_name = row["last_name"].strip()
        parsed_dob = _parse_dob(row["dob"].strip())
        if parsed_dob is None:
            error_details.append(f"Row {line_num}: internal DOB parse failure.")
            continue

        # Canonicalise sex
        sex_canonical = _SEX_MAP.get(
            row.get("sex", "").strip().lower(),
            row.get("sex", ""),
        )
        mrn = row.get("mrn", "").strip() or None

        # Canonical overrides used for both INSERT and UPDATE paths.
        canonical = {
            "first_name": first_name,
            "last_name": last_name,
            "dob": parsed_dob.strftime("%Y-%m-%d"),
            "sex": sex_canonical,
            "mrn": mrn or "",
        }

        try:
            with raf_cursor() as cur:
                # Build dynamic column set based on the live schema (cached).
                live_cols = _get_patients_columns(cur)

                # First check MBI / SSN / (name+dob) via the canonical
                # deduplication helper, then fall back to MRN-based matching.
                ssn_val = row.get("ssn", "").strip() or None
                mbi_val = row.get("mbi", "").strip() or None
                existing_pid, matched_field = _find_existing_patient(
                    cur,
                    ssn_val,
                    mbi_val,
                    parsed_dob,
                    first_name,
                    last_name,
                    tenant_id=tid,
                )
                if existing_pid is None:
                    existing_pid = _find_existing_pid(
                        cur, first_name, last_name, parsed_dob, mrn, tenant_id=tid
                    )
                    if existing_pid is not None:
                        matched_field = "mrn_or_name_dob"
                if existing_pid is not None:
                    if on_duplicate == "skip":
                        logger.info(
                            "patient_import: duplicate skipped (row %d, matched by %s, existing pid=%d)",
                            line_num,
                            matched_field,
                            existing_pid,
                        )
                        duplicates_skipped += 1
                        continue
                    # on_duplicate == "update" — update non-key fields only.
                    update_values: dict[str, Any] = {}
                    for csv_col in PATIENTS_TABLE_COLUMNS:
                        if csv_col not in live_cols:
                            continue
                        if csv_col in ("first_name", "last_name", "dob"):
                            continue  # don't overwrite match keys
                        raw_val = canonical.get(csv_col, row.get(csv_col, ""))
                        if raw_val is None:
                            continue
                        raw_val = str(raw_val).strip()
                        if raw_val == "":
                            continue
                        update_values[csv_col] = raw_val
                    if update_values:
                        update_values["source"] = source
                        if "updated_by" in live_cols:
                            update_values["updated_by"] = uploaded_by[:64]
                        set_clause = ", ".join(f"`{c}` = %s" for c in update_values)
                        sql = f"UPDATE patients SET {set_clause} WHERE id = %s AND tenant_id = %s"
                        cur.execute(sql, (*update_values.values(), existing_pid, tid))
                        updated += 1
                    else:
                        duplicates_skipped += 1
                    continue

                # --- INSERT path ---------------------------------------------------
                values: dict[str, Any] = {}
                for csv_col in PATIENTS_TABLE_COLUMNS:
                    if csv_col not in live_cols:
                        continue
                    raw_val = canonical.get(csv_col, row.get(csv_col, ""))
                    if raw_val is None:
                        continue
                    raw_val = str(raw_val).strip()
                    if raw_val == "":
                        continue
                    values[csv_col] = raw_val

                # Always-populated audit / metadata columns.
                values["source"] = source
                if "tenant_id" in live_cols:
                    values["tenant_id"] = tid
                if "created_by" in live_cols:
                    values["created_by"] = uploaded_by[:64]
                if "updated_by" in live_cols:
                    values["updated_by"] = uploaded_by[:64]
                if "status" in live_cols and "status" not in values:
                    values["status"] = "active"

                if not values:
                    error_details.append(
                        f"Row {line_num}: no writable columns resolved — schema mismatch."
                    )
                    continue

                cols_sql = ", ".join(f"`{c}`" for c in values)
                placeholders = ", ".join(["%s"] * len(values))
                sql = f"INSERT INTO patients ({cols_sql}) VALUES ({placeholders})"
                cur.execute(sql, tuple(values.values()))
                imported += 1

        except Exception as exc:
            logger.error(
                "patient_import: error inserting row %d (%s %s): %s",
                line_num,
                first_name,
                last_name,
                exc,
            )
            error_details.append(
                f"Row {line_num} ({first_name} {last_name}): database error — {exc}"
            )

    return {
        "total_rows": total_rows,
        "imported": imported,
        "updated": updated,
        "deleted": deleted_count,
        "duplicates_skipped": duplicates_skipped,
        "errors": len(error_details),
        "error_details": error_details,
    }
