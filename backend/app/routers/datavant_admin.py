# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""
Datavant Switchboard — admin management endpoints.

Allows operators to submit chart retrieval requests, browse request history,
and verify that Datavant credentials are present and reachable.

Route prefix: /api/admin/datavant
Tags: datavant-admin
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/datavant",
    tags=["datavant-admin"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChartRequestBody(BaseModel):
    raf_patient_id: int = Field(..., description="Internal RAF patient ID")
    dos_from: str = Field(..., description="Date of service start (YYYY-MM-DD)")
    dos_to: str = Field(..., description="Date of service end (YYYY-MM-DD)")
    reason: str = Field(
        default="RAF risk adjustment coding",
        max_length=255,
        description="Clinical reason for the chart request",
    )


class ChartRequestResponse(BaseModel):
    request_id: str
    status: str
    estimated_turnaround_days: int
    db_id: Optional[int] = None


class ChartRequestRecord(BaseModel):
    id: int
    tenant_id: int
    raf_patient_id: int
    datavant_request_id: str
    submitted_at: Optional[str]
    status: str
    dos_from: Optional[str]
    dos_to: Optional[str]
    reason: Optional[str]
    cost_estimate_dollars: Optional[float]


class ChartRequestsListResponse(BaseModel):
    items: List[ChartRequestRecord]
    total: int
    limit: int
    offset: int


class CredentialsCheckResponse(BaseModel):
    configured: bool
    api_base_reachable: bool
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /api/admin/datavant/request
# ---------------------------------------------------------------------------


@router.post(
    "/request",
    response_model=ChartRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a Datavant chart retrieval request",
)
async def submit_chart_request(
    body: ChartRequestBody,
    current_user: Any = Depends(get_current_user),
) -> ChartRequestResponse:
    """Submit a new chart retrieval request to the Datavant Switchboard.

    The request is persisted in ``datavant_chart_requests`` and forwarded to
    Datavant.  Datavant will call our webhook when the chart is ready.

    Args:
        body: Patient ID, date-of-service window, and clinical reason.
        current_user: Authenticated user from bearer token.

    Returns:
        Datavant request ID, initial status, and estimated turnaround days.
    """
    from app.services.partners.datavant import DatavantClient  # noqa: PLC0415

    client = DatavantClient()

    # Build minimal demographics from the patient record.
    try:
        from app.db import raf_cursor  # noqa: PLC0415

        with raf_cursor() as cur:
            cur.execute(
                "SELECT first_name, last_name, dob, member_id "
                "FROM patients WHERE id = %s AND tenant_id = %s",
                (body.raf_patient_id, current_user.get("tenant_id")),
            )
            patient = cur.fetchone()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient {body.raf_patient_id} not found",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("datavant_admin: failed to fetch patient %s: %s", body.raf_patient_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve patient demographics",
        ) from exc

    demographics = {
        "first_name": patient.get("first_name", ""),
        "last_name": patient.get("last_name", ""),
        "dob": str(patient.get("dob", "")),
        "member_id": patient.get("member_id", ""),
    }

    try:
        result = client.submit_chart_request(
            patient_demographics=demographics,
            date_of_service_from=body.dos_from,
            date_of_service_to=body.dos_to,
            reason=body.reason,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("datavant_admin: submit_chart_request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Datavant API request failed",
        ) from exc

    # Persist to datavant_chart_requests.
    db_id: Optional[int] = None
    try:
        from app.db import raf_cursor  # noqa: PLC0415

        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO datavant_chart_requests
                    (tenant_id, raf_patient_id, datavant_request_id,
                     submitted_at, status, dos_from, dos_to, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    current_user.get("tenant_id"),
                    body.raf_patient_id,
                    result["request_id"],
                    datetime.now(timezone.utc),
                    result["status"],
                    body.dos_from,
                    body.dos_to,
                    body.reason,
                ),
            )
            db_id = cur.lastrowid
    except Exception as exc:
        logger.warning("datavant_admin: failed to persist chart request: %s", exc)

    return ChartRequestResponse(
        request_id=result["request_id"],
        status=result["status"],
        estimated_turnaround_days=result["estimated_turnaround_days"],
        db_id=db_id,
    )


# ---------------------------------------------------------------------------
# GET /api/admin/datavant/requests
# ---------------------------------------------------------------------------


