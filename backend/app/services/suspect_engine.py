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
from datetime import date
from typing import Any

from app.db import raf_cursor
from app.services import openemr_connector as emr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coded_icd_set(patient_id: int) -> set[str]:
    """Return the normalised set of ICD-10 codes already in billing."""
    codes = emr.get_billing_codes(patient_id)
    return {
        (r.get("code") or "").replace(".", "").strip().upper()
        for r in codes
        if r.get("code")
    }


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
        return {r["hcc_code"].strip().upper() for r in rows if r.get("hcc_code")}
    except Exception as exc:
        logger.error("_coded_hcc_set failed pid=%s: %s", patient_id, exc)
        return set()


def _suspect_fingerprint(patient_id: int, source: str, code: str) -> str:
    """Stable MD5 dedup key for a suspect (patient + source + code)."""
    raw = f"{patient_id}|{source}|{code}".lower()
    return hashlib.md5(raw.encode()).hexdigest()


def _store_suspect(suspect: dict[str, Any]) -> int | None:
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
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_suspect_conditions (
                    patient_id, fingerprint, source,
                    suspected_icd, suspected_hcc, description,
                    evidence, confidence, status,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, 'open',
                    NOW(), NOW()
                )
                ON DUPLICATE KEY UPDATE
                    confidence = GREATEST(confidence, VALUES(confidence)),
                    evidence   = VALUES(evidence),
                    updated_at = NOW()
                """,
                (
                    suspect["patient_id"],
                    suspect["fingerprint"],
                    suspect["source"],
                    suspect.get("suspected_icd") or "",
                    suspect.get("suspected_hcc") or "",
                    suspect.get("description") or "",
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

def scan_medications(patient_id: int) -> list[dict[str, Any]]:
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
    medications = emr.get_medications(patient_id)
    if not medications:
        return []

    coded_icds = _coded_icd_set(patient_id)
    coded_hccs = _coded_hcc_set(patient_id)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            cur.execute("SELECT * FROM raf_medication_signals")
            signals = cur.fetchall()
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

def scan_labs(patient_id: int) -> list[dict[str, Any]]:
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

    coded_icds = _coded_icd_set(patient_id)
    coded_hccs = _coded_hcc_set(patient_id)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            cur.execute("SELECT * FROM raf_lab_signals")
            signals = cur.fetchall()
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
    current_year: int = 2026,
) -> list[dict[str, Any]]:
    """
    Flag HCCs coded in the prior measurement year that have NOT been
    recaptured in the current year.

    CMS requires chronic conditions to be re-documented every year; a missing
    recapture is a direct RAF revenue gap.
    """
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
                    AND rc.year          = 2024
                WHERE rph.patient_id      = %s
                  AND rph.measurement_year = %s
                """,
                (patient_id, prior_year),
            )
            prior_rows = cur.fetchall()
    except Exception as exc:
        logger.error("scan_historical_hccs DB error pid=%s: %s", patient_id, exc)
        return []

    for row in prior_rows:
        hcc = (row.get("hcc_code") or "").strip().upper()
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

def scan_note_vs_billing(patient_id: int) -> list[dict[str, Any]]:
    """
    Compare diagnoses identified by Gemini NLP in clinical notes
    against what has actually been coded in billing.

    Reads completed raf_nlp_jobs where result_json contains an
    'identified_diagnoses' list:
        [{"icd_code": "E11.9", "hcc_code": "HCC37",
          "description": "...", "confidence": 0.9, "note_snippet": "..."}]

    Only diagnoses in notes but NOT in billing are returned as suspects.
    """
    coded_icds = _coded_icd_set(patient_id)
    suspects: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, encounter_id, result_json, created_at
                FROM raf_nlp_jobs
                WHERE patient_id = %s
                  AND status      = 'completed'
                  AND result_json IS NOT NULL
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
                    coded_hccs = _coded_hcc_set(patient_id)
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

def run_full_suspect_scan(patient_id: int) -> list[dict[str, Any]]:
    """
    Execute all four scans, deduplicate on fingerprint (keeping highest
    confidence when same fingerprint appears in multiple scans), persist
    each suspect to raf_suspect_conditions, and return the stored list.
    """
    all_suspects: list[dict[str, Any]] = []
    all_suspects.extend(scan_medications(patient_id))
    all_suspects.extend(scan_labs(patient_id))
    all_suspects.extend(scan_historical_hccs(patient_id))
    all_suspects.extend(scan_note_vs_billing(patient_id))

    # Deduplicate within this batch by fingerprint
    seen: dict[str, dict[str, Any]] = {}
    for s in all_suspects:
        fp = s["fingerprint"]
        if fp not in seen or s["confidence"] > seen[fp]["confidence"]:
            seen[fp] = s

    deduped = list(seen.values())

    stored: list[dict[str, Any]] = []
    for suspect in deduped:
        row_id = _store_suspect(suspect)
        suspect["id"] = row_id
        stored.append(suspect)

    logger.info(
        "run_full_suspect_scan pid=%s → %d raw, %d after dedup, %d stored",
        patient_id, len(all_suspects), len(deduped), len(stored),
    )
    return stored


