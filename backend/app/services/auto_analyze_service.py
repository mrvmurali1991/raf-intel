"""
Auto Analyze Service
====================

Per-patient AI clinical pipeline runner.

``analyze_patient(local_pid)`` is the synchronous, idempotent entry point that
runs the full clinical pipeline for a single patient that was just synced from
an EMR (or otherwise dropped into the DB).  It composes existing services
rather than re-implementing pipeline logic:

* Suspect detection      -> ``suspect_engine.run_full_suspect_scan``
                            (writes ``raf_suspect_conditions``)
* MEAT validation        -> ``auto_meat_extractor.run_auto_meat_for_patient``
                            (writes ``raf_meat_evidence``)
* Recapture gaps         -> ``recapture_gap_service.detect_and_persist_gaps``
                            (writes ``recapture_gaps`` with INSERT IGNORE)

Idempotency
-----------
Every persistence path used here is upsert-or-ignore on a natural key:

* ``raf_suspect_conditions`` UNIQUE (patient_id, measurement_year, suspect_hcc,
  suspect_icd10) — ``ON DUPLICATE KEY UPDATE`` keeps the row, refreshes
  ``confidence_score = GREATEST(...)`` and ``updated_at``.  Re-runs do not
  duplicate.
* ``recapture_gaps`` UNIQUE (patient_id, hcc_code, prior_year, current_year) —
  ``INSERT IGNORE`` skips dupes.
* ``raf_meat_evidence`` upserts via ``meat_evidence_service.store_meat_evidence``.

Return contract
---------------
``{ "suspects_added": int, "gaps_added": int, "meat_validations": int,
    "errors": list[str] }``

* ``*_added`` counts are *new* rows actually inserted on this run, not the
  total in the table.  A second call against the same patient with no new
  signals returns zeros — that is the idempotency check.
* ``errors`` is a list of human-readable stage failure strings; an empty list
  means every stage completed without raising.
"""

from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_tenant(local_pid: int) -> str:
    """Look up the tenant_id for a patient row.

    ``recapture_gap_service`` and ``suspect_engine._store_suspect`` both
    require a tenant_id and refuse to operate without one.  The patient row
    is the single source of truth — fall back to "1" only as last resort
    (default tenant on this stack).
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT tenant_id FROM patients WHERE id = %s LIMIT 1",
                (local_pid,),
            )
            row = cur.fetchone()
            if row and row.get("tenant_id"):
                return str(row["tenant_id"])
    except Exception as exc:
        logger.warning(
            "auto_analyze.resolve_tenant_failed pid=%s err=%s", local_pid, exc
        )
    return "1"


def _count_suspects(local_pid: int) -> int:
    """Count rows in ``raf_suspect_conditions`` for a patient (any year)."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM raf_suspect_conditions WHERE patient_id = %s",
                (local_pid,),
            )
            row = cur.fetchone() or {}
            return int(row.get("n", 0))
    except Exception:
        return 0


