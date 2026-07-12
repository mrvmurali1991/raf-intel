"""
Feature flags router.

Endpoints
---------
GET  /api/feature-flags             — merged registry + per-user overrides
PUT  /api/feature-flags/{key}       — body {"enabled": bool}; upsert override
POST /api/feature-flags/reset       — wipe all of the user's overrides

All endpoints require an authenticated user via ``Depends(get_current_user)``.
Flags are scoped per-user — there is no tenant fallback path here, the user
identity is mandatory.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
CurrentUser = dict
from app.services import feature_flag_service as flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feature-flags", tags=["feature-flags"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SetFlagBody(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="List all feature flags merged with the user's overrides",
)
def get_flags(
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return every registered feature flag.  Each item carries the resolved
    ``enabled`` value (registry default, overridden by the user's saved value).

    Response shape:
        {
          "user_id": 1,
          "count": 9,
          "flags": [
            {
              "key": "provider_peer_percentile",
              "name": "Peer percentile ribbon",
              "description": "...",
              "category": "Benchmarks",
              "default_enabled": true,
              "scope": "user",
              "enabled": true
            },
            ...
          ]
        }
    """
    items = flags.list_flags(current_user["id"])
    return {
        "user_id": current_user["id"],
        "count": len(items),
        "flags": items,
    }


@router.put(
    "/{key}",
    summary="Enable or disable a single feature flag for the current user",
)
def update_flag(
    key: str,
    body: SetFlagBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Upsert a per-user override.  Returns the resolved flag after the change.
    Returns 404 when *key* is not in the registry — we refuse to persist
    overrides for unknown flags.
    """
    try:
        resolved = flags.set_flag(
            user_id=current_user["id"],
            key=key,
            enabled=body.enabled,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown feature flag: {key}")
    except Exception as exc:
        logger.error("feature_flags.update_flag failed key=%s: %s", key, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"user_id": current_user["id"], "flag": resolved}


@router.post(
    "/reset",
    summary="Reset every feature flag override for the current user to defaults",
)
def reset_flags(
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Delete every override row for the current user.  Subsequent reads fall
    back to registry defaults.  Returns the number of overrides removed.
    """
    try:
        deleted = flags.reset_user_flags(current_user["id"])
    except Exception as exc:
        logger.error("feature_flags.reset_flags failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    items = flags.list_flags(current_user["id"])
    return {
        "user_id": current_user["id"],
        "deleted": deleted,
        "flags": items,
    }
