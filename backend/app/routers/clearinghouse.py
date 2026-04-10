"""
Clearinghouse Integration router — real-time eligibility verification
via ANSI X12 270/271 transactions and modern REST APIs.

Endpoints
---------
POST   /api/clearinghouse/connections           – Create a new connection
GET    /api/clearinghouse/connections           – List connections
PUT    /api/clearinghouse/connections/{id}      – Update a connection
POST   /api/clearinghouse/connections/{id}/test – Test connection reachability
POST   /api/clearinghouse/check                 – Single eligibility check
POST   /api/clearinghouse/batch                 – Batch eligibility verification
GET    /api/clearinghouse/checks                – List checks with filters
GET    /api/clearinghouse/checks/{id}           – Check detail (includes payloads)
GET    /api/clearinghouse/batch/{id}            – Batch status and progress
GET    /api/clearinghouse/dashboard             – Aggregate statistics

Authentication: all endpoints require a valid Bearer JWT.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id
from app.services.clearinghouse_service import (
    create_batch,
    create_connection,
    get_batch,
    get_check,
    get_dashboard_stats,
    list_checks,
    list_connections,
    run_eligibility_check,
    test_connection,
    update_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clearinghouse", tags=["clearinghouse"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

VendorLiteral = Literal[
    "availity",
    "change_healthcare",
    "waystar",
    "trizetto",
    "custom",
]

ConnectionStatusLiteral = Literal["active", "inactive", "testing"]

ServiceTypeLiteral = Literal[
    "health_benefit_plan",
    "medicare_part_a",
    "medicare_part_b",
    "medicare_advantage",
]


class CreateConnectionRequest(BaseModel):
    """Payload for creating a new clearinghouse connection."""
    name: str = Field(
        ...,
        max_length=255,
        description="Human-readable label for this connection",
    )
    vendor: VendorLiteral = Field(
        default="custom",
        description="Clearinghouse vendor identifier",
    )
    api_base_url: str = Field(
        ...,
        max_length=512,
        description="Base URL for the vendor REST API or X12 gateway (https://...)",
    )
    api_key: str | None = Field(
        default=None,
        description="API key or OAuth client ID — encrypted at rest",
    )
    api_secret: str | None = Field(
        default=None,
        description="API secret or OAuth client secret — encrypted at rest",
    )
    sender_id: str | None = Field(
        default=None,
        max_length=50,
        description="X12 ISA06 sender identifier",
    )
    receiver_id: str | None = Field(
        default=None,
        max_length=50,
        description="X12 ISA08 receiver identifier",
    )
    submitter_id: str | None = Field(
        default=None,
        max_length=50,
        description="NPI or Tax ID of the submitting organisation",
    )
    test_mode: bool = Field(
        default=True,
        description=(
            "When True (default) all transactions are sent to the vendor sandbox. "
            "Set False only after verifying credentials in test mode."
        ),
    )
    status: ConnectionStatusLiteral = Field(
        default="testing",
        description="Initial operational status",
    )

    @field_validator("api_base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("api_base_url must begin with http:// or https://")
        return v.rstrip("/")


class UpdateConnectionRequest(BaseModel):
    """Fields that may be updated on an existing clearinghouse connection."""
    name: str | None = Field(default=None, max_length=255)
    api_base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, description="Replaces the stored API key (re-encrypted)")
    api_secret: str | None = Field(default=None, description="Replaces the stored API secret (re-encrypted)")
    sender_id: str | None = Field(default=None, max_length=50)
    receiver_id: str | None = Field(default=None, max_length=50)
    submitter_id: str | None = Field(default=None, max_length=50)
    test_mode: bool | None = Field(default=None)
    status: ConnectionStatusLiteral | None = Field(default=None)

    @field_validator("api_base_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("api_base_url must begin with http:// or https://")
        return v.rstrip("/") if v else v


class EligibilityCheckRequest(BaseModel):
    """Payload for a single real-time eligibility check."""
    connection_id: int = Field(
        ...,
        description="ID of the clearinghouse_connections record to use",
    )
    member_id: str = Field(
        ...,
        max_length=100,
        description="Health plan member / subscriber ID",
    )
    patient_name: str = Field(
        ...,
        max_length=255,
        description='Patient full name in "LAST FIRST" format',
    )
    patient_dob: str = Field(
        ...,
        description="Patient date of birth — YYYY-MM-DD or YYYYMMDD",
    )
    payer_id: str = Field(
        ...,
        max_length=20,
        description="ANSI/ACAS payer ID (e.g. '00001' for Aetna)",
    )
    payer_name: str = Field(
        default="",
        max_length=255,
        description="Human-readable payer name",
    )
    service_type: ServiceTypeLiteral = Field(
        default="health_benefit_plan",
        description="X12 service type category for the inquiry",
    )
    patient_id: int | None = Field(
        default=None,
        description="Optional OpenEMR patient ID (pid) to link the check to a patient record",
    )
    use_cache: bool = Field(
        default=True,
        description=(
            "Return a cached result (up to 4 hours old) when available. "
            "Set False to force a fresh inquiry."
        ),
    )

    @field_validator("patient_dob")
    @classmethod
    def validate_dob(cls, v: str) -> str:
        # Accept YYYYMMDD or YYYY-MM-DD
        normalised = v.replace("-", "")
        if not normalised.isdigit() or len(normalised) != 8:
            raise ValueError("patient_dob must be YYYYMMDD or YYYY-MM-DD")
        return v


class BatchPatientRecord(BaseModel):
    """One patient entry within a batch eligibility request."""
    member_id: str = Field(..., max_length=100)
    patient_name: str = Field(..., max_length=255)
    patient_dob: str = Field(..., description="YYYYMMDD or YYYY-MM-DD")
    payer_id: str = Field(..., max_length=20)
    payer_name: str = Field(default="", max_length=255)
    service_type: ServiceTypeLiteral = Field(default="health_benefit_plan")
    patient_id: int | None = Field(default=None)

    @field_validator("patient_dob")
    @classmethod
    def validate_dob(cls, v: str) -> str:
        normalised = v.replace("-", "")
        if not normalised.isdigit() or len(normalised) != 8:
            raise ValueError("patient_dob must be YYYYMMDD or YYYY-MM-DD")
        return v


class BatchCheckRequest(BaseModel):
    """Payload for a batch eligibility verification job."""
    connection_id: int = Field(
        ...,
        description="ID of the clearinghouse connection to use for all checks in this batch",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional label for this batch run (e.g. 'May 2026 Roster Check')",
    )
    patients: list[BatchPatientRecord] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of patient records to verify (1–500 per batch)",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connection_or_404(connection_id: int, tenant_id: str) -> dict[str, Any]:
    """Verify a connection exists and belongs to this tenant."""
    from app.services.clearinghouse_service import get_connection
    conn = get_connection(connection_id)
    if not conn or str(conn.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clearinghouse connection {connection_id} not found.",
        )
    return conn


def _check_or_404(check_id: int, tenant_id: str) -> dict[str, Any]:
    """Verify an eligibility check exists and belongs to this tenant."""
    check = get_check(check_id)
    if not check or str(check.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Eligibility check {check_id} not found.",
        )
    return check


def _batch_or_404(batch_id: int, tenant_id: str) -> dict[str, Any]:
    """Verify a batch job exists and belongs to this tenant."""
    batch = get_batch(batch_id)
    if not batch or str(batch.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Eligibility batch {batch_id} not found.",
        )
    return batch


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

@router.get(
    "/connections",
    summary="List clearinghouse connections",
)
def list_clearinghouse_connections(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return all clearinghouse connections for the current tenant.

    API keys and secrets are never included in the response.
    """
    try:
        connections = list_connections(tenant_id)
        return {"total": len(connections), "connections": connections}
    except Exception as exc:
        logger.error("clearinghouse/connections list error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve connections.",
        )


