"""
CMS RAPS / EDPS Submission Service.

Handles the full lifecycle of MA plan CMS risk-adjustment data submissions:

  1. RAPS file generation — fixed-width Risk Adjustment Processing System format
     per CMS RAPS file specification (Chapter 9, Medicare Managed Care Manual).
  2. EDPS file generation — Encounter Data Processing System 837P/837I format.
  3. Pre-submission validation — ICD-10, NPI, date, HCC-mapping checks.
  4. MAO-002 response parsing — CMS transaction reply acceptance/rejection.
  5. MAO-004 response parsing — CMS payment reconciliation report.
  6. Submission statistics — batch summaries, deadlines, acceptance rates.

All file I/O uses the path configured in settings.submission_output_dir
(defaults to /tmp/cms_submissions when not set).

DISCLAIMER: Generated files use CMS RAPS/EDPS specifications as documented in
publicly available CMS guidance.  Plans MUST review output files against the
current-year CMS RAPS/EDPS Technical Specifications before transmitting to CMS.
This software does not guarantee CMS acceptance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_OUTPUT_DIR = "./data/submissions"


def _output_dir() -> Path:
    """Return (and create) the CMS submission output directory."""
    try:
        from app.config import settings

        d = Path(getattr(settings, "submission_output_dir", _DEFAULT_OUTPUT_DIR))
    except Exception:
        d = Path(_DEFAULT_OUTPUT_DIR)
    if str(d).startswith("/tmp"):
        logger.warning(
            "Submission output directory is under /tmp (%s) — files may be lost on restart. "
            "Set submission_output_dir to a persistent path in production.",
            d,
        )
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# CMS submission schedule — sweep types and annual deadlines
# ---------------------------------------------------------------------------

# Payment year -> list of (sweep_label, deadline_date)
_CMS_DEADLINES: dict[int, list[dict[str, str]]] = {
    2024: [
        {
            "sweep": "Initial",
            "deadline": "2024-01-26",
            "description": "Initial submission sweep",
        },
        {
            "sweep": "Midyear",
            "deadline": "2024-07-26",
            "description": "Mid-year correction sweep",
        },
        {
            "sweep": "Final",
            "deadline": "2025-01-31",
            "description": "Final reconciliation sweep",
        },
    ],
    2025: [
        {
            "sweep": "Initial",
            "deadline": "2025-01-31",
            "description": "Initial submission sweep",
        },
        {
            "sweep": "Midyear",
            "deadline": "2025-07-25",
            "description": "Mid-year correction sweep",
        },
        {
            "sweep": "Final",
            "deadline": "2026-01-30",
            "description": "Final reconciliation sweep",
        },
    ],
    2026: [
        {
            "sweep": "Initial",
            "deadline": "2026-01-30",
            "description": "Initial submission sweep",
        },
        {
            "sweep": "Midyear",
            "deadline": "2026-07-31",
            "description": "Mid-year correction sweep",
        },
        {
            "sweep": "Final",
            "deadline": "2027-01-29",
            "description": "Final reconciliation sweep",
        },
    ],
}

# Provider type codes used in RAPS
_PROVIDER_TYPE_MAP = {
    "physician": "01",
    "facility": "60",
    "hospital": "60",
    "specialist": "01",
    "default": "01",
}


# ---------------------------------------------------------------------------
# RAPS fixed-width format helpers
# ---------------------------------------------------------------------------
# CMS RAPS Beneficiary Detail Record — field positions per CMS specification.
# Header and Trailer records bracket the detail records.


def _raps_header(plan_id: str, payment_year: int, sweep_type: str) -> str:
    """
    Build a RAPS header record (record type 'A').

    Layout (1-indexed, fixed-width 500 chars):
      Pos 1:     Record type = 'A'
      Pos 2-12:  Plan ID (H-number) left-justified, space-padded
      Pos 13-16: Payment year (YYYY)
      Pos 17-21: Sweep type, space-padded
      Pos 22-29: Submission date YYYYMMDD
      Pos 30-500: Spaces
    """
    rec = (
        "A"
        + plan_id[:11].ljust(11)
        + str(payment_year)[:4]
        + sweep_type[:5].ljust(5)
        + date.today().strftime("%Y%m%d")
    )
    return rec.ljust(500)


def _raps_trailer(plan_id: str, record_count: int) -> str:
    """
    Build a RAPS trailer record (record type 'Z').

    Pos 1:     'Z'
    Pos 2-12:  Plan ID
    Pos 13-21: Record count, zero-padded to 9 digits
    Pos 22-500: Spaces
    """
    rec = "Z" + plan_id[:11].ljust(11) + str(record_count).zfill(9)
    return rec.ljust(500)


def _raps_detail(
    hicn_mbi: str,
    icd10: str,
    dos_from: str,
    dos_through: str,
    provider_npi: str,
    provider_type: str,
    payment_year: int,
    delete_ind: str = "N",
) -> str:
    """
    Build one RAPS beneficiary detail record (record type 'B').

    Layout (simplified fixed-width, 500 chars):
      Pos 1:      'B'
      Pos 2-13:   HICN/MBI (12 chars, right-padded)
      Pos 14-23:  Provider NPI (10 chars)
      Pos 24-25:  Provider type code (2 chars)
      Pos 26:     Delete indicator (1 char: N or D)
      Pos 27-33:  ICD-10 code (7 chars, right-padded, no dot)
      Pos 34-41:  DOS from YYYYMMDD
      Pos 42-49:  DOS through YYYYMMDD
      Pos 50-53:  Payment year YYYY
      Pos 54-500: Spaces
    """
    # Normalize ICD-10: remove dot, left-justify in 7-char field
    icd_clean = icd10.replace(".", "").upper()[:7].ljust(7)
    # Normalize dates — ensure YYYYMMDD
    dos_f = _normalize_date_8(dos_from)
    dos_t = _normalize_date_8(dos_through)
    npi = (provider_npi or "").strip()[:10].ljust(10)
    ptype = (provider_type or "01")[:2]
    mbi = (hicn_mbi or "").strip()[:12].ljust(12)

    rec = (
        "B"
        + mbi
        + npi
        + ptype
        + (delete_ind or "N")[:1]
        + icd_clean
        + dos_f
        + dos_t
        + str(payment_year)[:4]
    )
    return rec.ljust(500)


def _normalize_date_8(d: Any) -> str:
    """Convert a date/datetime/string to YYYYMMDD.  Returns spaces on failure."""
    if not d:
        return " " * 8
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y%m%d")
    s = str(d).strip()
    # Already YYYYMMDD
    if re.fullmatch(r"\d{8}", s):
        return s
    # YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(1) + m.group(2) + m.group(3)
    return " " * 8


# ---------------------------------------------------------------------------
# EDPS 837P helpers (simplified ISA/GS/ST envelope)
# ---------------------------------------------------------------------------

_EDI_SPECIAL_CHARS_RE = re.compile(r"[*~:]")


def _sanitize_edi_id(value: str) -> str:
    """Strip EDI delimiter characters from ISA sender/receiver IDs."""
    return _EDI_SPECIAL_CHARS_RE.sub("", value)


def _edps_isa_envelope(sender_id: str, receiver_id: str, control_num: str) -> str:
    """Build an EDI 837P ISA envelope header."""
    sender_id = _sanitize_edi_id(sender_id)
    receiver_id = _sanitize_edi_id(receiver_id)
    today = date.today()
    d6 = today.strftime("%y%m%d")
    t4 = datetime.now().strftime("%H%M")
    return (
        f"ISA*00*          *00*          *ZZ*{sender_id:<15}*ZZ*{receiver_id:<15}"
        f"*{d6}*{t4}*^*00501*{control_num.zfill(9)}*0*P*:"
        f"~\n"
    )


def _edps_gs_header(sender_id: str, receiver_id: str, control_num: str) -> str:
    today = date.today().strftime("%Y%m%d")
    t = datetime.now().strftime("%H%M%S")
    return (
        f"GS*HC*{sender_id}*{receiver_id}*{today}*{t}*{control_num}*X*005010X222A1~\n"
    )


def _edps_gs_trailer(tx_count: int, control_num: str) -> str:
    return f"GE*{tx_count}*{control_num}~\n"


def _edps_isa_trailer(control_num: str) -> str:
    return f"IEA*1*{control_num.zfill(9)}~\n"


def _edps_claim_segment(
    claim_id: str,
    patient_id: int,
    hicn_mbi: str,
    icd10: str,
    dos_from: str,
    dos_through: str,
    rendering_npi: str,
    facility_npi: str,
    place_of_service: str = "11",
) -> str:
    """
    Build minimal 837P claim loop for a single diagnosis encounter.

    This generates the essential NM1/CLM/DTP/HI/NPI segments.
    Plans must merge these into complete 837 transactions using their
    clearinghouse or CMS Direct submission pipeline.
    """
    dos_f = _normalize_date_8(dos_from)
    icd_clean = icd10.replace(".", "").upper()
    lines = [
        f"CLM*{claim_id}*0***{place_of_service}:B:1*Y*A*Y*I~",
        f"DTP*472*RD8*{dos_f}-{_normalize_date_8(dos_through)}~",
        f"HI*ABK:{icd_clean}~",
        f"NM1*82*1****{rendering_npi}~" if rendering_npi else "",
        f"NM1*77*2****{facility_npi}~" if facility_npi else "",
    ]
    return "\n".join(l for l in lines if l) + "\n"


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------

_IDEMPOTENCY_TERMINAL_STATUSES = frozenset({"generated", "submitted", "transmitted"})


def _compute_idempotency_key(
    tenant_id: str,
    payment_year: int,
    sweep_type: str,
    file_type: str,
    patient_ids: list[int],
) -> str:
    """
    Return a deterministic 32-character hex key for the given submission parameters.

    The key encodes (tenant, year, sweep, format, sorted patient set) so that
    re-triggering generation for the exact same data set produces the same key.
    """
    sorted_ids_hash = hashlib.sha256(
        ",".join(str(pid) for pid in sorted(patient_ids)).encode()
    ).hexdigest()
    key_input = f"{tenant_id}:{payment_year}:{sweep_type}:{file_type}:{sorted_ids_hash}"
    return hashlib.sha256(key_input.encode()).hexdigest()[:32]


def _find_existing_batch(idempotency_key: str) -> dict[str, Any] | None:
    """
    Return an existing submission_batches row whose idempotency_key matches
    and whose status is one of the terminal statuses, or None if not found.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM submission_batches
                WHERE idempotency_key = %s
                  AND status IN ('generated', 'submitted', 'transmitted', 'pending', 'validated')
                LIMIT 1
                """,
                (idempotency_key,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning("_find_existing_batch query error (non-fatal): %s", exc)
        return None
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# FHIR-awareness helpers
# ---------------------------------------------------------------------------


def _get_active_connection_type() -> str | None:
    """
    Return the connection_type of the active EMR connection ('fhir_r4',
    'rest_api', 'direct_db', etc.) or None when no active connection exists.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT connection_type FROM emr_connections WHERE is_active = 1 LIMIT 1"
            )
            row = cur.fetchone()
            return row["connection_type"] if row else None
    except Exception as exc:
        logger.debug("_get_active_connection_type query failed (non-fatal): %s", exc)
        return None


