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
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.suspect_engine import (
    run_full_suspect_scan,
    get_suspects_for_patient,
    get_all_open_suspects,
    accept_suspect,
    dismiss_suspect,
    scan_medications,
    scan_labs,
)
from app.services.openemr_connector import get_patient, get_all_patients

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suspects", tags=["suspects"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class AcceptRequest(BaseModel):
    reviewed_by: str = Field(..., min_length=1, description="User or system marking this suspect as accepted")


class DismissRequest(BaseModel):
    reviewed_by: str = Field(..., min_length=1, description="User or system dismissing this suspect")
    reason: str = Field(default="dismissed via api", description="Reason for dismissal")


class BulkUpdateRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, description="List of suspect IDs to update")
    action: Literal["accept", "dismiss"] = Field(..., description="Action to perform")
    reviewed_by: str = Field(..., min_length=1, description="User performing the bulk update")
    reason: str = Field(default="bulk update", description="Reason (required when dismissing)")


class SuspectResponse(BaseModel):
    suspect_id: int
    patient_id: int
    status: str
    suspect_hcc: int
    suspect_icd10: str
    evidence_type: str
    confidence_score: float


class BulkUpdateResult(BaseModel):
    action: str
    requested: int
    succeeded: int
    failed: int
    errors: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# GET /api/suspects  –  all open suspects across all patients
# ---------------------------------------------------------------------------

@router.get("", summary="List all open suspect conditions across all patients")
def list_suspects(
    status: str = Query(
        default="open",
        description="Filter by status: open | accepted | dismissed | coded | all",
    ),
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum records to return"),
) -> dict[str, Any]:
    """
    Return suspect conditions across every patient.

    Results are joined with OpenEMR ``patient_data`` (via ``get_all_open_suspects``)
    so each record includes ``patient_name``.  Records are sorted by
    ``confidence_score`` descending (highest confidence first).
    """
    try:
        suspects: list[dict[str, Any]] = get_all_open_suspects()
    except Exception as exc:
        logger.error("list_suspects – get_all_open_suspects failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve suspects: {exc}")

    # Apply status filter (get_all_open_suspects may already filter to 'open')
    if status != "all":
        suspects = [s for s in suspects if s.get("status") == status]

    # Sort by confidence_score descending
    suspects.sort(key=lambda s: float(s.get("confidence_score", 0)), reverse=True)

    return {
        "status_filter": status,
        "count": len(suspects),
        "suspects": suspects[:limit],
    }


# ---------------------------------------------------------------------------
# POST /api/suspects/scan-all  –  must appear before /{pid} to avoid clash
# ---------------------------------------------------------------------------

