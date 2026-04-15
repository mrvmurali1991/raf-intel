"""
Authentication Pydantic schemas.

Used by the auth router for request validation and response serialisation.
Keeping schemas separate from router logic enables reuse across tests,
CLI tools, and other consumers.
"""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials submitted to POST /api/auth/login."""

    email: EmailStr = Field(..., description="User's registered email address")
    password: str = Field(..., min_length=1, description="Plain-text password")
    mfa_code: str | None = Field(None, description="TOTP code if MFA is enabled")


class TokenResponse(BaseModel):
    """Successful authentication response containing access and refresh tokens."""

    access_token: str = Field(..., description="Short-lived JWT access token")
    refresh_token: str = Field(..., description="Long-lived refresh token")
    token_type: str = Field("bearer", description="OAuth2 token type")
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    """Request body for POST /api/auth/refresh."""

    refresh_token: str = Field(..., description="Valid refresh token")


class UserResponse(BaseModel):
    """Public user profile returned by GET /api/auth/me."""

    id: int
    email: str
    full_name: str | None = None
    role: str | None = None
    tenant_id: str | None = None
    is_active: bool = True
    mfa_enabled: bool = False


class ChangePasswordRequest(BaseModel):
    """Request body for POST /api/auth/change-password."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
