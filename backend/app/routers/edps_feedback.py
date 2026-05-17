"""
EDPS / CMS MAO-004 feedback router.

Two endpoints — both tenant-scoped — drive the RAF Reconciliation card:

* ``POST /api/edps/feedback/upload``
      Multipart CSV upload. Parsed by
      :func:`app.services.edps_ingest.parse_mao004_csv` and bulk-inserted
      via :func:`app.services.edps_ingest.upsert_edps_rows`. Returns an
      ingest summary (row counts + per-row error notes).

* ``GET /api/edps/feedback/{patient_id}?year=YYYY``
      Returns the latest CMS response we have on file for that patient
      and measurement year. 404 when none has been received yet.

The frontend consumes the GET shape indirectly via the
``/api/raf-central/{pid}`` payload — see ``router_central.py`` for the
join into ``financial_impact.accepted_raf``. The dedicated GET here is
exposed mostly for debugging and for tools that want to surface the
underlying CMS response history.
"""

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services.edps_ingest import (
    EDPS_CSV_COLUMNS,
    get_latest_feedback,
    parse_mao004_csv,
    upsert_edps_rows,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/edps/feedback", tags=["edps-feedback"])

# CMS MAO-004 files arrive in modest sizes (one plan-year batch). Cap the
# upload at 10 MB — anything bigger is almost certainly an unrelated file.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class EDPSIngestSummary(BaseModel):
    """Outcome of a single CSV upload."""

    rows_total: int = Field(..., description="Rows seen in the CSV (excluding header).")
    rows_upserted: int = Field(..., description="Rows successfully inserted.")
    rows_failed: int = Field(..., description="Rows rejected for any reason.")
    errors: list[str] = Field(
        default_factory=list,
        description="First 50 row-level error messages (if any).",
    )
    expected_columns: list[str] = Field(
        default_factory=lambda: list(EDPS_CSV_COLUMNS),
        description="Header contract enforced by the parser.",
    )


class EDPSFeedback(BaseModel):
    """Latest CMS response for a patient + measurement year."""

    id: int
    patient_id: int
    measurement_year: int
    tenant_id: str
    accepted_raf: Optional[float] = Field(
        None,
        description="CMS-accepted RAF score (sum of accepted-HCC coefficients + demographics).",
    )
    accepted_hcc_codes: list[int] = Field(default_factory=list)
    rejected_hcc_codes: list[int] = Field(default_factory=list)
    rejected_hcc_details: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Per-HCC reject detail when the CSV carried "
            "``rejected_hcc_details_json``. Each entry has keys "
            "hcc_code, reason_code, reason_text, encounter_id."
        ),
    )
    response_received_at: Optional[str] = None
    ingested_at: Optional[str] = None


class EDPSFeedbackListItem(BaseModel):
    """One submission row in the aggregate ``GET /api/edps/feedback`` list."""

    id: int
    patient_id: int
    measurement_year: int
    tenant_id: str
    accepted_raf: Optional[float] = None
    accepted_hcc_codes: list[int] = Field(default_factory=list)
    rejected_hcc_codes: list[int] = Field(default_factory=list)
    rejected_hcc_details: list[dict[str, Any]] = Field(default_factory=list)
    response_received_at: Optional[str] = None
    ingested_at: Optional[str] = None


