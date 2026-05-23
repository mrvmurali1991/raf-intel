"""
Uploads router — CSV/Excel patient data uploads.

Supports two shapes:

1. Multi-sheet XLSX (new): A workbook produced from the RAF Intelligence
   import template (``RAF_Patient_Import_Template.xlsx``) containing the
   sheets ``Patients``, ``HCC_Conditions``, ``MEAT_Evidence``,
   ``Suspect_Conditions`` (plus optional ``Reference_Codes`` /
   ``Instructions`` metadata sheets that are ignored). This path imports
   patients, HCC conditions, MEAT evidence, suspect conditions, and
   computes per-patient RAF scores — all inside a single transaction.

2. Legacy single-sheet CSV / XLSX: Falls back to the original
   ``patient_import_service`` importer so existing customer workflows
   keep working.

Routes
------
GET    /api/uploads/template       Download patient upload template
POST   /api/uploads/patients       Upload a CSV/XLSX file of patients
GET    /api/uploads                List past upload sessions for the tenant
GET    /api/uploads/{upload_id}    Details of a single upload
DELETE /api/uploads/{upload_id}    Soft-delete (is_active=0) patients from an upload
"""

import hashlib
import io
import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.rate_limit import limiter
from app.services.audit_logger import log_phi_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

# ---------------------------------------------------------------------------
# Template static file location
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "RAF_Patient_Import_Template.xlsx")
_TEMPLATE_CONTRACT_PATH = os.path.join(_TEMPLATE_DIR, "template_contract.md")

# ---------------------------------------------------------------------------
# Fixed sheet contract — these names and column lists MUST match the
# parallel-agent-generated Excel template exactly. Do NOT rename.
# ---------------------------------------------------------------------------

SHEET_PATIENTS = "Patients"
SHEET_HCC = "HCC_Conditions"
SHEET_MEAT = "MEAT_Evidence"
SHEET_SUSPECTS = "Suspect_Conditions"

PATIENTS_COLUMNS = [
    "mrn",
    "first_name",
    "middle_name",
    "last_name",
    "dob",
    "sex",
    "birth_sex",
    "gender_identity",
    "pronouns",
    "race",
    "ethnicity",
    "preferred_language",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "zip",
    "ssn",
    "mbi",
    "insurance_type",
    "emergency_contact_name",
    "emergency_contact_phone",
    "pcp_provider",
    "measurement_year",
]
HCC_COLUMNS = [
    "mrn",
    "measurement_year",
    "hcc_code",
    "icd10_code",
    "diagnosis_description",
    "raf_coefficient",
    "meat_status",
]
MEAT_COLUMNS = [
    "mrn",
    "hcc_code",
    "encounter_date",
    "meat_m",
    "meat_e",
    "meat_a",
    "meat_t",
    "raw_note_excerpt",
]
SUSPECTS_COLUMNS = [
    "mrn",
    "measurement_year",
    "suspect_hcc",
    "suspect_icd10",
    "evidence_type",
    "evidence_detail",
    "confidence_score",
    "rationale",
]

# DB column list for `patients` inserts — defined once so we don't duplicate.
PATIENT_DB_INSERT_COLUMNS = [
    "mrn",
    "first_name",
    "middle_name",
    "last_name",
    "dob",
    "sex",
    "birth_sex",
    "gender_identity",
    "pronouns",
    "race",
    "ethnicity",
    "preferred_language",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "zip",
    "ssn",
    "mbi",
    "insurance_type",
    "emergency_contact_name",
    "emergency_contact_phone",
    "source",
    "status",
    "is_active",
    "tenant_id",
    "data_source",
    "upload_id",
]

