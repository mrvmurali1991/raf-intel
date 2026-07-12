"""
Claims Data Ingestion Service — 837P / 837I / CSV.

Parses and processes healthcare claims files, matches patients to OpenEMR
patient records, maps ICD-10 codes to HCC categories, and supports batch
processing with summary statistics.

Supported formats:
  - CSV (primary customer format)
  - X12 837P (professional claims, EDI)
  - X12 837I (institutional claims, EDI)

NOTE: The 837 parsers implement a simplified direct-parse approach without
external EDI libraries. They handle the standard X12 delimited format with:
  segment terminator  ~
  element separator   *
  sub-element sep     :
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
from datetime import date, datetime
from typing import Any

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Claim format identifiers
FORMAT_CSV = "csv"
FORMAT_837P = "837p"
FORMAT_837I = "837i"

# Batch statuses
STATUS_UPLOADED = "uploaded"
STATUS_PARSED = "parsed"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# CSV Claims Parser
# ---------------------------------------------------------------------------

def parse_csv_claims(content: bytes | str) -> list[dict[str, Any]]:
    """
    Parse a CSV claims file into a list of normalized claim dicts.

    Expected columns (case-insensitive, extra columns are ignored):
      claim_id, patient_name, patient_dob, patient_gender, member_id,
      provider_npi, provider_name, date_of_service, icd10_codes (pipe-delimited),
      cpt_codes, charges, payer_name, place_of_service

    Returns list of claim dicts with normalized field names.
    """
    if isinstance(content, bytes):
        # Try UTF-8 first; fall back to latin-1 for common EDI encodings
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content

    reader = csv.DictReader(io.StringIO(text))
    claims: list[dict[str, Any]] = []

    # Normalize header keys: lowercase + strip whitespace
    for row_num, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}

        # ICD-10 codes can be pipe-delimited in a single column
        raw_icd = row.get("icd10_codes") or row.get("icd10") or row.get("diagnosis_codes") or ""
        icd10_codes = [c.strip().upper() for c in raw_icd.split("|") if c.strip()]

        # CPT codes similarly
        raw_cpt = row.get("cpt_codes") or row.get("cpt") or row.get("procedure_codes") or ""
        cpt_codes = [c.strip() for c in raw_cpt.split("|") if c.strip()]

        # Normalize charges to float
        raw_charges = row.get("charges") or row.get("charge_amount") or "0"
        try:
            charges = float(raw_charges.replace(",", "").replace("$", ""))
        except ValueError:
            charges = 0.0

        claim = {
            "source_claim_id": row.get("claim_id") or row.get("claimid") or f"row-{row_num}",
            "patient_name": row.get("patient_name") or row.get("member_name") or "",
            "patient_dob": _parse_date_str(row.get("patient_dob") or row.get("dob") or ""),
            "patient_gender": _normalize_gender(row.get("patient_gender") or row.get("gender") or ""),
            "member_id": row.get("member_id") or row.get("memberid") or row.get("subscriber_id") or "",
            "provider_npi": row.get("provider_npi") or row.get("npi") or "",
            "provider_name": row.get("provider_name") or row.get("rendering_provider") or "",
            "date_of_service": _parse_date_str(row.get("date_of_service") or row.get("dos") or row.get("service_date") or ""),
            "icd10_codes": icd10_codes,
            "cpt_codes": cpt_codes,
            "charges": charges,
            "payer_name": row.get("payer_name") or row.get("insurance") or row.get("payer") or "",
            "place_of_service": row.get("place_of_service") or row.get("pos") or "",
            "claim_type": "professional",
            "raw_row": row_num,
        }
        claims.append(claim)

    logger.info("CSV parser: parsed %d claims", len(claims))
    return claims


# ---------------------------------------------------------------------------
# 837P Parser (Professional Claims)
# ---------------------------------------------------------------------------

def parse_837p_claims(content: bytes | str) -> list[dict[str, Any]]:
    """
    Parse an X12 837P EDI file into normalized claim dicts.

    Handles standard X12 envelope:
      ISA*...*~ (interchange control header)
      GS*...*~  (functional group header)
      ST*837*~  (transaction set header)
      NM1 loops for subscriber/patient/provider
      CLM (claim information)
      HI  (diagnosis codes — HI*ABK: is principal ICD-10)
      SV1 (service line)
      DTP (dates)
      REF (reference IDs including member ID)
    """
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content

    # X12 uses ~ as segment terminator; normalize line endings
    text = text.replace("\r\n", "").replace("\n", "").replace("\r", "")

    # Detect element separator from ISA segment (position 3)
    elem_sep = "*"
    sub_sep = ":"
    seg_term = "~"

    # Try to auto-detect from ISA
    isa_match = re.search(r"ISA(.)(.*?)\1", text)
    if isa_match:
        elem_sep = isa_match.group(1)
        # Sub-element separator is ISA16
        isa_parts = text[text.find("ISA"):text.find(seg_term, text.find("ISA"))].split(elem_sep)
        if len(isa_parts) >= 17:
            sub_sep = isa_parts[16][:1] or ":"

    segments = [s.strip() for s in text.split(seg_term) if s.strip()]

    claims: list[dict[str, Any]] = []
    current_claim: dict[str, Any] | None = None
    current_patient: dict[str, str] = {}
    current_subscriber: dict[str, str] = {}
    current_provider: dict[str, str] = {}
    nm1_context: str = ""  # tracks which NM1 loop we're in

    for raw_seg in segments:
        parts = raw_seg.split(elem_sep)
        seg_id = parts[0].strip().upper()

        if seg_id == "NM1":
            # NM1*IL = subscriber, NM1*QC = patient, NM1*82/85 = rendering/billing provider
            if len(parts) < 2:
                continue
            nm1_type = parts[1].strip().upper()
            nm1_context = nm1_type
            lname = parts[3].strip() if len(parts) > 3 else ""
            fname = parts[4].strip() if len(parts) > 4 else ""
            full_name = f"{fname} {lname}".strip()
            npi = parts[9].strip() if len(parts) > 9 else ""

            if nm1_type == "IL":  # insured / subscriber
                current_subscriber = {"name": full_name, "npi": npi}
            elif nm1_type == "QC":  # patient
                current_patient = {"name": full_name}
            elif nm1_type in ("82", "85", "77"):  # rendering / billing provider
                current_provider = {"name": full_name, "npi": npi}

        elif seg_id == "DMG":
            # DMG*D8*YYYYMMDD*gender
            dob_raw = parts[2].strip() if len(parts) > 2 else ""
            gender_raw = parts[3].strip() if len(parts) > 3 else ""
            dob = _parse_date_str(dob_raw)
            gender = _normalize_gender(gender_raw)
            if nm1_context == "QC":
                current_patient.update({"dob": dob, "gender": gender})
            else:
                current_subscriber.update({"dob": dob, "gender": gender})

        elif seg_id == "REF":
            # REF*1W = member ID, REF*SY = SSN, REF*HJ = claim number
            if len(parts) < 3:
                continue
            ref_qual = parts[1].strip().upper()
            ref_val = parts[2].strip()
            if ref_qual in ("1W", "IG", "SY") and current_claim is None:
                current_subscriber["member_id"] = ref_val
            elif ref_qual == "1W" and current_claim is not None:
                current_claim["member_id"] = ref_val
            elif ref_qual == "HJ" and current_claim is not None:
                current_claim["source_claim_id"] = ref_val

        elif seg_id == "CLM":
            # CLM*claim_id*charges*...*pos:...*...
            if current_claim is not None:
                claims.append(current_claim)

            claim_id = parts[1].strip() if len(parts) > 1 else str(uuid.uuid4())[:8]
            charges_raw = parts[2].strip() if len(parts) > 2 else "0"
            try:
                charges = float(charges_raw)
            except ValueError:
                charges = 0.0

            # CLM05 = place of service info (sub-element: pos_code:qualifier:response)
            pos = ""
            if len(parts) > 5:
                clm05_parts = parts[5].split(sub_sep)
                pos = clm05_parts[0].strip()

            # Use patient name if available, else subscriber
            patient_name = current_patient.get("name") or current_subscriber.get("name") or ""
            patient_dob = current_patient.get("dob") or current_subscriber.get("dob") or ""
            patient_gender = current_patient.get("gender") or current_subscriber.get("gender") or ""
            member_id = current_subscriber.get("member_id") or ""

            current_claim = {
                "source_claim_id": claim_id,
                "patient_name": patient_name,
                "patient_dob": patient_dob,
                "patient_gender": patient_gender,
                "member_id": member_id,
                "provider_npi": current_provider.get("npi") or "",
                "provider_name": current_provider.get("name") or "",
                "date_of_service": "",
                "icd10_codes": [],
                "cpt_codes": [],
                "charges": charges,
                "payer_name": "",
                "place_of_service": pos,
                "claim_type": "professional",
                "admission_date": "",
                "discharge_date": "",
            }

        elif seg_id == "HI" and current_claim is not None:
            # HI*ABK:ICD10_CODE (principal diagnosis)
            # HI*ABF:ICD10_CODE (other diagnosis)
            # HI*BK:ICD10_CODE (older format)
            for hi_part in parts[1:]:
                hi_subs = hi_part.split(sub_sep)
                if len(hi_subs) < 2:
                    continue
                qualifier = hi_subs[0].strip().upper()
                code = hi_subs[1].strip().upper()
                if qualifier in ("ABK", "ABF", "BK", "BF", "ABN", "ABJ") and code:
                    # Normalize: remove dots, uppercase
                    normalized = code.replace(".", "").upper()
                    if normalized not in current_claim["icd10_codes"]:
                        current_claim["icd10_codes"].append(normalized)

        elif seg_id == "SV1" and current_claim is not None:
            # SV1*HC:CPT_CODE*charges*...*
            if len(parts) > 1:
                sv1_subs = parts[1].split(sub_sep)
                if len(sv1_subs) >= 2:
                    cpt = sv1_subs[1].strip()
                    if cpt and cpt not in current_claim["cpt_codes"]:
                        current_claim["cpt_codes"].append(cpt)
            # SV1 charges override CLM charges if more specific
            if len(parts) > 2:
                try:
                    current_claim["charges"] = max(
                        current_claim["charges"], float(parts[2].strip() or "0")
                    )
                except ValueError:
                    pass

        elif seg_id == "DTP" and current_claim is not None:
            # DTP*472 = date of service, DTP*435 = admission, DTP*096 = discharge
            if len(parts) < 4:
                continue
            dtp_qual = parts[1].strip()
            dtp_fmt = parts[2].strip()
            dtp_val = parts[3].strip()
            parsed_date = _parse_date_str(dtp_val)
            if dtp_qual in ("472", "291"):  # date of service
                current_claim["date_of_service"] = parsed_date
            elif dtp_qual == "435":  # admission date
                current_claim["admission_date"] = parsed_date
            elif dtp_qual == "096":  # discharge date
                current_claim["discharge_date"] = parsed_date

        elif seg_id in ("SE", "GE", "IEA"):
            # Transaction/group/interchange end
            if current_claim is not None:
                claims.append(current_claim)
                current_claim = None

    # Flush last claim if transaction didn't close cleanly
    if current_claim is not None:
        claims.append(current_claim)

    logger.info("837P parser: parsed %d claims", len(claims))
    return claims


# ---------------------------------------------------------------------------
# 837I Parser (Institutional Claims)
# ---------------------------------------------------------------------------

def parse_837i_claims(content: bytes | str) -> list[dict[str, Any]]:
    """
    Parse an X12 837I EDI file into normalized claim dicts.

    Institutional-specific segments beyond 837P:
      CLM05 — facility type code / bill type
      CL1   — admission type, admission source, discharge status
      HI    — includes admitting diagnosis (ABJ), principal (ABK/ABF),
               and other diagnoses; also procedure codes
      DTP*435 — admission date
      DTP*096 — discharge date
    """
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content

    text = text.replace("\r\n", "").replace("\n", "").replace("\r", "")

    elem_sep = "*"
    sub_sep = ":"
    seg_term = "~"

    isa_pos = text.find("ISA")
    if isa_pos >= 0:
        isa_parts = text[isa_pos:text.find(seg_term, isa_pos)].split(elem_sep)
        if len(isa_parts) >= 17:
            sub_sep = isa_parts[16][:1] or ":"

    segments = [s.strip() for s in text.split(seg_term) if s.strip()]

    claims: list[dict[str, Any]] = []
    current_claim: dict[str, Any] | None = None
    current_patient: dict[str, str] = {}
    current_subscriber: dict[str, str] = {}
    current_provider: dict[str, str] = {}
    nm1_context: str = ""

    for raw_seg in segments:
        parts = raw_seg.split(elem_sep)
        seg_id = parts[0].strip().upper()

        if seg_id == "NM1":
            if len(parts) < 2:
                continue
            nm1_type = parts[1].strip().upper()
            nm1_context = nm1_type
            lname = parts[3].strip() if len(parts) > 3 else ""
            fname = parts[4].strip() if len(parts) > 4 else ""
            full_name = f"{fname} {lname}".strip()
            npi = parts[9].strip() if len(parts) > 9 else ""

            if nm1_type == "IL":
                current_subscriber = {"name": full_name, "npi": npi}
            elif nm1_type == "QC":
                current_patient = {"name": full_name}
            elif nm1_type in ("82", "85", "77", "FA"):  # FA = facility
                current_provider = {"name": full_name, "npi": npi}

        elif seg_id == "DMG":
            dob_raw = parts[2].strip() if len(parts) > 2 else ""
            gender_raw = parts[3].strip() if len(parts) > 3 else ""
            dob = _parse_date_str(dob_raw)
            gender = _normalize_gender(gender_raw)
            if nm1_context == "QC":
                current_patient.update({"dob": dob, "gender": gender})
            else:
                current_subscriber.update({"dob": dob, "gender": gender})

        elif seg_id == "REF":
            if len(parts) < 3:
                continue
            ref_qual = parts[1].strip().upper()
            ref_val = parts[2].strip()
            if ref_qual in ("1W", "IG") and current_claim is None:
                current_subscriber["member_id"] = ref_val
            elif ref_qual in ("1W", "IG") and current_claim is not None:
                current_claim["member_id"] = ref_val
            elif ref_qual == "HJ" and current_claim is not None:
                current_claim["source_claim_id"] = ref_val

        elif seg_id == "CLM":
            if current_claim is not None:
                claims.append(current_claim)

            claim_id = parts[1].strip() if len(parts) > 1 else str(uuid.uuid4())[:8]
            charges_raw = parts[2].strip() if len(parts) > 2 else "0"
            try:
                charges = float(charges_raw)
            except ValueError:
                charges = 0.0

            # CLM05: bill_type_code:qualifier:response for institutional
            facility_type = ""
            if len(parts) > 5:
                clm05_parts = parts[5].split(sub_sep)
                facility_type = clm05_parts[0].strip()

            patient_name = current_patient.get("name") or current_subscriber.get("name") or ""
            patient_dob = current_patient.get("dob") or current_subscriber.get("dob") or ""
            patient_gender = current_patient.get("gender") or current_subscriber.get("gender") or ""
            member_id = current_subscriber.get("member_id") or ""

            current_claim = {
                "source_claim_id": claim_id,
                "patient_name": patient_name,
                "patient_dob": patient_dob,
                "patient_gender": patient_gender,
                "member_id": member_id,
                "provider_npi": current_provider.get("npi") or "",
                "provider_name": current_provider.get("name") or "",
                "date_of_service": "",
                "icd10_codes": [],
                "cpt_codes": [],
                "charges": charges,
                "payer_name": "",
                "place_of_service": facility_type,
                "claim_type": "institutional",
                "facility_type": facility_type,
                "admission_date": "",
                "discharge_date": "",
                "admission_type": "",
                "admission_source": "",
                "discharge_status": "",
                "admitting_diagnosis": "",
                "principal_diagnosis": "",
            }

        elif seg_id == "CL1" and current_claim is not None:
            # CL1*admission_type*admission_source*discharge_status
            current_claim["admission_type"] = parts[1].strip() if len(parts) > 1 else ""
            current_claim["admission_source"] = parts[2].strip() if len(parts) > 2 else ""
            current_claim["discharge_status"] = parts[3].strip() if len(parts) > 3 else ""

        elif seg_id == "HI" and current_claim is not None:
            for hi_part in parts[1:]:
                hi_subs = hi_part.split(sub_sep)
                if len(hi_subs) < 2:
                    continue
                qualifier = hi_subs[0].strip().upper()
                code = hi_subs[1].strip().upper()
                if not code:
                    continue
                normalized = code.replace(".", "").upper()
                if qualifier == "ABJ":  # admitting diagnosis
                    current_claim["admitting_diagnosis"] = normalized
                    if normalized not in current_claim["icd10_codes"]:
                        current_claim["icd10_codes"].append(normalized)
                elif qualifier in ("ABK", "BK"):  # principal diagnosis
                    current_claim["principal_diagnosis"] = normalized
                    if normalized not in current_claim["icd10_codes"]:
                        current_claim["icd10_codes"].insert(0, normalized)
                elif qualifier in ("ABF", "BF", "ABN"):  # other diagnoses
                    if normalized not in current_claim["icd10_codes"]:
                        current_claim["icd10_codes"].append(normalized)
                elif qualifier in ("BO", "BR"):  # revenue codes / procedure codes
                    if normalized not in current_claim["cpt_codes"]:
                        current_claim["cpt_codes"].append(normalized)

        elif seg_id == "SV2" and current_claim is not None:
            # SV2 is institutional service line (revenue code * charge)
            if len(parts) > 2:
                try:
                    line_charge = float(parts[2].strip() or "0")
                    current_claim["charges"] = max(current_claim["charges"], line_charge)
                except ValueError:
                    pass

        elif seg_id == "DTP" and current_claim is not None:
            if len(parts) < 4:
                continue
            dtp_qual = parts[1].strip()
            dtp_val = parts[3].strip()
            parsed_date = _parse_date_str(dtp_val)
            if dtp_qual in ("472", "291"):
                current_claim["date_of_service"] = parsed_date
            elif dtp_qual == "435":
                current_claim["admission_date"] = parsed_date
                if not current_claim["date_of_service"]:
                    current_claim["date_of_service"] = parsed_date
            elif dtp_qual == "096":
                current_claim["discharge_date"] = parsed_date

        elif seg_id in ("SE", "GE", "IEA"):
            if current_claim is not None:
                claims.append(current_claim)
                current_claim = None

    if current_claim is not None:
        claims.append(current_claim)

    logger.info("837I parser: parsed %d claims", len(claims))
    return claims


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(filename: str, content: bytes) -> str:
    """
    Auto-detect claims file format from filename extension and/or content.

    Returns one of: 'csv', '837p', '837i'
    """
    lower_name = filename.lower()

    if lower_name.endswith(".csv"):
        return FORMAT_CSV

    if lower_name.endswith((".edi", ".x12", ".txt", ".837")):
        # Inspect content to distinguish 837P vs 837I
        sample = content[:2000].decode("latin-1", errors="replace").upper()
        # 837I transaction sets contain institutional-specific segments CL1 or SV2.
        # Check explicit type markers first, then fall back to segment inspection.
        if "837I" in sample or "CL1*" in sample or "SV2*" in sample:
            return FORMAT_837I
        # 837P is the default professional format (also carries GS*HC).
        return FORMAT_837P

    # Peek at content regardless of extension
    sample = content[:500].decode("latin-1", errors="replace").strip()
    if sample.startswith("ISA"):
        inner = content[:3000].decode("latin-1", errors="replace").upper()
        if "CL1*" in inner or "SV2*" in inner:
            return FORMAT_837I
        return FORMAT_837P

    # Default to CSV
    return FORMAT_CSV


def parse_claims_file(filename: str, content: bytes) -> tuple[str, list[dict[str, Any]]]:
    """
    Detect format and parse a claims file.

    Returns (format_detected, list_of_claims).
    """
    fmt = detect_format(filename, content)
    logger.info("Parsing claims file '%s' as format '%s'", filename, fmt)

    if fmt == FORMAT_CSV:
        return fmt, parse_csv_claims(content)
    if fmt == FORMAT_837I:
        return fmt, parse_837i_claims(content)
    return fmt, parse_837p_claims(content)


# ---------------------------------------------------------------------------
# Database helpers — batch management
# ---------------------------------------------------------------------------

def create_batch(
    filename: str,
    file_format: str,
    file_size: int,
    uploaded_by: str = "api",
    tenant_id: str = "",
) -> int:
    """Insert a new claims batch record and return its ID."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO claims_batches
                (batch_uuid, filename, file_format, file_size, status, uploaded_by, tenant_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (str(uuid.uuid4()), filename, file_format, file_size, STATUS_UPLOADED, uploaded_by, tenant_id or None),
        )
        batch_id = cur.lastrowid
    logger.info("Created claims batch id=%d filename='%s' format=%s tenant_id=%s", batch_id, filename, file_format, tenant_id)
    return batch_id