def _lookup_emr_pid_for_raf_patient(raf_patient_id: int) -> int | None:
    """
    For FHIR/REST connections, resolve the external OpenEMR patient PID that
    corresponds to an internal RAF patient ID by consulting emr_patient_matches.

    Returns the external EMR pid on success, or None when no match is found.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT epm.emr_pid
                FROM emr_patient_matches epm
                JOIN emr_connections ec ON ec.id = epm.connection_id
                WHERE ec.is_active = 1
                  AND (epm.raf_patient_id = %s OR epm.id = %s)
                LIMIT 1
                """,
                (raf_patient_id, raf_patient_id),
            )
            row = cur.fetchone()
            return int(row["emr_pid"]) if row and row.get("emr_pid") else None
    except Exception as exc:
        logger.debug(
            "_lookup_emr_pid_for_raf_patient failed for patient %s (non-fatal): %s",
            raf_patient_id,
            exc,
        )
        return None


def _resolve_mbi(raf_patient_id: int, demographics_hicn_mbi: str | None, conn_type: str | None) -> str:
    """
    Return the best available HICN/MBI for a patient.

    Priority:
    1. Value already present in raf_patient_demographics.hicn_mbi.
    2. For FHIR/REST connections: resolve the external OpenEMR pid via
       emr_patient_matches, then call OpenEMR insurance_data lookup.
    3. For direct_db connections: call OpenEMR insurance_data lookup directly
       with the raf_patient_id (which equals the OpenEMR pid in that topology).
    4. Empty string when all lookups fail.
    """
    if demographics_hicn_mbi:
        return demographics_hicn_mbi

    if conn_type in ("fhir_r4", "rest_api"):
        emr_pid = _lookup_emr_pid_for_raf_patient(raf_patient_id)
        if emr_pid is not None:
            return _lookup_mbi_from_openemr(emr_pid)
        # No matched EMR record — MBI must be populated in raf_patient_demographics
        logger.debug(
            "_resolve_mbi: no emr_patient_matches row for raf_patient_id=%s; "
            "MBI will be empty unless raf_patient_demographics.hicn_mbi is set",
            raf_patient_id,
        )
        return ""

    # direct_db: raf_patient_id == OpenEMR pid
    return _lookup_mbi_from_openemr(raf_patient_id)


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------


