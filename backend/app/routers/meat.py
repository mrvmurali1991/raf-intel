"""
MEAT Validation Router
======================
HTTP endpoints wrapping `app.services.meat_validator`.

Endpoints
---------
POST /api/meat/validate
    Body: {note_text, icd_codes[]}
    Runs `validate_meat_batch` against the supplied note and returns
    one MEAT result per ICD code.

POST /api/meat/validate-single
    Body: {note_text, icd_code, hcc_label?}
    Runs `validate_meat` for a single condition.

POST /api/meat/run-for-patient/{patient_id}
    Batch job: fetches the patient's recent documents and all HCC rows
    from `raf_patient_hcc`, runs `validate_meat` for every HCC against
    the most-recent note, and UPDATES `raf_patient_hcc.meat_status`
    with the resulting COMPLETE / PARTIAL / MISSING value. Returns a
    summary of how many HCCs fell into each bucket.

NOTE: The /run-for-patient endpoint is a pragmatic short-term batch
pathway. It should eventually be moved to a scheduled celery/cron job
that walks the tenant's active patient set off the request thread so
the HTTP API is not blocked on per-patient NLP work.

Implementation note: the project's existing raw-SQL pattern is the
`raf_cursor()` context manager with `%s` parameterized placeholders
(see routers/raf.py, routers/audit.py). We follow that convention
here rather than introducing a SQLAlchemy `Session` dependency, which
would require touching additional files outside this router.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id
from app.db import raf_cursor
from app.services.meat_evidence_service import (
    calculate_meat_completeness,
    update_hcc_meat_status,
)
from app.services.meat_validator import validate_meat, validate_meat_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meat", tags=["meat"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ValidateBatchRequest(BaseModel):
    note_text: str = Field(..., description="Full clinical note text")
    icd_codes: list[str] = Field(
        default_factory=list,
        description="List of ICD-10-CM codes to validate against the note",
    )


class ValidateSingleRequest(BaseModel):
    note_text: str = Field(..., description="Full clinical note text")
    icd_code: str = Field(..., description="ICD-10-CM code being validated")
    hcc_label: str | None = Field(
        default=None,
        description="Optional human-readable HCC label for mention detection",
    )


class ValidateBatchResponse(BaseModel):
    results: list[dict]


class RunForPatientResponse(BaseModel):
    patient_id: int
    hccs_validated: int
    complete: int
    partial: int
    missing: int


class ValidateSingleResponse(BaseModel):
    status: str
    icd_code: str
    hcc_label: str | None = None
    evidence: dict[str, Any] | None = None
    score: float | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/validate", response_model=ValidateBatchResponse)
def validate_batch(
    body: ValidateBatchRequest,
    current_user: dict = Depends(get_current_user),
) -> ValidateBatchResponse:
    """Validate MEAT evidence for a list of ICD codes against one note."""
    try:
        results = validate_meat_batch(body.note_text, body.icd_codes)
        return ValidateBatchResponse(results=results)
    except Exception as exc:
        logger.exception("meat.validate_batch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="MEAT validation failed")


@router.post("/validate-single", response_model_exclude_none=True)
def validate_single(
    body: ValidateSingleRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate MEAT evidence for a single ICD code / HCC label."""
    try:
        return validate_meat(body.note_text, body.icd_code, body.hcc_label)
    except Exception as exc:
        logger.exception("meat.validate_single failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="MEAT validation failed")


@router.post("/run-for-patient/{patient_id}", response_model=RunForPatientResponse)
def run_for_patient(
    patient_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> RunForPatientResponse:
    """
    Run MEAT validation across every HCC assigned to *patient_id*,
    using that patient's most recent clinical note, and write the
    resulting status back to `raf_patient_hcc.meat_status`.

    TODO: replace this with an async celery/cron batch job so the
    HTTP request is not blocked on per-HCC NLP work.
    """

    try:
        # ------------------------------------------------------------------
        # Detect FHIR patients — they are stored in emr_patient_matches, not
        # the local `documents` table.  For them we refresh meat_status from
        # already-stored evidence and return the summary without re-running
        # the NLP validator (clinical notes come from the FHIR source and are
        # not cached locally).
        # ------------------------------------------------------------------
        is_fhir = False
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM emr_patient_matches epm
                    JOIN emr_connections ec ON ec.id = epm.connection_id
                    WHERE ec.is_active = 1
                      AND ec.connection_type IN ('fhir_r4', 'rest_api')
                      AND (epm.id = %s OR epm.raf_patient_id = %s)
                    LIMIT 1
                    """,
                    (patient_id, patient_id),
                )
                is_fhir = cur.fetchone() is not None
        except Exception as fhir_check_err:
            logger.warning(
                "meat.run_for_patient: FHIR check failed for pid=%s: %s",
                patient_id, fhir_check_err,
            )

        if is_fhir:
            # Refresh meat_status from existing evidence rows and return summary.
            update_hcc_meat_status(patient_id)
            report = calculate_meat_completeness(patient_id)
            return RunForPatientResponse(
                patient_id=patient_id,
                hccs_validated=report["total_hccs"],
                complete=report["complete_hccs"],
                partial=report["partial_hccs"],
                missing=report["missing_hccs"],
            )

        # 1. Fetch most-recent note for the patient (tenant-scoped).
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, patient_id, note_text, created_at, tenant_id
                FROM documents
                WHERE patient_id = %s
                  AND tenant_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (patient_id, tenant_id),
            )
            doc_row = cur.fetchone()

        if not doc_row:
            raise HTTPException(
                status_code=404,
                detail=f"No documents found for patient {patient_id}",
            )

        note_text = doc_row["note_text"] if isinstance(doc_row, dict) else doc_row[2]
        if not note_text:
            raise HTTPException(
                status_code=422,
                detail=f"Most recent document for patient {patient_id} has empty note_text",
            )

        # 2. Fetch the patient's HCC rows with ICD codes.
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, hcc_code, icd10_codes
                FROM raf_patient_hcc
                WHERE patient_id = %s
                  AND tenant_id = %s
                """,
                (patient_id, tenant_id),
            )
            hcc_rows = cur.fetchall()

        complete = partial = missing = 0
        updates: list[tuple[str, Any]] = []

        for row in hcc_rows:
            row_id = row["id"] if isinstance(row, dict) else row[0]
            hcc_code = row["hcc_code"] if isinstance(row, dict) else row[1]
            icd_field = row["icd10_codes"] if isinstance(row, dict) else row[2]

            # icd10_codes column may be comma-separated string or list-ish.
            if not icd_field:
                icd_codes: list[str] = []
            elif isinstance(icd_field, (list, tuple)):
                icd_codes = [str(c).strip() for c in icd_field if c]
            else:
                icd_codes = [c.strip() for c in str(icd_field).split(",") if c.strip()]

            # Score worst-across-codes for this HCC row.
            row_status = "MISSING"
            for code in icd_codes:
                result = validate_meat(note_text, code, str(hcc_code))
                s = result.get("status", "MISSING")
                # Upgrade: MISSING < PARTIAL < COMPLETE
                if s == "COMPLETE":
                    row_status = "COMPLETE"
                    break
                if s == "PARTIAL" and row_status == "MISSING":
                    row_status = "PARTIAL"

            if row_status == "COMPLETE":
                complete += 1
            elif row_status == "PARTIAL":
                partial += 1
            else:
                missing += 1

            updates.append((row_status, row_id))

        # 3. Persist results — single batched UPDATE instead of per-row calls.
        if updates:
            with raf_cursor() as cur:
                cur.executemany(
                    """
                    UPDATE raf_patient_hcc
                    SET meat_status = %s
                    WHERE id = %s
                      AND tenant_id = %s
                    """,
                    [(status, row_id, tenant_id) for status, row_id in updates],
                )

        return RunForPatientResponse(
            patient_id=patient_id,
            hccs_validated=len(updates),
            complete=complete,
            partial=partial,
            missing=missing,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "meat.run_for_patient failed pid=%s: %s", patient_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="MEAT batch validation failed"
        )