@router.get(
    "/requests",
    response_model=ChartRequestsListResponse,
    summary="List Datavant chart retrieval requests",
)
async def list_chart_requests(
    filter_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Any = Depends(get_current_user),
) -> ChartRequestsListResponse:
    """Return a paginated list of Datavant chart requests for the current tenant.

    Args:
        filter_status: Optional status filter (e.g. ``submitted``, ``complete``).
        limit: Page size (default 20, max 200).
        offset: Row offset for pagination.
        current_user: Authenticated user from bearer token.

    Returns:
        Paginated list of chart request records with total count.
    """
    tenant_id = current_user.get("tenant_id")
    try:
        from app.db import raf_cursor  # noqa: PLC0415

        with raf_cursor() as cur:
            if filter_status:
                cur.execute(
                    """
                    SELECT SQL_CALC_FOUND_ROWS
                        id, tenant_id, raf_patient_id, datavant_request_id,
                        submitted_at, status, dos_from, dos_to, reason,
                        cost_estimate_dollars
                      FROM datavant_chart_requests
                     WHERE tenant_id = %s AND status = %s
                     ORDER BY submitted_at DESC
                     LIMIT %s OFFSET %s
                    """,
                    (tenant_id, filter_status, limit, offset),
                )
            else:
                cur.execute(
                    """
                    SELECT SQL_CALC_FOUND_ROWS
                        id, tenant_id, raf_patient_id, datavant_request_id,
                        submitted_at, status, dos_from, dos_to, reason,
                        cost_estimate_dollars
                      FROM datavant_chart_requests
                     WHERE tenant_id = %s
                     ORDER BY submitted_at DESC
                     LIMIT %s OFFSET %s
                    """,
                    (tenant_id, limit, offset),
                )
            rows = cur.fetchall() or []
            cur.execute("SELECT FOUND_ROWS()")
            total = (cur.fetchone() or {}).get("FOUND_ROWS()", len(rows))
    except Exception as exc:
        logger.error("datavant_admin: list_chart_requests failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query chart requests",
        ) from exc

    items = [
        ChartRequestRecord(
            id=r["id"],
            tenant_id=r["tenant_id"],
            raf_patient_id=r["raf_patient_id"],
            datavant_request_id=r["datavant_request_id"],
            submitted_at=str(r["submitted_at"]) if r.get("submitted_at") else None,
            status=r["status"],
            dos_from=str(r["dos_from"]) if r.get("dos_from") else None,
            dos_to=str(r["dos_to"]) if r.get("dos_to") else None,
            reason=r.get("reason"),
            cost_estimate_dollars=(
                float(r["cost_estimate_dollars"])
                if r.get("cost_estimate_dollars") is not None
                else None
            ),
        )
        for r in rows
    ]
    return ChartRequestsListResponse(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# GET /api/admin/datavant/credentials/check
# ---------------------------------------------------------------------------


@router.get(
    "/credentials/check",
    response_model=CredentialsCheckResponse,
    summary="Check Datavant credentials configuration",
)
async def credentials_check(
    current_user: Any = Depends(get_current_user),
) -> CredentialsCheckResponse:
    """Verify that Datavant credentials are configured and the API base is reachable.

    Checks environment variables without making a real chart-request.  The
    reachability test performs an HTTP HEAD request to ``DATAVANT_API_BASE``
    with a 5-second timeout.

    Args:
        current_user: Authenticated user from bearer token.

    Returns:
        ``configured`` (bool) — all three env vars are non-empty.
        ``api_base_reachable`` (bool) — HTTP HEAD to api_base returned < 500.
        ``detail`` — human-readable explanation when not configured.
    """
    api_base = os.getenv("DATAVANT_API_BASE", "")
    api_key = os.getenv("DATAVANT_API_KEY", "")
    customer_id = os.getenv("DATAVANT_CUSTOMER_ID", "")

    configured = bool(api_base and api_key and customer_id)

    if not configured:
        missing = [
            name
            for name, val in [
                ("DATAVANT_API_BASE", api_base),
                ("DATAVANT_API_KEY", api_key),
                ("DATAVANT_CUSTOMER_ID", customer_id),
            ]
            if not val
        ]
        return CredentialsCheckResponse(
            configured=False,
            api_base_reachable=False,
            detail=f"Missing env vars: {', '.join(missing)}",
        )

    # Attempt a lightweight reachability probe.
    reachable = False
    detail: Optional[str] = None
    try:
        import httpx  # noqa: PLC0415

        with httpx.Client(timeout=5.0) as client:
            resp = client.head(api_base)
            reachable = resp.status_code < 500
            detail = f"HTTP {resp.status_code}"
    except Exception as exc:
        logger.debug("swallowed exception", exc_info=True)
        detail = f"Unreachable: {exc}"

    return CredentialsCheckResponse(
        configured=True,
        api_base_reachable=reachable,
        detail=detail,
    )