def generate_raps_file(
    tenant_id: str,
    payment_year: int,
    sweep_type: str,
    plan_id: str = "H9999",
) -> dict[str, Any]:
    """
    Generate a CMS RAPS fixed-width submission file for the given tenant/year/sweep.

    Steps:
    1. Query raf_patient_hcc for all confirmed HCC records for the tenant.
    2. Join to raf_patient_demographics / OpenEMR for HICN/MBI.
    3. Write one RAPS detail record per unique (patient, ICD-10, encounter).
    4. Wrap with RAPS header and trailer records.
    5. Save file; create submission_batches row; insert submission_records rows.

    Returns a dict with batch_id, file_path, record_count, and summary.
    """

    batch_id = str(uuid.uuid4())

    # -- Detect active EMR connection type (FHIR vs direct_db) ---------------
    conn_type = _get_active_connection_type()

    # -- Pull HCC / encounter data from RAF DB --------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    h.patient_id,
                    h.hcc_code,
                    h.icd10_codes,
                    h.measurement_year,
                    h.confirmed_date,
                    h.encounter_id,
                    h.provider_npi,
                    h.provider_type,
                    d.hicn_mbi,
                    d.dos_from,
                    d.dos_through
                FROM raf_patient_hcc h
                LEFT JOIN raf_patient_demographics d
                    ON h.patient_id = d.patient_id
                WHERE h.tenant_id = %s
                  AND h.measurement_year = %s
                  AND (h.status = 'confirmed' OR h.status IS NULL)
                ORDER BY h.patient_id, h.hcc_code
                """,
                (tenant_id, payment_year),
            )
            hcc_rows = cur.fetchall()
    except Exception as exc:
        logger.error("generate_raps_file HCC query error: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to query HCC data: {exc}") from exc

    # -- Idempotency check ----------------------------------------------------
    patient_ids = list({row["patient_id"] for row in hcc_rows})
    idempotency_key = _compute_idempotency_key(
        tenant_id, payment_year, sweep_type, "RAPS", patient_ids
    )
    existing = _find_existing_batch(idempotency_key)
    if existing:
        logger.info(
            "generate_raps_file: duplicate detected idempotency_key=%s batch=%s",
            idempotency_key,
            existing.get("id"),
        )
        return {**dict(existing), "duplicate": True}

    if not hcc_rows:
        logger.warning(
            "generate_raps_file: no confirmed HCC records for tenant=%s year=%s",
            tenant_id,
            payment_year,
        )

    # -- Build RAPS detail records ---------------------------------------------
    raps_lines: list[str] = [_raps_header(plan_id, payment_year, sweep_type)]
    record_rows: list[dict[str, Any]] = []
    detail_count = 0

    for row in hcc_rows:
        # Resolve HICN/MBI: prefer demographics table; fall back via FHIR-aware lookup
        hicn_mbi = _resolve_mbi(row["patient_id"], row.get("hicn_mbi"), conn_type)
        provider_npi = (row.get("provider_npi") or "").strip() or "0000000000"
        provider_type = _PROVIDER_TYPE_MAP.get(
            (row.get("provider_type") or "").lower(), _PROVIDER_TYPE_MAP["default"]
        )

        # Expand icd10_codes — stored as JSON array or comma-separated string
        icd_list = _parse_icd_list(row.get("icd10_codes"))

        # Use encounter dates if available, else fall back to confirmed_date / year
        dos_from = (
            row.get("dos_from") or row.get("confirmed_date") or f"{payment_year}-01-01"
        )
        dos_through = (
            row.get("dos_through")
            or row.get("confirmed_date")
            or f"{payment_year}-12-31"
        )

        for icd10 in icd_list:
            if not icd10:
                continue
            raps_lines.append(
                _raps_detail(
                    hicn_mbi=hicn_mbi,
                    icd10=icd10,
                    dos_from=str(dos_from),
                    dos_through=str(dos_through),
                    provider_npi=provider_npi,
                    provider_type=provider_type,
                    payment_year=payment_year,
                )
            )
            record_rows.append(
                {
                    "patient_id": row["patient_id"],
                    "hicn_mbi": hicn_mbi,
                    "hcc_code": str(row.get("hcc_code") or ""),
                    "icd10_code": icd10,
                    "dos_from": dos_from,
                    "dos_through": dos_through,
                    "provider_npi": provider_npi,
                    "provider_type": provider_type,
                }
            )
            detail_count += 1

    raps_lines.append(_raps_trailer(plan_id, detail_count))

    # -- Write file -----------------------------------------------------------
    out_dir = _output_dir() / tenant_id / str(payment_year)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"RAPS_{tenant_id}_{payment_year}_{sweep_type}_{batch_id[:8]}.txt"
    file_path = out_dir / file_name
    content = "\n".join(raps_lines) + "\n"
    file_path.write_text(content, encoding="utf-8")
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    # -- Persist batch and records to DB --------------------------------------
    _insert_batch(
        batch_id=batch_id,
        tenant_id=tenant_id,
        file_type="RAPS",
        payment_year=payment_year,
        sweep_type=sweep_type,
        record_count=detail_count,
        file_path=str(file_path),
        file_hash=file_hash,
        idempotency_key=idempotency_key,
    )
    _insert_records(batch_id, tenant_id, record_rows)

    logger.info(
        "RAPS file generated: batch=%s records=%d path=%s",
        batch_id,
        detail_count,
        file_path,
    )
    return {
        "batch_id": batch_id,
        "file_type": "RAPS",
        "payment_year": payment_year,
        "sweep_type": sweep_type,
        "record_count": detail_count,
        "file_path": str(file_path),
        "file_hash": file_hash,
        "status": "pending",
    }


def generate_edps_file(
    tenant_id: str,
    payment_year: int,
    sweep_type: str,
    sender_id: str = "MASENDER",
    receiver_id: str = "CMSEDPS00",
    plan_id: str = "H9999",
) -> dict[str, Any]:
    """
    Generate an EDPS 837P-formatted encounter data file for the given tenant/year/sweep.

    Produces an EDI 837P file containing one claim loop per (patient, ICD-10, encounter).
    Returns batch metadata and file path.
    """

    batch_id = str(uuid.uuid4())
    control_num = str(int(datetime.now().timestamp()))[-9:]

    # -- Detect active EMR connection type (FHIR vs direct_db) ---------------
    conn_type = _get_active_connection_type()

    # -- Query encounter data -------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    h.patient_id,
                    h.hcc_code,
                    h.icd10_codes,
                    h.measurement_year,
                    h.confirmed_date,
                    h.encounter_id,
                    h.provider_npi,
                    h.facility_npi,
                    h.place_of_service,
                    d.hicn_mbi,
                    d.dos_from,
                    d.dos_through
                FROM raf_patient_hcc h
                LEFT JOIN raf_patient_demographics d
                    ON h.patient_id = d.patient_id
                WHERE h.tenant_id = %s
                  AND h.measurement_year = %s
                  AND (h.status = 'confirmed' OR h.status IS NULL)
                ORDER BY h.patient_id, h.hcc_code
                """,
                (tenant_id, payment_year),
            )
            hcc_rows = cur.fetchall()
    except Exception as exc:
        logger.error("generate_edps_file query error: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to query encounter data: {exc}") from exc

    # -- Idempotency check ----------------------------------------------------
    patient_ids = list({row["patient_id"] for row in hcc_rows})
    idempotency_key = _compute_idempotency_key(
        tenant_id, payment_year, sweep_type, "EDPS", patient_ids
    )
    existing = _find_existing_batch(idempotency_key)
    if existing:
        logger.info(
            "generate_edps_file: duplicate detected idempotency_key=%s batch=%s",
            idempotency_key,
            existing.get("id"),
        )
        return {**dict(existing), "duplicate": True}

    # -- Build 837P content ---------------------------------------------------
    lines: list[str] = [
        _edps_isa_envelope(sender_id, receiver_id, control_num),
        _edps_gs_header(sender_id, receiver_id, control_num),
    ]

    record_rows: list[dict[str, Any]] = []
    tx_count = 0
    seq = 1

    for row in hcc_rows:
        # Resolve HICN/MBI: prefer demographics table; fall back via FHIR-aware lookup
        hicn_mbi = _resolve_mbi(row["patient_id"], row.get("hicn_mbi"), conn_type)
        rendering_npi = (row.get("provider_npi") or "").strip() or "0000000000"
        facility_npi = (row.get("facility_npi") or "").strip() or "0000000000"
        pos = row.get("place_of_service") or "11"
        dos_from = (
            row.get("dos_from") or row.get("confirmed_date") or f"{payment_year}-01-01"
        )
        dos_through = (
            row.get("dos_through")
            or row.get("confirmed_date")
            or f"{payment_year}-12-31"
        )
        icd_list = _parse_icd_list(row.get("icd10_codes"))

        for icd10 in icd_list:
            if not icd10:
                continue
            claim_id = f"CLM{row['patient_id']:08d}{seq:04d}"
            lines.append(
                _edps_claim_segment(
                    claim_id=claim_id,
                    patient_id=row["patient_id"],
                    hicn_mbi=hicn_mbi,
                    icd10=icd10,
                    dos_from=str(dos_from),
                    dos_through=str(dos_through),
                    rendering_npi=rendering_npi,
                    facility_npi=facility_npi,
                    place_of_service=str(pos),
                )
            )
            record_rows.append(
                {
                    "patient_id": row["patient_id"],
                    "hicn_mbi": hicn_mbi,
                    "hcc_code": str(row.get("hcc_code") or ""),
                    "icd10_code": icd10,
                    "dos_from": dos_from,
                    "dos_through": dos_through,
                    "provider_npi": rendering_npi,
                    "provider_type": "01",
                }
            )
            tx_count += 1
            seq += 1

    lines.append(_edps_gs_trailer(tx_count, control_num))
    lines.append(_edps_isa_trailer(control_num))

    # -- Write file -----------------------------------------------------------
    out_dir = _output_dir() / tenant_id / str(payment_year)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"EDPS_{tenant_id}_{payment_year}_{sweep_type}_{batch_id[:8]}.edi"
    file_path = out_dir / file_name
    content = "".join(lines)
    file_path.write_text(content, encoding="utf-8")
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    _insert_batch(
        batch_id=batch_id,
        tenant_id=tenant_id,
        file_type="EDPS",
        payment_year=payment_year,
        sweep_type=sweep_type,
        record_count=tx_count,
        file_path=str(file_path),
        file_hash=file_hash,
        idempotency_key=idempotency_key,
    )
    _insert_records(batch_id, tenant_id, record_rows)

    logger.info(
        "EDPS file generated: batch=%s transactions=%d path=%s",
        batch_id,
        tx_count,
        file_path,
    )
    return {
        "batch_id": batch_id,
        "file_type": "EDPS",
        "payment_year": payment_year,
        "sweep_type": sweep_type,
        "record_count": tx_count,
        "file_path": str(file_path),
        "file_hash": file_hash,
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# Pre-submission validation
# ---------------------------------------------------------------------------

_ICD10_PATTERN = re.compile(r"^[A-Z]\d{2}(\.\w{1,4})?$", re.IGNORECASE)
_NPI_PATTERN = re.compile(r"^\d{10}$")


def validate_submission(batch_id: str) -> dict[str, Any]:
    """
    Run all active validation rules against the records in the given batch.

    Checks performed per record:
    - valid_icd10:       ICD-10 format A##.#### (via regex + optional icd_validator)
    - valid_dates:       dos_from <= dos_through, not in the future, within payment year
    - valid_npi:         10-digit numeric NPI
    - hicn_mbi_present:  HICN/MBI is not blank
    - no_duplicates:     same (patient_id, icd10_code, dos_from) within batch
    - hcc_mapped:        ICD-10 maps to at least one HCC in raf_patient_hcc

    Updates submission_records.validation_status and validation_errors.
    Updates submission_batches counts (valid_count, invalid_count, warning_count).

    Returns a summary dict with per-rule error counts and record-level results.
    """


    # -- Load records ---------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, patient_id, hicn_mbi, hcc_code, icd10_code,
                       dos_from, dos_through, provider_npi
                FROM submission_records
                WHERE batch_id = %s
                """,
                (batch_id,),
            )
            records = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"Failed to load submission records: {exc}") from exc

    if not records:
        return {
            "batch_id": batch_id,
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "warnings": 0,
            "rules": {},
            "records": [],
        }

    # Load batch metadata for payment year
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT payment_year FROM submission_batches WHERE id = %s",
                (batch_id,),
            )
            batch_meta = cur.fetchone()
    except Exception:
        batch_meta = None
    payment_year = int((batch_meta or {}).get("payment_year", date.today().year))

    # Dedup tracker: (patient_id, icd10_code, dos_from)
    seen_records: dict[tuple, int] = {}
    rule_counts: dict[str, int] = {
        "valid_icd10": 0,
        "valid_dates": 0,
        "valid_npi": 0,
        "hicn_mbi_present": 0,
        "no_duplicates": 0,
    }

    results: list[dict[str, Any]] = []
    valid_count = invalid_count = warning_count = 0

    for rec in records:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        # 1. ICD-10 format
        icd = (rec.get("icd10_code") or "").strip()
        if not icd or not _ICD10_PATTERN.match(icd):
            errors.append(
                {"rule": "valid_icd10", "message": f"Invalid ICD-10 format: '{icd}'"}
            )
            rule_counts["valid_icd10"] += 1
        else:
            # Attempt validation via icd_validator if available
            try:
                from app.services.icd_validator import normalize_code, validate_code

                if not validate_code(normalize_code(icd)):
                    warnings.append(
                        {
                            "rule": "valid_icd10",
                            "message": f"ICD-10 code not found in reference: {icd}",
                        }
                    )
                    rule_counts["valid_icd10"] += 1
            except ImportError:
                pass

        # 2. Date validation
        dos_from = rec.get("dos_from")
        dos_through = rec.get("dos_through")
        if dos_from and dos_through:
            try:
                df = (
                    dos_from
                    if isinstance(dos_from, date)
                    else date.fromisoformat(str(dos_from))
                )
                dt = (
                    dos_through
                    if isinstance(dos_through, date)
                    else date.fromisoformat(str(dos_through))
                )
                today = date.today()
                if df > dt:
                    errors.append(
                        {
                            "rule": "valid_dates",
                            "message": "dos_from is after dos_through",
                        }
                    )
                    rule_counts["valid_dates"] += 1
                if df > today or dt > today:
                    warnings.append(
                        {
                            "rule": "valid_dates",
                            "message": "Service date is in the future",
                        }
                    )
                if df.year != payment_year and dt.year != payment_year:
                    warnings.append(
                        {
                            "rule": "valid_dates",
                            "message": f"Service date year does not match payment year {payment_year}",
                        }
                    )
            except (ValueError, TypeError) as exc:
                errors.append(
                    {"rule": "valid_dates", "message": f"Unparseable date: {exc}"}
                )
                rule_counts["valid_dates"] += 1
        else:
            warnings.append({"rule": "valid_dates", "message": "Missing service dates"})

        # 3. NPI format
        npi = (rec.get("provider_npi") or "").strip()
        if npi and not _NPI_PATTERN.match(npi):
            errors.append(
                {"rule": "valid_npi", "message": f"NPI must be 10 digits: '{npi}'"}
            )
            rule_counts["valid_npi"] += 1

        # 4. HICN/MBI present
        mbi = (rec.get("hicn_mbi") or "").strip()
        if not mbi:
            errors.append(
                {"rule": "hicn_mbi_present", "message": "HICN/MBI is missing"}
            )
            rule_counts["hicn_mbi_present"] += 1

        # 5. Duplicate check within batch
        dedup_key = (rec["patient_id"], icd, str(dos_from))
        if dedup_key in seen_records:
            warnings.append(
                {
                    "rule": "no_duplicates",
                    "message": f"Duplicate record: same patient/ICD/DOS as record id={seen_records[dedup_key]}",
                }
            )
            rule_counts["no_duplicates"] += 1
        else:
            seen_records[dedup_key] = rec["id"]

        # Determine record status
        if errors:
            vstatus = "invalid"
            invalid_count += 1
        elif warnings:
            vstatus = "warning"
            warning_count += 1
        else:
            vstatus = "valid"
            valid_count += 1

        all_issues = errors + warnings
        # Persist validation result
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    UPDATE submission_records
                    SET validation_status = %s,
                        validation_errors = %s
                    WHERE id = %s
                    """,
                    (
                        vstatus,
                        json.dumps(all_issues) if all_issues else None,
                        rec["id"],
                    ),
                )
        except Exception as exc:
            logger.warning(
                "Failed to update validation for record %s: %s", rec["id"], exc
            )

        results.append(
            {
                "record_id": rec["id"],
                "patient_id": rec["patient_id"],
                "icd10_code": icd,
                "validation_status": vstatus,
                "errors": errors,
                "warnings": warnings,
            }
        )

    # -- Update batch counts --------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE submission_batches
                SET valid_count   = %s,
                    invalid_count = %s,
                    warning_count = %s,
                    status        = %s
                WHERE id = %s
                """,
                (
                    valid_count,
                    invalid_count,
                    warning_count,
                    "validated",
                    batch_id,
                ),
            )
    except Exception as exc:
        logger.warning("Failed to update batch validation counts: %s", exc)

    summary = {
        "batch_id": batch_id,
        "total": len(records),
        "valid": valid_count,
        "invalid": invalid_count,
        "warnings": warning_count,
        "pass_rate": round(valid_count / len(records) * 100, 1) if records else 0.0,
        "rules": rule_counts,
        "records": results,
    }

    logger.info(
        "Validation complete batch=%s total=%d valid=%d invalid=%d warnings=%d",
        batch_id,
        len(records),
        valid_count,
        invalid_count,
        warning_count,
    )
    return summary


# ---------------------------------------------------------------------------
# MAO-002 response parsing
# ---------------------------------------------------------------------------


def parse_mao002_response(
    batch_id: str, file_content: str, file_name: str = ""
) -> dict[str, Any]:
    """
    Parse a CMS MAO-002 (RAPS Transaction Reply) file and update record statuses.

    MAO-002 format (fixed-width):
      Each detail line contains:
        - HICN/MBI (pos 1-12)
        - ICD-10 (pos 13-19, no dot)
        - DOS from (pos 20-27 YYYYMMDD)
        - Status code (pos 28: A=Accepted, R=Rejected, D=Duplicate)
        - Error code (pos 29-34)
        - Error description (pos 35-94)

    Lines starting with 'A' are header; 'Z' are trailer; 'B' are detail.
    """

    accepted = rejected = duplicate = 0
    update_log: list[dict[str, Any]] = []

    lines = file_content.splitlines()
    for line in lines:
        if not line or line[0] not in ("B", "b"):
            continue
        if len(line) < 28:
            continue

        mbi = line[1:13].strip()
        icd_raw = line[13:20].strip()
        dos_from_s = line[20:28].strip()
        status_c = line[28:29].strip().upper() if len(line) > 28 else ""
        error_code = line[29:35].strip() if len(line) > 35 else ""
        error_desc = line[35:95].strip() if len(line) > 95 else ""

        # Re-insert dot into ICD-10
        icd10 = _add_icd_dot(icd_raw)

        if status_c == "A":
            cms_status = "accepted"
            accepted += 1
        elif status_c == "R":
            cms_status = "rejected"
            rejected += 1
        elif status_c == "D":
            cms_status = "duplicate"
            duplicate += 1
        else:
            cms_status = "unknown"

        # Find matching record in batch
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM submission_records
                    WHERE batch_id = %s
                      AND icd10_code = %s
                      AND hicn_mbi   = %s
                    LIMIT 1
                    """,
                    (batch_id, icd10, mbi),
                )
                match = cur.fetchone()
                if match:
                    cur.execute(
                        """
                        UPDATE submission_records
                        SET cms_status     = %s,
                            cms_error_code = %s,
                            cms_error_desc = %s
                        WHERE id = %s
                        """,
                        (
                            cms_status,
                            error_code or None,
                            error_desc or None,
                            match["id"],
                        ),
                    )
                    update_log.append(
                        {
                            "record_id": match["id"],
                            "icd10": icd10,
                            "mbi": mbi,
                            "cms_status": cms_status,
                            "error_code": error_code,
                        }
                    )
        except Exception as exc:
            logger.warning("MAO-002 record update error: %s", exc)

    # Store response metadata
    _insert_response(
        batch_id=batch_id,
        response_type="MAO-002",
        file_name=file_name,
        raw_content=file_content[
            :65535
        ],  # cap to avoid giant LONGTEXT writes in one call
        accepted_count=accepted,
        rejected_count=rejected,
        duplicate_count=duplicate,
    )

    # Update batch status
    _update_batch_status_from_response(batch_id, accepted, rejected)

    logger.info(
        "MAO-002 parsed batch=%s accepted=%d rejected=%d duplicate=%d",
        batch_id,
        accepted,
        rejected,
        duplicate,
    )
    return {
        "batch_id": batch_id,
        "response_type": "MAO-002",
        "accepted": accepted,
        "rejected": rejected,
        "duplicate": duplicate,
        "records_updated": len(update_log),
        "details": update_log,
    }


