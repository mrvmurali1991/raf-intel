"""
RAF Intelligence schema package.

Sub-modules:
    common        — APIResponse envelope, PaginatedResponse, ErrorDetail
    auth          — LoginRequest, TokenResponse, UserResponse
    patient       — PatientResponse, PatientListResponse
    raf           — RAFScoreResponse, RAFBreakdownResponse, HCCComponent
    pipeline      — PipelineRunStatus, PipelineTriggerRequest
    api_contracts — canonical field-name contracts (patient, RAF, pipeline, etc.)
    response      — legacy APIResponse envelope (see common.py for new code)
    pagination    — PaginationParams, PaginatedResponse, cursor_meta
"""

from app.schemas.response import APIResponse, ErrorDetail, MetaInfo, ok, err
from app.schemas.pagination import PaginationParams, PaginatedResponse, cursor_meta
from app.schemas.common import APIResponse as CommonAPIResponse  # noqa: F401

__all__ = [
    # Legacy response helpers (preserved for backward compat)
    "APIResponse",
    "ErrorDetail",
    "MetaInfo",
    "ok",
    "err",
    "PaginationParams",
    "PaginatedResponse",
    "cursor_meta",
    # New common envelope
    "CommonAPIResponse",
]
