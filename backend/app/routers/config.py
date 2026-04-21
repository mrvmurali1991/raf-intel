"""System configuration router — AI analysis controls.

Endpoints
---------
GET /api/config/ai-settings   Current AI analysis controls for the tenant.
PUT /api/config/ai-settings   Update AI analysis controls.

Values fall back tenant -> global -> hardcoded default. Writes are always
tenant-scoped so one tenant cannot affect another. ``pipeline:write`` is
required to modify settings.
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services import config_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])


class AiSettingsResponse(BaseModel):
    ai_analysis_cutoff_date: str = Field(..., description="ISO date YYYY-MM-DD")
    max_analyses_per_patient_per_day: int


class AiSettingsUpdate(BaseModel):
    ai_analysis_cutoff_date: str | None = None
    max_analyses_per_patient_per_day: int | None = None

    @field_validator("ai_analysis_cutoff_date")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("ai_analysis_cutoff_date must be ISO date YYYY-MM-DD") from exc
        return v

    @field_validator("max_analyses_per_patient_per_day")
    @classmethod
    def _validate_cap(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 100):
            raise ValueError("max_analyses_per_patient_per_day must be between 1 and 100")
        return v


def _build_response(tenant_id: str) -> AiSettingsResponse:
    return AiSettingsResponse(
        ai_analysis_cutoff_date=config_service.get_ai_analysis_cutoff_date(tenant_id),
        max_analyses_per_patient_per_day=config_service.get_max_analyses_per_patient_per_day(
            tenant_id
        ),
    )


@router.get("/ai-settings", response_model=AiSettingsResponse, summary="Get AI analysis settings")
@limiter.limit("60/minute")
def get_ai_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "read")),
) -> AiSettingsResponse:
    try:
        return _build_response(tenant_id)
    except Exception as exc:
        logger.error("config.ai_settings: read failed tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch AI settings")


@router.put("/ai-settings", response_model=AiSettingsResponse, summary="Update AI analysis settings")
@limiter.limit("30/minute")
def update_ai_settings(
    payload: AiSettingsUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("pipeline", "write")),
) -> AiSettingsResponse:
    updates: dict[str, Any] = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Request body must include at least one field.")

    try:
        if "ai_analysis_cutoff_date" in updates:
            config_service.set_config(
                "ai_analysis_cutoff_date", updates["ai_analysis_cutoff_date"], tenant_id=tenant_id
            )
        if "max_analyses_per_patient_per_day" in updates:
            config_service.set_config(
                "max_analyses_per_patient_per_day",
                str(updates["max_analyses_per_patient_per_day"]),
                tenant_id=tenant_id,
            )
    except Exception as exc:
        logger.error(
            "config.ai_settings: update failed tenant=%s: %s", tenant_id, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to save AI settings")

    logger.info(
        "config.ai_settings: updated tenant=%s by=%s fields=%s",
        tenant_id,
        current_user.get("email") or current_user.get("id"),
        list(updates.keys()),
    )
    return _build_response(tenant_id)
