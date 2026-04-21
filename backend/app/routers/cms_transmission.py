"""
CMS SFTP File Transmission router — manage SFTP configuration, transmit
submission files to CMS, and retrieve CMS response files.

Endpoints
---------
GET    /api/cms-transmission/config                        – Get SFTP config (password masked)
PUT    /api/cms-transmission/config                        – Save / update SFTP config
POST   /api/cms-transmission/test                          – Test SFTP connection
POST   /api/cms-transmission/transmit/{submission_id}      – Transmit submission file to CMS
POST   /api/cms-transmission/check-responses               – Check for and download CMS responses
GET    /api/cms-transmission/history                       – Transmission history (paginated)
GET    /api/cms-transmission/history/{transmission_id}     – Single transmission detail

Authentication: all endpoints require a valid Bearer JWT.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id
from app.services.circuit_breaker import CircuitBreakerError
from app.services.cms_sftp_service import (
    check_for_responses,
    get_sftp_config,
    get_transmission_detail,
    get_transmission_history,
    save_sftp_config,
    test_sftp_connection,
    transmit_submission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cms-transmission", tags=["CMS Transmission"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

AuthTypeLiteral = Literal["password", "private_key"]


class SFTPConfigRequest(BaseModel):
    """Payload for creating or updating the CMS SFTP configuration."""

    host: str = Field(..., max_length=255, description="SFTP server hostname or IP address")
    port: int = Field(default=22, ge=1, le=65535, description="SFTP server port (default 22)")
    username: str = Field(..., max_length=255, description="SFTP login username")
    auth_type: AuthTypeLiteral = Field(
        default="password",
        description="Authentication method: 'password' or 'private_key'",
    )
    password: str | None = Field(
        default=None,
        description="SFTP password — required when auth_type is 'password'. Stored encrypted.",
    )
    private_key_path: str | None = Field(
        default=None,
        max_length=512,
        description="Absolute path to PEM private key on the server — required when auth_type is 'private_key'.",
    )
    remote_upload_dir: str = Field(
        default="/upload",
        max_length=512,
        description="Remote directory where submission files are deposited",
    )
    remote_response_dir: str = Field(
        default="/response",
        max_length=512,
        description="Remote directory where CMS places response / acknowledgement files",
    )

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("host must not be blank")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username must not be blank")
        return v


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

_MASK_VISIBLE_CHARS = 4


def _mask_password(password: str | None) -> str | None:
    """Return the password with all but the last 4 characters replaced by '*'.

    Returns None when no password is stored, and '****' when the password is
    shorter than or equal to the visible character count.
    """
    if password is None:
        return None
    if len(password) <= _MASK_VISIBLE_CHARS:
        return "*" * len(password)
    return "*" * (len(password) - _MASK_VISIBLE_CHARS) + password[-_MASK_VISIBLE_CHARS:]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    summary="Get SFTP configuration",
    description="Returns the stored CMS SFTP configuration for the caller's tenant. The password field is masked — only the last 4 characters are visible.",
)
def get_config(user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id)) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)
    try:
        config: dict[str, Any] = get_sftp_config(tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("Failed to retrieve SFTP config for tenant %s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve SFTP configuration.",
        ) from exc

    if config is None:
        return {"configured": False, "message": "No SFTP configuration found for this tenant."}

    # Mask the password before returning to the caller.
    if "password" in config:
        config = {**config, "password": _mask_password(config["password"])}

    return {**config, "configured": True}


@router.put(
    "/config",
    summary="Save / update SFTP configuration",
    description=(
        "Persists CMS SFTP settings for the caller's tenant. "
        "host and username are required. "
        "Supply password when auth_type='password', or private_key_path when auth_type='private_key'."
    ),
)
def update_config(
    payload: SFTPConfigRequest,
    user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)

    # Business-logic validation: ensure the correct credential field is present.
    if payload.auth_type == "password" and not payload.password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="password is required when auth_type is 'password'.",
        )
    if payload.auth_type == "private_key" and not payload.private_key_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="private_key_path is required when auth_type is 'private_key'.",
        )

    try:
        result: dict[str, Any] = save_sftp_config(
            tenant_id=tenant_id,
            config=payload.model_dump(),
        )
    except Exception as exc:
        logger.exception("Failed to save SFTP config for tenant %s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save SFTP configuration.",
        ) from exc

    return result


@router.post(
    "/test",
    summary="Test SFTP connection",
    description="Attempts to open an SFTP session with the stored configuration and returns a success or failure report.",
)
def test_connection(user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id)) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)
    try:
        result: dict[str, Any] = test_sftp_connection(tenant_id=tenant_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("SFTP connection test failed for tenant %s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SFTP connection test encountered an unexpected error. Check server logs.",
        ) from exc

    return result


@router.post(
    "/transmit/{submission_id}",
    summary="Transmit submission file to CMS",
    description="Uploads the generated submission file for the given submission_id to the CMS SFTP server and records the transmission event.",
    status_code=status.HTTP_202_ACCEPTED,
)
def transmit(
    submission_id: str,
    user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)
    try:
        result: dict[str, Any] = transmit_submission(
            tenant_id=tenant_id,
            submission_id=submission_id,
        )
    except HTTPException:
        raise
    except CircuitBreakerError as exc:
        logger.warning("CMS SFTP circuit breaker open: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CMS SFTP service is temporarily unavailable. Please retry later.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission file not found for submission_id '{submission_id}'.",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Transmission failed for submission %s (tenant %s)", submission_id, tenant_id
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Transmission to CMS failed. Check server logs for details.",
        ) from exc

    return result


@router.post(
    "/check-responses",
    summary="Check for and download CMS response files",
    description=(
        "Polls the configured CMS SFTP response directory, downloads any new acknowledgement "
        "or response files, stores them locally, and returns a summary of what was retrieved."
    ),
)
def check_responses(user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id)) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)
    try:
        result: dict[str, Any] = check_for_responses(tenant_id=tenant_id)
    except HTTPException:
        raise
    except CircuitBreakerError as exc:
        logger.warning("CMS SFTP circuit breaker open: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CMS SFTP service is temporarily unavailable. Please retry later.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except Exception as exc:
        logger.exception("Response check failed for tenant %s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not retrieve CMS response files. Check server logs.",
        ) from exc

    return result


@router.get(
    "/history",
    summary="Get transmission history",
    description="Returns a paginated list of CMS transmission events for the caller's tenant, ordered by most recent first.",
)
def list_history(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of records to return"),
    offset: int = Query(default=0, ge=0, description="Number of records to skip (for pagination)"),
    user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)
    try:
        rows = get_transmission_history(
            tenant_id=tenant_id,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("Failed to fetch transmission history for tenant %s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve transmission history.",
        ) from exc

    return {"count": len(rows), "history": rows}


@router.get(
    "/history/{transmission_id}",
    summary="Get transmission detail",
    description="Returns the full detail record for a single CMS transmission event, including status, timestamps, and any error messages.",
)
def get_history_detail(
    transmission_id: str,
    user: dict = Depends(get_current_user), tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    # tenant_id from Depends(get_tenant_id)
    try:
        result: dict[str, Any] | None = get_transmission_detail(
            tenant_id=tenant_id,
            transmission_id=transmission_id,
        )
    except Exception as exc:
        logger.exception(
            "Failed to fetch transmission %s for tenant %s", transmission_id, tenant_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve transmission detail.",
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transmission '{transmission_id}' not found.",
        )

    return result
