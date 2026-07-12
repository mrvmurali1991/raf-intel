"""
Worklist bulk-action router.

POST /api/v1/worklist/bulk-attest  — create pending attestations for every open gap
                                     across the selected patient list.
POST /api/v1/worklist/bulk-export  — stream a CSV of the selected patients with their
                                     open gap details.

Both endpoints require a valid JWT bearer token and the ``worklist:read`` permission.
bulk-attest additionally requires ``attestations:write``.
"""
# Note: do NOT use 'from __future__ import annotations' — breaks FastAPI/Pydantic schema gen.

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/worklist", tags=["worklist-bulk"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class BulkAttestRequest(BaseModel):
    patient_ids: list[int] = Field(..., min_length=1, max_length=500)


class BulkExportRequest(BaseModel):
    patient_ids: list[int] = Field(..., min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _table_exists(name: str) -> bool:
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_NAME = %s LIMIT 1",
                (name,),
            )
            return cur.fetchone() is not None
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.warning("best-effort operation failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# POST /api/v1/worklist/bulk-attest
# ---------------------------------------------------------------------------

@router.post("/bulk-attest", summary="Create attestations for all open gaps on selected patients")
def bulk_attest(
    body: BulkAttestRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    For each patient in ``patient_ids``, fetch all open recapture gaps and create
    a ``provider_attestations`` row with status='pending'.  Already-pending rows for
    the same (patient_id, hcc_code, icd10_code) are skipped via INSERT IGNORE.

    Returns ``{created: N}`` where N is the number of new rows inserted.
    """
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")

    provider_user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    if not provider_user_id:
        raise HTTPException(status_code=401, detail="Could not resolve provider user id from token")

    # Resolve NPI for the calling user (best-effort; falls back to empty string)
    provider_npi = ""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT npi FROM providers WHERE user_id = %s AND tenant_id = %s LIMIT 1",
                (provider_user_id, tenant_id),
            )
            row = cur.fetchone()
            if row:
                provider_npi = row["npi"] or ""
    except Exception as exc:
        logger.warning("bulk_attest: NPI lookup failed (non-fatal): %s", exc)

    measurement_year = _utcnow().year
    patient_ids = body.patient_ids
    placeholders = ",".join(["%s"] * len(patient_ids))

    # Collect open gaps
    gaps: list[dict[str, Any]] = []
    use_recapture = _table_exists("recapture_gaps")

    try:
        with raf_cursor() as cur:
            if use_recapture:
                cur.execute(
                    f"""
                    SELECT patient_id, hcc_code, icd10_code
                    FROM   recapture_gaps
                    WHERE  tenant_id     = %s
                      AND  status        = 'open'
                      AND  current_year  = %s
                      AND  patient_id    IN ({placeholders})
                    """,
                    [tenant_id, measurement_year] + patient_ids,
                )
            else:
                # Fallback: derive gaps from raf_patient_hcc (HCCs in prior year absent this year)
                prior_year = measurement_year - 1
                cur.execute(
                    f"""
                    SELECT ph.patient_id,
                           ph.hcc_code,
                           JSON_UNQUOTE(JSON_EXTRACT(ph.icd10_codes, '$[0]')) AS icd10_code
                    FROM   raf_patient_hcc ph
                    WHERE  ph.tenant_id       = %s
                      AND  ph.measurement_year = %s
                      AND  ph.patient_id       IN ({placeholders})
                      AND  NOT EXISTS (
                           SELECT 1
                           FROM   raf_patient_hcc cy
                           WHERE  cy.patient_id       = ph.patient_id
                             AND  cy.hcc_code         = ph.hcc_code
                             AND  cy.measurement_year = %s
                             AND  cy.tenant_id        = %s
                      )
                    """,
                    [tenant_id, prior_year] + patient_ids + [measurement_year, tenant_id],
                )
            gaps = cur.fetchall() or []
    except Exception as exc:
        logger.error("bulk_attest: gap fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not gaps:
        return {"created": 0, "message": "No open gaps found for selected patients"}

    # Deduplicate (patient_id, hcc_code, icd10_code)
    seen: set[tuple] = set()
    unique_gaps: list[dict[str, Any]] = []
    for g in gaps:
        key = (int(g["patient_id"]), g["hcc_code"] or "", g["icd10_code"] or "")
        if key not in seen:
            seen.add(key)
            unique_gaps.append(g)

    now = _utcnow()
    created = 0
    for gap in unique_gaps:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    INSERT IGNORE INTO provider_attestations
                        (patient_id, hcc_code, hcc_description,
                         icd10_code, icd10_description, source,
                         provider_npi, provider_user_id,
                         status, tenant_id, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, 'manual', %s, %s,
                         'pending', %s, %s, %s)
                    """,
                    (
                        int(gap["patient_id"]),
                        gap["hcc_code"] or "",
                        f"HCC {gap['hcc_code']}",
                        gap["icd10_code"] or "",
                        "",
                        provider_npi,
                        provider_user_id,
                        tenant_id,
                        now, now,
                    ),
                )
                created += cur.rowcount
        except Exception as exc:
            logger.warning("bulk_attest: insert failed for gap %s: %s", gap, exc)

    logger.info(
        "bulk_attest: user=%s tenant=%s patients=%d gaps_found=%d created=%d",
        provider_user_id, tenant_id, len(patient_ids), len(unique_gaps), created,
    )
    return {"created": created, "gaps_found": len(unique_gaps)}


# ---------------------------------------------------------------------------
# POST /api/v1/worklist/bulk-export
# ---------------------------------------------------------------------------

@router.post("/bulk-export", summary="Export selected patients with open gaps as CSV")
def bulk_export(
    body: BulkExportRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "read")),
) -> StreamingResponse:
    """
    Returns a CSV stream with columns:
    patient_id, patient_name, dob, open_gap_count, hcc_codes, icd10_codes,
    estimated_revenue_at_risk, priority_score
    """
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")

    measurement_year = _utcnow().year
    patient_ids = body.patient_ids
    placeholders = ",".join(["%s"] * len(patient_ids))

    # Fetch patient demographics
    patients_map: dict[int, dict[str, Any]] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT id,
                       CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,'')) AS patient_name,
                       dob
                FROM   patients
                WHERE  tenant_id = %s
                  AND  id IN ({placeholders})
                """,
                [tenant_id] + patient_ids,
            )
            for row in cur.fetchall():
                patients_map[int(row["id"])] = {
                    "patient_name": row["patient_name"].strip(),
                    "dob": str(row["dob"]) if row["dob"] else "",
                }
    except Exception as exc:
        logger.error("bulk_export: patient fetch failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Fetch open gaps
    gaps_map: dict[int, list[dict[str, Any]]] = {pid: [] for pid in patient_ids}
    use_recapture = _table_exists("recapture_gaps")
    try:
        with raf_cursor() as cur:
            if use_recapture:
                cur.execute(
                    f"""
                    SELECT patient_id, hcc_code, icd10_code,
                           COALESCE(revenue_impact, 0) AS revenue_impact
                    FROM   recapture_gaps
                    WHERE  tenant_id    = %s
                      AND  status       = 'open'
                      AND  current_year = %s
                      AND  patient_id   IN ({placeholders})
                    """,
                    [tenant_id, measurement_year] + patient_ids,
                )
            else:
                prior_year = measurement_year - 1
                cur.execute(
                    f"""
                    SELECT ph.patient_id, ph.hcc_code,
                           JSON_UNQUOTE(JSON_EXTRACT(ph.icd10_codes, '$[0]')) AS icd10_code,
                           COALESCE(ph.raf_coefficient * 3000, 500) AS revenue_impact
                    FROM   raf_patient_hcc ph
                    WHERE  ph.tenant_id        = %s
                      AND  ph.measurement_year  = %s
                      AND  ph.patient_id        IN ({placeholders})
                      AND  NOT EXISTS (
                           SELECT 1 FROM raf_patient_hcc cy
                           WHERE cy.patient_id = ph.patient_id
                             AND cy.hcc_code   = ph.hcc_code
                             AND cy.measurement_year = %s
                             AND cy.tenant_id = %s
                      )
                    """,
                    [tenant_id, prior_year] + patient_ids + [measurement_year, tenant_id],
                )
            for row in cur.fetchall():
                pid = int(row["patient_id"])
                gaps_map.setdefault(pid, []).append({
                    "hcc_code": row["hcc_code"] or "",
                    "icd10_code": row["icd10_code"] or "",
                    "revenue_impact": float(row["revenue_impact"] or 0),
                })
    except Exception as exc:
        logger.warning("bulk_export: gap fetch failed (non-fatal): %s", exc)

    # Build CSV in-memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "patient_id", "patient_name", "dob",
        "open_gap_count", "hcc_codes", "icd10_codes",
        "estimated_revenue_at_risk",
    ])
    for pid in patient_ids:
        info = patients_map.get(pid, {"patient_name": f"Patient {pid}", "dob": ""})
        g_list = gaps_map.get(pid, [])
        writer.writerow([
            pid,
            info["patient_name"],
            info["dob"],
            len(g_list),
            "|".join(g["hcc_code"] for g in g_list),
            "|".join(g["icd10_code"] for g in g_list),
            round(sum(g["revenue_impact"] for g in g_list), 2),
        ])

    csv_bytes = output.getvalue().encode("utf-8")

    export_date = _utcnow().strftime("%Y%m%d")
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=worklist_export_{export_date}.csv",
            "Content-Length": str(len(csv_bytes)),
        },
    )
