"""AI analysis gating: eligibility filter + per-patient daily rate limit.

Two responsibilities:

1. ``get_eligible_patients`` — returns the set of patient IDs whose
   primary record (``patients``) OR any child record
   (``form_clinical_notes``, ``fhir_observations``, ``fhir_conditions``,
   ``fhir_medications``, ``fhir_encounters``) has been updated at or
   after the configured cutoff date.

2. ``can_run_analysis`` + ``record_run_start``/``record_run_finish`` —
   hard per-patient daily cap (default 2 runs/calendar day UTC) using
   the ``ai_analysis_runs`` table (migration 014).

The cutoff date and cap are read from ``system_config`` via
``config_service.get_config`` (keys defined by Agent 2 / migration 013:
``ai_analysis_cutoff_date`` and ``max_analyses_per_patient_per_day``).

This module deliberately does NOT orchestrate the pipeline, call the
LLM, or mutate analysis outputs. It only decides who is eligible and
whether a run may proceed.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config (with safe defaults if config_service or keys are missing)
# ---------------------------------------------------------------------------

_DEFAULT_CUTOFF_DATE = date(2026, 4, 15)
_DEFAULT_MAX_RUNS_PER_DAY = 2

_CFG_KEY_CUTOFF = "ai_analysis_cutoff_date"
_CFG_KEY_MAX_RUNS = "max_analyses_per_patient_per_day"


def _get_config(key: str, tenant_id: Optional[str] = None) -> Optional[str]:
    """Best-effort read from config_service; returns None on any failure.

    Import is deferred so this module works even while Agent 2 is still
    shipping ``config_service``.
    """
    try:
        from app.services import config_service  # type: ignore

        return config_service.get_config(key, tenant_id=tenant_id)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — config is optional at import time
        # Fall back to reading system_config directly.
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM system_config "
                    "WHERE config_key = %s AND (tenant_id = %s OR tenant_id IS NULL) "
                    "ORDER BY tenant_id IS NULL ASC LIMIT 1",
                    (key, tenant_id),
                )
                row = cur.fetchone()
                if row:
                    return row["config_value"] if isinstance(row, dict) else row[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("system_config lookup failed for %s: %s", key, exc)
    return None


def _resolve_cutoff(tenant_id: Optional[str], override: Optional[date]) -> date:
    if override is not None:
        return override
    raw = _get_config(_CFG_KEY_CUTOFF, tenant_id)
    if raw:
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except ValueError:
            logger.warning("Invalid %s=%r; using default", _CFG_KEY_CUTOFF, raw)
    return _DEFAULT_CUTOFF_DATE


def _resolve_max_runs(tenant_id: Optional[str]) -> int:
    raw = _get_config(_CFG_KEY_MAX_RUNS, tenant_id)
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            logger.warning("Invalid %s=%r; using default", _CFG_KEY_MAX_RUNS, raw)
    return _DEFAULT_MAX_RUNS_PER_DAY


# ---------------------------------------------------------------------------
# Eligibility filter
# ---------------------------------------------------------------------------

# FHIR child tables live in the RAF DB and link by fhir_patient_id (string).
# We map fhir_patient_id → OpenEMR pid via emr_patient_matches when present;
# otherwise we fall back to treating fhir_patient_id as the patient key.
_FHIR_CHILD_TABLES = (
    "fhir_observations",
    "fhir_conditions",
    "fhir_medications",
    "fhir_encounters",
)


def get_eligible_patients(
    tenant_id: str,
    cutoff_date: Optional[date] = None,
) -> list[str]:
    """Return patient IDs (as strings) eligible for AI analysis.

    A patient is eligible if:
      - ``patients.updated_at >= cutoff_date`` (OpenEMR), OR
      - any child record (clinical notes / FHIR obs / conditions /
        medications / encounters) has ``updated_at >= cutoff_date``.

    Patient IDs are returned as strings (OpenEMR ``pid`` cast to str).
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    cutoff = _resolve_cutoff(tenant_id, cutoff_date)
    cutoff_dt = datetime.combine(cutoff, datetime.min.time())

    eligible: set[str] = set()

    # 1) OpenEMR-side: patients + form_clinical_notes.
    #    OpenEMR uses `date` as the default last-modified timestamp on
    #    many legacy tables; we try `updated_at` first and fall back.
    with openemr_cursor(tenant_id=tenant_id) as cur:
        for sql in (
            "SELECT pid FROM patient_data WHERE updated_at >= %s",
            "SELECT pid FROM patient_data WHERE date >= %s",
        ):
            try:
                cur.execute(sql, (cutoff_dt,))
                eligible.update(str(r["pid"]) for r in cur.fetchall() if r.get("pid") is not None)
                break
            except Exception as exc:  # noqa: BLE001 — column variant
                logger.debug("patient_data query variant failed: %s", exc)

        for sql in (
            "SELECT DISTINCT pid FROM form_clinical_notes WHERE updated_at >= %s",
            "SELECT DISTINCT pid FROM form_clinical_notes WHERE date >= %s",
        ):
            try:
                cur.execute(sql, (cutoff_dt,))
                eligible.update(str(r["pid"]) for r in cur.fetchall() if r.get("pid") is not None)
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("form_clinical_notes query variant failed: %s", exc)

    # 2) RAF-side: fhir_* child tables — collect changed fhir_patient_ids,
    #    then translate to local pid via emr_patient_matches.
    changed_fhir_ids: set[str] = set()
    with raf_cursor() as cur:
        for tbl in _FHIR_CHILD_TABLES:
            try:
                cur.execute(
                    f"SELECT DISTINCT fhir_patient_id FROM {tbl} "
                    f"WHERE updated_at >= %s AND fhir_patient_id IS NOT NULL",
                    (cutoff_dt,),
                )
                changed_fhir_ids.update(
                    r["fhir_patient_id"] if isinstance(r, dict) else r[0]
                    for r in cur.fetchall()
                )
            except Exception as exc:  # noqa: BLE001 — table may not exist yet
                logger.debug("%s not queryable for eligibility: %s", tbl, exc)

        if changed_fhir_ids:
            try:
                placeholders = ",".join(["%s"] * len(changed_fhir_ids))
                cur.execute(
                    f"SELECT DISTINCT local_pid, fhir_patient_id "
                    f"FROM emr_patient_matches "
                    f"WHERE tenant_id = %s AND fhir_patient_id IN ({placeholders})",
                    (tenant_id, *changed_fhir_ids),
                )
                matched = {
                    (r["fhir_patient_id"] if isinstance(r, dict) else r[1]):
                        (r["local_pid"] if isinstance(r, dict) else r[0])
                    for r in cur.fetchall()
                }
                for fhir_id in changed_fhir_ids:
                    pid = matched.get(fhir_id)
                    eligible.add(str(pid) if pid is not None else str(fhir_id))
            except Exception as exc:  # noqa: BLE001
                logger.debug("emr_patient_matches lookup failed: %s", exc)
                # Fallback: use fhir ids directly as patient ids.
                eligible.update(str(fid) for fid in changed_fhir_ids)

    return sorted(eligible)


