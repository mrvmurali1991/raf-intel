"""
Standardized API response envelope for RAF Intelligence.

All API responses should use these schemas to ensure consistent structure
for API consumers. The envelope distinguishes success from failure, provides
structured error details, and carries pagination/timing metadata.

Usage in a router:
    from app.schemas.response import APIResponse, ErrorDetail, MetaInfo, ok, err

    @router.get("/items")
    def list_items() -> APIResponse:
        return ok(data=[...], meta=MetaInfo(total=100, page=1, limit=20))

    @router.get("/items/{id}")
    def get_item(id: int) -> APIResponse:
        item = fetch(id)
        if not item:
            return err("NOT_FOUND", "Item not found", status_code=404)
        return ok(data=item)
"""

# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """Structured error payload returned when success=False."""

    code: str = Field(
        ...,
        description="Machine-readable error code in SCREAMING_SNAKE_CASE.",
        examples=["NOT_FOUND", "VALIDATION_ERROR", "RATE_LIMIT_EXCEEDED"],
    )
    message: str = Field(
        ...,
        description="Human-readable error summary suitable for display.",
        examples=["Patient not found", "Validation failed"],
    )
    details: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional list of field-level or item-level error details. "
            "Each entry may include 'field', 'message', and 'value'."
        ),
        examples=[[{"field": "email", "message": "invalid email format"}]],
    )

    model_config = {"json_schema_extra": {"examples": [
        {
            "code": "VALIDATION_ERROR",
            "message": "Validation failed",
            "details": [{"field": "dob", "message": "must be a valid ISO-8601 date"}],
        }
    ]}}


class MetaInfo(BaseModel):
    """Metadata attached to successful responses — pagination, timing, tracing."""

    page: int | None = Field(default=None, description="Current page number (1-based).", ge=1)
    limit: int | None = Field(default=None, description="Maximum items per page.", ge=1)
    total: int | None = Field(default=None, description="Total matching records across all pages.", ge=0)
    has_next: bool | None = Field(default=None, description="Whether a next page exists.")
    request_id: str | None = Field(
        default=None,
        description="Echo of the X-Request-ID header for end-to-end tracing.",
    )
    duration_ms: float | None = Field(
        default=None,
        description="Server-side processing time in milliseconds.",
    )

    model_config = {"json_schema_extra": {"examples": [
        {"page": 1, "limit": 20, "total": 157, "has_next": True, "request_id": "a1b2c3d4"}
    ]}}


# ---------------------------------------------------------------------------
# Root envelope
# ---------------------------------------------------------------------------


class APIResponse(BaseModel):
    """
    Universal response envelope for RAF Intelligence API.

    - Successful responses: success=True, data=<payload>, error=None
    - Error responses:      success=False, data=None, error=<ErrorDetail>
    - Paginated responses:  success=True, data=<list>, meta=<MetaInfo with page/total>
    """

    success: bool = Field(..., description="True when the request completed without error.")
    data: Any = Field(
        default=None,
        description="Response payload. Null on error responses.",
    )
    error: ErrorDetail | None = Field(
        default=None,
        description="Structured error detail. Null on success responses.",
    )
    meta: MetaInfo | None = Field(
        default=None,
        description="Pagination, timing, and tracing metadata.",
    )

    model_config = {"json_schema_extra": {"examples": [
        {
            "success": True,
            "data": {"id": 1, "name": "John Doe"},
            "error": None,
            "meta": {"request_id": "a1b2c3d4"},
        },
        {
            "success": False,
            "data": None,
            "error": {
                "code": "NOT_FOUND",
                "message": "Patient not found",
                "details": None,
            },
            "meta": None,
        },
    ]}}


# ---------------------------------------------------------------------------
# Factory helpers — keeps router code concise
# ---------------------------------------------------------------------------


def ok(
    data: Any = None,
    meta: MetaInfo | None = None,
    request_id: str | None = None,
) -> dict:
    """
    Build a success envelope dict (use dict to avoid double-serialisation with
    JSONResponse or FastAPI's native serializer).

    Args:
        data:       The response payload.
        meta:       Optional MetaInfo. If request_id is provided separately and
                    meta is None, a MetaInfo is created with just request_id.
        request_id: Shortcut to inject request_id into meta.

    Returns:
        dict matching the APIResponse shape.
    """
    if request_id and meta is None:
        meta = MetaInfo(request_id=request_id)
    elif request_id and meta is not None:
        meta = meta.model_copy(update={"request_id": request_id})

    return {
        "success": True,
        "data": data,
        "error": None,
        "meta": meta.model_dump(exclude_none=True) if meta else None,
    }


def err(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> dict:
    """
    Build an error envelope dict.

    Args:
        code:       Machine-readable error code (e.g. "NOT_FOUND").
        message:    Human-readable error summary.
        details:    Optional list of field-level errors.
        request_id: Optional trace ID.

    Returns:
        dict matching the APIResponse shape.
    """
    meta = MetaInfo(request_id=request_id) if request_id else None
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": meta.model_dump(exclude_none=True) if meta else None,
    }
