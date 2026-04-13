"""
Pipeline settings router — per-tenant pipeline mode configuration.

Endpoints
---------
GET  /api/pipeline/settings        Current pipeline settings for the tenant.
PUT  /api/pipeline/settings        Update pipeline settings.
GET  /api/pipeline/settings/modes  Available pipeline modes with descriptions.

Pipeline modes
--------------
auto_ai     Full 8-phase pipeline: EMR Sync → Normalize → AI Analysis →
            RAF Calc → Hierarchy → Suspects → Gaps → Webhooks.
auto_basic  3-phase pipeline without AI: EMR Sync → Normalize → RAF Calc.
            This is the default for all new tenants.
manual      No auto-chain; every step must be triggered manually.

Security
--------
- All queries are tenant-scoped to the JWT-authenticated user's tenant.
- GET requires ``pipeline:read``.
- PUT requires ``pipeline:write``.
- The table must already exist (created by Alembic migration
  005_pipeline_settings_table).  The router never runs DDL.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_MODES = {"auto_ai", "auto_basic", "manual"}

_MODE_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "auto_ai": {
        "label": "Auto AI Sync",
        "description": (
            "Full 8-phase pipeline: EMR Sync → Normalize → AI Analysis → "
            "RAF Calc → Hierarchy → Suspects → Gaps → Webhooks."
        ),
        "phases": [
            "emr_sync",
            "normalize",
            "ai_analysis",
            "raf_calc",
            "hierarchy",
            "suspects",
            "gaps",
            "webhooks",
        ],
        "phase_count": 8,
        "ai_required": True,
    },
    "auto_basic": {
        "label": "Auto Basic Sync",
        "description": (
            "3-phase pipeline without AI: EMR Sync → Normalize → RAF Calc. "
            "Current default behaviour."
        ),
        "phases": ["emr_sync", "normalize", "raf_calc"],
        "phase_count": 3,
        "ai_required": False,
    },
    "manual": {
        "label": "Manual Sync",
        "description": (
            "No automatic pipeline chaining. Every step must be triggered "
            "manually via the UI or API."
        ),
        "phases": [],
        "phase_count": 0,
        "ai_required": False,
    },
}

# ---------------------------------------------------------------------------
# Default row returned when the tenant has no saved settings yet
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS: dict[str, Any] = {
    "pipeline_mode": "auto_basic",
    "ai_analysis_enabled": False,
    "suspect_scan_enabled": True,
    "gap_generation_enabled": True,
    "hierarchy_enabled": True,
    "webhook_enabled": False,
    "gemini_max_concurrent": 5,
    "updated_by": None,
    "updated_at": None,
    "created_at": None,
}


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class PipelineSettingsResponse(BaseModel):
    tenant_id: str
    pipeline_mode: str
    ai_analysis_enabled: bool
    suspect_scan_enabled: bool
    gap_generation_enabled: bool
    hierarchy_enabled: bool
    webhook_enabled: bool
    gemini_max_concurrent: int
    updated_by: str | None = None
    updated_at: datetime | None = None
    created_at: datetime | None = None


class PipelineSettingsUpdate(BaseModel):
    pipeline_mode: str | None = None  # 'auto_ai' | 'auto_basic' | 'manual'
    ai_analysis_enabled: bool | None = None
    suspect_scan_enabled: bool | None = None
    gap_generation_enabled: bool | None = None
    hierarchy_enabled: bool | None = None
    webhook_enabled: bool | None = None
    gemini_max_concurrent: int | None = None

    @field_validator("pipeline_mode")
    @classmethod
    def _validate_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_MODES:
            raise ValueError(
                f"Invalid pipeline_mode {v!r}. Must be one of: {sorted(_VALID_MODES)}"
            )
        return v

    @field_validator("gemini_max_concurrent")
    @classmethod
    def _validate_concurrency(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 50):
            raise ValueError("gemini_max_concurrent must be between 1 and 50")
        return v


class PipelineModeDetail(BaseModel):
    mode: str
    label: str
    description: str
    phases: list[str]
    phase_count: int
    ai_required: bool


class PipelineModesResponse(BaseModel):
    modes: list[PipelineModeDetail]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: dict, tenant_id: str) -> PipelineSettingsResponse:
    """Convert a DB row dict to the response model, coercing TINYINT bools."""
    return PipelineSettingsResponse(
        tenant_id=tenant_id,
        pipeline_mode=row["pipeline_mode"],
        ai_analysis_enabled=bool(row["ai_analysis_enabled"]),
        suspect_scan_enabled=bool(row["suspect_scan_enabled"]),
        gap_generation_enabled=bool(row["gap_generation_enabled"]),
        hierarchy_enabled=bool(row["hierarchy_enabled"]),
        webhook_enabled=bool(row["webhook_enabled"]),
        gemini_max_concurrent=row["gemini_max_concurrent"],
        updated_by=row.get("updated_by"),
        updated_at=row.get("updated_at"),
        created_at=row.get("created_at"),
    )


def _fetch_settings(tenant_id: str) -> dict | None:
    """Return the raw DB row for the tenant, or None if no row exists."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT pipeline_mode, ai_analysis_enabled, suspect_scan_enabled,
                   gap_generation_enabled, hierarchy_enabled, webhook_enabled,
                   gemini_max_concurrent, updated_by, updated_at, created_at
            FROM pipeline_settings
            WHERE tenant_id = %s
            LIMIT 1
            """,
            (tenant_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/settings",
    response_model=PipelineSettingsResponse,
    summary="Get pipeline settings",
)
@limiter.limit("60/minute")
def get_pipeline_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> PipelineSettingsResponse:
    """Return the current pipeline settings for the authenticated tenant.

    If the tenant has never saved settings, the call succeeds and returns
    the system defaults (``auto_basic`` mode, AI disabled).
    """
    try:
        row = _fetch_settings(tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline_settings: fetch failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch pipeline settings")

    if row is None:
        # No saved row — synthesise a response from the defaults so the
        # frontend always gets a valid object, not a 404.
        return PipelineSettingsResponse(
            tenant_id=tenant_id,
            **_DEFAULT_SETTINGS,  # type: ignore[arg-type]
        )

    return _row_to_response(row, tenant_id)


@router.put(
    "/settings",
    response_model=PipelineSettingsResponse,
    summary="Update pipeline settings",
)
@limiter.limit("30/minute")
def update_pipeline_settings(
    payload: PipelineSettingsUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "write")),
) -> PipelineSettingsResponse:
    """Upsert pipeline settings for the authenticated tenant.

    Only fields included in the request body are changed; omitted fields
    retain their current (or default) values.  At least one field must be
    provided.
    """
    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=422,
            detail="Request body must include at least one field to update.",
        )

    # Resolve the current row so we can merge defaults for missing fields on
    # an UPSERT — MySQL ON DUPLICATE KEY UPDATE only touches the columns we
    # explicitly provide, so we need the current state for the response.
    try:
        current_row = _fetch_settings(tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline_settings: pre-upsert fetch failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch pipeline settings")

    # Build the full settings dict by layering: defaults → current DB row → payload
    merged: dict[str, Any] = dict(_DEFAULT_SETTINGS)
    if current_row:
        merged.update(
            {
                "pipeline_mode": current_row["pipeline_mode"],
                "ai_analysis_enabled": bool(current_row["ai_analysis_enabled"]),
                "suspect_scan_enabled": bool(current_row["suspect_scan_enabled"]),
                "gap_generation_enabled": bool(current_row["gap_generation_enabled"]),
                "hierarchy_enabled": bool(current_row["hierarchy_enabled"]),
                "webhook_enabled": bool(current_row["webhook_enabled"]),
                "gemini_max_concurrent": current_row["gemini_max_concurrent"],
            }
        )
    for k, v in update_data.items():
        merged[k] = v

    updated_by = current_user.get("email") or current_user.get("username") or str(
        current_user.get("id", "")
    )

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_settings
                    (tenant_id, pipeline_mode, ai_analysis_enabled,
                     suspect_scan_enabled, gap_generation_enabled,
                     hierarchy_enabled, webhook_enabled, gemini_max_concurrent,
                     updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    pipeline_mode          = VALUES(pipeline_mode),
                    ai_analysis_enabled    = VALUES(ai_analysis_enabled),
                    suspect_scan_enabled   = VALUES(suspect_scan_enabled),
                    gap_generation_enabled = VALUES(gap_generation_enabled),
                    hierarchy_enabled      = VALUES(hierarchy_enabled),
                    webhook_enabled        = VALUES(webhook_enabled),
                    gemini_max_concurrent  = VALUES(gemini_max_concurrent),
                    updated_by             = VALUES(updated_by)
                """,
                (
                    tenant_id,
                    merged["pipeline_mode"],
                    int(merged["ai_analysis_enabled"]),
                    int(merged["suspect_scan_enabled"]),
                    int(merged["gap_generation_enabled"]),
                    int(merged["hierarchy_enabled"]),
                    int(merged["webhook_enabled"]),
                    merged["gemini_max_concurrent"],
                    updated_by,
                ),
            )
    except Exception as exc:
        logger.error(
            "pipeline_settings: upsert failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to save pipeline settings")

    logger.info(
        "pipeline_settings: updated [tenant=%s by=%s mode=%s]",
        tenant_id,
        updated_by,
        merged["pipeline_mode"],
    )

    # Re-fetch to return authoritative DB timestamps
    try:
        saved_row = _fetch_settings(tenant_id)
    except Exception as exc:
        logger.error(
            "pipeline_settings: post-upsert fetch failed [tenant=%s]: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Settings saved but failed to re-fetch"
        )

    if saved_row is None:
        # Should be unreachable after a successful INSERT … ON DUPLICATE KEY UPDATE
        raise HTTPException(status_code=500, detail="Settings saved but row not found")

    return _row_to_response(saved_row, tenant_id)


@router.get(
    "/settings/modes",
    response_model=PipelineModesResponse,
    summary="List available pipeline modes",
)
@limiter.limit("120/minute")
def get_pipeline_modes(
    request: Request,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> PipelineModesResponse:
    """Return all available pipeline modes with human-readable descriptions.

    The response is static metadata — no DB query is performed.  The
    frontend can use this to populate a mode-selector UI without hardcoding
    labels or phase lists.
    """
    modes = [
        PipelineModeDetail(mode=mode, **detail)
        for mode, detail in _MODE_DESCRIPTIONS.items()
    ]
    return PipelineModesResponse(modes=modes)
