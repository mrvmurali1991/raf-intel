"""
EDI generation router — outbound 837 (encounter) and 834 (enrollment).

Endpoints
---------
    POST /api/edi/837/generate    — generate 837 batch
    POST /api/edi/834/generate    — generate 834 enrollment file
    GET  /api/edi/files/{file_id} — download a previously generated file
    GET  /api/edi/files           — list files for the tenant

Validator gate
--------------
For 837, when `run_pre_submission_validator=true`, every patient is checked
against R1–R6.  Patients with any HIGH-severity finding are excluded UNLESS
the caller explicitly passes `confirm_override=true` and a non-empty
`override_reason`.  Overrides are audited as `EDI_837_OVERRIDE_HIGH_SEVERITY`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id
from app.services.edi import (
    generate_834_enrollment,
    generate_837_batch,
)
from app.services.edi.pre_submission_validator import validate_batch
from app.services.edi.storage import get_edi_file, save_edi_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/edi", tags=["edi"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class Generate837Request(BaseModel):
    patient_ids: list[int] = Field(..., min_length=1, description="RAF patient IDs to include")
    payment_year: int = Field(..., ge=2020, le=2030)
    run_pre_submission_validator: bool = Field(
        default=True,
        description="When true, run R1-R6 and exclude HIGH-severity rows",
    )
    confirm_override: bool = Field(
        default=False,
        description="Set true to bypass HIGH-severity gate.  Requires override_reason.",
    )
    override_reason: str | None = Field(
        default=None, max_length=500,
        description="Required when confirm_override=true",
    )
    submitter_info: dict[str, Any] | None = None


class Generate834Request(BaseModel):
    patient_ids: list[int] = Field(..., min_length=1)
    plan_year: int = Field(..., ge=2020, le=2030)
    sponsor_info: dict[str, Any] | None = None


class GenerateResponse(BaseModel):
    file_id: str
    transaction: Literal["837", "834"]
    total_encounters: int
    file_size: int
    sha256: str
    download_url: str
    errors: list[dict[str, Any]] = Field(default_factory=list)
    excluded_patient_ids: list[int] = Field(default_factory=list)
    override_applied: bool = False


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

def _emit(event_type: str, *, tenant_id: str, user_id: Any, payload: dict[str, Any]) -> None:
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            event_type,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            subject_type="edi_file",
            subject_id=payload.get("file_id"),
            payload=payload,
        )
    except Exception as exc:
        logger.warning("EDI audit emit failed (%s): %s", event_type, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/837/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_837(
    body: Generate837Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> GenerateResponse:
    """Generate an 837 file for the given patients/payment year."""
    user_id = current_user.get("id") or current_user.get("user_id")

    validator_findings: list[dict[str, Any]] = []
    excluded: list[int] = []
    eligible_ids = list(body.patient_ids)
    override_applied = False

    if body.run_pre_submission_validator:
        report = validate_batch(body.patient_ids, body.payment_year)
        validator_findings = report["per_patient"]
        failed_ids = report["failed_patient_ids"]

        if failed_ids and not body.confirm_override:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "pre_submission_high_severity",
                    "message": (
                        "One or more patients have HIGH-severity findings.  "
                        "Re-submit with confirm_override=true and an override_reason "
                        "to force generation, or remove the failing patients."
                    ),
                    "failed_patient_ids": failed_ids,
                    "high_severity_total": report["high_severity_total"],
                    "per_patient": validator_findings,
                },
            )

        if failed_ids and body.confirm_override:
            if not body.override_reason or not body.override_reason.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="override_reason is required when confirm_override=true",
                )
            override_applied = True
            _emit(
                "EDI_837_OVERRIDE_HIGH_SEVERITY",
                tenant_id=tenant_id,
                user_id=user_id,
                payload={
                    "failed_patient_ids": failed_ids,
                    "reason": body.override_reason.strip(),
                    "high_severity_total": report["high_severity_total"],
                },
            )
            eligible_ids = list(body.patient_ids)
        else:
            eligible_ids = report["passed_patient_ids"]
            excluded = failed_ids

    submitter = dict(body.submitter_info or {})
    submitter.setdefault("submitter_id", f"TENANT{tenant_id}")

    try:
        edi_text = generate_837_batch(
            patient_ids=eligible_ids,
            payment_year=body.payment_year,
            submitter_info=submitter,
        )
    except Exception as exc:
        logger.exception("generate_837_batch failed")
        raise HTTPException(status_code=500, detail=f"837 generation failed: {exc}") from exc

    encounter_count = edi_text.count("\nCLM*") + (1 if edi_text.startswith("CLM*") else 0)
    if encounter_count == 0:
        # Quick scan — count ST*837 segments as a fallback
        encounter_count = edi_text.count("ST*837*")

    saved = save_edi_file(
        tenant_id=tenant_id,
        transaction="837",
        content=edi_text,
        encounter_count=encounter_count,
        metadata={
            "payment_year": body.payment_year,
            "patient_ids": body.patient_ids,
            "eligible_patient_ids": eligible_ids,
            "excluded_patient_ids": excluded,
            "override_applied": override_applied,
        },
    )

    _emit(
        "EDI_FILE_GENERATED_837",
        tenant_id=tenant_id,
        user_id=user_id,
        payload={
            "file_id": saved["id"],
            "encounter_count": encounter_count,
            "file_size": saved["file_size"],
            "hash_sha256": saved["sha256"],
            "payment_year": body.payment_year,
            "patient_count": len(eligible_ids),
            "override_applied": override_applied,
        },
    )

    return GenerateResponse(
        file_id=saved["id"],
        transaction="837",
        total_encounters=encounter_count,
        file_size=saved["file_size"],
        sha256=saved["sha256"],
        download_url=f"/api/edi/files/{saved['id']}",
        errors=[f for f in validator_findings if f.get("findings")],
        excluded_patient_ids=excluded,
        override_applied=override_applied,
    )


@router.post(
    "/834/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_834(
    body: Generate834Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> GenerateResponse:
    """Generate an 834 enrollment file for the given patients/plan year."""
    user_id = current_user.get("id") or current_user.get("user_id")

    sponsor = dict(body.sponsor_info or {})
    sponsor.setdefault("sender_id", f"TENANT{tenant_id}")

    try:
        edi_text = generate_834_enrollment(
            patient_ids=body.patient_ids,
            plan_year=body.plan_year,
            sponsor_info=sponsor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("generate_834_enrollment failed")
        raise HTTPException(status_code=500, detail=f"834 generation failed: {exc}") from exc

    member_count = edi_text.count("\nINS*")

    saved = save_edi_file(
        tenant_id=tenant_id,
        transaction="834",
        content=edi_text,
        encounter_count=member_count,
        metadata={
            "plan_year": body.plan_year,
            "patient_ids": body.patient_ids,
        },
    )

    _emit(
        "EDI_FILE_GENERATED_834",
        tenant_id=tenant_id,
        user_id=user_id,
        payload={
            "file_id": saved["id"],
            "encounter_count": member_count,
            "file_size": saved["file_size"],
            "hash_sha256": saved["sha256"],
            "plan_year": body.plan_year,
            "patient_count": len(body.patient_ids),
        },
    )

    return GenerateResponse(
        file_id=saved["id"],
        transaction="834",
        total_encounters=member_count,
        file_size=saved["file_size"],
        sha256=saved["sha256"],
        download_url=f"/api/edi/files/{saved['id']}",
    )


@router.get("/files/{file_id}")
def download_edi_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """Download a previously generated EDI file."""
    row = get_edi_file(file_id=file_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"EDI file {file_id} not found")
    path = row.get("file_path")
    if not path:
        raise HTTPException(status_code=404, detail="EDI file path missing")

    txn = row.get("transaction", "837")
    return FileResponse(
        path=path,
        media_type="application/edi-x12",
        filename=f"{txn}_{file_id}.edi",
    )