def update_batch_status(batch_id: int, status: str, error_message: str | None = None) -> None:
    """Update batch processing status."""
    with raf_cursor() as cur:
        if error_message:
            cur.execute(
                "UPDATE claims_batches SET status=%s, error_message=%s, updated_at=NOW() WHERE id=%s",
                (status, error_message[:1000], batch_id),
            )
        else:
            cur.execute(
                "UPDATE claims_batches SET status=%s, updated_at=NOW() WHERE id=%s",
                (status, batch_id),
            )


def store_parsed_claims(batch_id: int, claims: list[dict[str, Any]]) -> int:
    """
    Bulk-insert parsed claims into the claims_records table.

    Returns the number of rows inserted.
    """
    if not claims:
        return 0

    rows = [
        (
            batch_id,
            claim.get("source_claim_id") or "",
            claim.get("patient_name") or "",
            claim.get("patient_dob") or None,
            claim.get("patient_gender") or "",
            claim.get("member_id") or "",
            claim.get("provider_npi") or "",
            claim.get("provider_name") or "",
            claim.get("date_of_service") or None,
            json.dumps(claim.get("icd10_codes") or []),
            json.dumps(claim.get("cpt_codes") or []),
            claim.get("charges") or 0.0,
            claim.get("payer_name") or "",
            claim.get("place_of_service") or "",
            claim.get("claim_type") or "professional",
            claim.get("facility_type") or "",
            claim.get("admission_date") or None,
            claim.get("discharge_date") or None,
            claim.get("admission_type") or "",
            claim.get("admission_source") or "",
            claim.get("discharge_status") or "",
            claim.get("admitting_diagnosis") or "",
            claim.get("principal_diagnosis") or "",
        )
        for claim in claims
    ]
    with raf_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO claims_records (
                batch_id, source_claim_id, patient_name, patient_dob,
                patient_gender, member_id, provider_npi, provider_name,
                date_of_service, icd10_codes, cpt_codes, charges,
                payer_name, place_of_service, claim_type,
                facility_type, admission_date, discharge_date,
                admission_type, admission_source, discharge_status,
                admitting_diagnosis, principal_diagnosis,
                created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                NOW()
            )
            """,
            rows,
        )
    inserted = len(rows)

    # Update batch claim count
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE claims_batches SET claim_count=%s, updated_at=NOW() WHERE id=%s",
            (inserted, batch_id),
        )

    logger.info("Stored %d claims for batch_id=%d", inserted, batch_id)
    return inserted


def get_batch(batch_id: int, tenant_id: str = "") -> dict[str, Any] | None:
    """Return a single batch record by ID."""
    with raf_cursor() as cur:
        if tenant_id:
            cur.execute("SELECT * FROM claims_batches WHERE id=%s AND tenant_id=%s", (batch_id, tenant_id))
        else:
            cur.execute("SELECT * FROM claims_batches WHERE id=%s", (batch_id,))
        row = cur.fetchone()
    return _serialize_row(row) if row else None


def list_batches(limit: int = 50, offset: int = 0, tenant_id: str = "") -> list[dict[str, Any]]:
    """Return all claims batches ordered by most recent.

    Falls back to an unfiltered (no tenant_id clause) query when the
    ``tenant_id`` column is absent from ``claims_batches`` due to schema
    drift, so a missing migration never produces a 500 for callers.
    """
    try:
        with raf_cursor() as cur:
            if tenant_id:
                cur.execute(
                    "SELECT * FROM claims_batches WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (tenant_id, limit, offset),
                )
            else:
                cur.execute(
                    "SELECT * FROM claims_batches ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            rows = cur.fetchall()
        return [_serialize_row(r) for r in rows]
    except Exception as exc:
        exc_lower = str(exc).lower()
        if "tenant_id" in exc_lower or "unknown column" in exc_lower:
            logger.warning(
                "claims_batches missing tenant_id column — returning unfiltered list. "
                "Run migration 021_batch1_schema_additions to fix. Error: %s",
                exc,
            )
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        "SELECT * FROM claims_batches ORDER BY created_at DESC LIMIT %s OFFSET %s",
                        (limit, offset),
                    )
                    rows = cur.fetchall()
                return [_serialize_row(r) for r in rows]
            except Exception as inner_exc:
                logger.error("list_batches fallback also failed: %s", inner_exc)
                return []
        raise


def delete_batch(batch_id: int, tenant_id: str = "") -> int:
    """Delete a batch and all associated claims. Returns rows deleted.

    When *tenant_id* is supplied the DELETE is scoped to that tenant so a
    caller cannot delete a batch belonging to a different tenant.
    """
    with raf_cursor() as cur:
        cur.execute("DELETE FROM claims_records WHERE batch_id=%s", (batch_id,))
        deleted_claims = cur.rowcount
        if tenant_id:
            cur.execute(
                "DELETE FROM claims_batches WHERE id=%s AND tenant_id=%s",
                (batch_id, tenant_id),
            )
        else:
            cur.execute("DELETE FROM claims_batches WHERE id=%s", (batch_id,))
    logger.info("Deleted batch_id=%d (%d claims removed)", batch_id, deleted_claims)
    return deleted_claims


def get_batch_claims(
    batch_id: int, limit: int = 100, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Return paginated claims for a batch with total count."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM claims_records WHERE batch_id=%s",
            (batch_id,),
        )
        total = (cur.fetchone() or {}).get("cnt", 0)
        cur.execute(
            "SELECT * FROM claims_records WHERE batch_id=%s ORDER BY id LIMIT %s OFFSET %s",
            (batch_id, limit, offset),
        )
        rows = cur.fetchall()
    return [_serialize_row(r) for r in rows], total


# ---------------------------------------------------------------------------
# Patient matching
# ---------------------------------------------------------------------------

def match_patients_to_openemr(batch_id: int) -> dict[str, Any]:
    """
    Attempt to match claim patients to OpenEMR pids.

    Matching strategy (in priority order):
      1. Exact member_id match against OpenEMR pubpid / insurance subscriber ID
      2. Exact name + DOB match (normalized last name, first name, DOB)
      3. Fuzzy name match (last name Soundex + DOB year)

    Updates claims_records.openemr_pid where a match is found.
    Returns a summary dict with match counts.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, patient_name, patient_dob, member_id FROM claims_records WHERE batch_id=%s",
            (batch_id,),
        )
        claim_rows = cur.fetchall()

    matched = 0
    unmatched = 0

    for claim_row in claim_rows:
        claim_id = claim_row["id"]
        patient_name = claim_row.get("patient_name") or ""
        patient_dob = claim_row.get("patient_dob")
        member_id = (claim_row.get("member_id") or "").strip()

        pid = None

        # Strategy 1: member_id lookup
        if member_id and pid is None:
            pid = _match_by_member_id(member_id)

        # Strategy 2: exact name + DOB
        if not pid and patient_name:
            pid = _match_by_name_dob(patient_name, patient_dob)

        # Strategy 3: fuzzy name + DOB year
        if not pid and patient_name and patient_dob:
            pid = _match_by_name_dob_fuzzy(patient_name, patient_dob)

        if pid:
            with raf_cursor() as cur2:
                cur2.execute(
                    "UPDATE claims_records SET openemr_pid=%s WHERE id=%s",
                    (pid, claim_id),
                )
            matched += 1
        else:
            unmatched += 1

    total = matched + unmatched
    logger.info(
        "Patient matching batch_id=%d: %d/%d matched (%.1f%%)",
        batch_id, matched, total, (matched / total * 100) if total else 0,
    )
    return {
        "total": total,
        "matched": matched,
        "unmatched": unmatched,
        "match_rate": round(matched / total, 4) if total else 0.0,
    }


