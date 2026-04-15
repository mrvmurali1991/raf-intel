"""
Common Pydantic schemas shared across domains.

Provides the canonical API response envelope, pagination models, and error
detail structures. Use these as base classes or return types in routers to
ensure consistent response shapes across all endpoints.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Machine-readable error detail included in non-2xx responses."""

    code: str = Field(..., description="Short error code, e.g. 'VALIDATION_ERROR'")
    message: str = Field(..., description="Human-readable error description")
    field: str | None = Field(None, description="Field that caused the error, if applicable")


class APIResponse(BaseModel, Generic[T]):
    """
    Standard API response envelope.

    All endpoints should return data wrapped in this model so that client
    code has a consistent shape to deserialise.

    Example::

        return APIResponse(success=True, data={"score": 1.23}, message="OK")
    """

    success: bool = Field(..., description="True when the request succeeded")
    data: T | None = Field(None, description="Response payload")
    message: str | None = Field(None, description="Optional human-readable message")
    errors: list[ErrorDetail] | None = Field(None, description="Error details on failure")

    @classmethod
    def ok(cls, data: Any = None, message: str | None = None) -> "APIResponse":
        return cls(success=True, data=data, message=message)

    @classmethod
    def err(cls, message: str, errors: list[ErrorDetail] | None = None) -> "APIResponse":
        return cls(success=False, data=None, message=message, errors=errors)


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response wrapper."""

    items: list[T]
    total: int = Field(..., description="Total number of matching records")
    page: int = Field(..., ge=1, description="Current page (1-indexed)")
    page_size: int = Field(..., ge=1, description="Number of items per page")
    has_next: bool = Field(..., description="True if more pages exist")
    has_prev: bool = Field(..., description="True if previous pages exist")
