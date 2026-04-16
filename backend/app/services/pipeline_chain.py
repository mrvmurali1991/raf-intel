"""
Pipeline auto-chain — wires EMR sync through normalization, optional AI
analysis, RAF scoring, suspect detection, gap generation, and webhook
delivery in a fully automated 8-phase chain.

Call ``setup_pipeline_chain()`` once at application startup (from the
lifespan handler in ``app/main.py``).  After that, completing any pipeline
stage automatically triggers the next one without any manual intervention.

Chain
-----
① ``"emr_sync_completed"``
       → sync_encounters(tenant_id) + sync_diagnoses(tenant_id)
       → emits ``"normalization_completed"``

② ``"normalization_completed"``
       → reads pipeline_settings for the tenant
       → if mode == 'auto_ai' and ai_analysis_enabled: emits ``"analysis_requested"``
       → otherwise (auto_basic / manual / AI disabled): runs RAF calc directly
         and emits ``"raf_calculation_completed"``

③ ``"analysis_requested"``  [auto_ai mode only]
       → fetches unanalyzed encounters, runs AI/NLP pipeline per encounter
       → saves encounter analysis, suspects, MEAT evidence
       → emits ``"analysis_completed"``

④ ``"analysis_completed"``
       → calculate_raf_for_all_patients(tenant_id)
       → apply HCC hierarchy trumping (if hierarchy_enabled)
       → emits ``"raf_calculation_completed"``

⑤ ``"raf_calculation_completed"``
       → run_full_suspect_scan for all active patients (if suspect_scan_enabled)
       → emits ``"suspect_scan_completed"``

⑥ ``"suspect_scan_completed"``
       → generate_care_gaps(tenant_id) (if gap_generation_enabled)
       → emits ``"pipeline_completed"``

⑧ ``"pipeline_completed"``
       → closes the tracking row, fires webhook (if webhook_enabled)

Configuration
-------------
Set the environment variable ``RAF_AUTO_CHAIN=false`` to disable the entire
chain (useful in integration tests or when running only partial pipelines).
The default is ``true``.

pipeline_settings (per-tenant DB row)
--------------------------------------
- pipeline_mode           : 'auto_basic' (default) | 'auto_ai' | 'manual'
- ai_analysis_enabled     : bool  — gates Phase ③
- suspect_scan_enabled    : bool  — gates Phase ⑤  (default True)
- gap_generation_enabled  : bool  — gates Phase ⑥  (default True)
- hierarchy_enabled       : bool  — gates HCC hierarchy in Phase ④ (default True)
- webhook_enabled         : bool  — gates webhook in Phase ⑧ (default False)

Robustness features
-------------------
- ``pipeline_runs`` table tracks every run end-to-end with step granularity.
- Idempotency: a run with the same (tenant_id, sync_id) is never started twice.
- Error recovery: if encounter normalisation fails the run is marked failed
  immediately (diagnoses depend on encounters); if diagnosis normalisation
  fails, RAF calculation still proceeds against whatever data already exists
  so that partial progress is not lost.
- AI analysis failures fall through to RAF calc — no partial-failure abort.
- Retry logic: transient DB errors (lost connection, deadlock) are retried
  up to ``_MAX_RETRIES`` times with a short back-off.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Any

import mysql.connector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

_MAX_RETRIES: int = 2          # extra attempts after the first failure
_RETRY_BACKOFF_S: float = 0.5  # seconds to wait between retry attempts

# MySQL error numbers that are safe to retry (transient failures)
_RETRYABLE_MYSQL_ERRNOS: frozenset[int] = frozenset(
    {
        1213,  # ER_LOCK_DEADLOCK
        2006,  # CR_SERVER_GONE_ERROR
        2013,  # CR_SERVER_LOST
        2055,  # CR_SERVER_LOST_EXTENDED
    }
)


# ---------------------------------------------------------------------------
# Feature flag — read once at import time so tests can patch os.environ
# ---------------------------------------------------------------------------


def _auto_chain_enabled() -> bool:
    """Return True unless RAF_AUTO_CHAIN is explicitly set to a falsy value."""
    raw = os.environ.get("RAF_AUTO_CHAIN", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


PIPELINE_AUTO_CHAIN_ENABLED: bool = _auto_chain_enabled()


# ---------------------------------------------------------------------------
# pipeline_runs helpers
# ---------------------------------------------------------------------------


def _ensure_pipeline_tables() -> None:
    """CREATE TABLE IF NOT EXISTS for pipeline_runs and pipeline_settings.

    Last-resort guard for environments where the Alembic migrations
    003_pipeline_runs_table and 005_pipeline_settings_table have not been run
    yet.  In normal deployments the tables are created by the migrations before
    the app starts.
    """
    from app.db import raf_cursor

    pipeline_runs_ddl = """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
        tenant_id     VARCHAR(64)  NOT NULL,
        trigger_event VARCHAR(128) NOT NULL,
        connection_id INT          NULL,
        sync_type     VARCHAR(64)  NULL,
        sync_id       VARCHAR(255) NULL,
        status        ENUM('pending','running','completed','failed')
                      NOT NULL DEFAULT 'pending',
        steps_completed LONGTEXT   NULL,
        current_step  VARCHAR(128) NULL,
        started_at    DATETIME     NULL,
        finished_at   DATETIME     NULL,
        error_message TEXT         NULL,
        stats         LONGTEXT     NULL,
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_pipeline_runs_tenant_sync (tenant_id, sync_id),
        KEY ix_pipeline_runs_tenant_status (tenant_id, status),
        KEY ix_pipeline_runs_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

    pipeline_settings_ddl = """
    CREATE TABLE IF NOT EXISTS pipeline_settings (
        id                     INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
        tenant_id              VARCHAR(64)  NOT NULL,
        pipeline_mode          ENUM('auto_basic','auto_ai','manual')
                               NOT NULL DEFAULT 'auto_basic',
        ai_analysis_enabled    TINYINT(1)   NOT NULL DEFAULT 0,
        suspect_scan_enabled   TINYINT(1)   NOT NULL DEFAULT 1,
        gap_generation_enabled TINYINT(1)   NOT NULL DEFAULT 1,
        hierarchy_enabled      TINYINT(1)   NOT NULL DEFAULT 1,
        webhook_enabled        TINYINT(1)   NOT NULL DEFAULT 0,
        gemini_max_concurrent  INT          NOT NULL DEFAULT 5,
        updated_by             VARCHAR(100) NULL,
        updated_at             DATETIME     NOT NULL
                               DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
        created_at             DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_pipeline_settings_tenant (tenant_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

    try:
        with raf_cursor() as cur:
            cur.execute(pipeline_runs_ddl)
        logger.debug("pipeline_chain: pipeline_runs table ensured.")
    except Exception as exc:
        logger.warning(
            "pipeline_chain: could not ensure pipeline_runs table: %s", exc
        )

    try:
        with raf_cursor() as cur:
            cur.execute(pipeline_settings_ddl)
        logger.debug("pipeline_chain: pipeline_settings table ensured.")
    except Exception as exc:
        logger.warning(
            "pipeline_chain: could not ensure pipeline_settings table: %s", exc
        )

    # Idempotent: add document_sync_enabled column if it does not yet exist.
    # MySQL raises error 1060 (ER_DUP_FIELDNAME) when the column is already
    # present — we catch and ignore that specific error so repeated startups
    # are safe.
    try:
        with raf_cursor() as cur:
            cur.execute(
                "ALTER TABLE pipeline_settings "
                "ADD COLUMN document_sync_enabled TINYINT(1) NOT NULL DEFAULT 1"
            )
        logger.debug("pipeline_chain: added document_sync_enabled column to pipeline_settings.")
    except mysql.connector.Error as exc:
        if exc.errno == 1060:
            # Column already exists — this is expected after the first run.
            logger.debug("pipeline_chain: document_sync_enabled column already exists (ok).")
        else:
            logger.warning(
                "pipeline_chain: could not add document_sync_enabled column: %s", exc
            )
    except Exception as exc:
        logger.warning(
            "pipeline_chain: could not add document_sync_enabled column: %s", exc
        )


# Backward-compat alias so external callers are not broken.
_ensure_pipeline_runs_table = _ensure_pipeline_tables


def _is_retryable(exc: Exception) -> bool:
    """Return True when *exc* is a transient MySQL error worth retrying."""
    if isinstance(exc, mysql.connector.Error):
        return exc.errno in _RETRYABLE_MYSQL_ERRNOS
    return False


def _with_retry(fn, *args, **kwargs):
    """Call *fn* with up to ``_MAX_RETRIES`` extra attempts on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(1 + _MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES and _is_retryable(exc):
                logger.warning(
                    "pipeline_chain: transient DB error on attempt %d/%d — retrying in %.1fs: %s",
                    attempt + 1,
                    1 + _MAX_RETRIES,
                    _RETRY_BACKOFF_S,
                    exc,
                )
                time.sleep(_RETRY_BACKOFF_S)
            else:
                raise
    raise last_exc  # unreachable; satisfies type-checkers


def _create_run(
    *,
    tenant_id: str,
    trigger_event: str,
    connection_id: int | None,
    sync_type: str | None,
    sync_id: str | None,
) -> int | None:
    """Insert a new pipeline_runs row in 'pending' status.

    Returns:
        The new row id on success.
        -1 when the run is a duplicate (same sync_id already in-flight/done).
        None when tracking is unavailable (table missing, etc.).
    """
    from app.db import raf_cursor

    def _insert():
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs
                    (tenant_id, trigger_event, connection_id, sync_type, sync_id,
                     status, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                """,
                (
                    tenant_id,
                    trigger_event,
                    connection_id,
                    sync_type,
                    sync_id,
                    datetime.now(timezone.utc),
                ),
            )
            return cur.lastrowid

    try:
        return _with_retry(_insert)
    except mysql.connector.IntegrityError as exc:
        # Duplicate key on (tenant_id, sync_id) — already running or done.
        if exc.errno == 1062 and sync_id:
            logger.info(
                "pipeline_chain: duplicate run skipped [tenant=%s sync_id=%s]: %s",
                tenant_id,
                sync_id,
                exc,
            )
            return -1
        logger.warning("pipeline_chain: _create_run IntegrityError: %s", exc)
        return None
    except Exception as exc:
        logger.warning("pipeline_chain: _create_run failed: %s", exc)
        return None


def _update_run(
    run_id: int | None,
    *,
    status: str | None = None,
    current_step: str | None = None,
    step_completed: str | None = None,
    error_message: str | None = None,
    stats: dict | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Apply field updates to a pipeline_runs row.

    Silently skips when run_id is None, 0, or -1 (no tracking row).
    All failures are logged but never re-raised so tracking never breaks the
    pipeline itself.
    """
    if not run_id or run_id < 0:
        return

    from app.db import raf_cursor

    def _do_update():
        with raf_cursor() as cur:
            sets: list[str] = []
            params: list[Any] = []

            if status is not None:
                sets.append("status = %s")
                params.append(status)
            if current_step is not None:
                sets.append("current_step = %s")
                params.append(current_step)
            if error_message is not None:
                sets.append("error_message = %s")
                params.append(error_message[:4096])
            if started_at is not None:
                sets.append("started_at = %s")
                params.append(started_at)
            if finished_at is not None:
                sets.append("finished_at = %s")
                params.append(finished_at)
            if stats is not None:
                sets.append("stats = %s")
                params.append(json.dumps(stats))

            if step_completed is not None:
                # Atomically append to the JSON array in steps_completed.
                sets.append(
                    "steps_completed = IF(steps_completed IS NULL, %s, "
                    "JSON_ARRAY_APPEND(steps_completed, '$', %s))"
                )
                params.append(json.dumps([step_completed]))
                params.append(step_completed)

            if not sets:
                return

            params.append(run_id)
            sql = f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = %s"
            cur.execute(sql, params)

    try:
        _with_retry(_do_update)
    except Exception as exc:
        logger.warning(
            "pipeline_chain: _update_run failed [run_id=%s]: %s", run_id, exc
        )


# ---------------------------------------------------------------------------
# In-process run-id stash for cross-handler propagation
#
# When sync_diagnoses succeeds it emits "normalization_completed" internally.
# We cannot inject pipeline_run_id into that payload (the normalization service
# owns that emit), so we stash the id here keyed by tenant_id.  The next
# handler pops it and attaches to the same tracking row.
#
# In multi-tenant environments the key differs per tenant so no collisions.
# If the stash misses (process restart etc.) the RAF handler degrades safely.
# ---------------------------------------------------------------------------

_run_id_lock = threading.Lock()
_run_id_stash: dict[str, int] = {}


def _stash_run_id(tenant_id: str, run_id: int) -> None:
    with _run_id_lock:
        _run_id_stash[tenant_id] = run_id


def _pop_run_id(tenant_id: str) -> int | None:
    with _run_id_lock:
        return _run_id_stash.pop(tenant_id, None)


# ---------------------------------------------------------------------------
# Pipeline settings helper
# ---------------------------------------------------------------------------


def _get_pipeline_settings(tenant_id: str) -> dict:
    """Read pipeline_settings for this tenant. Returns defaults if no row."""
    from app.db import raf_cursor

    defaults = {
        "pipeline_mode": "auto_basic",
        "ai_analysis_enabled": False,
        "suspect_scan_enabled": True,
        "gap_generation_enabled": True,
        "hierarchy_enabled": True,
        "webhook_enabled": False,
        "document_sync_enabled": True,
    }
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT * FROM pipeline_settings WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row:
                return {**defaults, **{k: v for k, v in row.items() if v is not None}}
    except Exception:
        pass
    return defaults


# ---------------------------------------------------------------------------
# Individual stage handlers
# ---------------------------------------------------------------------------


def _handle_emr_sync_completed(payload: dict[str, Any]) -> None:
    """Run encounter + diagnosis normalisation after a successful EMR sync.

    Triggered by the ``"emr_sync_completed"`` internal event.

    Expected payload keys
    ~~~~~~~~~~~~~~~~~~~~~
    tenant_id     : str  — the tenant whose EMR data was synced
    connection_id : int  — the EMR connection that was synced (informational)
    sync_type     : str  — e.g. ``"incremental"`` or ``"full"``
    sync_id       : str  — optional idempotency key (e.g. Celery job id)
    """
    from app.services import encounter_normalization_service as norm_svc

    tenant_id: str = payload.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "pipeline_chain: tenant_id is required in payload — "
            "refusing to process event without tenant scope (HIPAA multi-tenant isolation)"
        )

    connection_id: int | None = payload.get("connection_id")
    sync_type: str | None = payload.get("sync_type")
    sync_id: str | None = payload.get("sync_id")

    logger.info(
        "pipeline_chain: emr_sync_completed → starting encounter normalisation "
        "[tenant=%s connection_id=%s sync_type=%s sync_id=%s]",
        tenant_id,
        connection_id,
        sync_type,
        sync_id,
    )

    # ---- Create tracking row -----------------------------------------------
    run_id = _create_run(
        tenant_id=tenant_id,
        trigger_event="emr_sync_completed",
        connection_id=connection_id,
        sync_type=sync_type,
        sync_id=sync_id,
    )
    if run_id == -1:
        logger.info(
            "pipeline_chain: idempotency guard — duplicate run skipped "
            "[tenant=%s sync_id=%s]",
            tenant_id,
            sync_id,
        )
        return

    _update_run(
        run_id,
        status="running",
        current_step="sync_encounters",
        started_at=datetime.now(timezone.utc),
    )

    # ---- Step 1: sync_encounters -------------------------------------------
    enc_stats: dict[str, Any] = {}
    try:
        enc_result = norm_svc.sync_encounters(tenant_id=tenant_id, connection_id=connection_id)
        enc_stats = enc_result if isinstance(enc_result, dict) else {"result": str(enc_result)}
        logger.info(
            "pipeline_chain: sync_encounters done [tenant=%s] %s",
            tenant_id,
            enc_result,
        )
        _update_run(run_id, step_completed="sync_encounters")
    except Exception as exc:
        logger.error(
            "pipeline_chain: sync_encounters FAILED [tenant=%s]: %s", tenant_id, exc
        )
        _update_run(
            run_id,
            status="failed",
            error_message=f"sync_encounters failed: {exc}",
            finished_at=datetime.now(timezone.utc),
        )
        # Diagnoses depend on encounter rows — abort the chain entirely.
        return

    # ---- Step 2: sync_diagnoses --------------------------------------------
    diag_stats: dict[str, Any] = {}
    diag_failed = False
    try:
        _update_run(run_id, current_step="sync_diagnoses")
        diag_result = norm_svc.sync_diagnoses(tenant_id=tenant_id, connection_id=connection_id)
        diag_stats = diag_result if isinstance(diag_result, dict) else {"result": str(diag_result)}
        logger.info(
            "pipeline_chain: sync_diagnoses done [tenant=%s] %s",
            tenant_id,
            diag_result,
        )
        _update_run(run_id, step_completed="sync_diagnoses")
    except Exception as exc:
        diag_failed = True
        logger.error(
            "pipeline_chain: sync_diagnoses FAILED [tenant=%s]: %s — "
            "RAF calculation will still proceed on existing data",
            tenant_id,
            exc,
        )
        _update_run(
            run_id,
            error_message=f"sync_diagnoses failed (non-fatal, RAF will still run): {exc}",
            step_completed="sync_diagnoses_failed",
        )
        # Do NOT return — RAF calculation runs on whatever diagnoses already
        # exist in the database.  Partial progress is better than no progress.

    # ---- Record intermediate stats and pass run_id forward -----------------
    # Include document sync counts from the triggering payload when present
    # (FHIR sync populates these; plain EMR syncs leave them absent).
    documents_synced: int = int(payload.get("documents_synced") or 0)
    documents_failed: int = int(payload.get("documents_failed") or 0)
    if documents_synced or documents_failed:
        logger.info(
            "pipeline_chain: FHIR documents processed during sync "
            "[tenant=%s synced=%d failed=%d] — document analysis already "
            "performed inline by FHIR sync agent",
            tenant_id,
            documents_synced,
            documents_failed,
        )

    combined_stats = {
        **enc_stats,
        **diag_stats,
        "diag_step_failed": diag_failed,
        "documents_synced": documents_synced,
        "documents_failed": documents_failed,
    }
    _update_run(run_id, stats=combined_stats, current_step="raf_calculation")

    # Call the next phase directly rather than relying on emit_internal,
    # which uses a ThreadPoolExecutor that doesn't work in Celery's forked workers.
    _handle_normalization_completed({
        "tenant_id": tenant_id,
        "patient_ids": [],
        "pipeline_run_id": run_id,
        "partial": diag_failed,
    })


def _handle_normalization_completed(payload: dict[str, Any]) -> None:
    """Phase ②: Route to AI analysis or RAF calc after encounter/diagnosis normalisation.

    Triggered by the ``"normalization_completed"`` internal event.

    Expected payload keys
    ~~~~~~~~~~~~~~~~~~~~~
    tenant_id      : str        — the tenant to recalculate
    patient_ids    : list[str]  — (informational) affected patient IDs
    pipeline_run_id: int        — (optional) propagated tracking row id
    """
    from app.services.raf_calculator import calculate_raf_for_all_patients

    tenant_id: str = payload.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "pipeline_chain: tenant_id is required in payload — "
            "refusing to process event without tenant scope (HIPAA multi-tenant isolation)"
        )
    patient_ids: list[str] = payload.get("patient_ids", [])

    # Recover tracking row: prefer payload-carried id, then stash lookup.
    run_id: int = payload.get("pipeline_run_id") or _pop_run_id(tenant_id) or 0

    # Check pipeline settings to decide next phase
    settings = _get_pipeline_settings(tenant_id)

    if settings.get("pipeline_mode") == "auto_ai" and settings.get("ai_analysis_enabled"):
        # Phase ③: AI Analysis — route to Celery task or fast-forward depending
        # on the PIPELINE_AI_ENABLED env var.
        #
        # PIPELINE_AI_ENABLED=true  → dispatch task_analyze_encounters_batch to
        #   the "heavy" Celery queue.  The task emits "analysis_completed" when
        #   done, which triggers Phase ④ (RAF calc) automatically.
        #
        # PIPELINE_AI_ENABLED=false (default) → skip AI and emit
        #   "analysis_completed" immediately so the rest of the chain (RAF calc,
        #   suspects, gaps, webhook) still runs.  This keeps existing deployments
        #   safe: AI is opt-in.
        _pipeline_ai_raw = os.environ.get("PIPELINE_AI_ENABLED", "false").strip().lower()
        _pipeline_ai_on = _pipeline_ai_raw not in ("0", "false", "no", "off")

        _update_run(run_id, current_step="ai_analysis")
        _stash_run_id(tenant_id, run_id)

        if _pipeline_ai_on:
            logger.info(
                "pipeline_chain: normalization_completed → dispatching AI analysis "
                "task (PIPELINE_AI_ENABLED=true) "
                "[tenant=%s mode=auto_ai affected_patients=%d run_id=%s]",
                tenant_id,
                len(patient_ids),
                run_id or "none",
            )
            try:
                from app.services.celery_tasks import dispatch_analyze_encounters_batch
                dispatch_analyze_encounters_batch(
                    tenant_id=tenant_id,
                    patient_ids=[int(p) for p in patient_ids] if patient_ids else None,
                    max_encounters=500,
                )
            except Exception as dispatch_exc:
                logger.error(
                    "pipeline_chain: failed to dispatch task_analyze_encounters_batch "
                    "[tenant=%s]: %s — falling through to RAF calc",
                    tenant_id,
                    dispatch_exc,
                )
                # Dispatch failed: fall through directly so the chain does not stall.
                _handle_analysis_completed({
                    "tenant_id": tenant_id,
                    "analyzed_count": 0,
                    "pipeline_run_id": run_id,
                })
        else:
            # AI disabled via env var — skip Phase ③ and continue directly.
            logger.info(
                "pipeline_chain: normalization_completed → PIPELINE_AI_ENABLED=false, "
                "skipping AI analysis and emitting analysis_completed "
                "[tenant=%s run_id=%s]",
                tenant_id,
                run_id or "none",
            )
            _handle_analysis_completed({
                "tenant_id": tenant_id,
                "analyzed_count": 0,
                "pipeline_run_id": run_id,
            })
        return

    # Default: auto_basic — go straight to RAF calc (existing behavior)
    logger.info(
        "pipeline_chain: normalization_completed → starting RAF batch recalculation "
        "[tenant=%s mode=%s affected_patients=%d run_id=%s]",
        tenant_id,
        settings.get("pipeline_mode", "auto_basic"),
        len(patient_ids),
        run_id or "none",
    )

    _update_run(run_id, current_step="raf_calculation", status="running")

    try:
        results = calculate_raf_for_all_patients(tenant_id=tenant_id)
        success_count = sum(1 for r in results if "error" not in r)
        error_count = sum(1 for r in results if "error" in r)
        logger.info(
            "pipeline_chain: RAF batch recalculation done [tenant=%s] "
            "total=%d success=%d errors=%d",
            tenant_id,
            len(results),
            success_count,
            error_count,
        )
        _update_run(
            run_id,
            step_completed="raf_calculation",
            stats={
                "raf_total": len(results),
                "raf_success": success_count,
                "raf_errors": error_count,
            },
        )
        _handle_raf_calculation_completed({
            "tenant_id": tenant_id,
            "total": len(results),
            "success": success_count,
            "errors": error_count,
            "pipeline_run_id": run_id,
        })
    except Exception as exc:
        logger.error(
            "pipeline_chain: RAF batch recalculation FAILED [tenant=%s]: %s",
            tenant_id,
            exc,
        )
        _update_run(
            run_id,
            status="failed",
            error_message=f"raf_calculation failed: {exc}",
            finished_at=datetime.now(timezone.utc),
        )