@router.post("/scan-all", summary="Run suspect scan for all patients")
def scan_all_patients() -> dict[str, Any]:
    """
    Iterate over every patient returned by ``get_all_patients`` and run a
    full suspect scan for each one.  Returns a summary of totals and any
    per-patient errors encountered.
    """
    try:
        patients: list[dict[str, Any]] = get_all_patients()
    except Exception as exc:
        logger.error("scan_all_patients – get_all_patients failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve patient list: {exc}")

    total_new = 0
    errors: list[dict[str, Any]] = []
    per_patient: list[dict[str, Any]] = []

    for patient in patients:
        pid: int = int(patient.get("pid") or patient.get("id") or 0)
        if not pid:
            continue
        try:
            found = run_full_suspect_scan(pid)
            new_count = len(found)
            total_new += new_count
            per_patient.append({"pid": pid, "new_suspects": new_count})
            logger.info("scan_all: pid=%s found %s suspects", pid, new_count)
        except Exception as exc:
            logger.warning("scan_all: pid=%s failed: %s", pid, exc)
            errors.append({"pid": pid, "error": str(exc)})

    return {
        "patients_scanned": len(patients),
        "patients_with_errors": len(errors),
        "total_new_suspects": total_new,
        "per_patient": per_patient,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# POST /api/suspects/bulk-update  –  must appear before /{pid}
# ---------------------------------------------------------------------------

@router.post("/bulk-update", summary="Bulk accept or dismiss multiple suspects")
def bulk_update(body: BulkUpdateRequest) -> BulkUpdateResult:
    """
    Accept or dismiss a list of suspect IDs in a single call.

    Body::

        {
          "ids": [1, 2, 3],
          "action": "accept" | "dismiss",
          "reviewed_by": "dr_smith",
          "reason": "not clinically relevant"   // used only for dismiss
        }
    """
    succeeded = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    for sid in body.ids:
        try:
            if body.action == "accept":
                accept_suspect(sid, reviewed_by=body.reviewed_by)
            else:
                dismiss_suspect(sid, reason=body.reason, reviewed_by=body.reviewed_by)
            succeeded += 1
        except Exception as exc:
            failed += 1
            errors.append({"suspect_id": sid, "error": str(exc)})
            logger.warning("bulk_update: id=%s action=%s failed: %s", sid, body.action, exc)

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

@router.get("/{pid}", summary="Get suspect conditions for a specific patient")
def get_patient_suspects(
    pid: int,
    status: str = Query(
        default="open",
        description="Filter by status: open | accepted | dismissed | coded | all",
    ),
) -> dict[str, Any]:
    """
    Return all suspect conditions for the patient identified by ``pid``.

    Patient existence is validated against OpenEMR before querying suspects.
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found in OpenEMR")

    try:
        suspects: list[dict[str, Any]] = get_suspects_for_patient(pid)
    except Exception as exc:
        logger.error("get_patient_suspects pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve suspects for patient {pid}: {exc}")

    if status != "all":
        suspects = [s for s in suspects if s.get("status") == status]

    suspects.sort(key=lambda s: float(s.get("confidence_score", 0)), reverse=True)

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    return {
        "pid": pid,
        "patient_name": patient_name,
        "status_filter": status,
        "count": len(suspects),
        "suspects": suspects,
    }


# ---------------------------------------------------------------------------
# POST /api/suspects/scan/{pid}  –  run full suspect scan for one patient
# ---------------------------------------------------------------------------

@router.post("/scan/{pid}", summary="Run full suspect scan for a patient")
def scan_patient(pid: int) -> dict[str, Any]:
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
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found in OpenEMR")

    try:
        new_suspects: list[dict[str, Any]] = run_full_suspect_scan(pid)
    except Exception as exc:
        logger.error("scan_patient pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=f"Suspect scan failed for patient {pid}: {exc}")

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    logger.info("scan_patient: pid=%s found %s new suspects", pid, len(new_suspects))

    return {
        "pid": pid,
        "patient_name": patient_name,
        "new_suspects_found": len(new_suspects),
        "suspects": new_suspects,
    }


# ---------------------------------------------------------------------------
# PUT /api/suspects/{suspect_id}/accept
# ---------------------------------------------------------------------------

@router.put("/{suspect_id}/accept", summary="Accept a suspect condition")
def accept_suspect_endpoint(suspect_id: int, body: AcceptRequest) -> dict[str, Any]:
    """
    Mark a suspect condition as **accepted** (the clinician agrees it should
    be coded for this encounter).

    Body::

        { "reviewed_by": "dr_smith" }
    """
    try:
        updated = accept_suspect(suspect_id, reviewed_by=body.reviewed_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("accept_suspect_endpoint id=%s: %s", suspect_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to accept suspect {suspect_id}: {exc}")

    return {
        "suspect_id": suspect_id,
        "action": "accepted",
        "reviewed_by": body.reviewed_by,
        "record": updated,
    }


# ---------------------------------------------------------------------------
# PUT /api/suspects/{suspect_id}/dismiss
# ---------------------------------------------------------------------------

@router.put("/{suspect_id}/dismiss", summary="Dismiss a suspect condition")
def dismiss_suspect_endpoint(suspect_id: int, body: DismissRequest) -> dict[str, Any]:
    """
    Mark a suspect condition as **dismissed** (the clinician reviewed and
    determined the condition is not present or not codeable this encounter).

    Body::

        {
          "reviewed_by": "dr_smith",
          "reason": "patient condition resolved"
        }
    """
    try:
        updated = dismiss_suspect(
            suspect_id,
            reason=body.reason,
            reviewed_by=body.reviewed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("dismiss_suspect_endpoint id=%s: %s", suspect_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to dismiss suspect {suspect_id}: {exc}")

    return {
        "suspect_id": suspect_id,
        "action": "dismissed",
        "reviewed_by": body.reviewed_by,
        "reason": body.reason,
        "record": updated,
    }