def _match_by_member_id(member_id: str) -> int | None:
    """Try to find an OpenEMR pid from a subscriber/member ID."""
    try:
        with openemr_cursor() as cur:
            # pubpid is often the member/insurance ID in OpenEMR
            cur.execute(
                "SELECT pid FROM patient_data WHERE pubpid=%s LIMIT 1",
                (member_id,),
            )
            row = cur.fetchone()
            if row:
                return int(row["pid"])
    except Exception as exc:
        logger.debug("_match_by_member_id error: %s", exc)
    return None


def _match_by_name_dob(patient_name: str, patient_dob: Any) -> int | None:
    """Exact first+last name and DOB match against OpenEMR patient_data."""
    if not patient_name or not patient_dob:
        return None

    name_parts = patient_name.strip().split()
    if len(name_parts) < 2:
        return None

    # Assume "First Last" or "Last, First" format
    if "," in patient_name:
        parts = patient_name.split(",", 1)
        lname = parts[0].strip()
        fname = parts[1].strip().split()[0] if parts[1].strip() else ""
    else:
        fname = name_parts[0]
        lname = name_parts[-1]

    dob_str = str(patient_dob)[:10] if patient_dob else ""

    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT pid FROM patient_data
                WHERE UPPER(fname)=UPPER(%s)
                  AND UPPER(lname)=UPPER(%s)
                  AND DOB=%s
                LIMIT 1
                """,
                (fname, lname, dob_str),
            )
            row = cur.fetchone()
            if row:
                return int(row["pid"])
    except Exception as exc:
        logger.debug("_match_by_name_dob error: %s", exc)
    return None


def _match_by_name_dob_fuzzy(patient_name: str, patient_dob: Any) -> int | None:
    """
    Fuzzy match: last name LIKE + DOB year match.
    Reduces false positives by requiring both last name prefix and birth year.
    """
    if not patient_name or not patient_dob:
        return None

    name_parts = patient_name.strip().split()
    lname = name_parts[-1] if name_parts else ""

    dob_str = str(patient_dob)[:10] if patient_dob else ""
    birth_year = dob_str[:4] if len(dob_str) >= 4 else ""

    if len(lname) < 3 or not birth_year:
        return None

    # Use first 4 chars of last name as fuzzy prefix to reduce false matches
    lname_prefix = lname[:4]

    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT pid, fname, lname, DOB FROM patient_data
                WHERE UPPER(lname) LIKE UPPER(%s)
                  AND YEAR(DOB) = %s
                LIMIT 5
                """,
                (f"{lname_prefix}%", birth_year),
            )
            candidates = cur.fetchall()

        # Score candidates by name similarity
        best_pid = None
        best_score = 0

        for candidate in candidates:
            c_full = f"{candidate.get('fname', '')} {candidate.get('lname', '')}".strip().upper()
            target = patient_name.upper()
            score = _name_similarity(target, c_full)
            if score > best_score and score >= 0.7:
                best_score = score
                best_pid = int(candidate["pid"])

        return best_pid
    except Exception as exc:
        logger.debug("_match_by_name_dob_fuzzy error: %s", exc)
    return None