# ---------------------------------------------------------------------------
# Query suspects
# ---------------------------------------------------------------------------

def save_suspects_from_analysis(
    patient_id: int,
    encounter_id: int | None,
    suspect_conditions: list[dict[str, Any]],
) -> int:
    """
    Persist suspect conditions returned by the skill pipeline.

    Each item in *suspect_conditions* is expected to have at least:
        condition, icd10, confidence, evidence_type, evidence

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
        row_id = _store_suspect({
            "patient_id": patient_id,
            "fingerprint": fp,
            "source": source,
            "suspected_icd": icd,
            "suspected_hcc": hcc,
            "description": description,
            "confidence": confidence,
            "evidence": evidence,
        })
        if row_id is not None:
            stored += 1

    logger.info(
        "save_suspects_from_analysis pid=%s enc=%s → %d/%d stored",
        patient_id, encounter_id, stored, len(suspect_conditions),
    )
    return stored


def get_suspects_for_patient(patient_id: int) -> list[dict[str, Any]]:
    """
    Return all suspect conditions for a patient, sorted by confidence desc.
    Reads directly from raf_suspect_conditions.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM raf_suspect_conditions
                WHERE patient_id = %s
                ORDER BY confidence_score DESC, created_at DESC
                """,
                (patient_id,),
            )
            rows = cur.fetchall()
        return [_serialize_suspect(r) for r in rows]
    except Exception as exc:
        logger.error("get_suspects_for_patient pid=%s: %s", patient_id, exc)
        return []


def get_all_open_suspects() -> list[dict[str, Any]]:
    """
    Return all open (unreviewed) suspects across all patients, sorted by
    confidence descending.  Patient name is joined from OpenEMR when available.
    """
    sql_joined = """
        SELECT
            sc.*,
            CONCAT(pd.fname, ' ', pd.lname) AS patient_name
        FROM raf_suspect_conditions sc
        LEFT JOIN openemr.patient_data pd ON pd.pid = sc.patient_id
        WHERE sc.status = 'open'
        ORDER BY sc.confidence DESC, sc.patient_id ASC, sc.created_at DESC
    """
    sql_plain = """
        SELECT *
        FROM raf_suspect_conditions
        WHERE status = 'open'
        ORDER BY confidence_score DESC, patient_id ASC, created_at DESC
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql_joined)
            rows = cur.fetchall()
        return [_serialize_suspect(r) for r in rows]
    except Exception as exc:
        logger.warning(
            "get_all_open_suspects cross-DB join failed (%s); retrying without join", exc
        )
    try:
        with raf_cursor() as cur:
            cur.execute(sql_plain)
            rows = cur.fetchall()
        return [_serialize_suspect(r) for r in rows]
    except Exception as exc2:
        logger.error("get_all_open_suspects failed: %s", exc2)
        return []


# ---------------------------------------------------------------------------
# Accept / dismiss workflows
# ---------------------------------------------------------------------------

def accept_suspect(suspect_id: int, reviewed_by: str) -> dict[str, Any]:
    """
    Mark a suspect as accepted (provider agrees the condition should be coded).
    Returns the updated record.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_suspect_conditions
                SET status      = 'accepted',
                    reviewed_by = %s,
                    updated_at  = NOW()
                WHERE id = %s
                """,
                (reviewed_by, suspect_id),
            )
            cur.execute(
                "SELECT * FROM raf_suspect_conditions WHERE id = %s",
                (suspect_id,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Suspect {suspect_id} not found")
        logger.info("Suspect %s accepted by %s", suspect_id, reviewed_by)
        return _serialize_suspect(row)
    except Exception as exc:
        logger.error("accept_suspect failed id=%s: %s", suspect_id, exc)
        raise


def dismiss_suspect(
    suspect_id: int,
    reason: str,
    reviewed_by: str,
) -> dict[str, Any]:
    """
    Mark a suspect as dismissed with a documented reason.
    Returns the updated record.
    """
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
                """,
                (reason, reviewed_by, suspect_id),
            )
            cur.execute(
                "SELECT * FROM raf_suspect_conditions WHERE id = %s",
                (suspect_id,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Suspect {suspect_id} not found")
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