@router.post(
    "/connections",
    status_code=status.HTTP_201_CREATED,
    summary="Create a clearinghouse connection",
)
def create_clearinghouse_connection(
    body: CreateConnectionRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Register a new clearinghouse vendor connection.

    API keys and secrets are encrypted at rest using AES-256-GCM before being
    stored; plaintext credentials are never persisted.

    New connections default to ``test_mode=True`` and ``status=testing``.
    Activate the connection (``status=active``, ``test_mode=False``) only
    after verifying credentials with ``POST /connections/{id}/test``.
    """
    try:
        conn_id = create_connection(
            tenant_id=tenant_id,
            name=body.name,
            vendor=body.vendor,
            api_base_url=body.api_base_url,
            api_key=body.api_key,
            api_secret=body.api_secret,
            sender_id=body.sender_id,
            receiver_id=body.receiver_id,
            submitter_id=body.submitter_id,
            test_mode=body.test_mode,
            status=body.status,
        )
    except Exception as exc:
        if "Duplicate" in str(exc) or "1062" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A connection named '{body.name}' already exists.",
            )
        logger.error("clearinghouse/connections create error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create connection.",
        )

    logger.info(
        "clearinghouse/connections: created id=%d vendor=%s user=%s tenant=%s",
        conn_id, body.vendor, current_user.get("id"), tenant_id,
    )
    conn = _connection_or_404(conn_id, tenant_id)
    # Strip encrypted credential fields before returning
    conn.pop("api_key_encrypted", None)
    conn.pop("api_secret_encrypted", None)
    return conn


@router.put(
    "/connections/{connection_id}",
    summary="Update a clearinghouse connection",
)
def update_clearinghouse_connection(
    connection_id: int,
    body: UpdateConnectionRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Update mutable fields on an existing clearinghouse connection.

    Providing ``api_key`` or ``api_secret`` replaces the stored value with a
    freshly encrypted copy.  Omit these fields to leave credentials unchanged.
    """
    _connection_or_404(connection_id, tenant_id)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update.",
        )

    try:
        success = update_connection(connection_id, tenant_id, **updates)
    except Exception as exc:
        logger.error("clearinghouse/connections update error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update connection.",
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update had no effect.",
        )

    conn = _connection_or_404(connection_id, tenant_id)
    conn.pop("api_key_encrypted", None)
    conn.pop("api_secret_encrypted", None)
    return conn


