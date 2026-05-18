"""
Suspects router — manages suspect conditions (missing / unconfirmed HCC codes).

Table: raf_suspect_conditions
  id, patient_id, measurement_year, suspect_hcc, suspect_icd10,
  evidence_type  ENUM('medication','lab','imaging','referral','historical'),
  evidence_detail JSON, confidence_score DECIMAL(5,4),
  status  ENUM('open','accepted','dismissed','coded'),
  reviewed_by, reviewed_at, created_at, updated_at

Endpoints
---------
GET  /api/suspects                   – all open suspects, sorted by confidence
GET  /api/suspects/{pid}             – suspects for a single patient
POST /api/suspects/scan/{pid}        – run full suspect scan for a patient
POST /api/suspects/scan-all          – run suspect scan for every patient
PUT  /api/suspects/{suspect_id}/accept   – mark accepted / coded
PUT  /api/suspects/{suspect_id}/dismiss  – mark dismissed
POST /api/suspects/bulk-update       – bulk accept or dismiss
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from mysql.connector.errors import Error as MySQLError

from app.auth import get_current_user, require_permission
from app.db import raf_cursor
from app.rate_limit import limiter
from app.services.openemr_connector import get_all_patients, get_patient
from app.services.redis_cache import (
    invalidate_hedis_scores,
    invalidate_v28_portfolio,
)
from app.services.suspect_engine import (
    accept_suspect,
    dismiss_suspect,
    get_all_open_suspects,
    get_suspects_for_patient,
    run_full_suspect_scan,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Override-gate helpers
# ---------------------------------------------------------------------------

# MEAT statuses that make an accept "risky" and require an override reason.
_RISKY_MEAT_STATUSES: frozenset[str] = frozenset(
    {"partial", "incomplete", "unknown", "pending_rule_review"}
)

_MIN_OVERRIDE_REASON_LEN = 20


def _compute_risk_factors(suspect_id: int, tenant_id: str) -> list[str]:
    """Return a list of human-readable risk-factor strings for a suspect.

    Queries raf_suspect_conditions for confidence + the joined raf_patient_hcc
    row for meat_status, and the immutable_audit_log for any recent
    CLINICAL_RULE_GATE_DENIED event for this suspect's HCC + patient.

    If data is missing or the query fails, returns an empty list so callers
    treat the accept as NOT risky (graceful degradation per spec).
    """
    factors: list[str] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT sc.confidence_score,
                       sc.suspect_hcc,
                       sc.patient_id,
                       ph.meat_status
                FROM   raf_suspect_conditions sc
                LEFT JOIN raf_patient_hcc ph
                       ON ph.patient_id  = sc.patient_id
                      AND ph.hcc_code    = sc.suspect_hcc
                      AND ph.tenant_id   = sc.tenant_id
                WHERE  sc.id        = %s
                  AND  sc.tenant_id = %s
                LIMIT 1
                """,
                (suspect_id, tenant_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning(
            "_compute_risk_factors: DB query failed for suspect=%s — treating as not risky: %s",
            suspect_id, exc,
        )
        return []

    if not row:
        return []

    confidence = float(row.get("confidence_score") or 1.0)
    meat_status: str | None = (row.get("meat_status") or "").lower() or None
    suspect_hcc: int | None = row.get("suspect_hcc")
    patient_id: int | None = row.get("patient_id")

    if confidence < 0.70:
        factors.append(f"low_confidence:{confidence:.2f}")

    if meat_status and meat_status in _RISKY_MEAT_STATUSES:
        factors.append(f"meat_status:{meat_status}")

    # Check immutable_audit_log for a recent CLINICAL_RULE_GATE_DENIED event
    # for this patient+HCC combination (within current measurement year).
    if suspect_hcc and patient_id:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM   immutable_audit_log
                    WHERE  event_type  = 'CLINICAL_RULE_GATE_DENIED'
                      AND  patient_id  = %s
                      AND  JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.hcc_code')) = %s
                    ORDER BY event_ts DESC
                    LIMIT 1
                    """,
                    (str(patient_id), str(suspect_hcc)),
                )
                denied_row = cur.fetchone()
            if denied_row:
                factors.append(f"clinical_rule_denied:hcc{suspect_hcc}")
        except Exception as exc:
            logger.warning(
                "_compute_risk_factors: audit_log query failed for suspect=%s hcc=%s — skipping rule check: %s",
                suspect_id, suspect_hcc, exc,
            )

    return factors

router = APIRouter(prefix="/api/suspects", tags=["suspects"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


# RADV defense-basis allow-list. Must match
# frontend/src/components/AcceptConfirmDialog.tsx DEFENSE_BASIS_OPTIONS.
# Enforced server-side so a scripted POST cannot bypass the UI gate
# (patient-safety round-3 new gap #1). "Re-billing correction" was
# intentionally removed in round 2 as regulatory-red-flag language.
_ALLOWED_DEFENSE_BASES = {
    "Provider clinical judgment",
    "Additional chart evidence exists",
    "Late-arriving lab or imaging result",
    "Other (explain)",
}


class AcceptRequest(BaseModel):
    override_reason: str | None = Field(
        default=None,
        min_length=None,
        max_length=4000,
        description=(
            "Required (min 20 chars) when accepting a low-confidence / "
            "incomplete-MEAT / clinically-denied suspect. Omit for clean accepts."
        ),
    )
    defense_basis: str | None = Field(
        default=None,
        description=(
            "Must be one of the allow-listed RADV defense bases. "
            "Free-text values are rejected with HTTP 422."
        ),
    )

    @field_validator("defense_basis")
    @classmethod
    def _validate_defense_basis(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if v not in _ALLOWED_DEFENSE_BASES:
            raise ValueError(
                f"defense_basis must be one of: {sorted(_ALLOWED_DEFENSE_BASES)}"
            )
        return v

    @field_validator("override_reason")
    @classmethod
    def _validate_override_reason(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return v
        s = v.strip()
        # Reject character-spam (repeated single char ≥ 80% of the string).
        # Round-3 finding #7: 20-char minimum was satisfied by "aaaaaaa...".
        if len(s) >= 4:
            most_common = max((s.count(c) for c in set(s)), default=0)
            if most_common / len(s) >= 0.8:
                raise ValueError(
                    "override_reason appears to be character-spam — "
                    "please describe the clinical basis in plain English."
                )
        return v


class DismissRequest(BaseModel):
    reason: str = Field(default="dismissed via api", description="Reason for dismissal")


class BulkUpdateRequest(BaseModel):
    ids: list[int] = Field(
        ..., min_length=1, description="List of suspect IDs to update"
    )
    action: Literal["accept", "dismiss"] = Field(..., description="Action to perform")
    reason: str = Field(
        default="bulk update", description="Reason (required when dismissing)"
    )


class SuspectResponse(BaseModel):
    suspect_id: int
    patient_id: int
    status: str
    suspect_hcc: int
    suspect_icd10: str
    evidence_type: str
    confidence_score: float
    # Calibration layer — see services/raf/calibration/__init__.py for the
    # full caveats.  raw_confidence mirrors confidence_score; the new
    # calibrated_confidence is a probability in [0,1] produced by the
    # per-source calibrator artifacts.  When the calibration feature flag
    # is off or no artifact exists, calibrated_confidence == raw_confidence.
    raw_confidence: float | None = None
    calibrated_confidence: float | None = None


class BulkUpdateResult(BaseModel):
    action: str
    requested: int
    succeeded: int
    failed: int
    errors: list[dict[str, Any]]


class SuspectListResponse(BaseModel):
    status_filter: str
    count: int
    limit: int
    offset: int
    suspects: list[dict[str, Any]]


class SuspectPatientResponse(BaseModel):
    pid: int
    patient_name: str
    status_filter: str
    year_filter: int | None
    count: int
    suspects: list[dict[str, Any]]


class ScanPatientResponse(BaseModel):
    pid: int
    patient_name: str
    new_suspects_found: int
    suspects: list[dict[str, Any]]


class ScanAllResponse(BaseModel):
    patients_scanned: int
    patients_with_errors: int
    total_new_suspects: int
    per_patient: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class AcceptActionResponse(BaseModel):
    suspect_id: int
    action: str
    reviewed_by: str
    record: dict[str, Any]


class DismissActionResponse(BaseModel):
    suspect_id: int
    action: str
    reviewed_by: str
    reason: str
    record: dict[str, Any]


# ---------------------------------------------------------------------------
# GET /api/suspects  –  all open suspects across all patients
# ---------------------------------------------------------------------------


@router.get("", summary="List all open suspect conditions across all patients", response_model=SuspectListResponse)
@limiter.limit("60/minute")
def list_suspects(
    request: Request,
    status: str = Query(
        default="open",
        description="Filter by status: open | accepted | dismissed | coded | all",
    ),
    limit: int = Query(
        default=200, ge=1, le=1000, description="Maximum records to return"
    ),
    offset: int = Query(
        default=0, ge=0, description="Pagination offset"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "read")),
) -> SuspectListResponse:
    """
    Return suspect conditions across every patient.

    Results are joined with OpenEMR ``patient_data`` (via ``get_all_open_suspects``)
    so each record includes ``patient_name``.  Records are sorted by
    ``confidence_score`` descending (highest confidence first).
    """
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        suspects: list[dict[str, Any]] = get_all_open_suspects(
            limit=limit, offset=offset, tenant_id=tenant_id
        )
    except Exception as exc:
        logger.exception("list_suspects – get_all_open_suspects failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    # Apply status filter (get_all_open_suspects may already filter to 'open')
    if status != "all":
        suspects = [s for s in suspects if s.get("status") == status]

    # Sort by confidence_score descending (DB already ordered, but defensive)
    suspects.sort(key=lambda s: float(s.get("confidence_score", 0)), reverse=True)

    return SuspectListResponse(
        status_filter=status,
        count=len(suspects),
        limit=limit,
        offset=offset,
        suspects=suspects,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/scan-all  –  must appear before /{pid} to avoid clash
# ---------------------------------------------------------------------------


@router.post("/scan-all", summary="Run suspect scan for all patients", response_model=ScanAllResponse)
@limiter.limit("2/minute")
def scan_all_patients(
    request: Request,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> ScanAllResponse:
    """
    Iterate over every patient returned by ``get_all_patients`` and run a
    full suspect scan for each one.  Returns a summary of totals and any
    per-patient errors encountered.
    """
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        patients: list[dict[str, Any]] = get_all_patients(tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("scan_all_patients – get_all_patients failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    # Guard: for large populations use the background job endpoint instead
    if len(patients) > 100:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Patient count ({len(patients)}) exceeds the synchronous limit of 100. "
                "Use the background job endpoint (POST /api/jobs/dispatch/suspects-scan) instead."
            ),
        )

    total_new = 0
    errors: list[dict[str, Any]] = []
    per_patient: list[dict[str, Any]] = []

    for patient in patients:
        pid: int = int(patient.get("pid") or patient.get("id") or 0)
        if not pid:
            continue
        try:
            found = run_full_suspect_scan(
                pid, year=year, tenant_id=current_user.get("tenant_id") or None
            )
            new_count = len(found)
            total_new += new_count
            per_patient.append({"pid": pid, "new_suspects": new_count})
            logger.info("scan_all: pid=%s found %s suspects", pid, new_count)
        except Exception as exc:
            logger.warning("scan_all: pid=%s failed: %s", pid, exc)
            errors.append({"pid": pid, "error": str(exc)})

    return ScanAllResponse(
        patients_scanned=len(patients),
        patients_with_errors=len(errors),
        total_new_suspects=total_new,
        per_patient=per_patient,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/bulk-update  –  must appear before /{pid}
# ---------------------------------------------------------------------------


@router.post("/bulk-update", summary="Bulk accept or dismiss multiple suspects")
@limiter.limit("20/minute")
def bulk_update(
    request: Request,
    body: BulkUpdateRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> BulkUpdateResult:
    """
    Accept or dismiss a list of suspect IDs in a single call.

    Body::

        {
          "ids": [1, 2, 3],
          "action": "accept" | "dismiss",
          "reason": "not clinically relevant"   // used only for dismiss
        }

    The reviewer identity is derived from the authenticated JWT — the client
    cannot spoof the ``reviewed_by`` field.
    """
    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    reviewed_by = f"user:{_uid or 'unknown'} ({current_user.get('email', 'unknown')})"
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    succeeded = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    for sid in body.ids:
        try:
            if body.action == "accept":
                accept_suspect(sid, reviewed_by=reviewed_by, tenant_id=tenant_id,
                               reviewed_by_user_id=reviewer_user_id)
            else:
                dismiss_suspect(sid, reason=body.reason, reviewed_by=reviewed_by, tenant_id=tenant_id,
                                reviewed_by_user_id=reviewer_user_id)
            succeeded += 1
        except Exception as exc:
            failed += 1
            errors.append({"suspect_id": sid, "error": str(exc)})
            logger.warning(
                "bulk_update: id=%s action=%s failed: %s", sid, body.action, exc
            )

    # Bulk accepts can shift many HCCs at once — invalidate v28/HEDIS caches.
    if body.action == "accept" and succeeded > 0:
        try:
            invalidate_v28_portfolio(tenant_id)
            invalidate_hedis_scores(tenant_id)
        except Exception as exc:
            logger.debug("bulk_update: cache invalidation failed: %s", exc)

    return BulkUpdateResult(
        action=body.action,
        requested=len(body.ids),
        succeeded=succeeded,
        failed=failed,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# GET /api/suspects/{pid}  –  suspects for a single patient
# ---------------------------------------------------------------------------


@router.get("/{pid}", summary="Get suspect conditions for a specific patient", response_model=SuspectPatientResponse)
@limiter.limit("60/minute")
def get_patient_suspects(
    request: Request,
    pid: int,
    status: str = Query(
        default="open",
        description="Filter by status: open | accepted | dismissed | coded | all",
    ),
    year: int | None = Query(
        default=None,
        description="Filter by measurement_year (e.g. 2025). Omit to return all years.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "read")),
) -> SuspectPatientResponse:
    """
    Return all suspect conditions for the patient identified by ``pid``.

    Patient existence is validated against OpenEMR before querying suspects.

    Pass ``?year=2025`` to restrict results to a specific ``measurement_year``.
    When omitted, suspects for all years are returned.
    """
    tenant_id: str = current_user.get("tenant_id") or ""
    from app.services.audit_logger import log_phi_access
    from app.services.patient_service import patient_is_accessible
    if not patient_is_accessible(pid, tenant_id):
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found"
        )

    patient = get_patient(pid)
    if not patient:
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found in OpenEMR"
        )

    log_phi_access(
        action="view",
        resource="suspect",
        patient_id=pid,
        user=current_user.get("email") or current_user.get("sub") or "unknown",
        details=f"status={status} year={year}",
        tenant_id=tenant_id or "unknown",
    )

    try:
        suspects: list[dict[str, Any]] = get_suspects_for_patient(
            pid, year=year, tenant_id=tenant_id or None
        )
    except Exception as exc:
        logger.exception(
            "get_patient_suspects pid=%s tenant=%s user=%s: %s",
            pid, tenant_id, current_user.get("email") or current_user.get("id"), exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )

    if status != "all":
        suspects = [s for s in suspects if s.get("status") == status]

    suspects.sort(key=lambda s: float(s.get("confidence_score", 0)), reverse=True)

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    return SuspectPatientResponse(
        pid=pid,
        patient_name=patient_name,
        status_filter=status,
        year_filter=year,
        count=len(suspects),
        suspects=suspects,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/scan/{pid}  –  run full suspect scan for one patient
# ---------------------------------------------------------------------------


@router.post("/scan/{pid}", summary="Run full suspect scan for a patient", response_model=ScanPatientResponse)
def scan_patient(
    pid: int,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> ScanPatientResponse:
    """
    Execute all suspect-detection passes for the given patient:

    * Medication-based suspects (``scan_medications``)
    * Lab-based suspects (``scan_labs``)
    * Historical HCC suspects
    * Note-vs-billing gap suspects

    All passes are orchestrated by ``run_full_suspect_scan``.  New suspects
    are persisted to ``raf_suspect_conditions``.  Already-known suspects are
    deduplicated by the engine and not double-inserted.
    """
    tenant_id: str = current_user.get("tenant_id") or ""
    from app.services.patient_service import patient_is_accessible
    if not patient_is_accessible(pid, tenant_id):
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found in OpenEMR"
        )
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found in OpenEMR"
        )

    try:
        new_suspects: list[dict[str, Any]] = run_full_suspect_scan(
            pid, year=year, tenant_id=tenant_id or None
        )
    except Exception as exc:
        logger.exception(
            "scan_patient pid=%s tenant=%s user=%s: %s",
            pid, tenant_id, current_user.get("email") or current_user.get("id"), exc,
        )
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    logger.info(
        "scan_patient: pid=%s tenant=%s user=%s found %s new suspects",
        pid, tenant_id, current_user.get("email") or current_user.get("id"), len(new_suspects),
    )

    return ScanPatientResponse(
        pid=pid,
        patient_name=patient_name,
        new_suspects_found=len(new_suspects),
        suspects=new_suspects,
    )


# ---------------------------------------------------------------------------
# PUT /api/suspects/{suspect_id}/accept
# ---------------------------------------------------------------------------


@router.put("/{suspect_id}/accept", summary="Accept a suspect condition", response_model=AcceptActionResponse)
def accept_suspect_endpoint(
    suspect_id: int,
    body: AcceptRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> AcceptActionResponse:
    """
    Mark a suspect condition as **accepted** (the clinician agrees it should
    be coded for this encounter).

    The reviewer identity is derived from the authenticated JWT.

    **Override gate** — before writing the acceptance the endpoint computes
    whether this is a *risky accept*:

    * ``confidence_score < 0.70``
    * ``meat_status`` in ``{partial, incomplete, unknown, pending_rule_review}``
    * A ``CLINICAL_RULE_GATE_DENIED`` audit event exists for this HCC/patient

    If any risk factor is present and ``override_reason`` is absent or shorter
    than 20 characters, HTTP 422 is returned with the exact risk factors so the
    frontend can surface the confirmation dialog.  Agent-H's dialog already
    sends ``override_reason`` in these cases, so the happy path is unaffected.

    When an override is accepted, the reason is persisted to the new
    ``accept_override_reason`` / ``accept_defense_basis`` /
    ``accept_risk_factors_json`` columns and a ``SUSPECT_ACCEPTED_OVERRIDE``
    immutable-audit event is emitted.  If migration 024 has not yet applied
    (column-unknown DB error) the persistence is skipped with a WARNING and
    the accept still succeeds — callers are never blocked by missing schema.
    """
    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    reviewed_by = f"user:{_uid or 'unknown'} ({current_user.get('email', 'unknown')})"
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    # ------------------------------------------------------------------
    # Override gate
    # ------------------------------------------------------------------
    risk_factors = _compute_risk_factors(suspect_id, tenant_id)
    is_risky = len(risk_factors) > 0

    if is_risky:
        reason = (body.override_reason or "").strip()
        if len(reason) < _MIN_OVERRIDE_REASON_LEN:
            raise HTTPException(
                status_code=422,
                detail={
                    "detail": (
                        "Override reason required for low-confidence / "
                        "incomplete-MEAT acceptance"
                    ),
                    "risk_factors": risk_factors,
                },
            )

    # ------------------------------------------------------------------
    # Perform the accept
    # ------------------------------------------------------------------
    try:
        updated = accept_suspect(
            suspect_id,
            reviewed_by=reviewed_by,
            tenant_id=tenant_id,
            reviewed_by_user_id=reviewer_user_id,
        )
    except ValueError as exc:
        logger.exception("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.exception("accept_suspect_endpoint id=%s: %s", suspect_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # ------------------------------------------------------------------
    # Persist override metadata (gracefully degrade if 024 not applied)
    # ------------------------------------------------------------------
    if is_risky:
        risk_json = json.dumps(risk_factors)
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    UPDATE raf_suspect_conditions
                    SET accept_override_reason   = %s,
                        accept_defense_basis     = %s,
                        accept_risk_factors_json = %s
                    WHERE id        = %s
                      AND tenant_id = %s
                    """,
                    (
                        (body.override_reason or "").strip()[:500],
                        (body.defense_basis or "")[:100] or None,
                        risk_json,
                        suspect_id,
                        tenant_id,
                    ),
                )
        except MySQLError as exc:
            # Narrow catch: only ignore the specific "column does not exist"
            # error (errno 1054) which means migration 024 hasn't run yet.
            # Any other MySQL error (deadlock, FK violation, schema mismatch
            # elsewhere) is a real audit-write failure and must propagate so
            # the global handler turns it into a logged 500 with traceback —
            # silently swallowing all exceptions left a class of bugs where
            # the accept persisted but the override was never recorded
            # (HCC review round-5 blocker #2).
            errno = getattr(exc, "errno", None)
            if errno == 1054:
                logger.warning(
                    "accept_suspect_endpoint: override columns missing "
                    "(migration 024 not applied) — suspect_id=%s",
                    suspect_id,
                )
            else:
                raise

        # Emit immutable audit event — non-fatal if it fails.
        try:
            from app.services.immutable_audit import emit_audit_event

            emit_audit_event(
                "SUSPECT_ACCEPTED_OVERRIDE",
                tenant_id=tenant_id,
                actor_user_id=reviewer_user_id,
                subject_type="suspect",
                subject_id=str(suspect_id),
                payload={
                    "override_reason": (body.override_reason or "").strip(),
                    "defense_basis": body.defense_basis or None,
                    "risk_factors": risk_factors,
                    "actor_email": current_user.get("email") or "unknown",
                },
            )
        except Exception as exc:
            logger.warning(
                "accept_suspect_endpoint: immutable audit emit failed for "
                "SUSPECT_ACCEPTED_OVERRIDE suspect_id=%s: %s",
                suspect_id, exc,
            )

    # ------------------------------------------------------------------
    # Cache invalidation — accepting a suspect shifts V28 RAF + HEDIS
    # numerators.  Evict both for this tenant; the next read will rebuild.
    # ------------------------------------------------------------------
    try:
        invalidate_v28_portfolio(tenant_id)
        invalidate_hedis_scores(tenant_id)
    except Exception as exc:
        logger.debug("accept_suspect: cache invalidation failed: %s", exc)

    return AcceptActionResponse(
        suspect_id=suspect_id,
        action="accepted",
        reviewed_by=reviewed_by,
        record=updated,
    )