class EDPSFeedbackListResponse(BaseModel):
    year: int
    tenant_id: str
    total: int
    items: list[EDPSFeedbackListItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=EDPSIngestSummary,
    summary="Upload a CMS MAO-004 CSV response file",
)
@limiter.limit("20/minute")
async def upload_feedback(
    request: Request,
    file: UploadFile = File(
        ...,
        description=(
            "CSV file with header: "
            "patient_id,measurement_year,accepted_raf,"
            "accepted_hcc_codes,rejected_hcc_codes,response_received_at"
            "[,rejected_hcc_details_json]"
        ),
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> EDPSIngestSummary:
    fname = (file.filename or "").strip().lower()
    if not fname.endswith(".csv"):
        # Keep the door open for a future ``.dat`` fixed-width path by
        # rejecting only the unknown extensions explicitly.
        raise HTTPException(
            status_code=422,
            detail="EDPS feedback ingest currently accepts only .csv uploads.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large. Max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB "
                "for MAO-004 CSV uploads."
            ),
        )

    tenant_id = get_tenant_id(current_user)

    try:
        rows = parse_mao004_csv(content)
    except ValueError as exc:
        # Header validation surfaces as a 422 with the expected schema so
        # the user can fix and retry without reading our docs.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("edps upload: parser crashed")
        raise HTTPException(
            status_code=500, detail=f"Failed to parse CSV: {exc}"
        ) from exc

    result = upsert_edps_rows(rows, tenant_id=str(tenant_id))
    logger.info(
        "edps upload: tenant=%s file=%s total=%s upserted=%s failed=%s",
        tenant_id,
        file.filename,
        result.rows_total,
        result.rows_upserted,
        result.rows_failed,
    )
    return EDPSIngestSummary(
        rows_total=result.rows_total,
        rows_upserted=result.rows_upserted,
        rows_failed=result.rows_failed,
        errors=result.errors[:50],
    )


# ---------------------------------------------------------------------------
# GET / (aggregate listing) — must be declared BEFORE the path-param route
# below so FastAPI does not match "" against /{patient_id}.
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=EDPSFeedbackListResponse,
    summary="List all EDPS feedback submissions for the caller's tenant + year",
)
@limiter.limit("60/minute")
def list_feedback(
    request: Request,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> EDPSFeedbackListResponse:
    """Return every EDPS submission for the caller's tenant in *year*.

    Includes the new ``rejected_hcc_details`` per row when the CSV carried
    it. Backward compatible: rows ingested without the optional column
    return an empty list for that field instead of failing.
    """
    from app.db import raf_cursor as _raf_cursor

    import json as _json

    measurement_year = year or date.today().year
    tenant_id = get_tenant_id(current_user)

    items: list[EDPSFeedbackListItem] = []
    with _raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, patient_id, measurement_year, tenant_id,
                   accepted_raf, accepted_hcc_codes, rejected_hcc_codes,
                   rejected_hcc_details,
                   response_received_at, ingested_at
              FROM raf_edps_feedback
             WHERE tenant_id = %s
               AND measurement_year = %s
             ORDER BY COALESCE(response_received_at, ingested_at) DESC, id DESC
            """,
            (str(tenant_id), int(measurement_year)),
        )
        rows = cur.fetchall() or []

    for row in rows:
        out = dict(row)
        if out.get("accepted_raf") is not None:
            try:
                out["accepted_raf"] = float(out["accepted_raf"])
            except (TypeError, ValueError):
                out["accepted_raf"] = None
        for col in ("accepted_hcc_codes", "rejected_hcc_codes", "rejected_hcc_details"):
            val = out.get(col)
            if isinstance(val, (bytes, bytearray)):
                val = val.decode("utf-8")
            if isinstance(val, str):
                try:
                    out[col] = _json.loads(val)
                except _json.JSONDecodeError:
                    out[col] = []
            elif val is None:
                out[col] = []
        for col in ("response_received_at", "ingested_at"):
            if hasattr(out.get(col), "isoformat"):
                out[col] = out[col].isoformat()
        items.append(EDPSFeedbackListItem(**out))

    return EDPSFeedbackListResponse(
        year=measurement_year,
        tenant_id=str(tenant_id),
        total=len(items),
        items=items,
    )


# ---------------------------------------------------------------------------
# GET /{patient_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{patient_id}",
    response_model=EDPSFeedback,
    summary="Latest EDPS feedback for a patient + measurement year",
)
@limiter.limit("120/minute")
def get_feedback(
    request: Request,
    patient_id: int,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> EDPSFeedback:
    """Return the most-recent CMS response for a given pid + year.

    Tenant-scoped through ``get_tenant_id``: callers can only see rows
    written by their own tenant. ``year`` defaults to the current
    calendar year so the common case (today's measurement year) needs
    no query string.
    """
    measurement_year = year or date.today().year
    tenant_id = get_tenant_id(current_user)

    row: Optional[dict] = get_latest_feedback(
        patient_id=patient_id,
        measurement_year=measurement_year,
        tenant_id=str(tenant_id),
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No EDPS feedback on file for patient {patient_id} "
                f"in measurement year {measurement_year}."
            ),
        )
    return EDPSFeedback(**row)
