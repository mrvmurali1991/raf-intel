"""
Suspect Condition Detection Engine.

Identifies conditions that are likely present but not yet coded in the
patient's billing record.  Four scanning strategies:

  1. Medication signals  – drug name → suspected ICD-10 / HCC
  2. Lab signals         – abnormal lab values → suspected condition
  3. Historical HCC gap  – prior-year HCCs not recaptured in current year
  4. Note vs billing gap – Gemini NLP-identified diagnoses not in billing

Suspects are deduplicated by fingerprint, stored in raf_suspect_conditions,
and support accept / dismiss review workflows.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import date
from typing import Any

from app.db import raf_cursor
from app.services import openemr_connector as emr
from app.services.hcc_hierarchy import apply_hierarchy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached signal tables (5-minute TTL avoids N+1 DB hits per patient scan)
# ---------------------------------------------------------------------------
_medication_signals_cache: list[dict] | None = None
_medication_signals_ts: float = 0

_lab_signals_cache: list[dict] | None = None
_lab_signals_ts: float = 0

_SIGNAL_CACHE_TTL = 300  # seconds
_signal_cache_lock = threading.Lock()


def _get_medication_signals(cur) -> list[dict]:
    global _medication_signals_cache, _medication_signals_ts
    with _signal_cache_lock:
        if _medication_signals_cache is None or time.time() - _medication_signals_ts > _SIGNAL_CACHE_TTL:
            cur.execute("SELECT * FROM raf_medication_signals")
            _medication_signals_cache = cur.fetchall()
            _medication_signals_ts = time.time()
            logger.debug("Refreshed medication signals cache: %d rows", len(_medication_signals_cache))
        return _medication_signals_cache


def _get_lab_signals(cur) -> list[dict]:
    global _lab_signals_cache, _lab_signals_ts
    with _signal_cache_lock:
        if _lab_signals_cache is None or time.time() - _lab_signals_ts > _SIGNAL_CACHE_TTL:
            cur.execute("SELECT * FROM raf_lab_signals")
            _lab_signals_cache = cur.fetchall()
            _lab_signals_ts = time.time()
            logger.debug("Refreshed lab signals cache: %d rows", len(_lab_signals_cache))
        return _lab_signals_cache


# ---------------------------------------------------------------------------
# Patient list helper — supports both native and FHIR/REST patients
# ---------------------------------------------------------------------------

def _get_all_patient_ids(tenant_id: str) -> list[int]:
    """Return patient IDs to scan, sourced from the active connection type.

    When the tenant has an active FHIR R4 or REST API EMR connection the IDs
    are taken from ``emr_patient_matches`` (the ``emr_pid`` column contains the
    external patient identifier that every downstream EMR call expects).
    Otherwise the native ``patients`` table is used.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT connection_type FROM emr_connections "
            "WHERE is_active = 1 AND tenant_id = %s LIMIT 1",
            (tenant_id,),
        )
        row = cur.fetchone()
        if row and row["connection_type"] in ("fhir_r4", "rest_api"):
            cur.execute(
                """
                SELECT epm.patient_id AS patient_id
                FROM emr_patient_matches epm
                JOIN emr_connections ec ON ec.id = epm.connection_id
                WHERE ec.is_active = 1
                  AND ec.tenant_id = %s
                """,
                (tenant_id,),
            )
            logger.info(
                "_get_all_patient_ids tenant=%s using FHIR/REST source (emr_patient_matches)",
                tenant_id,
            )
        else:
            cur.execute(
                "SELECT id AS patient_id FROM patients "
                "WHERE is_active = 1 AND tenant_id = %s",
                (tenant_id,),
            )
            logger.info(
                "_get_all_patient_ids tenant=%s using native patients table",
                tenant_id,
            )
        return [r["patient_id"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coded_icd_set(patient_id: int, year: int | None = None) -> set[str]:
    """Return the normalised set of ICD-10 codes already in billing.

    When *year* is provided the result is restricted to encounters whose
    date falls within that calendar year, using a JOIN against
    form_encounter (mirroring the approach in _coded_hcc_set).
    """
    if year is None:
        codes = emr.get_billing_codes(patient_id)
        return {
            (r.get("code") or "").replace(".", "").strip().upper()
            for r in codes
            if r.get("code")
        }

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT nd.icd10_code AS code
                FROM normalized_diagnoses nd
                JOIN normalized_encounters ne
                    ON ne.encounter_id = nd.encounter_id
                WHERE nd.patient_id = %s
                  AND YEAR(ne.encounter_date) = %s
                  AND nd.icd10_code IS NOT NULL
                  AND nd.icd10_code != ''
                """,
                (patient_id, year),
            )
            rows = cur.fetchall()
        return {
            (r.get("code") or "").replace(".", "").strip().upper()
            for r in rows
            if r.get("code")
        }
    except Exception as exc:
        logger.error("_coded_icd_set failed pid=%s year=%s: %s", patient_id, year, exc)
        return set()


def _coded_hcc_set(patient_id: int, year: int | None = None) -> set[str]:
    """Return HCC codes already recorded in raf_patient_hcc."""
    try:
        with raf_cursor() as cur:
            if year:
                cur.execute(
                    """
                    SELECT DISTINCT hcc_code
                    FROM raf_patient_hcc
                    WHERE patient_id = %s AND measurement_year = %s
                    """,
                    (patient_id, year),
                )
            else:
                cur.execute(
                    "SELECT DISTINCT hcc_code FROM raf_patient_hcc WHERE patient_id = %s",
                    (patient_id,),
                )
            rows = cur.fetchall()
        return {str(r["hcc_code"]).strip().upper() for r in rows if r.get("hcc_code") is not None}
    except Exception as exc:
        logger.error("_coded_hcc_set failed pid=%s: %s", patient_id, exc)
        return set()


def _suspect_fingerprint(patient_id: int, source: str, code: str) -> str:
    """Stable SHA-256 dedup key for a suspect (patient + source + code)."""
    raw = f"{patient_id}|{source}|{code}".lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


_EVIDENCE_TYPE_MAP = {
    "medication": "medication",
    "medication_signal": "medication",
    "lab": "lab",
    "lab_signal": "lab",
    "history": "historical",
    "historical": "historical",
    "historical_hcc": "historical",
    "nlp": "referral",
    "note_vs_billing": "referral",
    "imaging": "imaging",
    "referral": "referral",
}


def _map_evidence_type(source: str) -> str:
    """Map internal source names to the evidence_type ENUM values."""
    return _EVIDENCE_TYPE_MAP.get(source, "medication")


def _store_suspect(
    suspect: dict[str, Any],
    measurement_year: int | None = None,
    tenant_id: str | None = None,
) -> int | None:
    """
    Insert or update a suspect condition row.  Returns the row id.

    raf_suspect_conditions schema:
        id               INT AUTO_INCREMENT PRIMARY KEY
        patient_id       INT NOT NULL
        fingerprint      VARCHAR(32) UNIQUE
        source           VARCHAR(50)    -- medication|lab|history|nlp
        suspected_icd    VARCHAR(20)
        suspected_hcc    VARCHAR(20)
        description      TEXT
        evidence         TEXT           -- JSON blob
        confidence       DECIMAL(4,3)
        status           VARCHAR(20)    -- open|accepted|dismissed
        dismissed_reason TEXT
        reviewed_by      VARCHAR(100)
        created_at       DATETIME
        updated_at       DATETIME
    """
    evidence_json = json.dumps(suspect.get("evidence") or {})
    _tenant = tenant_id or suspect.get("tenant_id")
    if not _tenant:
        raise ValueError(
            "_store_suspect called without a tenant_id — refusing to store suspect "
            "without tenant scope to prevent cross-tenant data leakage."
        )
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_suspect_conditions (
                    patient_id, measurement_year, tenant_id,
                    suspect_icd10, suspect_hcc, evidence_type,
                    evidence_detail, confidence_score, status,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, 'open',
                    NOW(), NOW()
                )
                ON DUPLICATE KEY UPDATE
                    id               = LAST_INSERT_ID(id),
                    confidence_score = GREATEST(confidence_score, VALUES(confidence_score)),
                    evidence_detail  = VALUES(evidence_detail),
                    updated_at       = NOW()
                """,
                (
                    suspect["patient_id"],
                    measurement_year or suspect.get("measurement_year") or date.today().year,
                    _tenant,
                    suspect.get("suspected_icd") or "",
                    suspect.get("suspected_hcc") or "",
                    _map_evidence_type(suspect.get("source") or "medication"),
                    evidence_json,
                    suspect.get("confidence", 0.5),
                ),
            )
            cur.execute("SELECT LAST_INSERT_ID() AS lid")
            row = cur.fetchone()
            return row["lid"] if row else None
    except Exception as exc:
        logger.error(
            "_store_suspect failed pid=%s fp=%s: %s",
            suspect.get("patient_id"), suspect.get("fingerprint"), exc,
        )
        return None


# ---------------------------------------------------------------------------
# Scan 1 – Medication signals
# ---------------------------------------------------------------------------

def scan_medications(patient_id: int, year: int | None = None) -> list[dict[str, Any]]:
    """
    Identify suspected conditions implied by a patient's active medications.

    Each prescription's drug name is matched against raf_medication_signals
    using LIKE-style substring patterns stored in drug_name_pattern.
    A suspect is emitted only when the implied ICD-10 / HCC is NOT already
    present in billing or raf_patient_hcc.

    raf_medication_signals schema:
        id                  INT
        drug_name_pattern   VARCHAR(200)   -- e.g. '%metformin%'
        rxnorm_code         VARCHAR(20)
        suspected_icd       VARCHAR(20)
        suspected_hcc       VARCHAR(20)
        description         TEXT
        confidence          DECIMAL(4,3)
    """
    medications = emr.get_medications(patient_id, year=year)
    if not medications:
        return []

    coded_icds = _coded_icd_set(patient_id, year=year)
    coded_hccs = _coded_hcc_set(patient_id, year=year)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            signals = _get_medication_signals(cur)
    except Exception as exc:
        logger.error("scan_medications: cannot load signals: %s", exc)
        return []

    for med in medications:
        drug_name = (med.get("drug") or "").lower().strip()
        rxnorm = str(med.get("rxnorm_drugcode") or "").strip()
        if not drug_name:
            continue

        for sig in signals:
            pattern = (sig.get("drug_name_pattern") or "").lower()
            # Convert SQL LIKE wildcards to a simple substring check
            clean_pattern = pattern.replace("%", "").replace("_", " ").strip()
            rx_sig = str(sig.get("rxnorm_code") or "").strip()

            rx_match = rxnorm and rx_sig and rxnorm == rx_sig
            name_match = clean_pattern and clean_pattern in drug_name
            if not (rx_match or name_match):
                continue

            icd = (sig.get("suspected_icd") or "").replace(".", "").strip().upper()
            hcc = (sig.get("suspected_hcc") or "").strip().upper()

            if icd and icd in coded_icds:
                continue
            if hcc and hcc in coded_hccs:
                continue

            fp = _suspect_fingerprint(patient_id, "medication", icd or hcc)
            suspects.append({
                "patient_id": patient_id,
                "fingerprint": fp,
                "source": "medication",
                "suspected_icd": icd,
                "suspected_hcc": hcc,
                "description": sig.get("description") or "",
                "confidence": float(sig.get("confidence") or 0.5),
                "measurement_year": year,
                "evidence": {
                    "drug_name": med.get("drug"),
                    "rxnorm": med.get("rxnorm_drugcode"),
                    "start_date": med.get("start_date"),
                    "medication_id": med.get("id"),
                    "signal_pattern": sig.get("drug_name_pattern"),
                },
            })

    logger.info("scan_medications pid=%s → %d suspects", patient_id, len(suspects))
    return suspects


# ---------------------------------------------------------------------------
# Scan 2 – Lab signals
# ---------------------------------------------------------------------------

def scan_labs(patient_id: int, year: int | None = None) -> list[dict[str, Any]]:
    """
    Identify suspected conditions from abnormal lab values.

    raf_lab_signals schema:
        id              INT
        result_code     VARCHAR(50)    -- LOINC or local order code
        result_name     VARCHAR(200)   -- partial name fallback
        operator        CHAR(2)        -- '>', '<', '>=', '<=', '='
        threshold_value DECIMAL(12,4)
        suspected_icd   VARCHAR(20)
        suspected_hcc   VARCHAR(20)
        description     TEXT
        confidence      DECIMAL(4,3)
    """
    labs = emr.get_labs(patient_id)
    if not labs:
        return []

    coded_icds = _coded_icd_set(patient_id, year=year)
    coded_hccs = _coded_hcc_set(patient_id, year=year)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            signals = _get_lab_signals(cur)
    except Exception as exc:
        logger.error("scan_labs: cannot load signals: %s", exc)
        return []

    _ops = {
        ">":  lambda v, t: v > t,
        "<":  lambda v, t: v < t,
        ">=": lambda v, t: v >= t,
        "<=": lambda v, t: v <= t,
        "=":  lambda v, t: v == t,
    }

    for lab in labs:
        result_code = (lab.get("result_code") or "").strip().upper()
        result_text = (lab.get("result_text") or "").lower()
        raw_value = lab.get("value")

        try:
            lab_value = float(str(raw_value).replace(",", ""))
        except (ValueError, TypeError):
            continue  # Non-numeric result

        for sig in signals:
            sig_code = (sig.get("result_code") or "").strip().upper()
            sig_name = (sig.get("result_name") or "").lower()

            code_match = sig_code and sig_code == result_code
            name_match = sig_name and sig_name in result_text
            if not (code_match or name_match):
                continue

            operator = (sig.get("operator") or ">").strip()
            threshold = float(sig.get("threshold_value") or 0)
            op_fn = _ops.get(operator)
            if op_fn is None or not op_fn(lab_value, threshold):
                continue

            icd = (sig.get("suspected_icd") or "").replace(".", "").strip().upper()
            hcc = (sig.get("suspected_hcc") or "").strip().upper()

            if icd and icd in coded_icds:
                continue
            if hcc and hcc in coded_hccs:
                continue

            fp = _suspect_fingerprint(patient_id, "lab", icd or hcc)
            suspects.append({
                "patient_id": patient_id,
                "fingerprint": fp,
                "source": "lab",
                "suspected_icd": icd,
                "suspected_hcc": hcc,
                "description": sig.get("description") or "",
                "confidence": float(sig.get("confidence") or 0.5),
                "measurement_year": year,
                "evidence": {
                    "result_code": lab.get("result_code"),
                    "result_text": lab.get("result_text"),
                    "value": raw_value,
                    "units": lab.get("units"),
                    "threshold": threshold,
                    "operator": operator,
                    "lab_date": lab.get("date"),
                    "lab_id": lab.get("id"),
                },
            })

    logger.info("scan_labs pid=%s → %d suspects", patient_id, len(suspects))
    return suspects


# ---------------------------------------------------------------------------
# Scan 3 – Historical HCC gap (annual recapture)
# ---------------------------------------------------------------------------

def scan_historical_hccs(
    patient_id: int,
    current_year: int = None,
) -> list[dict[str, Any]]:
    """
    Flag HCCs coded in the prior measurement year that have NOT been
    recaptured in the current year.

    CMS requires chronic conditions to be re-documented every year; a missing
    recapture is a direct RAF revenue gap.
    """
    current_year = current_year or date.today().year
    prior_year = current_year - 1
    current_hccs = _coded_hcc_set(patient_id, year=current_year)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    rph.hcc_code,
                    rph.icd_code,
                    rph.encounter_date,
                    COALESCE(rc.hcc_description, rph.hcc_code) AS description
                FROM raf_patient_hcc rph
                LEFT JOIN hcc_raf_coefficients rc
                    ON  rc.hcc_code      = rph.hcc_code
                    AND rc.model_segment = 'CNA'
                    AND rc.model_year    = %s
                WHERE rph.patient_id      = %s
                  AND rph.measurement_year = %s
                """,
                (prior_year, patient_id, prior_year),
            )
            prior_rows = cur.fetchall()
    except Exception as exc:
        logger.error("scan_historical_hccs DB error pid=%s: %s", patient_id, exc)
        return []

    for row in prior_rows:
        hcc = str(row.get("hcc_code") or "").strip().upper()
        if not hcc or hcc in current_hccs:
            continue

        encounter_date_raw = row.get("encounter_date")
        enc_date_str = (
            encounter_date_raw.isoformat()
            if hasattr(encounter_date_raw, "isoformat")
            else str(encounter_date_raw or "")
        )

        fp = _suspect_fingerprint(patient_id, "history", hcc)
        suspects.append({
            "patient_id": patient_id,
            "fingerprint": fp,
            "source": "history",
            "suspected_icd": (row.get("icd_code") or "").strip().upper(),
            "suspected_hcc": hcc,
            "description": (
                f"Annual recapture needed: {row.get('description') or hcc} "
                f"(coded {prior_year}, not yet recaptured {current_year})"
            ),
            "confidence": 0.85,
            "measurement_year": current_year,
            "evidence": {
                "prior_year": prior_year,
                "current_year": current_year,
                "prior_icd": row.get("icd_code"),
                "prior_encounter_date": enc_date_str,
            },
        })

    logger.info(
        "scan_historical_hccs pid=%s prior_year=%s → %d suspects",
        patient_id, prior_year, len(suspects),
    )
    return suspects


# ---------------------------------------------------------------------------
# Scan 4 – Note vs billing gap (Gemini NLP)
# ---------------------------------------------------------------------------

def scan_note_vs_billing(patient_id: int, year: int | None = None) -> list[dict[str, Any]]:
    """
    Compare diagnoses identified by Gemini NLP in clinical notes
    against what has actually been coded in billing.

    Reads completed raf_nlp_jobs where result_json contains an
    'identified_diagnoses' list:
        [{"icd_code": "E11.9", "hcc_code": "HCC37",
          "description": "...", "confidence": 0.9, "note_snippet": "..."}]

    Only diagnoses in notes but NOT in billing are returned as suspects.
    """
    coded_icds = _coded_icd_set(patient_id, year=year)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            if year is not None:
                cur.execute(
                    """
                    SELECT id, target_id AS encounter_id,
                           result_summary AS result_json, created_at
                    FROM raf_nlp_jobs
                    WHERE target_id IN (
                        SELECT encounter_id FROM normalized_encounters
                        WHERE patient_id = %s
                    )
                      AND target_type   = 'encounter'
                      AND status        = 'completed'
                      AND result_summary IS NOT NULL
                      AND YEAR(created_at) = %s
                    ORDER BY created_at DESC
                    """,
                    (patient_id, year),
                )
            else:
                cur.execute(
                    """
                    SELECT id, target_id AS encounter_id,
                           result_summary AS result_json, created_at
                    FROM raf_nlp_jobs
                    WHERE target_id IN (
                        SELECT encounter_id FROM normalized_encounters
                        WHERE patient_id = %s
                    )
                      AND target_type   = 'encounter'
                      AND status        = 'completed'
                      AND result_summary IS NOT NULL
                    ORDER BY created_at DESC
                    """,
                    (patient_id,),
                )
            jobs = cur.fetchall()
    except Exception as exc:
        logger.error("scan_note_vs_billing: NLP jobs query failed pid=%s: %s", patient_id, exc)
        return []

    # Lazy-load coded HCCs once
    coded_hccs: set[str] | None = None

    for job in jobs:
        raw_json = job.get("result_json") or "{}"
        try:
            result = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except json.JSONDecodeError:
            logger.warning("Malformed result_json for nlp_job id=%s", job.get("id"))
            continue

        identified = result.get("identified_diagnoses") or []
        if not isinstance(identified, list):
            continue

        for dx in identified:
            icd = (dx.get("icd_code") or "").replace(".", "").strip().upper()
            if not icd:
                continue
            if icd in coded_icds:
                continue

            hcc = (dx.get("hcc_code") or "").strip().upper()
            if hcc:
                if coded_hccs is None:
                    coded_hccs = _coded_hcc_set(patient_id, year=year)
                if hcc in coded_hccs:
                    continue

            created_raw = job.get("created_at")
            analysis_date = (
                created_raw.isoformat()
                if hasattr(created_raw, "isoformat")
                else str(created_raw or "")
            )

            fp = _suspect_fingerprint(patient_id, "nlp", icd)
            suspects.append({
                "patient_id": patient_id,
                "fingerprint": fp,
                "source": "nlp",
                "suspected_icd": icd,
                "suspected_hcc": hcc,
                "description": dx.get("description") or f"Found in clinical note – {icd}",
                "confidence": float(dx.get("confidence") or 0.6),
                "measurement_year": year,
                "evidence": {
                    "nlp_job_id": job.get("id"),
                    "encounter_id": job.get("encounter_id"),
                    "analysis_date": analysis_date,
                    "note_snippet": dx.get("note_snippet") or "",
                },
            })

    logger.info("scan_note_vs_billing pid=%s → %d suspects", patient_id, len(suspects))
    return suspects


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------

def run_full_suspect_scan(
    patient_id: int,
    year: int | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Execute all four scans, deduplicate on fingerprint (keeping highest
    confidence when same fingerprint appears in multiple scans), persist
    each suspect to raf_suspect_conditions, and return the stored list.

    *tenant_id* must be supplied so that stored rows carry the correct tenant
    scope; without it the suspects will not be visible in any tenant-filtered
    read path (dashboards, reports, insights).
    """
    all_suspects: list[dict[str, Any]] = []
    all_suspects.extend(scan_medications(patient_id, year=year))
    all_suspects.extend(scan_labs(patient_id, year=year))
    all_suspects.extend(scan_historical_hccs(patient_id, current_year=year))
    all_suspects.extend(scan_note_vs_billing(patient_id, year=year))

    # Deduplicate within this batch by fingerprint
    seen: dict[str, dict[str, Any]] = {}
    for s in all_suspects:
        fp = s["fingerprint"]
        if fp not in seen or s["confidence"] > seen[fp]["confidence"]:
            seen[fp] = s

    deduped = list(seen.values())

    stored: list[dict[str, Any]] = []
    for suspect in deduped:
        row_id = _store_suspect(suspect, tenant_id=tenant_id)
        suspect["id"] = row_id
        stored.append(suspect)

    logger.info(
        "run_full_suspect_scan pid=%s → %d raw, %d after dedup, %d stored",
        patient_id, len(all_suspects), len(deduped), len(stored),
    )
    return stored


def run_tenant_suspect_scan(
    tenant_id: str,
    year: int | None = None,
) -> dict[str, Any]:
    """
    Run ``run_full_suspect_scan`` for every patient belonging to *tenant_id*.

    Patient IDs are resolved via ``_get_all_patient_ids`` so both native
    (``patients`` table) and FHIR/REST (``emr_patient_matches``) patients are
    included automatically based on the active EMR connection type.

    Returns a summary dict::

        {
            "tenant_id": "...",
            "year": 2025,
            "patients_scanned": 42,
            "total_suspects_stored": 137,
            "errors": 0,
        }
    """
    patient_ids = _get_all_patient_ids(tenant_id)
    logger.info(
        "run_tenant_suspect_scan tenant=%s year=%s → %d patients to scan",
        tenant_id, year, len(patient_ids),
    )

    total_stored = 0
    error_count = 0
    for pid in patient_ids:
        try:
            stored = run_full_suspect_scan(pid, year=year, tenant_id=tenant_id)
            total_stored += len(stored)
        except Exception as exc:
            logger.error(
                "run_tenant_suspect_scan failed for pid=%s tenant=%s: %s",
                pid, tenant_id, exc,
            )
            error_count += 1

    summary = {
        "tenant_id": tenant_id,
        "year": year or date.today().year,
        "patients_scanned": len(patient_ids),
        "total_suspects_stored": total_stored,
        "errors": error_count,
    }
    logger.info("run_tenant_suspect_scan complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Query suspects
# ---------------------------------------------------------------------------

def save_suspects_from_analysis(
    patient_id: int,
    encounter_id: int | None,
    suspect_conditions: list[dict[str, Any]],
    tenant_id: str | None = None,
) -> int:
    """
    Persist suspect conditions returned by the skill pipeline.

    Each item in *suspect_conditions* is expected to have at least:
        condition, icd10, confidence, evidence_type, evidence

    *tenant_id* should be provided so that stored rows carry the correct
    tenant scope for all downstream tenant-filtered queries.

    Returns the number of suspects successfully stored.
    """
    stored = 0
    for sc in suspect_conditions:
        icd = (sc.get("icd10") or sc.get("suspected_icd") or "").strip()
        hcc = (sc.get("hcc") or sc.get("suspected_hcc") or "").strip()
        description = sc.get("condition") or sc.get("description") or ""
        confidence = float(sc.get("confidence") or 0.6)
        source = sc.get("evidence_type") or sc.get("source") or "nlp"

        if not icd and not description:
            continue

        fp = _suspect_fingerprint(patient_id, source, icd or description)
        evidence = {
            "encounter_id": encounter_id,
            "evidence_text": sc.get("evidence") or "",
            "source": source,
        }
        row_id = _store_suspect(
            {
                "patient_id": patient_id,
                "fingerprint": fp,
                "source": source,
                "suspected_icd": icd,
                "suspected_hcc": hcc,
                "description": description,
                "confidence": confidence,
                "evidence": evidence,
            },
            tenant_id=tenant_id,
        )
        if row_id is not None:
            stored += 1

    logger.info(
        "save_suspects_from_analysis pid=%s enc=%s → %d/%d stored",
        patient_id, encounter_id, stored, len(suspect_conditions),
    )
    return stored


def get_suspects_for_patient(
    patient_id: int,
    year: int | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return all suspect conditions for a patient, sorted by confidence desc.
    Reads directly from raf_suspect_conditions.

    When ``year`` is provided the query is filtered at the SQL level using
    ``measurement_year = %s``, avoiding a full table scan followed by
    in-memory filtering.  When ``tenant_id`` is provided the result is
    scoped to that tenant.
    """
    try:
        with raf_cursor() as cur:
            sql = """
                SELECT *
                FROM raf_suspect_conditions
                WHERE patient_id = %s
            """
            params: list = [patient_id]
            if year is not None:
                sql += " AND measurement_year = %s"
                params.append(year)
            if tenant_id is not None:
                sql += " AND tenant_id = %s"
                params.append(tenant_id)
            sql += " ORDER BY confidence_score DESC, created_at DESC"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [_serialize_suspect(r) for r in rows]
    except Exception as exc:
        logger.error("get_suspects_for_patient pid=%s: %s", patient_id, exc)
        return []


def get_all_open_suspects(
    limit: int = 1000,
    offset: int = 0,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return all open (unreviewed) suspects across all patients, sorted by
    confidence descending.  Patient name is joined from OpenEMR when available.

    Pagination is performed at the DB level via LIMIT/OFFSET to avoid loading
    the entire suspect table into memory.

    *tenant_id* must be supplied to enforce tenant isolation; without it the
    query would return suspects for every tenant in the database.
    """
    if not tenant_id:
        logger.warning("get_all_open_suspects called without tenant_id — returning empty list")
        return []

    # Collect the valid patient ID set for this tenant, respecting the active
    # connection type (native patients table vs FHIR/REST emr_patient_matches).
    try:
        valid_pids = _get_all_patient_ids(tenant_id)
    except Exception as exc:
        logger.error("get_all_open_suspects: _get_all_patient_ids failed: %s", exc)
        return []

    if not valid_pids:
        return []

    pid_placeholders = ",".join(["%s"] * len(valid_pids))

    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT sc.*
                FROM raf_suspect_conditions sc
                WHERE sc.status = 'open'
                  AND sc.tenant_id = %s
                  AND sc.patient_id IN ({pid_placeholders})
                ORDER BY sc.confidence_score DESC, sc.patient_id ASC, sc.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (tenant_id, *valid_pids, int(limit), int(offset)),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_all_open_suspects failed: %s", exc)
        return []

    suspects = [_serialize_suspect(r) for r in rows]

    # Enrich with patient names.  For native patients the name comes from the
    # patients table; for FHIR patients it comes from emr_patient_matches
    # (fname/lname columns).  We try both and merge.
    pids = sorted({int(s["patient_id"]) for s in suspects if s.get("patient_id") is not None})
    name_map: dict[int, str] = {}
    if pids:
        placeholders = ",".join(["%s"] * len(pids))
        # Native patients table
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"SELECT id, first_name, last_name FROM patients WHERE id IN ({placeholders})",
                    tuple(pids),
                )
                for row in cur.fetchall():
                    first = (row.get("first_name") or "").strip()
                    last = (row.get("last_name") or "").strip()
                    full = f"{first} {last}".strip()
                    if full:
                        name_map[int(row["id"])] = full
        except Exception as exc:
            logger.warning("get_all_open_suspects native name enrichment failed: %s", exc)

        # FHIR/EMR patients (fills gaps not covered by native table)
        remaining = [p for p in pids if p not in name_map]
        if remaining:
            rem_placeholders = ",".join(["%s"] * len(remaining))
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT epm.emr_pid  AS id,
                               epm.first_name,
                               epm.last_name
                        FROM emr_patient_matches epm
                        JOIN emr_connections ec ON ec.id = epm.connection_id
                        WHERE ec.tenant_id = %s
                          AND epm.emr_pid IN ({rem_placeholders})
                        """,
                        (tenant_id, *remaining),
                    )
                    for row in cur.fetchall():
                        first = (row.get("first_name") or "").strip()
                        last = (row.get("last_name") or "").strip()
                        full = f"{first} {last}".strip()
                        if full:
                            name_map[int(row["id"])] = full
            except Exception as exc:
                logger.warning("get_all_open_suspects FHIR name enrichment failed: %s", exc)

    for s in suspects:
        pid = s.get("patient_id")
        if pid is not None and int(pid) in name_map:
            s["patient_name"] = name_map[int(pid)]

    return suspects


# ---------------------------------------------------------------------------
# Accept / dismiss workflows
# ---------------------------------------------------------------------------

def accept_suspect(suspect_id: int, reviewed_by: str, tenant_id: str | None = None) -> dict[str, Any]:
    """
    Mark a suspect as accepted (provider agrees the condition should be coded).
    Also inserts the accepted HCC into raf_patient_hcc and recalculates RAF score.
    Returns the updated record.
    """
    if not tenant_id:
        raise ValueError("accept_suspect requires tenant_id to prevent cross-tenant mutation")
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_suspect_conditions
                SET status      = 'accepted',
                    reviewed_by = %s,
                    updated_at  = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                """,
                (reviewed_by, suspect_id, tenant_id),
            )
            cur.execute(
                "SELECT * FROM raf_suspect_conditions WHERE id = %s AND tenant_id = %s",
                (suspect_id, tenant_id),
            )
            row = cur.fetchone()

            if row and row.get("suspect_hcc"):
                # Insert accepted HCC into raf_patient_hcc
                from datetime import date as _date
                _year = _date.today().year
                _pid = row["patient_id"]
                _hcc = row["suspect_hcc"]
                _icd = row.get("suspect_icd10") or ""
                _desc = row.get("description") or ""
                _tenant = row.get("tenant_id")
                if not _tenant:
                    raise ValueError(
                        f"accept_suspect: suspect {suspect_id} has no tenant_id in the database — "
                        "cannot safely promote HCC without tenant scope."
                    )

                # HCC coefficient lookup from database
                # Determine model_segment from patient's most recent RAF score if available
                cur.execute(
                    "SELECT model_segment FROM raf_scores WHERE patient_id = %s AND measurement_year = %s ORDER BY updated_at DESC LIMIT 1",
                    (_pid, _year),
                )
                _seg_row = cur.fetchone()
                _model_segment = (_seg_row.get("model_segment") or "CNA") if _seg_row else "CNA"

                cur.execute(
                    "SELECT coefficient FROM hcc_raf_coefficients WHERE hcc_code = %s AND model_segment = %s LIMIT 1",
                    (_hcc, _model_segment),
                )
                _coeff_row = cur.fetchone()
                if _coeff_row:
                    _coeff = float(_coeff_row["coefficient"])
                else:
                    _coeff = 0.100
                    logger.warning(
                        "accept_suspect: no coefficient found in hcc_raf_coefficients for "
                        "hcc_code=%s model_segment=%s — using fallback 0.100",
                        _hcc, _model_segment,
                    )

                # Check if already exists
                cur.execute(
                    "SELECT id FROM raf_patient_hcc WHERE patient_id = %s AND hcc_code = %s AND measurement_year = %s AND tenant_id = %s",
                    (_pid, _hcc, _year, _tenant),
                )
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO raf_patient_hcc
                            (patient_id, measurement_year, tenant_id, hcc_code, hcc_description,
                             icd10_codes, icd10_code, icd_code, raf_coefficient, raf_weight,
                             meat_status, is_trumped, source, source_encounter_ids, model_version,
                             created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'missing', 0, 'suspect_accepted', '[]', 'V28', NOW(), NOW())
                    """, (_pid, _year, _tenant, _hcc, _desc,
                          json.dumps([_icd]), _icd, _icd, _coeff, _coeff))
                    logger.info("Inserted HCC %s into raf_patient_hcc for patient %s", _hcc, _pid)

                # Apply HCC hierarchy so subordinate HCCs are correctly trumped
                cur.execute(
                    "SELECT id, hcc_code, raf_coefficient FROM raf_patient_hcc "
                    "WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s",
                    (_pid, _year, _tenant),
                )
                all_hcc_rows = cur.fetchall()
                apply_hierarchy(all_hcc_rows, model_version="V28")
                for h in all_hcc_rows:
                    cur.execute(
                        "UPDATE raf_patient_hcc SET is_trumped = %s, trumped_by_hcc = %s WHERE id = %s",
                        (1 if h.get("is_trumped") else 0, h.get("trumped_by_hcc"), h["id"]),
                    )
                logger.info(
                    "Hierarchy applied for patient %s year %s: %d HCC(s) evaluated",
                    _pid, _year, len(all_hcc_rows),
                )

                # Recalculate RAF score
                cur.execute(
                    "SELECT hcc_code, raf_coefficient FROM raf_patient_hcc WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s AND (is_trumped = 0 OR is_trumped IS NULL)",
                    (_pid, _year, _tenant),
                )
                all_hccs = cur.fetchall()
                new_disease_score = sum(float(h.get("raf_coefficient") or 0) for h in all_hccs)
                new_hcc_count = len(all_hccs)

                cur.execute(
                    """UPDATE raf_scores
                       SET disease_score = %s, hcc_count = %s,
                           final_raf = demographic_score + %s + interaction_score,
                           updated_at = NOW()
                       WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s""",
                    (new_disease_score, new_hcc_count, new_disease_score, _pid, _year, _tenant),
                )
                logger.info("Recalculated RAF for patient %s: disease_score=%.3f, hcc_count=%d",
                           _pid, new_disease_score, new_hcc_count)

                # Push to EMR
                try:
                    emr.push_medical_problem(_pid, _desc, _icd)
                except Exception as e:
                    logger.warning("Failed to push suspect %s to EMR for patient %s: %s", suspect_id, _pid, e)

        if not row:
            raise ValueError(f"Suspect {suspect_id} not found")
        try:
            from app.services import raf_inbox
            raf_inbox.mark_dirty(pid=int(_pid), tenant_id=_tenant, reason="suspect")
        except Exception:
            logger.debug("raf_inbox.mark_dirty failed — non-fatal", exc_info=True)
        logger.info("Suspect %s accepted by %s", suspect_id, reviewed_by)
        return _serialize_suspect(row)
    except Exception as exc:
        logger.error("accept_suspect failed id=%s: %s", suspect_id, exc)
        raise


def dismiss_suspect(
    suspect_id: int,
    reason: str,
    reviewed_by: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Mark a suspect as dismissed with a documented reason.
    Returns the updated record.
    """
    if not tenant_id:
        raise ValueError("dismiss_suspect requires tenant_id to prevent cross-tenant mutation")
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_suspect_conditions
                SET status           = 'dismissed',
                    dismissed_reason = %s,
                    reviewed_by      = %s,
                    updated_at       = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                """,
                (reason, reviewed_by, suspect_id, tenant_id),
            )
            cur.execute(
                "SELECT * FROM raf_suspect_conditions WHERE id = %s AND tenant_id = %s",
                (suspect_id, tenant_id),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Suspect {suspect_id} not found")
        try:
            from app.services import raf_inbox
            raf_inbox.mark_dirty(pid=int(row["patient_id"]), tenant_id=tenant_id, reason="suspect")
        except Exception:
            logger.debug("raf_inbox.mark_dirty failed — non-fatal", exc_info=True)
        logger.info("Suspect %s dismissed by %s: %s", suspect_id, reviewed_by, reason)
        return _serialize_suspect(row)
    except Exception as exc:
        logger.error("dismiss_suspect failed id=%s: %s", suspect_id, exc)
        raise


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------

def _serialize_suspect(row: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise date/Decimal types and parse stored evidence JSON."""
    if not row:
        return {}
    result: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            result[k] = float(v)
        else:
            result[k] = v
    # Parse evidence if still a JSON string
    if isinstance(result.get("evidence"), str):
        try:
            result["evidence"] = json.loads(result["evidence"])
        except json.JSONDecodeError:
            pass
    return result