@router.post(
    "/connections/{connection_id}/test",
    summary="Test a clearinghouse connection",
)
def test_clearinghouse_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Probe the configured clearinghouse endpoint to verify credentials and
    network reachability.

    A synthetic test inquiry is sent (never stored as a billable transaction).
    Returns ``{"success": true, "message": "..."}`` on success.
    """
    _connection_or_404(connection_id, tenant_id)
    try:
        result = test_connection(connection_id, tenant_id)
    except Exception as exc:
        logger.error("clearinghouse/connections test error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Connection test failed with an unexpected error.",
        )

    logger.info(
        "clearinghouse/connections: test id=%d success=%s user=%s",
        connection_id, result.get("success"), current_user.get("id"),
    )
    return result


# ---------------------------------------------------------------------------
# Single eligibility check
# ---------------------------------------------------------------------------

@router.post(
    "/check",
    status_code=status.HTTP_201_CREATED,
    summary="Run a single real-time eligibility check",
)
def single_eligibility_check(
    body: EligibilityCheckRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Submit a real-time eligibility inquiry (ANSI X12 270) and receive the
    parsed coverage response (271).

    The result is persisted to ``eligibility_checks`` and returned immediately.
    For Medicare Advantage members the response includes ``raf_relevant_info``
    with CMS contract ID, PBP, plan type, and star rating where available.

    Results are cached for up to 4 hours per ``(tenant, member_id, payer_id,
    service_type, date)`` combination.  Pass ``use_cache=false`` to force a
    fresh inquiry.
    """
    _connection_or_404(body.connection_id, tenant_id)

    try:
        result = run_eligibility_check(
            tenant_id=tenant_id,
            connection_id=body.connection_id,
            member_id=body.member_id,
            patient_name=body.patient_name,
            patient_dob=body.patient_dob,
            payer_id=body.payer_id,
            payer_name=body.payer_name,
            service_type=body.service_type,
            patient_id=body.patient_id,
            use_cache=body.use_cache,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request")
    except Exception as exc:
        logger.error("clearinghouse/check error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Eligibility check failed.",
        )

    logger.info(
        "clearinghouse/check: check_id=%s member=%s eligible=%s user=%s",
        result.get("id"), body.member_id, result.get("is_eligible"), current_user.get("id"),
    )
    # Strip raw X12 / JSON payloads from the default response for brevity
    result.pop("request_payload", None)
    result.pop("response_payload", None)
    return result


# ---------------------------------------------------------------------------
# Batch eligibility
# ---------------------------------------------------------------------------

@router.post(
    "/batch",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a batch eligibility verification job",
)
def submit_batch_check(
    body: BatchCheckRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Enqueue a batch eligibility verification job for a list of patients (1–500).

    The batch is processed synchronously for small lists and tracked in
    ``eligibility_batch``.  Poll ``GET /batch/{id}`` for progress.

    Each patient record requires: ``member_id``, ``patient_name``,
    ``patient_dob``, ``payer_id``.
    """
    _connection_or_404(body.connection_id, tenant_id)

    patients_raw = [p.model_dump() for p in body.patients]

    try:
        batch_id = create_batch(
            tenant_id=tenant_id,
            connection_id=body.connection_id,
            name=body.name,
            patient_records=patients_raw,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request")
    except Exception as exc:
        logger.error("clearinghouse/batch create error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create batch.",
        )

    logger.info(
        "clearinghouse/batch: batch_id=%d count=%d user=%s tenant=%s",
        batch_id, len(patients_raw), current_user.get("id"), tenant_id,
    )
    batch = _batch_or_404(batch_id, tenant_id)
    return batch


# ---------------------------------------------------------------------------
# Checks — list and detail
# ---------------------------------------------------------------------------

@router.get(
    "/checks",
    summary="List eligibility checks",
)
def list_eligibility_checks(
    connection_id: int | None  = Query(default=None, description="Filter by connection"),
    patient_id:    int | None  = Query(default=None, description="Filter by patient"),
    payer_id:      str | None  = Query(default=None, description="Filter by payer ID"),
    check_status:  str | None  = Query(
        default=None,
        alias="status",
        description="Filter by status: pending, submitted, completed, error, timeout",
    ),
    service_type:  str | None  = Query(default=None, description="Filter by service type"),
    date_from:     str | None  = Query(default=None, description="check_date >= (YYYY-MM-DD)"),
    date_to:       str | None  = Query(default=None, description="check_date <= (YYYY-MM-DD)"),
    limit:         int         = Query(default=50, ge=1, le=200, description="Page size"),
    offset:        int         = Query(default=0, ge=0, description="Pagination offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return a paginated list of eligibility checks for the current tenant.

    Raw request/response payloads are excluded; use ``GET /checks/{id}`` to
    retrieve the full payload for a specific check.
    """
    _valid_statuses = {"pending", "submitted", "completed", "error", "timeout", None}
    if check_status not in _valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be one of: pending, submitted, completed, error, timeout",
        )

    try:
        rows, total = list_checks(
            tenant_id=tenant_id,
            connection_id=connection_id,
            patient_id=patient_id,
            payer_id=payer_id,
            status=check_status,
            service_type=service_type,
            check_date_from=date_from,
            check_date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("clearinghouse/checks list error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve eligibility checks.",
        )

    return {
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "checks": rows,
    }


@router.get(
    "/checks/{check_id}",
    summary="Get eligibility check detail",
)
def get_eligibility_check(
    check_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return full detail for a single eligibility check, including the raw
    X12 270 request and 271 response payloads.

    The ``raf_relevant_info`` field contains Medicare Advantage plan details
    (CMS contract ID, PBP, plan type, star rating) where available.
    """
    return _check_or_404(check_id, tenant_id)


# ---------------------------------------------------------------------------
# Batch status
# ---------------------------------------------------------------------------

@router.get(
    "/batch/{batch_id}",
    summary="Get batch eligibility job status",
)
def get_batch_status(
    batch_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return the current status and progress counters for a batch eligibility job.

    Poll this endpoint at a reasonable interval (e.g. every 5 seconds) until
    ``status`` is ``completed`` or ``error``.  The ``completed`` and ``failed``
    counters update incrementally as individual checks finish.
    """
    batch = _batch_or_404(batch_id, tenant_id)

    # Compute derived progress percentage
    total = batch.get("total_checks") or 0
    done  = (batch.get("completed") or 0) + (batch.get("failed") or 0)
    batch["progress_pct"] = round(done / total * 100, 1) if total > 0 else 0

    return batch


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    summary="Clearinghouse dashboard statistics",
)
def clearinghouse_dashboard(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return aggregate clearinghouse statistics for the current tenant:

    - Active / inactive / testing connection counts
    - Today's check volume, eligibility rate, error rate, avg response time
    - Month-to-date check and eligibility totals
    - The 5 most recent checks

    This endpoint is designed for a summary card or operational dashboard.
    """
    try:
        return get_dashboard_stats(tenant_id)
    except Exception as exc:
        logger.error("clearinghouse/dashboard error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard statistics.",
        )