_VALID_MEAT_STATUS = {"complete", "partial", "missing"}
_VALID_EVIDENCE_TYPE = {"medication", "lab", "imaging", "referral", "historical"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm_header(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().lower().replace(" ", "_")


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _parse_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(v: Any, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return default


def _parse_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return default


def _sheet_to_dicts(ws) -> list[dict[str, Any]]:
    """Convert a worksheet to list[dict] using the first non-empty row as header."""
    rows_iter = ws.iter_rows(values_only=True)
    headers: list[str] = []
    out: list[dict[str, Any]] = []
    for row in rows_iter:
        if not headers:
            if row is None or all(c is None or str(c).strip() == "" for c in row):
                continue
            headers = [_norm_header(c) for c in row]
            continue
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue
        d = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            d[h] = row[i] if i < len(row) else None
        out.append(d)
    return out


def _age_from_dob(dob: date | None, year: int) -> int | None:
    if dob is None:
        return None
    return max(0, year - dob.year - (1 if (dob.month, dob.day) > (12, 31) else 0))


def _demographic_score(age: int | None, sex: str | None) -> float:
    """Simple CMS-style demographic base score lookup for the CNA segment.

    Values are representative of the CMS-HCC v24 community non-dual aged
    factors and are used here only to give demo uploads a plausible,
    non-zero base score. Not intended for production RAF calculations.
    """
    if age is None:
        return 0.4
    s = (sex or "").strip().upper()[:1]
    if s == "F":
        if age < 65:
            return 0.283
        if age < 70:
            return 0.323
        if age < 75:
            return 0.381
        if age < 80:
            return 0.469
        if age < 85:
            return 0.579
        return 0.706
    if s == "M":
        if age < 65:
            return 0.312
        if age < 70:
            return 0.359
        if age < 75:
            return 0.422
        if age < 80:
            return 0.510
        if age < 85:
            return 0.621
        return 0.757
    return 0.4


def _age_band(age: int | None) -> str:
    if age is None:
        return "65-69"
    if age < 65:
        return "0-64"
    if age < 70:
        return "65-69"
    if age < 75:
        return "70-74"
    if age < 80:
        return "75-79"
    if age < 85:
        return "80-84"
    return "85+"


# ---------------------------------------------------------------------------
# Content-hash dedup helpers
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_upload_duplicate(
    tenant_id: str, content_hash: str
) -> dict[str, Any] | None:
    """Return the existing upload row if (tenant_id, content_hash) already succeeded.

    Returns None when:
    - The content_hash column does not exist (logs WARN, graceful fallback).
    - No prior upload exists for this hash.
    - The prior upload failed (allow retry).
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, status, filename
                  FROM raf_data_uploads
                 WHERE tenant_id = %s AND content_hash = %s
                 ORDER BY id DESC
                 LIMIT 1
                """,
                (tenant_id, content_hash),
            )
            row = cur.fetchone()
    except Exception as exc:
        # Catch unknown-column or any DB error — dedup is best-effort.
        exc_str = str(exc).lower()
        if "content_hash" in exc_str or "unknown column" in exc_str:
            logger.warning(
                "uploads: add `content_hash` column to raf_data_uploads to enable dedup"
            )
        else:
            logger.warning("uploads: dedup check failed (non-fatal): %s", exc)
        return None

    if row is None:
        return None

    status = str(row.get("status") or "")
    if status == "failed":
        # Prior attempt failed — allow re-upload as a retry.
        return None

    return dict(row)


# ---------------------------------------------------------------------------
# Multi-sheet importer
# ---------------------------------------------------------------------------


def _is_multi_sheet_template(wb) -> bool:
    names = set(wb.sheetnames)
    return SHEET_PATIENTS in names and SHEET_HCC in names


def _import_multi_sheet(
    wb,
    *,
    tenant_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """Import the multi-sheet RAF template.

    Runs entirely inside a single ``raf_cursor`` transaction; any raised
    exception rolls the whole thing back. Row-level data errors are
    collected into the ``errors`` list and do NOT abort the import — only
    structural errors (missing required sheets, unparseable columns) raise.
    """
    errors: list[str] = []

    # --- Pre-parse sheets --------------------------------------------------
    patients_rows = _sheet_to_dicts(wb[SHEET_PATIENTS])
    hcc_rows = _sheet_to_dicts(wb[SHEET_HCC])
    meat_rows = _sheet_to_dicts(wb[SHEET_MEAT]) if SHEET_MEAT in wb.sheetnames else []
    suspect_rows = (
        _sheet_to_dicts(wb[SHEET_SUSPECTS]) if SHEET_SUSPECTS in wb.sheetnames else []
    )

    if not patients_rows:
        raise HTTPException(
            status_code=422,
            detail="Patients sheet is empty — nothing to import.",
        )

    patients_inserted = 0
    patients_updated = 0
    hcc_inserted = 0
    meat_inserted = 0
    suspects_inserted = 0
    scores_computed = 0

    with raf_cursor() as cur:
        # 1) Create upload session row -------------------------------------
        try:
            cur.execute(
                """
                INSERT INTO raf_data_uploads
                    (tenant_id, uploaded_by, filename, file_size_bytes, file_type,
                     status, content_hash)
                VALUES (%s, %s, %s, %s, 'xlsx', 'processing', %s)
                """,
                (tenant_id, user_id, filename[:512], file_size, content_hash),
            )
        except Exception as col_exc:
            if "content_hash" in str(col_exc).lower() or "unknown column" in str(col_exc).lower():
                logger.warning(
                    "uploads: add `content_hash` column to raf_data_uploads to enable dedup"
                )
                cur.execute(
                    """
                    INSERT INTO raf_data_uploads
                        (tenant_id, uploaded_by, filename, file_size_bytes, file_type, status)
                    VALUES (%s, %s, %s, %s, 'xlsx', 'processing')
                    """,
                    (tenant_id, user_id, filename[:512], file_size),
                )
            else:
                raise
        upload_id = int(cur.lastrowid)

        # 2) Patients: upsert on (tenant_id, mrn) --------------------------
        mrn_to_pid: dict[str, int] = {}
        # Cache dob+sex for score computation later.
        pid_to_demo: dict[int, tuple[date | None, str]] = {}
        # Track measurement_year per patient (from Patients sheet row).
        pid_to_year: dict[int, int] = {}

        insert_cols = ", ".join(f"`{c}`" for c in PATIENT_DB_INSERT_COLUMNS)
        insert_placeholders = ", ".join(["%s"] * len(PATIENT_DB_INSERT_COLUMNS))
        patient_insert_sql = (
            f"INSERT INTO patients ({insert_cols}) VALUES ({insert_placeholders})"
        )

        # Build the list of updatable columns (everything except keys).
        update_cols = [
            c
            for c in PATIENT_DB_INSERT_COLUMNS
            if c not in ("mrn", "tenant_id", "is_active")
        ]
        update_set = ", ".join(f"`{c}` = %s" for c in update_cols)
        patient_update_sql = f"UPDATE patients SET {update_set} WHERE id = %s"

        current_year = datetime.now(timezone.utc).year

        for idx, raw in enumerate(patients_rows, start=2):
            try:
                mrn = _cell_str(raw.get("mrn"))
                if not mrn:
                    errors.append(f"Patients row {idx}: missing mrn, skipped")
                    continue
                first = _cell_str(raw.get("first_name"))
                last = _cell_str(raw.get("last_name"))
                dob = _parse_date(raw.get("dob"))
                if not first or not last or dob is None:
                    errors.append(
                        f"Patients row {idx} (mrn={mrn}): first_name/last_name/dob required"
                    )
                    continue
                sex = _cell_str(raw.get("sex"))[:20] or None
                measurement_year = _parse_int(raw.get("measurement_year"), current_year)

                values = [
                    mrn[:50],
                    first[:100],
                    (_cell_str(raw.get("middle_name")) or None),
                    last[:100],
                    dob,
                    sex,
                    (_cell_str(raw.get("birth_sex"))[:20] or None),
                    (_cell_str(raw.get("gender_identity"))[:50] or None),
                    (_cell_str(raw.get("pronouns"))[:30] or None),
                    (_cell_str(raw.get("race"))[:20] or None),
                    (_cell_str(raw.get("ethnicity"))[:20] or None),
                    (_cell_str(raw.get("preferred_language"))[:10] or "en"),
                    (_cell_str(raw.get("phone"))[:20] or None),
                    (_cell_str(raw.get("email"))[:100] or None),
                    (_cell_str(raw.get("address"))[:255] or None),
                    (_cell_str(raw.get("city"))[:100] or None),
                    (_cell_str(raw.get("state"))[:2] or None),
                    (_cell_str(raw.get("zip"))[:10] or None),
                    (_cell_str(raw.get("ssn"))[:11] or None),
                    (_cell_str(raw.get("mbi"))[:20] or None),
                    (_cell_str(raw.get("insurance_type"))[:50] or None),
                    (_cell_str(raw.get("emergency_contact_name"))[:200] or None),
                    (_cell_str(raw.get("emergency_contact_phone"))[:20] or None),
                    "excel",  # source
                    "active",  # status
                    1,  # is_active
                    str(tenant_id),  # tenant_id
                    "upload",  # data_source
                    upload_id,  # upload_id
                ]

                # Look up existing patient by (tenant_id, mrn).
                cur.execute(
                    "SELECT id FROM patients WHERE tenant_id = %s AND mrn = %s LIMIT 1",
                    (str(tenant_id), mrn),
                )
                existing = cur.fetchone()
                if existing:
                    pid = int(existing["id"])
                    # Update: values minus the mrn/tenant_id positions.
                    # Always reactivate on re-upload (is_active=1).
                    update_values = []
                    for c, val in zip(PATIENT_DB_INSERT_COLUMNS, values):
                        if c in ("mrn", "tenant_id"):
                            continue
                        update_values.append(val)
                    update_values.append(pid)
                    cur.execute(patient_update_sql, tuple(update_values))
                    patients_updated += 1
                else:
                    cur.execute(patient_insert_sql, tuple(values))
                    pid = int(cur.lastrowid)
                    patients_inserted += 1

                mrn_to_pid[mrn] = pid
                pid_to_demo[pid] = (dob, sex or "")
                pid_to_year[pid] = measurement_year
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"Patients row {idx}: {exc}")

        # 3) HCC Conditions -------------------------------------------------
        # (mrn, hcc_code) -> patient_hcc_id, used by MEAT lookup.
        hcc_key_to_id: dict[tuple[str, int], int] = {}
        # (pid, year) -> accumulated disease score & hcc_count
        disease_accum: dict[tuple[int, int], dict[str, Any]] = {}

        for idx, raw in enumerate(hcc_rows, start=2):
            try:
                mrn = _cell_str(raw.get("mrn"))
                if not mrn:
                    errors.append(f"HCC_Conditions row {idx}: missing mrn, skipped")
                    continue
                if mrn not in mrn_to_pid:
                    errors.append(
                        f"HCC_Conditions row {idx}: mrn={mrn} not found in Patients sheet"
                    )
                    continue
                pid = mrn_to_pid[mrn]
                year = _parse_int(
                    raw.get("measurement_year"), pid_to_year.get(pid, current_year)
                )
                hcc_code = _parse_int(raw.get("hcc_code"))
                if hcc_code <= 0:
                    errors.append(f"HCC_Conditions row {idx}: invalid hcc_code")
                    continue
                icd10 = _cell_str(raw.get("icd10_code")).upper()
                raf_coef = _parse_float(raw.get("raf_coefficient"))
                meat_status = _cell_str(raw.get("meat_status")).lower() or "missing"
                if meat_status not in _VALID_MEAT_STATUS:
                    meat_status = "missing"
                icd10_json = json.dumps([icd10] if icd10 else [])
                src_enc_json = json.dumps([])

                # raf_patient_hcc has a FK to raf_patient_demographics(patient_id,
                # measurement_year) — so make sure a demographics row exists.
                dob, sex = pid_to_demo.get(pid, (None, ""))
                age = _age_from_dob(dob, year)
                demo_sex = (sex or "").strip().upper()[:1]
                if demo_sex not in ("M", "F"):
                    demo_sex = "M"
                cur.execute(
                    """
                    INSERT INTO raf_patient_demographics
                        (patient_id, measurement_year, age_band, sex, tenant_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE age_band = VALUES(age_band), sex = VALUES(sex)
                    """,
                    (pid, year, _age_band(age), demo_sex, str(tenant_id)),
                )

                # Upsert raf_patient_hcc by (patient_id, hcc_code, measurement_year).
                cur.execute(
                    """
                    SELECT id, icd10_codes FROM raf_patient_hcc
                     WHERE patient_id = %s AND hcc_code = %s AND measurement_year = %s
                     LIMIT 1
                    """,
                    (pid, hcc_code, year),
                )
                existing = cur.fetchone()
                if existing:
                    phcc_id = int(existing["id"])
                    try:
                        old_codes = json.loads(existing["icd10_codes"] or "[]")
                    except (TypeError, json.JSONDecodeError):
                        old_codes = []
                    merged = sorted(set(list(old_codes) + ([icd10] if icd10 else [])))
                    cur.execute(
                        """
                        UPDATE raf_patient_hcc
                           SET icd10_codes = %s,
                               raf_coefficient = %s,
                               meat_status = %s,
                               tenant_id = %s
                         WHERE id = %s
                        """,
                        (
                            json.dumps(merged),
                            raf_coef,
                            meat_status,
                            str(tenant_id),
                            phcc_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO raf_patient_hcc
                            (patient_id, measurement_year, hcc_code, icd10_codes,
                             source_encounter_ids, raf_coefficient, meat_status, tenant_id,
                             model_version)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'V28')
                        """,
                        (
                            pid,
                            year,
                            hcc_code,
                            icd10_json,
                            src_enc_json,
                            raf_coef,
                            meat_status,
                            str(tenant_id),
                        ),
                    )
                    phcc_id = int(cur.lastrowid)
                    hcc_inserted += 1

                hcc_key_to_id[(mrn, hcc_code)] = phcc_id

                bucket = disease_accum.setdefault(
                    (pid, year),
                    {"disease": 0.0, "count": 0},
                )
                bucket["disease"] += raf_coef
                bucket["count"] += 1
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"HCC_Conditions row {idx}: {exc}")

        # 4) MEAT Evidence --------------------------------------------------
        for idx, raw in enumerate(meat_rows, start=2):
            try:
                mrn = _cell_str(raw.get("mrn"))
                hcc_code = _parse_int(raw.get("hcc_code"))
                key = (mrn, hcc_code)
                if key not in hcc_key_to_id:
                    errors.append(
                        f"MEAT_Evidence row {idx}: no HCC row for mrn={mrn} hcc={hcc_code}"
                    )
                    continue
                phcc_id = hcc_key_to_id[key]
                enc_date = _parse_date(raw.get("encounter_date")) or date.today()
                m = _cell_str(raw.get("meat_m"))
                e = _cell_str(raw.get("meat_e"))
                a = _cell_str(raw.get("meat_a"))
                t = _cell_str(raw.get("meat_t"))
                m_p = 1 if m else 0
                e_p = 1 if e else 0
                a_p = 1 if a else 0
                t_p = 1 if t else 0
                completeness = round((m_p + e_p + a_p + t_p) / 4.0, 4)
                excerpt = _cell_str(raw.get("raw_note_excerpt")) or None

                cur.execute(
                    """
                    INSERT INTO raf_meat_evidence
                        (patient_hcc_id, encounter_id, encounter_date,
                         meat_m, meat_e, meat_a, meat_t,
                         meat_m_present, meat_e_present, meat_a_present, meat_t_present,
                         completeness_score, raw_note_excerpt,
                         document_upload_id, document_hash, context_classification)
                    VALUES (%s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, 'upload')
                    """,
                    (
                        phcc_id,
                        enc_date,
                        m or None,
                        e or None,
                        a or None,
                        t or None,
                        m_p,
                        e_p,
                        a_p,
                        t_p,
                        completeness,
                        excerpt,
                        upload_id,    # document_upload_id: already in scope from step 1
                        content_hash, # document_hash: SHA-256 of the uploaded file
                    ),
                )
                meat_inserted += 1
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"MEAT_Evidence row {idx}: {exc}")

        # 5) Suspect Conditions --------------------------------------------
        for idx, raw in enumerate(suspect_rows, start=2):
            try:
                mrn = _cell_str(raw.get("mrn"))
                if mrn not in mrn_to_pid:
                    errors.append(
                        f"Suspect_Conditions row {idx}: mrn={mrn} not in Patients"
                    )
                    continue
                pid = mrn_to_pid[mrn]
                year = _parse_int(
                    raw.get("measurement_year"), pid_to_year.get(pid, current_year)
                )
                suspect_hcc = _parse_int(raw.get("suspect_hcc"))
                suspect_icd = _cell_str(raw.get("suspect_icd10")).upper()[:10]
                ev_type = _cell_str(raw.get("evidence_type")).lower()
                if ev_type not in _VALID_EVIDENCE_TYPE:
                    ev_type = "historical"
                ev_detail_text = _cell_str(raw.get("evidence_detail"))
                ev_detail_json = json.dumps({"detail": ev_detail_text})
                confidence = _parse_float(raw.get("confidence_score"))
                rationale = _cell_str(raw.get("rationale")) or None

                cur.execute(
                    """
                    INSERT INTO raf_suspect_conditions
                        (patient_id, measurement_year, suspect_hcc, suspect_icd10,
                         evidence_type, evidence_detail, confidence_score, status,
                         tenant_id, hcc_coefficient, confidence, rationale)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s)
                    """,
                    (
                        pid,
                        year,
                        suspect_hcc,
                        suspect_icd or "N/A",
                        ev_type,
                        ev_detail_json,
                        confidence,
                        str(tenant_id),
                        0.15,
                        confidence,
                        rationale,
                    ),
                )
                suspects_inserted += 1
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"Suspect_Conditions row {idx}: {exc}")

        # 6) RAF scores -----------------------------------------------------
        for (pid, year), bucket in disease_accum.items():
            try:
                dob, sex = pid_to_demo.get(pid, (None, ""))
                age = _age_from_dob(dob, year)
                demo_score = _demographic_score(age, sex)
                disease_score = float(bucket["disease"])
                interaction_score = 0.0
                total_raw = demo_score + disease_score + interaction_score
                final_raf = total_raw  # normalization_factor = 1.0
                hcc_count = int(bucket["count"])

                cur.execute(
                    """
                    INSERT INTO raf_scores
                        (patient_id, measurement_year, score_type, model_segment,
                         demographic_score, disease_score, interaction_score,
                         total_raw, normalization_factor, final_raf, hcc_count, tenant_id)
                    VALUES (%s, %s, 'prospective', 'CNA',
                            %s, %s, %s, %s, 1.0000, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        demographic_score = VALUES(demographic_score),
                        disease_score     = VALUES(disease_score),
                        interaction_score = VALUES(interaction_score),
                        total_raw         = VALUES(total_raw),
                        final_raf         = VALUES(final_raf),
                        hcc_count         = VALUES(hcc_count),
                        tenant_id         = VALUES(tenant_id),
                        calculated_at     = NOW()
                    """,
                    (
                        pid,
                        year,
                        demo_score,
                        disease_score,
                        interaction_score,
                        total_raw,
                        final_raf,
                        hcc_count,
                        str(tenant_id),
                    ),
                )
                scores_computed += 1
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"raf_scores (pid={pid}, year={year}): {exc}")

        # 7) Finalise upload row -------------------------------------------
        total_rows = (
            len(patients_rows) + len(hcc_rows) + len(meat_rows) + len(suspect_rows)
        )
        imported_rows = (
            patients_inserted
            + patients_updated
            + hcc_inserted
            + meat_inserted
            + suspects_inserted
        )
        failed_rows = len(errors)
        status = "completed" if failed_rows == 0 else "partial"
        err_summary = ("\n".join(errors[:50]))[:4000] or None
        cur.execute(
            """
            UPDATE raf_data_uploads
               SET status = %s,
                   row_count_total = %s,
                   row_count_imported = %s,
                   row_count_failed = %s,
                   error_summary = %s,
                   completed_at = %s
             WHERE id = %s
            """,
            (
                status,
                total_rows,
                imported_rows,
                failed_rows,
                err_summary,
                datetime.now(timezone.utc),
                upload_id,
            ),
        )

    return {
        "upload_id": upload_id,
        "patients_inserted": patients_inserted,
        "patients_updated": patients_updated,
        "hcc_inserted": hcc_inserted,
        "meat_inserted": meat_inserted,
        "suspects_inserted": suspects_inserted,
        "scores_computed": scores_computed,
        "errors": errors[:100],
        "status": "completed" if not errors else "partial",
    }


# ---------------------------------------------------------------------------
# Legacy single-sheet session helpers (kept for CSV / legacy XLSX path)
# ---------------------------------------------------------------------------


def _create_upload_session(
    tenant_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    file_type: str,
    content_hash: str | None = None,
) -> int:
    with raf_cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO raf_data_uploads
                    (tenant_id, uploaded_by, filename, file_size_bytes, file_type,
                     status, content_hash)
                VALUES (%s, %s, %s, %s, %s, 'processing', %s)
                """,
                (tenant_id, user_id, filename[:512], file_size, file_type, content_hash),
            )
        except Exception as col_exc:
            if "content_hash" in str(col_exc).lower() or "unknown column" in str(col_exc).lower():
                logger.warning(
                    "uploads: add `content_hash` column to raf_data_uploads to enable dedup"
                )
                cur.execute(
                    """
                    INSERT INTO raf_data_uploads
                        (tenant_id, uploaded_by, filename, file_size_bytes, file_type, status)
                    VALUES (%s, %s, %s, %s, %s, 'processing')
                    """,
                    (tenant_id, user_id, filename[:512], file_size, file_type),
                )
            else:
                raise
        return int(cur.lastrowid)


def _finalize_upload_session(
    upload_id: int,
    status: str,
    total: int,
    imported: int,
    failed: int,
    error_summary: str | None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE raf_data_uploads
               SET status = %s,
                   row_count_total = %s,
                   row_count_imported = %s,
                   row_count_failed = %s,
                   error_summary = %s,
                   completed_at = %s
             WHERE id = %s
            """,
            (
                status,
                total,
                imported,
                failed,
                (error_summary or "")[:4000] or None,
                datetime.now(timezone.utc),
                upload_id,
            ),
        )


def _tag_uploaded_rows(tenant_id: str, upload_id: int, since_id: int) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE patients
               SET data_source = 'upload', upload_id = %s
             WHERE tenant_id = %s AND id > %s AND is_active = 1
            """,
            (upload_id, tenant_id, since_id),
        )
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# Template download — serve the static multi-sheet template
# ---------------------------------------------------------------------------


@router.get("/template", summary="Download patient upload template")
def download_template(
    format: str = Query("xlsx", regex="^(csv|xlsx)$"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> Response:
    """Return the multi-sheet RAF patient import template as an XLSX file.

    Primary path: stream the pre-built static template from
    ``backend/app/data/RAF_Patient_Import_Template.xlsx``. If that file is
    missing (e.g. fresh checkout before the template has been generated),
    fall back to the legacy on-the-fly generator.
    """
    if format == "csv":
        from app.services.patient_import_service import get_import_template as _csv_tpl

        return Response(
            content=_csv_tpl(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=raf_patient_template.csv"
            },
        )

    if os.path.exists(_TEMPLATE_PATH):
        try:
            with open(_TEMPLATE_PATH, "rb") as fh:
                content = fh.read()
            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": (
                        'attachment; filename="RAF_Patient_Import_Template.xlsx"'
                    )
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to serve static template %s: %s", _TEMPLATE_PATH, exc
            )

    # Fallback: generate on the fly using the legacy single-sheet template.
    from app.services.patient_import_service import (
        get_import_template_xlsx as _xlsx_tpl,
    )

    return Response(
        content=_xlsx_tpl(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="RAF_Patient_Import_Template.xlsx"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Upload (patients)
# ---------------------------------------------------------------------------


@router.post("/patients", summary="Upload a CSV/XLSX file of patients")
@limiter.limit("10/minute")
async def upload_patients(
    request: Request,
    file: UploadFile = File(..., description="CSV or Excel (.xlsx) patient file"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    fname = (file.filename or "").strip()
    fname_lower = fname.lower()
    if not fname or not (fname_lower.endswith(".csv") or fname_lower.endswith(".xlsx")):
        raise HTTPException(
            status_code=422,
            detail="Only .csv and .xlsx files are accepted.",
        )
    file_type = "xlsx" if fname_lower.endswith(".xlsx") else "csv"

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    tenant_id = get_tenant_id(current_user)
    user_id = int(current_user.get("id") or 0)

    # ---- Compute content hash BEFORE any parsing -------------------------
    content_hash = _sha256_hex(content)

    # ---- Dedup check: same (tenant, hash) already successfully processed? -
    existing = _check_upload_duplicate(str(tenant_id), content_hash)
    if existing is not None:
        logger.info(
            "uploads: duplicate detected for tenant=%s hash=%s upload_id=%s",
            tenant_id,
            content_hash[:16],
            existing.get("id"),
        )
        return {
            "upload_id": int(existing["id"]),
            "filename": fname,
            "file_type": file_type,
            "duplicate": True,
            "warning": "duplicate_upload",
            "status": str(existing.get("status") or "completed"),
            "patients_inserted": 0,
            "patients_updated": 0,
            "hcc_inserted": 0,
            "meat_inserted": 0,
            "suspects_inserted": 0,
            "scores_computed": 0,
            "row_count_total": 0,
            "row_count_imported": 0,
            "row_count_failed": 0,
            "errors": [],
        }

    # ---- Multi-sheet XLSX path -------------------------------------------
    if file_type == "xlsx":
        import openpyxl  # lazy import — only needed for XLSX uploads

        try:
            wb = openpyxl.load_workbook(
                io.BytesIO(content), data_only=True, read_only=True
            )
        except Exception as exc:
            logger.warning("uploads: could not open xlsx: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=422,
                detail="Could not open Excel file (corrupted or unsupported format)",
            ) from exc

        if _is_multi_sheet_template(wb):
            try:
                result = _import_multi_sheet(
                    wb,
                    tenant_id=str(tenant_id),
                    user_id=user_id,
                    filename=fname,
                    file_size=len(content),
                    content_hash=content_hash,
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.exception("Multi-sheet import failed: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail="Multi-sheet import failed. Please check your file format and try again.",
                ) from exc

            log_phi_access(
                action="file_upload",
                resource="patient",
                details=(
                    f"upload_id={result['upload_id']} filename={fname!r} "
                    f"patients_ins={result['patients_inserted']} "
                    f"patients_upd={result['patients_updated']} "
                    f"hcc={result['hcc_inserted']} meat={result['meat_inserted']} "
                    f"suspects={result['suspects_inserted']} scores={result['scores_computed']}"
                ),
            )
            result["filename"] = fname
            result["file_type"] = "xlsx"
            result["duplicate"] = False
            return result

        # Otherwise fall through to the legacy single-sheet XLSX path.
        try:
            wb.close()
        except Exception:  # noqa: BLE001 — best-effort guard
            logger.debug("swallowed exception", exc_info=True)

    # ---- Legacy single-sheet / CSV path ----------------------------------
    from app.services.patient_import_service import (
        import_patients as _import,
    )
    from app.services.patient_import_service import (
        parse_patient_csv as _parse_csv,
    )
    from app.services.patient_import_service import (
        parse_patient_xlsx as _parse_xlsx,
    )

    if file_type == "xlsx":
        rows, parse_errors = _parse_xlsx(content)
    else:
        rows, parse_errors = _parse_csv(content)

    if parse_errors and not rows:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Could not parse uploaded file.",
                "errors": parse_errors,
            },
        )

    upload_id = _create_upload_session(
        tenant_id=str(tenant_id),
        user_id=user_id,
        filename=fname,
        file_size=len(content),
        file_type=file_type,
        content_hash=content_hash,
    )

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(id), 0) AS max_id FROM patients WHERE tenant_id = %s",
                (str(tenant_id),),
            )
            row = cur.fetchone()
            since_id = int(row["max_id"]) if row else 0
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        since_id = 0

    uploader_name = (
        current_user.get("username")
        or current_user.get("email")
        or current_user.get("sub")
        or "upload"
    )

    try:
        summary = _import(
            rows,
            uploaded_by=str(uploader_name),
            on_duplicate="update",
            source="csv" if file_type == "csv" else "excel",
            tenant_id=int(tenant_id) if str(tenant_id).isdigit() else 1,
        )
    except Exception as exc:
        logger.exception("uploads: import_patients failed: %s", exc)
        _finalize_upload_session(
            upload_id, "failed", len(rows), 0, len(rows), f"Importer error: {exc}"
        )
        raise HTTPException(status_code=500, detail="Import failed") from exc

    try:
        _tag_uploaded_rows(
            tenant_id=str(tenant_id), upload_id=upload_id, since_id=since_id
        )
    except Exception as exc:
        logger.warning("uploads: tag rows failed: %s", exc)

    total = int(summary.get("total_rows") or 0)
    imported = int(summary.get("imported") or 0)
    updated = int(summary.get("updated") or 0)
    failed = int(summary.get("errors") or 0)
    error_details = summary.get("error_details") or []
    if parse_errors:
        failed += len(parse_errors)
        error_details = list(parse_errors) + list(error_details)

    status = "completed"
    if failed and (imported + updated) == 0:
        status = "failed"
    elif failed:
        status = "partial"

    error_summary_str = (
        "\n".join(str(e) for e in error_details[:50]) if error_details else None
    )
    _finalize_upload_session(
        upload_id=upload_id,
        status=status,
        total=total,
        imported=imported + updated,
        failed=failed,
        error_summary=error_summary_str,
    )

    log_phi_access(
        action="file_upload",
        resource="patient",
        details=(
            f"upload_id={upload_id} filename={fname!r} total={total} "
            f"imported={imported} updated={updated} failed={failed}"
        ),
    )

    return {
        "upload_id": upload_id,
        "filename": fname,
        "file_type": file_type,
        "duplicate": False,
        "patients_inserted": imported,
        "patients_updated": updated,
        "hcc_inserted": 0,
        "meat_inserted": 0,
        "suspects_inserted": 0,
        "scores_computed": 0,
        "row_count_total": total,
        "row_count_imported": imported + updated,
        "row_count_failed": failed,
        "status": status,
        "errors": error_details[:100],
    }


# ---------------------------------------------------------------------------
# List / detail / delete
# ---------------------------------------------------------------------------


@router.get("", summary="List past patient uploads")
def list_uploads(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    tenant_id = get_tenant_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, uploaded_by, filename, file_size_bytes, file_type,
                   row_count_total, row_count_imported, row_count_failed,
                   status, created_at, completed_at
              FROM raf_data_uploads
             WHERE tenant_id = %s
             ORDER BY created_at DESC
             LIMIT 200
            """,
            (str(tenant_id),),
        )
        rows = cur.fetchall() or []
    out = []
    for r in rows:
        item = {k: v for k, v in r.items()}
        for k, v in list(item.items()):
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        out.append(item)
    return {"uploads": out, "total": len(out)}


@router.get("/{upload_id}", summary="Get details of a single upload")
def get_upload(
    upload_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    tenant_id = get_tenant_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM raf_data_uploads WHERE id = %s AND tenant_id = %s",
            (upload_id, str(tenant_id)),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Upload not found")
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM patients WHERE upload_id = %s AND tenant_id = %s AND is_active = 1",
            (upload_id, str(tenant_id)),
        )
        active_count = int((cur.fetchone() or {}).get("cnt") or 0)

    item = {k: v for k, v in row.items()}
    for k, v in list(item.items()):
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    item["active_patient_count"] = active_count
    return item


@router.delete("/{upload_id}", summary="Soft-delete all patients from an upload")
def delete_upload(
    upload_id: int,
    confirm: bool = Query(False, description="Set to true to confirm deletion"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Deletion requires ?confirm=true",
        )
    tenant_id = get_tenant_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM raf_data_uploads WHERE id = %s AND tenant_id = %s",
            (upload_id, str(tenant_id)),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Upload not found")

        cur.execute(
            "UPDATE patients SET is_active = 0 WHERE upload_id = %s AND tenant_id = %s AND is_active = 1",
            (upload_id, str(tenant_id)),
        )
        deleted = int(cur.rowcount or 0)

    log_phi_access(
        action="delete",
        resource="upload",
        details=f"upload_id={upload_id} soft_deleted={deleted}",
    )
    return {"upload_id": upload_id, "deleted": deleted}