# ---------------------------------------------------------------------------
# PUT /api/suspects/{suspect_id}/dismiss
# ---------------------------------------------------------------------------


@router.put("/{suspect_id}/dismiss", summary="Dismiss a suspect condition", response_model=DismissActionResponse)
def dismiss_suspect_endpoint(
    suspect_id: int,
    body: DismissRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> DismissActionResponse:
    """
    Mark a suspect condition as **dismissed** (the clinician reviewed and
    determined the condition is not present or not codeable this encounter).

    The reviewer identity is derived from the authenticated JWT.
    """
    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    reviewed_by = f"user:{_uid or 'unknown'} ({current_user.get('email', 'unknown')})"
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        updated = dismiss_suspect(
            suspect_id,
            reason=body.reason,
            reviewed_by=reviewed_by,
            tenant_id=tenant_id,
            reviewed_by_user_id=reviewer_user_id,
        )
    except ValueError as exc:
        logger.exception("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.exception("dismiss_suspect_endpoint id=%s: %s", suspect_id, exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    return DismissActionResponse(
        suspect_id=suspect_id,
        action="dismissed",
        reviewed_by=reviewed_by,
        reason=body.reason,
        record=updated,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/{suspect_id}/reverse-writeback
# ---------------------------------------------------------------------------

_MIN_REVERSAL_REASON_LEN = 30
_REVERSAL_ALLOWED_ROLES = frozenset({"coder", "admin", "physician"})


class ReverseWritebackRequest(BaseModel):
    reversal_reason: str = Field(
        ...,
        min_length=_MIN_REVERSAL_REASON_LEN,
        max_length=4000,
        description=(
            "Clinical or administrative reason for reversing the FHIR write-back "
            "(minimum 30 characters). This is recorded in the immutable audit log."
        ),
    )


class ReverseWritebackResponse(BaseModel):
    suspect_id: int
    condition_id: str
    reversed: bool
    reversal_reason: str


@router.post(
    "/{suspect_id}/reverse-writeback",
    summary="Reverse a previously written FHIR Condition (mark entered-in-error)",
    response_model=ReverseWritebackResponse,
)
@limiter.limit("10/minute")
def reverse_writeback_endpoint(
    request: Request,
    suspect_id: int,
    body: ReverseWritebackRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> ReverseWritebackResponse:
    """
    Mark the FHIR Condition previously pushed for *suspect_id* as
    ``entered-in-error`` in OpenEMR.

    This provides the reversal path required for Patient Safety compliance
    when an AI-suggested condition is accepted in error.

    * Requires ``reversal_reason`` of at least 30 characters.
    * Requires the caller's role to be ``coder`` or ``admin``.
    * Emits ``SUSPECT_WRITEBACK_REVERSED`` to the immutable audit log.
    * Updates ``raf_suspect_conditions.fhir_writeback_reversed_at`` and
      ``.fhir_writeback_reversal_reason``.
    """
    user_role: str = (current_user.get("role") or "").lower()
    if user_role not in _REVERSAL_ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Role '{user_role}' is not permitted to reverse FHIR write-backs. "
                "Required: coder or admin."
            ),
        )

    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    # Look up the condition_id stored on the suspect row
    condition_id: str | None = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT fhir_condition_id
                FROM   raf_suspect_conditions
                WHERE  id        = %s
                  AND  tenant_id = %s
                LIMIT  1
                """,
                (suspect_id, tenant_id),
            )
            row = cur.fetchone()
        if row:
            condition_id = (row.get("fhir_condition_id") or "").strip() or None
    except Exception as exc:
        logger.exception(
            "reverse_writeback_endpoint: DB lookup failed for suspect=%s: %s",
            suspect_id, exc,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    if not condition_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No FHIR condition_id found for suspect {suspect_id}. "
                "Either the write-back was never performed or the condition id was not recorded."
            ),
        )

    from app.services.fhir_problem_list import reverse_problem_list_condition

    try:
        result = reverse_problem_list_condition(
            condition_id=condition_id,
            reversal_reason=body.reversal_reason,
            tenant_id=tenant_id,
            user_id=reviewer_user_id or 0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        logger.exception(
            "reverse_writeback_endpoint: FHIR reversal failed suspect=%s condition=%s: %s",
            suspect_id, condition_id, exc,
        )
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "reverse_writeback_endpoint: unexpected error suspect=%s: %s",
            suspect_id, exc,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return ReverseWritebackResponse(
        suspect_id=suspect_id,
        condition_id=condition_id,
        reversed=result.get("success", False),
        reversal_reason=body.reversal_reason,
    )
