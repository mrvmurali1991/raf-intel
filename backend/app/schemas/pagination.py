"""
Pagination helpers for RAF Intelligence list endpoints.

Standardizes query-parameter parsing and response shaping for all endpoints
that return lists of resources (patients, audit logs, pipeline runs, etc.).

Usage in a router:
    from app.schemas.pagination import PaginationParams, PaginatedResponse, cursor_meta

    @router.get("/patients")
    def list_patients(
        params: PaginationParams = Depends(),
        current_user = Depends(get_current_user),
    ):
        items, total = svc.get_patients(
            tenant_id=...,
            offset=params.offset,
            limit=params.limit,
        )
        return PaginatedResponse.build(items=items, total=total, params=params)
"""

# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field
from fastapi import Query


# ---------------------------------------------------------------------------
# Query parameter schema
# ---------------------------------------------------------------------------


class PaginationParams:
    """
    Dependency-injectable pagination query parameters.

    Attach to any list endpoint via ``Depends(PaginationParams)``:

        @router.get("/items")
        def list_items(params: PaginationParams = Depends()):
            ...
    """

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number (1-based)."),
        limit: int = Query(default=20, ge=1, le=500, description="Items per page (max 500)."),
        sort_by: Optional[str] = Query(default=None, description="Field name to sort by."),
        sort_dir: Optional[str] = Query(
            default="asc",
            pattern="^(asc|desc)$",
            description="Sort direction: 'asc' or 'desc'.",
        ),
    ):
        self.page = page
        self.limit = limit
        self.sort_by = sort_by
        self.sort_dir = sort_dir

    @property
    def offset(self) -> int:
        """Zero-based row offset for SQL OFFSET clause."""
        return (self.page - 1) * self.limit

    def sql_order(self, allowed_fields: set[str], default_field: str) -> str:
        """
        Return a safe SQL ORDER BY fragment.

        Only allows sort_by values explicitly listed in *allowed_fields* to
        prevent SQL injection. Falls back to *default_field* if the requested
        field is not in the allowlist.

        Returns:
            e.g. "last_name ASC" or "created_at DESC"
        """
        field = self.sort_by if self.sort_by in allowed_fields else default_field
        direction = "DESC" if (self.sort_dir or "asc").lower() == "desc" else "ASC"
        return f"{field} {direction}"


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel):
    """
    Standardized paginated list response.

    Wraps the success envelope with pagination metadata so consumers always
    receive the same shape regardless of which resource is being listed.

    Fields mirror the APIResponse envelope but are flattened here for
    endpoints that return paginated lists directly (without the outer envelope).
    Use ``PaginatedResponse.build()`` to construct the response dict.
    """

    success: bool = True
    data: list[Any] = Field(..., description="The current page of items.")
    meta: dict[str, Any] = Field(..., description="Pagination metadata.")

    model_config = {"json_schema_extra": {"examples": [
        {
            "success": True,
            "data": [{"id": 1, "name": "Jane Smith"}],
            "meta": {
                "page": 1,
                "limit": 20,
                "total": 157,
                "has_next": True,
                "pages": 8,
            },
        }
    ]}}

    @classmethod
    def build(
        cls,
        items: list[Any],
        total: int,
        params: PaginationParams,
        request_id: Optional[str] = None,
        extra_meta: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        Build a paginated response dict ready for FastAPI to serialize.

        Args:
            items:      The current page of records.
            total:      Total number of matching records (all pages).
            params:     The PaginationParams from the request.
            request_id: Optional trace ID from request.state.request_id.
            extra_meta: Any additional keys to merge into the meta block.

        Returns:
            dict matching the PaginatedResponse / APIResponse shape.
        """
        pages = max(1, -(-total // params.limit))  # ceiling division
        has_next = params.page < pages

        meta: dict[str, Any] = {
            "page": params.page,
            "limit": params.limit,
            "total": total,
            "has_next": has_next,
            "pages": pages,
        }
        if request_id:
            meta["request_id"] = request_id
        if extra_meta:
            meta.update(extra_meta)

        return {
            "success": True,
            "data": items,
            "error": None,
            "meta": meta,
        }


# ---------------------------------------------------------------------------
# Convenience: build a cursor-based (keyset) page descriptor
# ---------------------------------------------------------------------------


def cursor_meta(
    items: list[Any],
    limit: int,
    cursor_field: str = "id",
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build metadata for cursor-based (keyset) pagination.

    Unlike offset pagination, cursor-based pagination uses the last item's
    field value as the next-page cursor. This is more efficient for large
    datasets but does not support random-page access.

    Args:
        items:        The current page of records (dicts or objects).
        limit:        The requested page size.
        cursor_field: The field used as the cursor (must be sortable and unique).
        request_id:   Optional trace ID.

    Returns:
        dict with has_next, next_cursor, and optional request_id.
    """
    has_next = len(items) == limit
    next_cursor: Optional[Any] = None
    if has_next and items:
        last = items[-1]
        next_cursor = (
            last.get(cursor_field) if isinstance(last, dict)
            else getattr(last, cursor_field, None)
        )

    meta: dict[str, Any] = {
        "has_next": has_next,
        "next_cursor": next_cursor,
        "limit": limit,
    }
    if request_id:
        meta["request_id"] = request_id
    return meta
