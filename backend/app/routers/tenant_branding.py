"""
Tenant co-branding router (Cotiviti / WEX pattern).

Endpoints
---------
GET /api/tenant/branding       — return the current user's tenant branding row
PUT /api/tenant/branding       — admin-only upsert of the tenant branding row

The branding row drives the CSS custom properties (``--brand-primary``,
``--brand-secondary``, ``--logo-text``) on the frontend so a tenant can
re-skin the product without a code change.

If no row exists for the user's tenant a sensible default (the RAF
Intelligence house brand) is returned so the UI always has values to bind
to.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_role
from app.db import raf_cursor
from app.services.immutable_audit import emit_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


# ---------------------------------------------------------------------------
# Defaults — must match the values declared in frontend globals.css :root
# ---------------------------------------------------------------------------
_DEFAULT_BRANDING: dict[str, Any] = {
    "display_name": "RAF Intelligence",
    "brand_primary": "#0F766E",
    "brand_secondary": "#134E4A",
    "logo_text": "RAF Intel",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class BrandingBody(BaseModel):
    """Payload accepted by PUT /api/tenant/branding."""

    display_name: str | None = Field(default=None, max_length=255)
    brand_primary: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="7-char hex color, e.g. '#0F766E'.",
    )
    brand_secondary: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="7-char hex color, e.g. '#134E4A'.",
    )
    logo_text: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_payload(tenant_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a DB row (or None) into the API response shape."""
    if not row:
        return {"tenant_id": tenant_id, **_DEFAULT_BRANDING}
    return {
        "tenant_id": tenant_id,
        "display_name": row.get("display_name") or _DEFAULT_BRANDING["display_name"],
        "brand_primary": row.get("brand_primary") or _DEFAULT_BRANDING["brand_primary"],
        "brand_secondary": row.get("brand_secondary")
        or _DEFAULT_BRANDING["brand_secondary"],
        "logo_text": row.get("logo_text") or _DEFAULT_BRANDING["logo_text"],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/branding",
    summary="Get the current tenant's branding (color, logo text)",
)
def get_tenant_branding(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the branding row for the authenticated user's tenant.

    If the tenant has not customized any branding yet the response carries
    the system defaults so the frontend can always set its CSS variables.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    if not tenant_id:
        # Caller is authenticated but has no tenant — return system defaults
        # so the UI still renders.
        return {"tenant_id": "", **_DEFAULT_BRANDING}

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT tenant_id, display_name, brand_primary, brand_secondary, "
                "logo_text FROM raf_tenant_branding WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("tenant_branding.get failed tenant=%s: %s", tenant_id, exc)
        # Never break the UI on a branding lookup failure — fall back to
        # defaults instead of returning 500.
        return {"tenant_id": tenant_id, **_DEFAULT_BRANDING}

    return _row_to_payload(tenant_id, row)


@router.put(
    "/branding",
    summary="Upsert the current tenant's branding (admin only)",
)
def put_tenant_branding(
    body: BrandingBody,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Admin-only upsert.  Any field omitted from the payload keeps its existing
    DB value (or the default if no row exists yet).
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Admin has no tenant assignment — cannot edit branding.",
        )

    # Merge submitted values over the existing row so PUT acts as a partial
    # upsert (clients can send just the fields they want to change).
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT display_name, brand_primary, brand_secondary, logo_text "
                "FROM raf_tenant_branding WHERE tenant_id = %s",
                (tenant_id,),
            )
            existing = cur.fetchone() or {}

            merged = {
                "display_name": body.display_name
                if body.display_name is not None
                else existing.get("display_name") or _DEFAULT_BRANDING["display_name"],
                "brand_primary": body.brand_primary
                if body.brand_primary is not None
                else existing.get("brand_primary") or _DEFAULT_BRANDING["brand_primary"],
                "brand_secondary": body.brand_secondary
                if body.brand_secondary is not None
                else existing.get("brand_secondary")
                or _DEFAULT_BRANDING["brand_secondary"],
                "logo_text": body.logo_text
                if body.logo_text is not None
                else existing.get("logo_text") or _DEFAULT_BRANDING["logo_text"],
            }

            cur.execute(
                """
                INSERT INTO raf_tenant_branding
                    (tenant_id, display_name, brand_primary, brand_secondary, logo_text)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    display_name    = VALUES(display_name),
                    brand_primary   = VALUES(brand_primary),
                    brand_secondary = VALUES(brand_secondary),
                    logo_text       = VALUES(logo_text)
                """,
                (
                    tenant_id,
                    merged["display_name"],
                    merged["brand_primary"],
                    merged["brand_secondary"],
                    merged["logo_text"],
                ),
            )
    except Exception as exc:
        logger.error("tenant_branding.put failed tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update tenant branding.")

    # Immutable audit trail — branding changes are visible to every user in
    # the tenant and a malicious swap (e.g. phishing logo) must be
    # traceable to a specific actor + diff.
    try:
        before = {
            "display_name": existing.get("display_name"),
            "brand_primary": existing.get("brand_primary"),
            "brand_secondary": existing.get("brand_secondary"),
            "logo_text": existing.get("logo_text"),
        }
        diff = {
            k: {"before": before.get(k), "after": merged.get(k)}
            for k in merged
            if before.get(k) != merged.get(k)
        }
        if not diff:
            # No-op PUT (idempotent retry) — skip the audit emit so the
            # immutable log doesn't fill with noisy empty-diff entries.
            return {"tenant_id": tenant_id, **merged}
        emit_audit_event(
            "TENANT_BRANDING_UPDATED",
            tenant_id=tenant_id,
            actor_user_id=int(current_user.get("id") or 0),
            subject_type="tenant_branding",
            subject_id=tenant_id,
            payload={"diff": diff, "after": merged},
        )
    except Exception as exc:  # noqa: BLE001 — audit failures must not 500
        logger.warning("tenant_branding audit emit failed: %s", exc)

    return {"tenant_id": tenant_id, **merged}