def _name_similarity(a: str, b: str) -> float:
    """
    Simple token-overlap similarity between two name strings.
    Returns a score between 0.0 and 1.0.
    """
    tokens_a = set(a.upper().split())
    tokens_b = set(b.upper().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# HCC Mapping
# ---------------------------------------------------------------------------

def map_hcc_codes_for_batch(batch_id: int) -> dict[str, Any]:
    """
    For each ICD-10 code in the batch, look up its HCC mapping and store it
    in claims_diagnoses table.

    Lookup order:
      1. hcc_icd10_crosswalk table in the RAF DB (if it exists)
      2. hccinfhir library (in-process lookup)

    Returns a summary with counts of codes mapped to HCCs.
    """
    # Collect all unique ICD-10 codes from this batch
    with raf_cursor() as cur:
        cur.execute(
            "SELECT DISTINCT id, icd10_codes, batch_id, openemr_pid FROM claims_records WHERE batch_id=%s",
            (batch_id,),
        )
        claim_rows = cur.fetchall()

    # Build a unique set of codes across all claims
    all_icd_codes: set[str] = set()
    for row in claim_rows:
        codes = _parse_json_list(row.get("icd10_codes"))
        all_icd_codes.update(codes)

    # Bulk lookup HCC mappings
    hcc_map = _lookup_hcc_bulk(list(all_icd_codes))

    # Store diagnoses records
    mapped_count = 0
    total_codes = 0

    with raf_cursor() as cur:
        # Clear existing diagnosis records for this batch
        cur.execute("DELETE FROM claims_diagnoses WHERE batch_id=%s", (batch_id,))

        for row in claim_rows:
            codes = _parse_json_list(row.get("icd10_codes"))
            claim_record_id = row["id"]
            openemr_pid = row.get("openemr_pid")

            for icd_code in codes:
                total_codes += 1
                hcc_info = hcc_map.get(icd_code, {})
                hcc_code = hcc_info.get("hcc_code")
                hcc_label = hcc_info.get("hcc_label") or ""

                if hcc_code:
                    mapped_count += 1

                cur.execute(
                    """
                    INSERT INTO claims_diagnoses
                        (batch_id, claim_record_id, openemr_pid, icd10_code,
                         hcc_code, hcc_label, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (batch_id, claim_record_id, openemr_pid, icd_code, hcc_code, hcc_label),
                )

    logger.info(
        "HCC mapping batch_id=%d: %d/%d codes mapped to HCC",
        batch_id, mapped_count, total_codes,
    )
    return {
        "total_codes": total_codes,
        "mapped_to_hcc": mapped_count,
        "unmapped": total_codes - mapped_count,
        "mapping_rate": round(mapped_count / total_codes, 4) if total_codes else 0.0,
    }


def _lookup_hcc_bulk(icd_codes: list[str]) -> dict[str, dict[str, Any]]:
    """
    Look up HCC mappings for a list of ICD-10 codes.

    Tries the hcc_icd10_crosswalk DB table first; falls back to hccinfhir.
    Returns dict keyed by ICD-10 code with {'hcc_code': str|None, 'hcc_label': str}.
    """
    result: dict[str, dict[str, Any]] = {code: {"hcc_code": None, "hcc_label": ""} for code in icd_codes}

    if not icd_codes:
        return result

    # Use hccinfhir as the single source of truth (not the crosswalk table)
    try:
        from app.services.hcc_mapping_service import map_icd10_batch
        mapped = map_icd10_batch(icd_codes, "V28")
        for code, info in mapped.items():
            if info:
                result[code] = {
                    "hcc_code": info.get("hcc_code"),
                    "hcc_label": "",
                }
                try:
                    from app.services.hccinfhir_utils import get_hcc_label
                    result[code]["hcc_label"] = get_hcc_label(info["hcc_code"]) or ""
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("_lookup_hcc_bulk hccinfhir failed, falling back to crosswalk: %s", exc)
        # Fallback to DB crosswalk
        db_found: set[str] = set()
        try:
            with raf_cursor() as cur:
                placeholders = ",".join(["%s"] * len(icd_codes))
                cur.execute(
                    f"SELECT icd10_code, hcc_code, hcc_label FROM hcc_icd10_crosswalk WHERE icd10_code IN ({placeholders})",
                    icd_codes,
                )
                rows = cur.fetchall()
                for row in rows:
                    code = (row.get("icd10_code") or "").strip().upper()
                    if code:
                        result[code] = {
                            "hcc_code": str(row.get("hcc_code") or ""),
                            "hcc_label": row.get("hcc_label") or "",
                        }
                        db_found.add(code)
        except Exception as _fallback_exc:
            logger.debug("hcc_icd10_crosswalk fallback also failed: %s", _fallback_exc)

    # For codes not found in DB, use hccinfhir
    remaining = [c for c in icd_codes if c not in db_found]
    if remaining:
        try:
            from hccinfhir import HCCInFHIR
            processor = HCCInFHIR(model_name="CMS-HCC Model V28")

            for code in remaining:
                try:
                    # Use a dummy demographics to just get the HCC mapping
                    test_result = processor.calculate_from_diagnosis(
                        [code], age=70, sex="M", prefix_override="CNA_"
                    )
                    if test_result.hcc_list:
                        hcc_val = str(test_result.hcc_list[0])
                        # Get label from hcc_details if available
                        label = ""
                        if test_result.hcc_details:
                            label = test_result.hcc_details[0].label or ""
                        result[code] = {"hcc_code": hcc_val, "hcc_label": label}
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
                    pass  # Code has no HCC mapping; leave as None
        except ImportError:
            logger.warning("hccinfhir not available for HCC fallback mapping")

    return result


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_batch(batch_id: int) -> dict[str, Any]:
    """
    Full batch processing pipeline:
      1. Match patients to OpenEMR pids
      2. Map ICD-10 codes to HCCs
      3. Update batch status to completed

    Returns a combined summary.
    """
    batch = get_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    update_batch_status(batch_id, STATUS_PROCESSING)

    try:
        matching_summary = match_patients_to_openemr(batch_id)
        hcc_summary = map_hcc_codes_for_batch(batch_id)

        # Compute and persist batch stats
        stats = compute_batch_stats(batch_id)

        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE claims_batches
                SET status=%s,
                    matched_patient_count=%s,
                    unique_patient_count=%s,
                    unique_provider_count=%s,
                    total_charges=%s,
                    updated_at=NOW()
                WHERE id=%s
                """,
                (
                    STATUS_COMPLETED,
                    matching_summary["matched"],
                    stats.get("unique_patients", 0),
                    stats.get("unique_providers", 0),
                    stats.get("total_charges", 0.0),
                    batch_id,
                ),
            )

        return {
            "batch_id": batch_id,
            "status": STATUS_COMPLETED,
            "patient_matching": matching_summary,
            "hcc_mapping": hcc_summary,
            "stats": stats,
        }

    except Exception as exc:
        update_batch_status(batch_id, STATUS_FAILED, str(exc))
        logger.error("process_batch failed for batch_id=%d: %s", batch_id, exc)
        raise


def compute_batch_stats(batch_id: int) -> dict[str, Any]:
    """Compute summary statistics for a batch."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_claims,
                    COUNT(DISTINCT patient_name) AS unique_patient_names,
                    COUNT(DISTINCT openemr_pid) AS unique_matched_patients,
                    COUNT(DISTINCT provider_npi) AS unique_providers,
                    SUM(charges) AS total_charges,
                    MIN(date_of_service) AS earliest_dos,
                    MAX(date_of_service) AS latest_dos,
                    SUM(CASE WHEN openemr_pid IS NOT NULL THEN 1 ELSE 0 END) AS matched_count
                FROM claims_records
                WHERE batch_id=%s
                """,
                (batch_id,),
            )
            row = cur.fetchone() or {}

        # HCC distribution
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT hcc_code, hcc_label, COUNT(*) AS occurrence_count
                FROM claims_diagnoses
                WHERE batch_id=%s AND hcc_code IS NOT NULL AND hcc_code != ''
                GROUP BY hcc_code, hcc_label
                ORDER BY occurrence_count DESC
                LIMIT 20
                """,
                (batch_id,),
            )
            hcc_dist = cur.fetchall()

        return {
            "total_claims": row.get("total_claims") or 0,
            "unique_patients": row.get("unique_patient_names") or 0,
            "unique_matched_patients": row.get("unique_matched_patients") or 0,
            "unique_providers": row.get("unique_providers") or 0,
            "total_charges": float(row.get("total_charges") or 0),
            "matched_count": row.get("matched_count") or 0,
            "earliest_dos": str(row.get("earliest_dos") or ""),
            "latest_dos": str(row.get("latest_dos") or ""),
            "hcc_distribution": [
                {
                    "hcc_code": r.get("hcc_code"),
                    "hcc_label": r.get("hcc_label") or "",
                    "count": r.get("occurrence_count") or 0,
                }
                for r in hcc_dist
            ],
        }
    except Exception as exc:
        logger.error("compute_batch_stats failed for batch_id=%d: %s", batch_id, exc)
        return {}


def get_batch_diagnoses(batch_id: int, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    """Return ICD-10 codes from a batch with their HCC mapping."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT icd10_code, hcc_code, hcc_label,
                   COUNT(*) AS claim_count,
                   COUNT(DISTINCT openemr_pid) AS patient_count
            FROM claims_diagnoses
            WHERE batch_id=%s
            GROUP BY icd10_code, hcc_code, hcc_label
            ORDER BY claim_count DESC
            LIMIT %s OFFSET %s
            """,
            (batch_id, limit, offset),
        )
        rows = cur.fetchall()
    return [_serialize_row(r) for r in rows]


def get_hcc_summary(batch_id: int, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    """Return HCC distribution for a batch."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT hcc_code, hcc_label,
                   COUNT(*) AS diagnosis_count,
                   COUNT(DISTINCT openemr_pid) AS patient_count,
                   COUNT(DISTINCT claim_record_id) AS claim_count
            FROM claims_diagnoses
            WHERE batch_id=%s AND hcc_code IS NOT NULL AND hcc_code != ''
            GROUP BY hcc_code, hcc_label
            ORDER BY diagnosis_count DESC
            LIMIT %s OFFSET %s
            """,
            (batch_id, limit, offset),
        )
        rows = cur.fetchall()
    return [_serialize_row(r) for r in rows]


def get_unmapped_patients(batch_id: int, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    """Return patients in a batch that could not be matched to OpenEMR."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT patient_name, patient_dob, patient_gender,
                   member_id, COUNT(*) AS claim_count
            FROM claims_records
            WHERE batch_id=%s AND (openemr_pid IS NULL OR openemr_pid = 0)
            GROUP BY patient_name, patient_dob, patient_gender, member_id
            ORDER BY patient_name
            LIMIT %s OFFSET %s
            """,
            (batch_id, limit, offset),
        )
        rows = cur.fetchall()
    return [_serialize_row(r) for r in rows]


def calculate_raf_for_batch(batch_id: int, measurement_year: int = 2026) -> dict[str, Any]:
    """
    Trigger RAF calculation for all patients in a batch that have been matched
    to an OpenEMR pid.

    Returns a summary of results.
    """
    from app.services.raf_calculator import calculate_raf_score

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT openemr_pid
            FROM claims_records
            WHERE batch_id=%s AND openemr_pid IS NOT NULL AND openemr_pid > 0
            """,
            (batch_id,),
        )
        rows = cur.fetchall()

    pids = [int(r["openemr_pid"]) for r in rows]
    logger.info("RAF calculation triggered for batch_id=%d: %d unique patients", batch_id, len(pids))

    results = []
    errors = []

    for pid in pids:
        try:
            raf_result = calculate_raf_score(pid, measurement_year)
            results.append({
                "patient_id": pid,
                "raf_score": raf_result.get("raf_score"),
                "hcc_count": len(raf_result.get("final_hcc_list") or []),
                "model_segment": raf_result.get("model_segment"),
            })
        except Exception as exc:
            logger.error("RAF calc failed for pid=%d in batch=%d: %s", pid, batch_id, exc)
            errors.append({"patient_id": pid, "error": str(exc)})

    return {
        "batch_id": batch_id,
        "measurement_year": measurement_year,
        "patients_processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }


def get_overall_stats() -> dict[str, Any]:
    """Return aggregate statistics across all claims batches."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_batches,
                    SUM(claim_count) AS total_claims,
                    SUM(matched_patient_count) AS total_matched_patients,
                    MAX(created_at) AS last_upload
                FROM claims_batches
                """
            )
            batch_row = cur.fetchone() or {}

            cur.execute(
                """
                SELECT COUNT(DISTINCT icd10_code) AS unique_icd_codes,
                       COUNT(DISTINCT hcc_code) AS unique_hccs
                FROM claims_diagnoses
                WHERE hcc_code IS NOT NULL AND hcc_code != ''
                """
            )
            diag_row = cur.fetchone() or {}

            cur.execute(
                "SELECT status, COUNT(*) AS cnt FROM claims_batches GROUP BY status"
            )
            status_rows = cur.fetchall()

        return {
            "total_batches": batch_row.get("total_batches") or 0,
            "total_claims": batch_row.get("total_claims") or 0,
            "total_matched_patients": batch_row.get("total_matched_patients") or 0,
            "last_upload": str(batch_row.get("last_upload") or ""),
            "unique_icd_codes": diag_row.get("unique_icd_codes") or 0,
            "unique_hcc_codes": diag_row.get("unique_hccs") or 0,
            "batches_by_status": {r["status"]: r["cnt"] for r in status_rows},
        }
    except Exception as exc:
        logger.error("get_overall_stats error: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _parse_date_str(raw: str | None) -> str:
    """
    Normalize a date string to YYYY-MM-DD. Returns empty string on failure.

    Handles: YYYYMMDD (X12 format), MM/DD/YYYY, YYYY-MM-DD, MM-DD-YYYY
    """
    if not raw:
        return ""
    raw = raw.strip()

    formats = [
        "%Y%m%d",      # X12 EDI: 20240115
        "%Y-%m-%d",    # ISO: 2024-01-15
        "%m/%d/%Y",    # US: 01/15/2024
        "%m-%d-%Y",    # US dash: 01-15-2024
        "%Y/%m/%d",    # Alt ISO: 2024/01/15
        "%d/%m/%Y",    # EU: 15/01/2024
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _normalize_gender(raw: str | None) -> str:
    """Normalize gender to 'M', 'F', or ''."""
    if not raw:
        return ""
    g = raw.strip().upper()
    if g in ("M", "MALE", "1"):
        return "M"
    if g in ("F", "FEMALE", "2"):
        return "F"
    return ""


def _parse_json_list(val: Any) -> list[str]:
    """Parse a JSON array string or return the value if already a list."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _serialize_row(row: dict[str, Any] | None) -> dict[str, Any]:
    """Convert MySQL row dict to JSON-serializable form."""
    if not row:
        return {}
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, bytes):
            out[k] = v.decode("utf-8", errors="replace")
        else:
            out[k] = v
    return out