# ---------------------------------------------------------------------------
# Per-patient daily rate limiter
# ---------------------------------------------------------------------------


def _utc_today_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = datetime(now.year, now.month, now.day)
    end = datetime(now.year, now.month, now.day, 23, 59, 59, 999_999)
    return start, end


def _count_runs_today(cur, tenant_id: str, patient_id: str) -> int:
    start, end = _utc_today_bounds()
    cur.execute(
        "SELECT COUNT(*) AS c FROM ai_analysis_runs "
        "WHERE tenant_id = %s AND patient_id = %s "
        "AND started_at >= %s AND started_at <= %s",
        (tenant_id, str(patient_id), start, end),
    )
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"] if isinstance(row, dict) else row[0])


def can_run_analysis(patient_id: str, tenant_id: str) -> bool:
    """Return True iff this patient has not yet hit today's cap."""
    if not patient_id or not tenant_id:
        raise ValueError("patient_id and tenant_id are required")
    max_runs = _resolve_max_runs(tenant_id)
    with raf_cursor() as cur:
        return _count_runs_today(cur, tenant_id, str(patient_id)) < max_runs


def record_run_start(
    patient_id: str,
    tenant_id: str,
    trigger_reason: Optional[str] = None,
) -> int:
    """Insert a new ai_analysis_runs row with status='running'.

    Returns the inserted row id. Does NOT re-check the cap — callers
    must call ``can_run_analysis`` first (cheap read) and then this
    (write). Keeping the two steps separate lets the orchestrator log
    its own denial reasons and avoid a transaction spanning the whole
    pipeline.
    """
    if not patient_id or not tenant_id:
        raise ValueError("patient_id and tenant_id are required")
    with raf_cursor() as cur:
        cur.execute(
            "INSERT INTO ai_analysis_runs "
            "(patient_id, tenant_id, started_at, status, trigger_reason) "
            "VALUES (%s, %s, %s, 'running', %s)",
            (str(patient_id), tenant_id, datetime.utcnow(), trigger_reason),
        )
        return int(cur.lastrowid)


def record_run_finish(
    run_id: int,
    status: str = "success",
) -> None:
    """Mark a previously-started run as finished.

    ``status`` is one of ``"success"`` or ``"failed"``.
    """
    if status not in ("success", "failed"):
        raise ValueError(f"invalid status: {status!r}")
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE ai_analysis_runs "
            "SET finished_at = %s, status = %s "
            "WHERE id = %s",
            (datetime.utcnow(), status, int(run_id)),
        )


__all__ = [
    "get_eligible_patients",
    "can_run_analysis",
    "record_run_start",
    "record_run_finish",
]
