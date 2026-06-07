"""
Pipeline status router — exposes pipeline_runs tracking data to the frontend.

Endpoints
---------
GET  /api/pipeline/status        Latest pipeline run for the authenticated tenant.
GET  /api/pipeline/runs          Paginated history of all pipeline runs.
GET  /api/pipeline/runs/{run_id} Detail for a single pipeline run.
POST /api/pipeline/trigger       Manually trigger the full pipeline or specific phases.
GET  /api/pipeline/phases        List all 8 pipeline phases with enabled/disabled status.

Security
--------
- All queries are tenant-scoped to the JWT-authenticated user's tenant.
- Requires ``pipeline:read`` permission (falls back gracefully to any
  authenticated user in deployments that have not yet provisioned the
  permission row).
- Trigger and phases endpoints require ``pipeline:write`` and ``pipeline:read``
  permissions respectively.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user, get_tenant_id, require_permission
from app.response import paginated_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PipelineRunSummary(BaseModel):
    id: int
    tenant_id: str
    trigger_event: str
    connection_id: int | None = None
    sync_type: str | None = None
    sync_id: str | None = None
    status: str
    steps_completed: list[str] | None = None
    current_step: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    stats: dict[str, Any] | None = None
    created_at: datetime


class PipelineTriggerRequest(BaseModel):
    phases: list[str] | None = None  # None = all phases; or specific phase names
    patient_ids: list[int] | None = None  # None = all patients


class PhaseInfo(BaseModel):
    name: str
    description: str
    trigger_event: str
    enabled: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_run(row: dict) -> PipelineRunSummary:
    """Coerce a raw DB dict into a PipelineRunSummary, handling JSON fields."""
    steps = row.get("steps_completed")
    if isinstance(steps, str):
        import json as _json
        try:
            steps = _json.loads(steps)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            steps = None
    stats = row.get("stats")
    if isinstance(stats, str):
        import json as _json
        try:
            stats = _json.loads(stats)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            stats = None

    return PipelineRunSummary(
        id=row["id"],
        tenant_id=row["tenant_id"],
        trigger_event=row["trigger_event"],
        connection_id=row.get("connection_id"),
        sync_type=row.get("sync_type"),
        sync_id=row.get("sync_id"),
        status=row["status"],
        steps_completed=steps if isinstance(steps, list) else None,
        current_step=row.get("current_step"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        error_message=row.get("error_message"),
        stats=stats if isinstance(stats, dict) else None,
        created_at=row["created_at"],
    )


def _count_pipeline_runs(tenant_id: str, *, status: str | None = None) -> int:
    """Return the total number of pipeline_runs rows for *tenant_id*."""
    from app.db import raf_cursor

    clauses: list[str] = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if status:
        clauses.append("status = %s")
        params.append(status)
    where = "WHERE " + " AND ".join(clauses)
    sql = f"SELECT COUNT(*) AS cnt FROM pipeline_runs {where}"

    with raf_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return int(row["cnt"]) if row else 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=PipelineRunSummary | None,
    summary="Latest pipeline run status",
)
def get_pipeline_status(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> PipelineRunSummary | None:
    """Return the most-recent pipeline run record for the authenticated tenant.

    Returns ``null`` (HTTP 200 with a JSON ``null`` body) when no pipeline has
    ever been triggered for this tenant — this is a valid state for new tenants.
    """
    from app.services.pipeline_chain import get_latest_pipeline_status

    try:
        row = get_latest_pipeline_status(tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline router: get_latest_pipeline_status failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to query pipeline status")

    if row is None:
        return None
    return _coerce_run(row)


@router.get(
    "/runs",
    summary="List pipeline runs",
)
def list_pipeline_runs(
    status: str | None = Query(None, description="Filter by status: pending, running, completed, failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> dict[str, Any]:
    """Return a paginated list of pipeline runs for the authenticated tenant.

    Results are ordered newest-first.  Use ``status`` to filter to a specific
    lifecycle stage (e.g. ``running`` to check for an in-flight pipeline).

    Response shape: {items, total, limit, offset, has_more}
    """
    from app.services.pipeline_chain import get_pipeline_runs

    # Validate the status filter value before hitting the DB.
    _VALID_STATUSES = {"pending", "running", "completed", "failed"}
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter {status!r}. Must be one of: {sorted(_VALID_STATUSES)}",
        )

    try:
        rows = get_pipeline_runs(
            tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = _count_pipeline_runs(tenant_id, status=status)
    except Exception as exc:
        logger.error(
            "pipeline router: get_pipeline_runs failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to query pipeline runs")

    return paginated_response(
        items=[_coerce_run(row).model_dump() for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/runs/{run_id}",
    response_model=PipelineRunSummary,
    summary="Get pipeline run detail",
)
def get_pipeline_run_detail(
    run_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> PipelineRunSummary:
    """Return full detail for a single pipeline run, tenant-scoped."""
    from app.services.pipeline_chain import get_pipeline_run

    try:
        row = get_pipeline_run(run_id, tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline router: get_pipeline_run failed [run_id=%s tenant=%s]: %s",
            run_id,
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to query pipeline run")

    if row is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run {run_id} not found")

    return _coerce_run(row)


# ---------------------------------------------------------------------------
# Phase metadata — single source of truth for ordering, names, and events
# ---------------------------------------------------------------------------

# Maps the user-facing phase name to the internal event that starts it.
# Emitting that event lets the existing handler chain take over from that point.
_PHASE_EVENT_MAP: dict[str, str] = {
    "emr_sync":        "emr_sync_completed",       # Phase 1 — triggers normalization
    "normalization":   "normalization_completed",   # Phase 2 — triggers RAF or AI
    "ai_analysis":     "analysis_requested",        # Phase 3 — AI/NLP (auto_ai mode)
    "raf_calculation": "normalization_completed",   # Phase 4 — RAF calc (via norm event)
    "suspect_scan":    "raf_calculation_completed", # Phase 5 — suspect detection
    "gap_generation":  "suspect_scan_completed",    # Phase 6 — care gap generation
}

# Canonical, ordered list of all 8 pipeline phases for display purposes.
_ALL_PHASES: list[dict[str, str]] = [
    {
        "name": "emr_sync",
        "description": "Fetch raw encounter and diagnosis data from the EMR connection.",
        "trigger_event": "emr_sync_completed",
        "settings_key": "",  # always enabled — driven by EMR connection
    },
    {
        "name": "normalization",
        "description": "Normalise raw EMR encounters and diagnoses into the RAF schema.",
        "trigger_event": "normalization_completed",
        "settings_key": "",  # always enabled — no individual gate
    },
    {
        "name": "ai_analysis",
        "description": "Run AI/NLP analysis on unanalyzed encounter notes (auto_ai mode only).",
        "trigger_event": "analysis_requested",
        "settings_key": "ai_analysis_enabled",
    },
    {
        "name": "analysis_completed",
        "description": "Internal bridge that transitions from AI analysis to RAF calculation.",
        "trigger_event": "analysis_completed",
        "settings_key": "ai_analysis_enabled",
    },
    {
        "name": "raf_calculation",
        "description": "Calculate HCC risk-adjustment factor scores for all active patients.",
        "trigger_event": "raf_calculation_completed",
        "settings_key": "",  # always enabled
    },
    {
        "name": "hierarchy",
        "description": "Apply HCC hierarchy trumping rules to remove dominated HCC codes.",
        "trigger_event": "raf_calculation_completed",
        "settings_key": "hierarchy_enabled",
    },
    {
        "name": "suspect_scan",
        "description": "Scan patients for suspected HCC conditions not yet documented.",
        "trigger_event": "suspect_scan_completed",
        "settings_key": "suspect_scan_enabled",
    },
    {
        "name": "gap_generation",
        "description": "Generate actionable care gaps from suspect conditions.",
        "trigger_event": "pipeline_completed",
        "settings_key": "gap_generation_enabled",
    },
]

_VALID_TRIGGER_PHASES: frozenset[str] = frozenset(_PHASE_EVENT_MAP)


@router.post(
    "/trigger",
    response_model=PipelineRunSummary,
    status_code=202,
    summary="Manually trigger the pipeline",
)
def trigger_pipeline(
    body: PipelineTriggerRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "write")),
) -> PipelineRunSummary:
    """Manually trigger the full pipeline chain or a subset of phases.

    When ``phases`` is omitted or ``null`` the full chain is started by emitting
    ``emr_sync_completed`` (skipping the actual EMR network call — useful when
    data is already present in the DB).

    Accepted phase names for targeted runs:

    - ``"ai_analysis"``     — emit ``analysis_requested``
    - ``"suspect_scan"``    — emit ``raf_calculation_completed`` (triggers suspect scan)
    - ``"gap_generation"``  — emit ``suspect_scan_completed``
    - ``"raf_calculation"`` — emit ``normalization_completed`` (triggers RAF calc)
    - ``"emr_sync"``        — emit ``emr_sync_completed`` (full chain)
    - ``"normalization"``   — emit ``normalization_completed`` (from Phase 2 onward)

    Returns the newly created ``pipeline_runs`` row in ``pending`` status.
    The pipeline executes asynchronously; poll ``GET /api/pipeline/status`` to
    track progress.
    """
    from app.services.event_emitter import emit_internal
    from app.services.pipeline_chain import (
        _create_run,
        _get_pipeline_settings,
        get_pipeline_run,
    )

    # Validate requested phase names.
    if body.phases is not None:
        invalid = sorted(set(body.phases) - _VALID_TRIGGER_PHASES)
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown phase(s): {invalid}. "
                    f"Valid choices: {sorted(_VALID_TRIGGER_PHASES)}"
                ),
            )

    settings = _get_pipeline_settings(tenant_id)

    # Determine which event to emit.  Multiple requested phases each get their
    # own emit so every branch starts independently.  When no phases are given
    # we fire the top-of-chain event for the full run.
    phases_to_run: list[str] = body.phases if body.phases else ["emr_sync"]

    # Derive a stable sync_id so the caller can correlate this trigger with
    # the resulting pipeline_runs row without a race.
    sync_id = f"manual-{uuid.uuid4().hex}"

    # Determine the primary trigger event label for the tracking row (first
    # phase wins; for multi-phase triggers we record the first event name).
    primary_event = _PHASE_EVENT_MAP[phases_to_run[0]]

    run_id = _create_run(
        tenant_id=tenant_id,
        trigger_event=primary_event,
        connection_id=None,
        sync_type="manual",
        sync_id=sync_id,
    )

    if run_id is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to create pipeline_runs tracking row. Check DB connectivity.",
        )
    if run_id == -1:
        raise HTTPException(
            status_code=409,
            detail="A pipeline run with this sync_id already exists. Retry in a moment.",
        )

    # Build the base payload shared across all emitted events.
    base_payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "sync_type": "manual",
        "sync_id": sync_id,
        "pipeline_run_id": run_id,
        "triggered_by": current_user.get("sub") or current_user.get("email"),
    }
    if body.patient_ids is not None:
        base_payload["patient_ids"] = body.patient_ids

    # Emit one internal event per requested phase.  Each fires asynchronously
    # in the pipeline thread pool so this endpoint returns immediately.
    for phase in phases_to_run:
        event = _PHASE_EVENT_MAP[phase]
        emit_internal(event, {**base_payload})
        logger.info(
            "pipeline router: manual trigger emitted '%s' [tenant=%s run_id=%s phase=%s]",
            event,
            tenant_id,
            run_id,
            phase,
        )

    # Return the freshly created tracking row.
    try:
        row = get_pipeline_run(run_id, tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline router: could not fetch new run row after trigger [run_id=%s]: %s",
            run_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Pipeline triggered but failed to fetch run row")

    if row is None:
        raise HTTPException(status_code=500, detail="Pipeline triggered but run row not found")

    return _coerce_run(row)


@router.get(
    "/phases",
    response_model=list[PhaseInfo],
    summary="List all pipeline phases",
)
def list_pipeline_phases(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> list[PhaseInfo]:
    """Return all 8 pipeline phases with their enabled/disabled status.

    Enabled status reflects the current ``pipeline_settings`` row for the
    authenticated tenant.  Phases without a settings gate (e.g. normalization,
    RAF calculation) are always reported as enabled.
    """
    from app.services.pipeline_chain import _get_pipeline_settings

    try:
        settings = _get_pipeline_settings(tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline router: _get_pipeline_settings failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to read pipeline settings")

    result: list[PhaseInfo] = []
    for phase in _ALL_PHASES:
        key = phase["settings_key"]
        if key:
            # Coerce to bool — DB may return 0/1 integers.
            enabled = bool(settings.get(key, True))
        else:
            enabled = True  # no individual gate; always active

        result.append(
            PhaseInfo(
                name=phase["name"],
                description=phase["description"],
                trigger_event=phase["trigger_event"],
                enabled=enabled,
            )
        )

    return result