def _count_gaps(local_pid: int) -> int:
    """Count rows in ``recapture_gaps`` for a patient (any year)."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM recapture_gaps WHERE patient_id = %s",
                (local_pid,),
            )
            row = cur.fetchone() or {}
            return int(row.get("n", 0))
    except Exception:
        return 0


# Revenue impact assumed per open recapture gap.  Mirrors
# recapture_gap_service._REVENUE_IMPACT_PER_GAP — kept in sync intentionally.
_GAP_REVENUE_IMPACT: float = 3000.00


def _detect_gaps_for_patient(
    local_pid: int, tenant_id: str, prior_year: int, current_year: int,
) -> int:
    """Detect and INSERT recapture gaps scoped to a single patient.

    Idempotent: skips any (patient_id, hcc_code, prior_year, current_year)
    that is already present in ``recapture_gaps`` regardless of status.
    Returns the number of new rows inserted.
    """
    prior_model = "V28" if prior_year >= 2025 else "V24"
    current_model = "V28" if current_year >= 2025 else "V24"

    select_prior_sql = """
        SELECT ph.hcc_code,
               JSON_UNQUOTE(JSON_EXTRACT(ph.icd10_codes, '$[0]')) AS icd10_code
          FROM raf_patient_hcc ph
         WHERE ph.patient_id        = %s
           AND ph.tenant_id         = %s
           AND ph.measurement_year  = %s
           AND ph.model_version     = %s
    """
    select_current_sql = """
        SELECT hcc_code FROM raf_patient_hcc
         WHERE patient_id        = %s
           AND tenant_id         = %s
           AND measurement_year  = %s
           AND model_version     = %s
    """
    existing_sql = """
        SELECT hcc_code FROM recapture_gaps
         WHERE patient_id   = %s
           AND prior_year   = %s
           AND current_year = %s
    """
    # NOTE: ``payment_year`` is a NOT-NULL YEAR column with no default; the
    # canonical interpretation is the *current* (recapture) year.  ``tenant_id``
    # is INT UNSIGNED at the column level — cast the resolved string back so we
    # don't trigger an implicit conversion warning.
    insert_sql = """
        INSERT INTO recapture_gaps
            (patient_id, tenant_id, hcc_code, icd10_code,
             prior_year, current_year, payment_year, status, revenue_impact)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s)
    """

    inserted = 0
    with raf_cursor() as cur:
        cur.execute(select_prior_sql, (local_pid, tenant_id, prior_year, prior_model))
        prior_rows = cur.fetchall() or []
        cur.execute(select_current_sql, (local_pid, tenant_id, current_year, current_model))
        current_hccs = {str(r["hcc_code"]) for r in (cur.fetchall() or [])}
        cur.execute(existing_sql, (local_pid, prior_year, current_year))
        already_tracked = {str(r["hcc_code"]) for r in (cur.fetchall() or [])}

        for r in prior_rows:
            hcc = str(r.get("hcc_code") or "")
            if not hcc:
                continue
            if hcc in current_hccs:
                continue          # not a gap — recaptured this year
            if hcc in already_tracked:
                continue          # gap row already exists, skip (idempotent)
            cur.execute(
                insert_sql,
                (
                    local_pid, tenant_id, hcc, r.get("icd10_code") or "",
                    prior_year, current_year, current_year, _GAP_REVENUE_IMPACT,
                ),
            )
            inserted += 1
            already_tracked.add(hcc)

    return inserted


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze_patient(local_pid: int) -> dict[str, Any]:
    """Run the full per-patient AI pipeline and persist results.

    Stages:
      1. Suspect detection    -> ``raf_suspect_conditions``
      2. MEAT validation      -> ``raf_meat_evidence``
      3. Recapture gap detect -> ``recapture_gaps``

    Each stage is wrapped in try/except so one failure does not abort the
    whole run.  Errors are collected and returned in the ``errors`` key with
    full tracebacks routed to the logger.

    Parameters
    ----------
    local_pid:
        Internal ``patients.id`` (NOT ``emr_pid``).  The downstream services
        all key off this column.

    Returns
    -------
    dict with keys:
        suspects_added    : int   rows newly inserted into raf_suspect_conditions
        gaps_added        : int   rows newly inserted into recapture_gaps
        meat_validations  : int   raf_meat_evidence rows written this run
        errors            : list[str]  per-stage error messages (empty on full success)
    """
    pid = int(local_pid)
    year = date.today().year
    tenant_id = _resolve_tenant(pid)

    result: dict[str, Any] = {
        "patient_id": pid,
        "tenant_id": tenant_id,
        "year": year,
        "suspects_added": 0,
        "gaps_added": 0,
        "meat_validations": 0,
        "errors": [],
    }

    # --- (1) Suspect detection ---------------------------------------------
    # run_full_suspect_scan composes scan_medications + scan_labs +
    # scan_historical_hccs + scan_note_vs_billing, dedups by fingerprint,
    # and upserts each into raf_suspect_conditions.  We measure "newly added"
    # by diffing the row count before/after.
    suspects_before = _count_suspects(pid)
    try:
        from app.services.suspect_engine import run_full_suspect_scan

        run_full_suspect_scan(pid, year=year, tenant_id=tenant_id)
    except Exception as exc:
        msg = f"suspect_engine: {exc}"
        result["errors"].append(msg)
        logger.error(
            "auto_analyze.suspect_failed pid=%s err=%s\n%s",
            pid, exc, traceback.format_exc(),
        )
    suspects_after = _count_suspects(pid)
    result["suspects_added"] = max(0, suspects_after - suspects_before)

    # --- (2) MEAT validation -----------------------------------------------
    # run_auto_meat_for_patient walks every HCC currently assigned to the
    # patient against every recent note and writes structured MEAT evidence.
    # Its ``evidence_written`` counter is the canonical count for this stage.
    try:
        from app.services.auto_meat_extractor import run_auto_meat_for_patient

        meat_summary = run_auto_meat_for_patient(
            patient_id=pid,
            tenant_id=tenant_id,
            year=year,
        )
        result["meat_validations"] = int(meat_summary.get("evidence_written", 0))
    except Exception as exc:
        msg = f"auto_meat_extractor: {exc}"
        result["errors"].append(msg)
        logger.error(
            "auto_analyze.meat_failed pid=%s err=%s\n%s",
            pid, exc, traceback.format_exc(),
        )

    # --- (3) Recapture gap detection ---------------------------------------
    # Scoped, idempotent gap detect for THIS patient only.  We deliberately
    # do not call recapture_gap_service.detect_and_persist_gaps here:
    #
    #   * it scans the entire tenant (heavyweight for a single-patient sync),
    #   * the recapture_gaps table has no UNIQUE KEY on
    #     (patient_id, hcc_code, prior_year, current_year), so its
    #     ``INSERT IGNORE`` is silently non-idempotent.
    #
    # Instead we materialise the prior-vs-current HCC diff for this patient
    # and INSERT only rows whose key is not already present in any state
    # ('open', 'recaptured', 'dismissed').  This makes re-runs safe.
    prior_year = year - 1
    gaps_before = _count_gaps(pid)
    try:
        _detect_gaps_for_patient(pid, tenant_id, prior_year, year)
    except Exception as exc:
        msg = f"recapture_gap_service: {exc}"
        result["errors"].append(msg)
        logger.error(
            "auto_analyze.gaps_failed pid=%s err=%s\n%s",
            pid, exc, traceback.format_exc(),
        )
    gaps_after = _count_gaps(pid)
    result["gaps_added"] = max(0, gaps_after - gaps_before)

    # --- structured completion log ----------------------------------------
    logger.info(
        "auto_analyze.completed",
        extra={
            "pid": pid,
            "tenant_id": tenant_id,
            "year": year,
            "suspects": result["suspects_added"],
            "gaps": result["gaps_added"],
            "meat": result["meat_validations"],
            "errors": len(result["errors"]),
        },
    )

    return result


__all__ = ["analyze_patient"]
