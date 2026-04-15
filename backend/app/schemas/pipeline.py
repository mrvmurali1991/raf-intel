"""
Pipeline Pydantic schemas.

Request/response shapes for the pipeline auto-chain run endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PipelineRunStatus(BaseModel):
    """Status of a single pipeline auto-chain run."""

    run_id: int
    tenant_id: str
    status: str = Field(..., description="pending | running | completed | failed")
    triggered_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result_summary: dict[str, Any] | None = None


class PipelineRunListResponse(BaseModel):
    """Paginated list of pipeline run history."""

    runs: list[PipelineRunStatus]
    total: int
    page: int = 1
    page_size: int = 25


class PipelineTriggerRequest(BaseModel):
    """Request body for manually triggering a pipeline run."""

    tenant_id: str
    triggered_by: str = Field("manual", description="Trigger source identifier")
    force: bool = Field(False, description="Force run even if auto-chain is disabled")