# ---------------------------------------------------------------------------
# MAO-004 response parsing
# ---------------------------------------------------------------------------


def parse_mao004_response(
    batch_id: str, file_content: str, file_name: str = ""
) -> dict[str, Any]:
    """
    Parse a CMS MAO-004 (Payment Reconciliation) report and store results.

    MAO-004 fixed-width line layout (simplified):
      Pos 1:      Record type ('D' = detail)
      Pos 2-13:   HICN/MBI
      Pos 14-20:  ICD-10 (no dot)
      Pos 21-28:  DOS from YYYYMMDD
      Pos 29-40:  Payment amount (right-justified, 2 decimal implied)
      Pos 41-48:  Risk score adjustment (8 chars, 4 decimal implied)
      Pos 49-68:  Notes / adjustment reason

    Returns reconciliation summary; updates submission_records.payment_amount
    and risk_score_adj where matches are found.
    """

    total_payment = 0.0
    records_updated = 0
    reconciliation: list[dict[str, Any]] = []

    for line in file_content.splitlines():
        if not line or line[0].upper() != "D":
            continue
        if len(line) < 48:
            continue

        mbi = line[1:13].strip()
        icd_raw = line[13:20].strip()
        icd10 = _add_icd_dot(icd_raw)
        dos_from = line[20:28].strip()
        pay_raw = line[28:40].strip()
        rscore = line[40:48].strip()
        notes = line[48:68].strip() if len(line) >= 68 else ""

        try:
            payment_amt = (
                float(pay_raw) / 100.0 if pay_raw.lstrip("-").isdigit() else 0.0
            )
        except (ValueError, ZeroDivisionError):
            payment_amt = 0.0

        try:
            risk_adj = float(rscore) / 10000.0 if rscore.lstrip("-").isdigit() else 0.0
        except ValueError:
            risk_adj = 0.0

        total_payment += payment_amt

        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM submission_records
                    WHERE batch_id   = %s
                      AND icd10_code = %s
                      AND hicn_mbi   = %s
                    LIMIT 1
                    """,
                    (batch_id, icd10, mbi),
                )
                match = cur.fetchone()
                if match:
                    cur.execute(
                        """
                        UPDATE submission_records
                        SET payment_amount  = %s,
                            risk_score_adj  = %s
                        WHERE id = %s
                        """,
                        (payment_amt, risk_adj, match["id"]),
                    )
                    records_updated += 1
        except Exception as exc:
            logger.warning("MAO-004 record update error: %s", exc)

        reconciliation.append(
            {
                "mbi": mbi,
                "icd10": icd10,
                "dos_from": dos_from,
                "payment": payment_amt,
                "risk_adj": risk_adj,
                "notes": notes,
            }
        )

    _insert_response(
        batch_id=batch_id,
        response_type="MAO-004",
        file_name=file_name,
        raw_content=file_content[:65535],
        total_payment=total_payment,
    )

    logger.info(
        "MAO-004 parsed batch=%s total_payment=%.2f records_updated=%d",
        batch_id,
        total_payment,
        records_updated,
    )
    return {
        "batch_id": batch_id,
        "response_type": "MAO-004",
        "total_payment": round(total_payment, 2),
        "records_updated": records_updated,
        "reconciliation": reconciliation,
    }


# ---------------------------------------------------------------------------
# Submission statistics
# ---------------------------------------------------------------------------


def get_submission_stats(tenant_id: str) -> dict[str, Any]:
    """
    Return aggregate submission statistics for the given tenant.

    Includes:
    - Total batches, total records submitted, overall acceptance rate
    - Per-payment-year breakdown
    - Upcoming CMS deadlines within the next 90 days
    """


    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                                     AS total_batches,
                    SUM(record_count)                            AS total_records,
                    SUM(valid_count)                             AS total_valid,
                    SUM(invalid_count)                           AS total_invalid
                FROM submission_batches
                WHERE tenant_id = %s
                """,
                (tenant_id,),
            )
            totals = cur.fetchone() or {}

            cur.execute(
                """
                SELECT payment_year, file_type,
                       COUNT(*) AS batches,
                       SUM(record_count) AS records,
                       SUM(valid_count) AS valid,
                       SUM(CASE WHEN status = 'accepted'  THEN 1 ELSE 0 END) AS accepted_batches,
                       SUM(CASE WHEN status = 'rejected'  THEN 1 ELSE 0 END) AS rejected_batches,
                       SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END) AS submitted_batches
                FROM submission_batches
                WHERE tenant_id = %s
                GROUP BY payment_year, file_type
                ORDER BY payment_year DESC, file_type
                """,
                (tenant_id,),
            )
            by_year = cur.fetchall()
    except Exception as exc:
        logger.error("get_submission_stats error: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to retrieve submission stats: {exc}") from exc

    total_records = int(totals.get("total_records") or 0)
    total_valid = int(totals.get("total_valid") or 0)
    acceptance_rate = (
        round(total_valid / total_records * 100, 1) if total_records else 0.0
    )

    # Upcoming deadlines within 90 days
    today = date.today()
    upcoming: list[dict[str, Any]] = []
    for yr, deadlines in sorted(_CMS_DEADLINES.items()):
        for dl in deadlines:
            dl_date = date.fromisoformat(dl["deadline"])
            days_until = (dl_date - today).days
            if 0 <= days_until <= 90:
                upcoming.append(
                    {
                        "payment_year": yr,
                        "sweep": dl["sweep"],
                        "deadline": dl["deadline"],
                        "days_until": days_until,
                        "description": dl["description"],
                    }
                )

    return {
        "tenant_id": tenant_id,
        "total_batches": int(totals.get("total_batches") or 0),
        "total_records": total_records,
        "total_valid": total_valid,
        "total_invalid": int(totals.get("total_invalid") or 0),
        "acceptance_rate": acceptance_rate,
        "by_year": [dict(r) for r in by_year],
        "upcoming_deadlines": upcoming,
    }