def _handle_analysis_requested(payload: dict[str, Any]) -> None:
    """Phase ③: Run AI/NLP analysis on unanalyzed encounters (auto_ai mode only).

    Triggered by the ``"analysis_requested"`` internal event.
    After completion (or partial failure), always emits ``"analysis_completed"``
    so the pipeline continues to RAF calculation.
    """
    from app.services.pipeline_orchestrator import run_verified_pipeline
    from app.services.openemr_connector import (
        get_clinical_notes,
        get_medications,
        get_problem_list,
        get_recapture_gaps,
        get_latest_vitals,
        get_medication_diagnoses,
    )
    from app.services.suspect_engine import save_suspects_from_analysis

    from app.services.raf_calculator import _calculate_age
    from app.db import raf_cursor

    tenant_id: str = payload.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "pipeline_chain: tenant_id is required in payload — "
            "refusing to process event without tenant scope (HIPAA multi-tenant isolation)"
        )

    run_id: int = payload.get("pipeline_run_id") or _pop_run_id(tenant_id) or 0
    _update_run(run_id, current_step="ai_analysis", status="running")

    analyzed_count = 0
    error_count = 0

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT ne.encounter_id, ne.openemr_encounter_id, ne.patient_id, ne.encounter_date
                FROM normalized_encounters ne
                LEFT JOIN raf_encounter_analysis rea ON rea.encounter_id = ne.encounter_id
                WHERE ne.tenant_id = %s AND rea.id IS NULL
                ORDER BY ne.encounter_date DESC
                LIMIT 500
                """,
                (tenant_id,),
            )
            encounters = cur.fetchall()

        logger.info(
            "pipeline_chain: ai_analysis found %d unanalyzed encounters [tenant=%s]",
            len(encounters),
            tenant_id,
        )

        for enc in encounters:
            try:
                encounter_id = enc["encounter_id"]
                emr_encounter_id = enc.get("openemr_encounter_id") or encounter_id
                patient_id = enc["patient_id"]

                # Get clinical notes using OpenEMR's encounter ID
                notes = get_clinical_notes(emr_encounter_id, tenant_id=tenant_id)
                if not notes:
                    continue
                note_text = "\n\n".join(
                    n.get("note_text") or n.get("subjective", "") or "" for n in notes
                )
                if not note_text.strip():
                    continue

                # Get patient demographics — try local patients table first,
                # then fall back to emr_patient_matches for FHIR patients.
                patient_age = None
                patient_sex = None
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT date_of_birth, gender FROM patients WHERE id = %s AND tenant_id = %s",
                            (patient_id, tenant_id),
                        )
                        patient_row = cur.fetchone()
                    if patient_row:
                        if patient_row.get("date_of_birth"):
                            patient_age = _calculate_age(patient_row["date_of_birth"])
                        patient_sex = patient_row.get("gender")
                    else:
                        # FHIR patient — look up in emr_patient_matches
                        from app.services.patient_service import _get_fhir_patient_row
                        fhir_row = _get_fhir_patient_row(patient_id)
                        if fhir_row:
                            dob_raw = fhir_row.get("DOB") or ""
                            if dob_raw:
                                patient_age = _calculate_age(str(dob_raw)[:10])
                            patient_sex = fhir_row.get("sex") or ""
                except Exception:
                    pass

                # Resolve emr_pid for OpenEMR lookups
                emr_pid = patient_id
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT emr_pid FROM patients WHERE id = %s AND tenant_id = %s",
                            (patient_id, tenant_id),
                        )
                        _emr_row = cur.fetchone()
                        if _emr_row and _emr_row.get("emr_pid"):
                            _raw = _emr_row["emr_pid"]
                            try:
                                emr_pid = int(float(_raw))
                            except (ValueError, TypeError):
                                emr_pid = str(_raw)  # FHIR UUID
                except Exception:
                    pass

                # Gather additional context — all best-effort
                medications = None
                problem_list = None
                recapture_gaps = None
                latest_vitals = None
                med_diagnoses = None
                try:
                    medications = [
                        m.get("drug", "") for m in (get_medications(emr_pid, tenant_id=tenant_id) or [])
                    ]
                except Exception:
                    pass
                try:
                    problem_list = get_problem_list(emr_pid, tenant_id=tenant_id)
                except Exception:
                    pass
                try:
                    recapture_gaps = get_recapture_gaps(emr_pid, date.today().year, tenant_id=tenant_id)
                except Exception:
                    pass
                try:
                    latest_vitals = get_latest_vitals(emr_pid, tenant_id=tenant_id)
                except Exception:
                    pass
                try:
                    med_diagnoses = get_medication_diagnoses(emr_pid, tenant_id=tenant_id)
                except Exception:
                    pass

                # Existing HCCs for context
                existing_hccs: list[str] = []
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT hcc_code FROM raf_patient_hcc "
                            "WHERE patient_id = %s AND measurement_year = %s",
                            (patient_id, date.today().year),
                        )
                        existing_hccs = [str(r["hcc_code"]) for r in cur.fetchall()]
                except Exception:
                    pass

                # Run the AI pipeline
                result = run_verified_pipeline(
                    clinical_note=note_text,
                    patient_age=patient_age,
                    patient_sex=patient_sex,
                    medications=medications,
                    existing_hccs=existing_hccs,
                    problem_list=problem_list,
                    recapture_gaps=recapture_gaps,
                    latest_vitals=latest_vitals,
                    med_diagnoses=med_diagnoses,
                )

                # Persist encounter analysis
                from app.services.analysis_service import save_encounter_analysis
                save_encounter_analysis(encounter_id, patient_id, result)

                # Persist suspects
                suspect_conditions = result.get("suspect_conditions", [])
                if suspect_conditions:
                    save_suspects_from_analysis(
                        patient_id, encounter_id, suspect_conditions, tenant_id=tenant_id
                    )

                analyzed_count += 1

                # Route the analysis result to auto-accept / human-review / full-audit
                try:
                    from app.services import confidence_router
                    from app.services import coder_worklist_service

                    routing = confidence_router.route_analysis_result(
                        medcat_entities=[],
                        gemini_diagnoses=result.get("diagnoses") or [],
                        negation_results=result.get("negated_conditions") or [],
                        candidate_codes=[],
                    )
                    routing_decision = routing.get("routing")
                    logger.info(
                        "pipeline_chain: routing=%s confidence=%.3f encounter=%s patient=%s",
                        routing_decision,
                        routing.get("overall_confidence", 0.0),
                        encounter_id,
                        patient_id,
                    )

                    if routing_decision in (
                        confidence_router.RoutingDecision.HUMAN_REVIEW,
                        confidence_router.RoutingDecision.FULL_AUDIT,
                    ):
                        hcc_codes = [
                            int(dx["hcc_code"])
                            for dx in (routing.get("review_codes") or [])
                            if dx.get("hcc_code") and str(dx["hcc_code"]).isdigit()
                        ]
                        coder_worklist_service.auto_queue_from_nlp(
                            nlp_results=[{
                                "patient_id": patient_id,
                                "encounter_id": encounter_id,
                                "hcc_codes": hcc_codes,
                                "priority": 2 if routing_decision == confidence_router.RoutingDecision.FULL_AUDIT else 3,
                            }],
                            assigning_user_id=1,
                            tenant_id=tenant_id,
                        )
                except Exception as routing_exc:
                    logger.warning(
                        "pipeline_chain: confidence routing failed for encounter %s: %s",
                        encounter_id,
                        routing_exc,
                    )

                logger.info(
                    "pipeline_chain: analyzed encounter %s for patient %s",
                    encounter_id,
                    patient_id,
                )

            except Exception as exc:
                error_count += 1
                logger.warning(
                    "pipeline_chain: ai_analysis failed for encounter %s: %s",
                    enc.get("encounter_id"),
                    exc,
                )
                continue

    except Exception as exc:
        logger.error(
            "pipeline_chain: ai_analysis FAILED [tenant=%s]: %s", tenant_id, exc
        )
        _update_run(
            run_id,
            status="failed",
            error_message=f"ai_analysis failed: {exc}",
            finished_at=datetime.now(timezone.utc),
        )
        # Fall through — emit analysis_completed so RAF still runs

    _update_run(
        run_id,
        step_completed="ai_analysis",
        stats={"ai_analyzed": analyzed_count, "ai_errors": error_count},
    )

    _stash_run_id(tenant_id, run_id)
    _handle_analysis_completed({
        "tenant_id": tenant_id,
        "analyzed_count": analyzed_count,
        "pipeline_run_id": run_id,
    })


def _handle_analysis_completed(payload: dict[str, Any]) -> None:
    """Phase ④: RAF calculation + HCC hierarchy trumping after AI analysis.

    Triggered by the ``"analysis_completed"`` internal event.
    Emits ``"raf_calculation_completed"`` on success.
    """
    from app.services.raf_calculator import calculate_raf_for_all_patients


    tenant_id: str = payload.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "pipeline_chain: tenant_id is required in payload — "
            "refusing to process event without tenant scope (HIPAA multi-tenant isolation)"
        )

    run_id: int = payload.get("pipeline_run_id") or _pop_run_id(tenant_id) or 0
    _update_run(run_id, current_step="raf_calculation", status="running")

    results: list = []
    success_count = 0
    error_count = 0
    try:
        results = calculate_raf_for_all_patients(tenant_id=tenant_id)
        success_count = sum(1 for r in results if "error" not in r)
        error_count = sum(1 for r in results if "error" in r)
        logger.info(
            "pipeline_chain: RAF calc done [tenant=%s] success=%d errors=%d",
            tenant_id,
            success_count,
            error_count,
        )
        _update_run(run_id, step_completed="raf_calculation")
    except Exception as exc:
        logger.error(
            "pipeline_chain: RAF calc FAILED [tenant=%s]: %s", tenant_id, exc
        )
        _update_run(
            run_id,
            status="failed",
            error_message=f"raf_calculation failed: {exc}",
            finished_at=datetime.now(timezone.utc),
        )
        return

    # Phase ④b: HCC Hierarchy Trumping (optional)
    settings = _get_pipeline_settings(tenant_id)
    if settings.get("hierarchy_enabled", True):
        try:
            from app.services.hcc_hierarchy import apply_hierarchy_to_all_patients
            _update_run(run_id, current_step="hcc_hierarchy")
            apply_hierarchy_to_all_patients(
                measurement_year=date.today().year,
                tenant_id=tenant_id,
            )
            _update_run(run_id, step_completed="hcc_hierarchy")
            logger.info("pipeline_chain: HCC hierarchy applied [tenant=%s]", tenant_id)
        except Exception as exc:
            logger.warning(
                "pipeline_chain: HCC hierarchy failed (non-fatal) [tenant=%s]: %s",
                tenant_id,
                exc,
            )
            _update_run(run_id, step_completed="hcc_hierarchy_failed")

    _update_run(
        run_id,
        step_completed="raf_and_hierarchy",
        stats={
            "raf_total": len(results),
            "raf_success": success_count,
            "raf_errors": error_count,
        },
    )

    # Pre-warm RAF score cache after calculation
    try:
        from app.services.cache_strategy import warm_raf_scores, invalidate_raf_scores
        invalidate_raf_scores(tenant_id)
        warm_raf_scores(tenant_id)
    except Exception as exc:
        logger.warning("pipeline_chain: cache warming after RAF calc failed: %s", exc)

    _handle_raf_calculation_completed({
        "tenant_id": tenant_id,
        "total": len(results),
        "success": success_count,
        "errors": error_count,
        "pipeline_run_id": run_id,
    })


def _handle_raf_calculation_completed(payload: dict[str, Any]) -> None:
    """Phase ⑤: Run suspect detection after RAF scoring.

    Triggered by the ``"raf_calculation_completed"`` internal event.
    Emits ``"suspect_scan_completed"`` when done (or skipped).
    """


    tenant_id: str = payload.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "pipeline_chain: tenant_id is required in payload — "
            "refusing to process event without tenant scope (HIPAA multi-tenant isolation)"
        )

    run_id: int = payload.get("pipeline_run_id") or _pop_run_id(tenant_id) or 0
    settings = _get_pipeline_settings(tenant_id)

    if settings.get("pipeline_mode") == "manual":
        logger.info(
            "pipeline_chain: raf_calculation_completed — manual mode, stopping [tenant=%s]",
            tenant_id,
        )
        _update_run(run_id, status="completed", finished_at=datetime.now(timezone.utc))
        return

    if not settings.get("suspect_scan_enabled", True):
        logger.info(
            "pipeline_chain: suspect scan disabled, skipping to gaps [tenant=%s]", tenant_id
        )
        _handle_suspect_scan_completed({"tenant_id": tenant_id, "pipeline_run_id": run_id})
        return

    _update_run(run_id, current_step="suspect_scan")
    total_suspects = 0
    patient_ids: list[str] = []
    try:
        from app.services.suspect_engine import run_full_suspect_scan

        patient_ids = _fetch_active_patient_ids(tenant_id)
        for pid_str in patient_ids:
            try:
                suspects = run_full_suspect_scan(
                    int(pid_str), year=date.today().year, tenant_id=tenant_id
                )
                total_suspects += len(suspects)
            except Exception as exc:
                logger.warning(
                    "pipeline_chain: suspect scan failed for patient %s: %s", pid_str, exc
                )

        _update_run(
            run_id,
            step_completed="suspect_scan",
            stats={"suspects_found": total_suspects, "patients_scanned": len(patient_ids)},
        )
        logger.info(
            "pipeline_chain: suspect scan done [tenant=%s] patients=%d suspects=%d",
            tenant_id,
            len(patient_ids),
            total_suspects,
        )
    except Exception as exc:
        logger.error(
            "pipeline_chain: suspect scan FAILED [tenant=%s]: %s", tenant_id, exc
        )
        _update_run(run_id, step_completed="suspect_scan_failed")

    _handle_suspect_scan_completed({
        "tenant_id": tenant_id,
        "pipeline_run_id": run_id,
    })


def _handle_suspect_scan_completed(payload: dict[str, Any]) -> None:
    """Phase ⑥: Generate care gaps from suspects.

    Triggered by the ``"suspect_scan_completed"`` internal event.
    Emits ``"pipeline_completed"`` when done (or skipped).
    """


    tenant_id: str = payload.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "pipeline_chain: tenant_id is required in payload — "
            "refusing to process event without tenant scope (HIPAA multi-tenant isolation)"
        )

    run_id: int = payload.get("pipeline_run_id") or _pop_run_id(tenant_id) or 0
    settings = _get_pipeline_settings(tenant_id)

    if not settings.get("gap_generation_enabled", True):
        logger.info(
            "pipeline_chain: gap generation disabled [tenant=%s]", tenant_id
        )
        _handle_pipeline_completed({"tenant_id": tenant_id, "pipeline_run_id": run_id})
        return

    _update_run(run_id, current_step="gap_generation")
    gaps_created = 0
    try:
        from app.services.care_gap_service import generate_care_gaps

        result = generate_care_gaps(tenant_id=tenant_id)
        gaps_created = result.get("gaps_created", 0) if isinstance(result, dict) else 0
        _update_run(
            run_id,
            step_completed="gap_generation",
            stats={"gaps_created": gaps_created},
        )
        logger.info(
            "pipeline_chain: gap generation done [tenant=%s] gaps=%d", tenant_id, gaps_created
        )
    except Exception as exc:
        logger.warning(
            "pipeline_chain: gap generation failed (non-fatal) [tenant=%s]: %s", tenant_id, exc
        )
        _update_run(run_id, step_completed="gap_generation_failed")

    _handle_pipeline_completed({
        "tenant_id": tenant_id,
        "pipeline_run_id": run_id,
        "gaps_created": gaps_created,
    })


def _handle_pipeline_completed(payload: dict[str, Any]) -> None:
    """Phase ⑧: Pipeline complete — close tracking row and fire webhook.

    Triggered by the ``"pipeline_completed"`` internal event.
    This is the terminal node of the full auto-chain.
    """
    tenant_id: str = payload.get("tenant_id") or ""
    run_id: int = payload.get("pipeline_run_id") or 0
    settings = _get_pipeline_settings(tenant_id)

    _update_run(
        run_id,
        status="completed",
        current_step=None,
        finished_at=datetime.now(timezone.utc),
    )

    logger.info(
        "pipeline_chain: FULL PIPELINE COMPLETED [tenant=%s run_id=%s mode=%s]",
        tenant_id,
        run_id,
        settings.get("pipeline_mode"),
    )

    # Pre-warm dashboard caches after full pipeline completion
    try:
        from app.services.cache_strategy import warm_dashboard, invalidate_dashboard, invalidate_worklist
        invalidate_dashboard(tenant_id)
        invalidate_worklist(tenant_id)
        warm_dashboard(tenant_id)
    except Exception as exc:
        logger.warning("pipeline_chain: dashboard cache warming failed: %s", exc)

    if settings.get("webhook_enabled"):
        try:
            from app.services.webhook_service import fire_event

            fire_event(
                "pipeline.full_run_completed",
                tenant_id,
                {
                    "pipeline_run_id": run_id,
                    "mode": settings.get("pipeline_mode"),
                    "gaps_created": payload.get("gaps_created", 0),
                },
            )
        except Exception as exc:
            logger.warning("pipeline_chain: webhook delivery failed: %s", exc)


# ---------------------------------------------------------------------------
# Helper: fetch active patient IDs for a tenant
# ---------------------------------------------------------------------------


def _fetch_active_patient_ids(tenant_id: str) -> list[str]:
    """Return string IDs of all active patients for *tenant_id*."""
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM patients WHERE tenant_id = %s AND is_active = 1",
                (tenant_id,),
            )
            return [str(row["id"]) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(
            "pipeline_chain: could not fetch active patient IDs [tenant=%s]: %s",
            tenant_id,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Public query API — used by the pipeline router
# ---------------------------------------------------------------------------


def get_pipeline_runs(
    tenant_id: str,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return pipeline_runs rows for *tenant_id* ordered by created_at DESC."""
    from app.db import raf_cursor

    clauses = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if status:
        clauses.append("status = %s")
        params.append(status)
    where = "WHERE " + " AND ".join(clauses)
    sql = f"""
        SELECT id, tenant_id, trigger_event, connection_id, sync_type, sync_id,
               status, steps_completed, current_step, started_at, finished_at,
               error_message, stats, created_at
          FROM pipeline_runs
         {where}
         ORDER BY created_at DESC
         LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    with raf_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() or []

    return [_parse_run_row(row) for row in rows]


def get_pipeline_run(run_id: int, tenant_id: str) -> dict | None:
    """Return a single pipeline_runs row, tenant-scoped."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, trigger_event, connection_id, sync_type, sync_id,
                   status, steps_completed, current_step, started_at, finished_at,
                   error_message, stats, created_at
              FROM pipeline_runs
             WHERE id = %s AND tenant_id = %s
            """,
            (run_id, tenant_id),
        )
        row = cur.fetchone()

    return _parse_run_row(row) if row else None


def get_latest_pipeline_status(tenant_id: str) -> dict | None:
    """Return the most-recent pipeline_runs row for *tenant_id*."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, trigger_event, connection_id, sync_type, sync_id,
                   status, steps_completed, current_step, started_at, finished_at,
                   error_message, stats, created_at
              FROM pipeline_runs
             WHERE tenant_id = %s
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (tenant_id,),
        )
        row = cur.fetchone()

    return _parse_run_row(row) if row else None