# ---------------------------------------------------------------------------
# Batch CRUD helpers
# ---------------------------------------------------------------------------


def get_batch(batch_id: str) -> dict[str, Any] | None:
    """Return a single submission batch record by id."""

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT * FROM submission_batches WHERE id = %s",
                (batch_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc
    return dict(row) if row else None


def list_batches(
    tenant_id: str,
    payment_year: int | None = None,
    file_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated list of submission batches for a tenant."""

    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if payment_year:
        conditions.append("payment_year = %s")
        params.append(payment_year)
    if file_type:
        conditions.append("file_type = %s")
        params.append(file_type.upper())
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = " AND ".join(conditions)
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM submission_batches WHERE {where}", params
            )
            total = (cur.fetchone() or {}).get("cnt", 0)
            cur.execute(
                f"""
                SELECT * FROM submission_batches
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }


def list_records(
    batch_id: str,
    validation_status: str | None = None,
    cms_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated list of submission records for a batch."""

    conditions = ["batch_id = %s"]
    params: list[Any] = [batch_id]
    if validation_status:
        conditions.append("validation_status = %s")
        params.append(validation_status)
    if cms_status:
        conditions.append("cms_status = %s")
        params.append(cms_status)

    where = " AND ".join(conditions)
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM submission_records WHERE {where}", params
            )
            total = (cur.fetchone() or {}).get("cnt", 0)
            cur.execute(
                f"""
                SELECT * FROM submission_records
                WHERE {where}
                ORDER BY id
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [_serialize_record(r) for r in rows],
    }


def mark_submitted(batch_id: str) -> dict[str, Any]:
    """Mark a batch as submitted and record the submission timestamp."""

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE submission_batches
                SET status       = 'submitted',
                    submitted_at = %s
                WHERE id = %s
                """,
                (datetime.now(timezone.utc), batch_id),
            )
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc
    result = get_batch(batch_id)
    if not result:
        raise ValueError(f"Batch {batch_id} not found")
    return result


def list_responses(batch_id: str) -> list[dict[str, Any]]:
    """Return all response files associated with a batch."""

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, batch_id, response_type, file_name,
                       parsed_at, accepted_count, rejected_count,
                       duplicate_count, total_payment, notes
                FROM submission_responses
                WHERE batch_id = %s
                ORDER BY parsed_at DESC
                """,
                (batch_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc
    return [dict(r) for r in rows]


def get_reconciliation(batch_id: str) -> dict[str, Any]:
    """Return payment reconciliation data for a batch."""

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT SUM(payment_amount) AS total_payment,
                       SUM(risk_score_adj) AS total_risk_adj,
                       COUNT(*)            AS record_count,
                       COUNT(CASE WHEN cms_status = 'accepted'  THEN 1 END) AS accepted,
                       COUNT(CASE WHEN cms_status = 'rejected'  THEN 1 END) AS rejected,
                       COUNT(CASE WHEN cms_status = 'duplicate' THEN 1 END) AS duplicate
                FROM submission_records
                WHERE batch_id = %s
                """,
                (batch_id,),
            )
            summary = cur.fetchone() or {}
            cur.execute(
                """
                SELECT patient_id, hicn_mbi, icd10_code, hcc_code,
                       dos_from, dos_through, cms_status,
                       payment_amount, risk_score_adj
                FROM submission_records
                WHERE batch_id = %s
                  AND payment_amount IS NOT NULL
                ORDER BY patient_id
                """,
                (batch_id,),
            )
            line_items = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc

    return {
        "batch_id": batch_id,
        "total_payment": float(summary.get("total_payment") or 0),
        "total_risk_adj": float(summary.get("total_risk_adj") or 0),
        "record_count": int(summary.get("record_count") or 0),
        "accepted": int(summary.get("accepted") or 0),
        "rejected": int(summary.get("rejected") or 0),
        "duplicate": int(summary.get("duplicate") or 0),
        "line_items": [_serialize_record(r) for r in line_items],
    }


def list_error_records(
    batch_id: str, limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    """Return records with validation errors or CMS rejections for correction."""

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM submission_records
                WHERE batch_id = %s
                  AND (validation_status IN ('invalid', 'warning')
                       OR cms_status = 'rejected')
                """,
                (batch_id,),
            )
            total = (cur.fetchone() or {}).get("cnt", 0)
            cur.execute(
                """
                SELECT * FROM submission_records
                WHERE batch_id = %s
                  AND (validation_status IN ('invalid', 'warning')
                       OR cms_status = 'rejected')
                ORDER BY validation_status DESC, id
                LIMIT %s OFFSET %s
                """,
                (batch_id, limit, offset),
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [_serialize_record(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Submission schedule
# ---------------------------------------------------------------------------


def get_submission_schedule(
    tenant_id: str, payment_year: int | None = None
) -> list[dict[str, Any]]:
    """
    Return the CMS submission deadline schedule for the tenant.

    Merges CMS standard deadlines with any tenant-custom entries stored in
    the submission_schedule table.
    """

    today = date.today()

    # Build base schedule from CMS defaults
    schedule: list[dict[str, Any]] = []
    years = [payment_year] if payment_year else list(_CMS_DEADLINES.keys())
    for yr in years:
        for dl in _CMS_DEADLINES.get(yr, []):
            dl_date = date.fromisoformat(dl["deadline"])
            schedule.append(
                {
                    "payment_year": yr,
                    "sweep_type": dl["sweep"],
                    "deadline_date": dl["deadline"],
                    "days_until": (dl_date - today).days,
                    "description": dl["description"],
                    "is_custom": False,
                    "is_overdue": dl_date < today,
                }
            )

    # Overlay with tenant custom overrides
    try:
        with raf_cursor() as cur:
            q = "SELECT * FROM submission_schedule WHERE tenant_id = %s"
            p: list[Any] = [tenant_id]
            if payment_year:
                q += " AND payment_year = %s"
                p.append(payment_year)
            cur.execute(q, p)
            custom_rows = cur.fetchall()
    except Exception as exc:
        logger.warning("get_submission_schedule custom query error: %s", exc)
        custom_rows = []

    for row in custom_rows:
        dl_date = (
            row["deadline_date"]
            if isinstance(row["deadline_date"], date)
            else date.fromisoformat(str(row["deadline_date"]))
        )
        entry = {
            "payment_year": row["payment_year"],
            "sweep_type": row["sweep_type"],
            "deadline_date": str(dl_date),
            "days_until": (dl_date - today).days,
            "description": row.get("description") or "",
            "is_custom": True,
            "is_overdue": dl_date < today,
        }
        # Replace matching default entry if one exists
        replaced = False
        for i, s in enumerate(schedule):
            if (
                s["payment_year"] == row["payment_year"]
                and s["sweep_type"] == row["sweep_type"]
            ):
                schedule[i] = entry
                replaced = True
                break
        if not replaced:
            schedule.append(entry)

    return sorted(schedule, key=lambda x: (x["payment_year"], x["deadline_date"]))


def upsert_submission_schedule(
    tenant_id: str,
    payment_year: int,
    sweep_type: str,
    deadline_date: str,
    description: str = "",
) -> dict[str, Any]:
    """Add or update a custom deadline for a tenant."""

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO submission_schedule
                    (tenant_id, payment_year, sweep_type, deadline_date, description, is_custom)
                VALUES (%s, %s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    deadline_date = VALUES(deadline_date),
                    description   = VALUES(description)
                """,
                (tenant_id, payment_year, sweep_type, deadline_date, description),
            )
    except Exception as exc:
        raise RuntimeError(f"DB error: {exc}") from exc

    return {
        "tenant_id": tenant_id,
        "payment_year": payment_year,
        "sweep_type": sweep_type,
        "deadline_date": deadline_date,
        "description": description,
        "is_custom": True,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _lookup_mbi_from_openemr(patient_id: int) -> str:
    """
    Attempt to retrieve the patient's MBI from OpenEMR insurance data.

    Falls back to an empty string if not found.  Plans should pre-load MBIs
    into raf_patient_demographics for reliable CMS submission.
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT subscriber_ss AS mbi
                FROM insurance_data
                WHERE pid = %s
                  AND type = 'primary'
                ORDER BY date DESC
                LIMIT 1
                """,
                (patient_id,),
            )
            row = cur.fetchone()
            return (row or {}).get("mbi") or ""
    except Exception as exc:
        logger.debug("MBI lookup failed for patient %s: %s", patient_id, exc)
        return ""


def _parse_icd_list(icd10_raw: Any) -> list[str]:
    """
    Parse icd10_codes from raf_patient_hcc into a clean list of code strings.

    Handles: JSON array, Python set-repr string, comma-separated, bare string.
    """
    if not icd10_raw:
        return []

    s = str(icd10_raw).strip()

    # JSON array: ["E11.9", "I10"]
    if s.startswith("["):
        try:
            items = json.loads(s)
            return [str(i).strip() for i in items if str(i).strip()]
        except json.JSONDecodeError:
            pass

    # Python set repr: {'E11.9', 'I10'}
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1]
        parts = [p.strip().strip("'\"") for p in inner.split(",")]
        return [p for p in parts if p]

    # Comma-separated
    if "," in s:
        return [p.strip() for p in s.split(",") if p.strip()]

    # Single code
    return [s] if s else []


def _add_icd_dot(code: str) -> str:
    """Re-insert the dot into a dotless ICD-10 code (e.g. 'E119' -> 'E11.9')."""
    code = code.strip().upper()
    if len(code) > 3 and "." not in code and code[0].isalpha():
        return code[:3] + "." + code[3:]
    return code


def _insert_batch(
    batch_id: str,
    tenant_id: str,
    file_type: str,
    payment_year: int,
    sweep_type: str,
    record_count: int,
    file_path: str,
    file_hash: str,
    idempotency_key: str | None = None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO submission_batches
                (id, tenant_id, file_type, payment_year, sweep_type,
                 record_count, file_path, file_hash, status, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
            """,
            (
                batch_id,
                tenant_id,
                file_type,
                payment_year,
                sweep_type,
                record_count,
                file_path,
                file_hash,
                idempotency_key,
            ),
        )


def _insert_records(
    batch_id: str,
    tenant_id: str,
    records: list[dict[str, Any]],
) -> None:
    if not records:
        return
    rows = [
        (
            batch_id,
            tenant_id,
            r["patient_id"],
            r.get("hicn_mbi"),
            r.get("hcc_code"),
            r["icd10_code"],
            r.get("dos_from"),
            r.get("dos_through"),
            r.get("provider_npi"),
            r.get("provider_type"),
        )
        for r in records
    ]
    with raf_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO submission_records
                (batch_id, tenant_id, patient_id, hicn_mbi, hcc_code,
                 icd10_code, dos_from, dos_through, provider_npi, provider_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )


def _insert_response(
    batch_id: str,
    response_type: str,
    file_name: str = "",
    raw_content: str = "",
    accepted_count: int = 0,
    rejected_count: int = 0,
    duplicate_count: int = 0,
    total_payment: float | None = None,
    notes: str = "",
) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO submission_responses
                    (batch_id, response_type, file_name, raw_content,
                     accepted_count, rejected_count, duplicate_count,
                     total_payment, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch_id,
                    response_type,
                    file_name or "",
                    raw_content or "",
                    accepted_count,
                    rejected_count,
                    duplicate_count,
                    total_payment,
                    notes or "",
                ),
            )
    except Exception as exc:
        logger.warning("_insert_response error: %s", exc)


def _update_batch_status_from_response(
    batch_id: str,
    accepted: int,
    rejected: int,
) -> None:
    if rejected == 0:
        new_status = "accepted"
    elif accepted == 0:
        new_status = "rejected"
    else:
        new_status = "partial"
    try:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE submission_batches SET status = %s WHERE id = %s",
                (new_status, batch_id),
            )
    except Exception as exc:
        logger.warning("_update_batch_status_from_response error: %s", exc)


def _serialize_record(row: dict) -> dict[str, Any]:
    """Convert a submission_records row to a JSON-serializable dict."""
    r = dict(row)
    # Parse validation_errors JSON if stored as string
    if isinstance(r.get("validation_errors"), (str, bytes)):
        try:
            r["validation_errors"] = json.loads(r["validation_errors"])
        except (json.JSONDecodeError, TypeError):
            pass
    # Convert date/datetime to string
    for key in ("dos_from", "dos_through", "created_at"):
        if isinstance(r.get(key), (date, datetime)):
            r[key] = str(r[key])
    # Convert Decimal to float
    for key in ("payment_amount", "risk_score_adj"):
        if r.get(key) is not None:
            try:
                r[key] = float(r[key])
            except (TypeError, ValueError):
                pass
    return r