def _parse_run_row(row: dict) -> dict:
    """Deserialise JSON blob fields in a pipeline_runs row."""
    for field in ("steps_completed", "stats"):
        raw = row.get(field)
        if raw and isinstance(raw, str):
            try:
                row[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return row


# ---------------------------------------------------------------------------
# Stale run cleanup
# ---------------------------------------------------------------------------


def cleanup_stale_runs() -> int:
    """Mark pipeline_runs stuck in 'running' or 'pending' for over 1 hour as failed.

    Returns the number of rows updated.  Safe to call from an admin endpoint
    as well as from ``setup_pipeline_chain()`` at startup.
    """
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
               SET status        = 'failed',
                   error_message = 'Stale run cleaned up (exceeded 1 hour timeout)',
                   finished_at   = NOW()
             WHERE status IN ('running', 'pending')
               AND created_at < NOW() - INTERVAL 1 HOUR
            """
        )
        count: int = cur.rowcount

    if count:
        logger.warning("pipeline_chain: cleaned up %d stale pipeline_run(s)", count)
    else:
        logger.debug("pipeline_chain: no stale pipeline_runs found")

    return count


# ---------------------------------------------------------------------------
# Public setup entry point
# ---------------------------------------------------------------------------


def setup_pipeline_chain() -> None:
    """Register all pipeline stage handlers with the event emitter.

    Must be called exactly once during application startup (e.g. from the
    FastAPI lifespan context).  Calling it multiple times will register
    duplicate handlers — guard with ``PIPELINE_AUTO_CHAIN_ENABLED`` or
    the module-level ``_chain_installed`` flag.

    When ``RAF_AUTO_CHAIN=false`` (or any equivalent falsy value) is set in
    the environment, this function logs a notice and returns without
    registering any handlers, effectively disabling the auto-chain.
    """
    global PIPELINE_AUTO_CHAIN_ENABLED  # re-read at call time for test flexibility
    PIPELINE_AUTO_CHAIN_ENABLED = _auto_chain_enabled()

    if not PIPELINE_AUTO_CHAIN_ENABLED:
        logger.info(
            "pipeline_chain: RAF_AUTO_CHAIN=false — pipeline auto-chaining is DISABLED"
        )
        return

    from app.services.event_emitter import register_handler

    # Best-effort: ensure the tracking table exists even if Alembic has not run.
    _ensure_pipeline_tables()

    # Clean up any runs that were left in-flight before the last process exit.
    cleanup_stale_runs()

    # Phase ① → ②: EMR sync → normalization
    register_handler("emr_sync_completed", _handle_emr_sync_completed)
    # Phase ② → ③/④: handled by direct call in _do_normalization (line ~532),
    # NOT via event handler — avoids duplicate Gemini dispatches.
    # register_handler("normalization_completed", _handle_normalization_completed)
    # Phase ③: AI analysis (dispatched when auto_ai mode is active)
    register_handler("analysis_requested", _handle_analysis_requested)
    # Phase ③ → ④: AI done → RAF calc + HCC hierarchy
    register_handler("analysis_completed", _handle_analysis_completed)
    # Phase ④ → ⑤: RAF done → suspect scan
    register_handler("raf_calculation_completed", _handle_raf_calculation_completed)
    # Phase ⑤ → ⑥: suspects done → gap generation
    register_handler("suspect_scan_completed", _handle_suspect_scan_completed)
    # Phase ⑧: pipeline complete → webhook + close tracking row
    register_handler("pipeline_completed", _handle_pipeline_completed)

    logger.info(
        "pipeline_chain: 8-phase auto-chain ENABLED — "
        "emr_sync → normalize → [ai_analysis] → raf_calc → hierarchy → suspects → gaps → webhook"
    )
