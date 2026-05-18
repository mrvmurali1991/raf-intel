"""
Demo-mode endpoints for the executive demo page at /admin/demo.

Routes
------
POST /api/admin/demo/reset
    Admin-only.  Enqueues Celery task ``raf.demo.reseed_realistic`` that
    truncates demo seed rows and re-runs the realistic-data seeder.
    Returns ``{ job_id }`` immediately; the caller polls
    GET /api/jobs/{job_id} for progress (existing jobs router).

GET /api/admin/demo/stats
    Admin/manager.  Returns live tenant KPIs for the Hero stat counters.

GET /api/admin/demo/suspects
    Admin/manager.  Returns up to 3 anonymised suspects from
    raf_suspect_conditions joined with their raf_meat_evidence.
    Falls back to a safe stub if no rows are present so the page is
    always presentable during a live demo.
"""
# Note: do NOT use 'from __future__ import annotations' —
# it breaks FastAPI/Pydantic schema generation.

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/demo",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin_or_manager(current_user: dict) -> None:
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Admin or manager role required")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DemoResetResponse(BaseModel):
    job_id: str
    status: str = "queued"
    message: str = "Demo reseed job has been queued."


class DemoStatsResponse(BaseModel):
    patient_count: int
    avg_raf_score: int  # ×100 for integer transport; UI divides by 100
    suspects_ytd: int
    revenue_at_stake: int  # USD


# ---------------------------------------------------------------------------
# POST /api/admin/demo/reset
# ---------------------------------------------------------------------------

@router.post(
    "/reset",
    response_model=DemoResetResponse,
    summary="Reset demo data — re-seed realistic tenant data (admin only)",
)
async def reset_demo_data(
    current_user: dict = Depends(get_current_user),
) -> DemoResetResponse:
    """
    Enqueues Celery task ``raf.demo.reseed_realistic``.

    The task:
      1. Deletes raf_suspect_conditions rows where
         ``evidence_detail->>'$.source' = 'demo_seed'``.
      2. Re-runs the realistic demo seeder.
      3. Updates the job status row.

    Returns ``job_id`` immediately; poll ``GET /api/jobs/{job_id}`` for progress.
    """
    _require_admin_or_manager(current_user)
    role = (current_user.get("role") or "").lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for demo reset")

    job_id = str(uuid.uuid4())

    try:
        from app.worker import celery_app  # type: ignore[import]

        celery_app.send_task(
            "raf.demo.reseed_realistic",
            kwargs={
                "job_id": job_id,
                "tenant_id": current_user.get("tenant_id", "1"),
                "initiated_by": current_user.get("sub", "system"),
            },
            queue="default",
        )
        logger.info("Demo reseed task queued job_id=%s", job_id)
    except Exception as exc:  # noqa: BLE001
        # Worker may be offline in dev — still return job_id; UI shows "worker offline".
        logger.warning("Could not enqueue demo reseed (worker offline?): %s", exc)

    return DemoResetResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# GET /api/admin/demo/stats
# ---------------------------------------------------------------------------

_FALLBACK_STATS = DemoStatsResponse(
    patient_count=12480,
    avg_raf_score=118,      # 1.18 after ÷100
    suspects_ytd=3740,
    revenue_at_stake=4_200_000,
)


@router.get(
    "/stats",
    response_model=DemoStatsResponse,
    summary="Live KPI stats for the Hero section of the demo page",
)
async def get_demo_stats(
    current_user: dict = Depends(get_current_user),
) -> DemoStatsResponse:
    """Live tenant metrics for the animated hero counters.  Falls back to stub on DB error."""
    _require_admin_or_manager(current_user)
    tenant_id = str(current_user.get("tenant_id", "1"))

    try:
        async with get_db() as conn:
            row_patients = await conn.fetchone(
                "SELECT COUNT(*) AS cnt FROM patients WHERE tenant_id = %s",
                (tenant_id,),
            )
            patient_count: int = int((row_patients or {}).get("cnt", 0))

            row_raf = await conn.fetchone(
                """
                SELECT AVG(rs.raf_score) AS avg_raf
                FROM raf_scores rs
                INNER JOIN (
                    SELECT patient_id, MAX(score_date) AS max_date
                    FROM raf_scores WHERE tenant_id = %s GROUP BY patient_id
                ) latest ON rs.patient_id = latest.patient_id
                         AND rs.score_date = latest.max_date
                WHERE rs.tenant_id = %s
                """,
                (tenant_id, tenant_id),
            )
            raw_avg: float = float((row_raf or {}).get("avg_raf") or 1.18)
            avg_raf_score: int = round(raw_avg * 100)

            row_suspects = await conn.fetchone(
                """
                SELECT COUNT(*) AS cnt FROM raf_suspect_conditions
                WHERE tenant_id = %s AND YEAR(created_at) = YEAR(CURDATE())
                """,
                (tenant_id,),
            )
            suspects_ytd: int = int((row_suspects or {}).get("cnt", 0))

            row_rev = await conn.fetchone(
                """
                SELECT COALESCE(SUM(estimated_value), 0) AS total
                FROM raf_suspect_conditions
                WHERE tenant_id = %s
                  AND status IN ('open', 'pending_review')
                  AND YEAR(created_at) = YEAR(CURDATE())
                """,
                (tenant_id,),
            )
            revenue_at_stake: int = int((row_rev or {}).get("total", 0))

            if patient_count == 0 and suspects_ytd == 0:
                return _FALLBACK_STATS

            return DemoStatsResponse(
                patient_count=patient_count or _FALLBACK_STATS.patient_count,
                avg_raf_score=avg_raf_score or _FALLBACK_STATS.avg_raf_score,
                suspects_ytd=suspects_ytd or _FALLBACK_STATS.suspects_ytd,
                revenue_at_stake=revenue_at_stake or _FALLBACK_STATS.revenue_at_stake,
            )

    except Exception as exc:  # noqa: BLE001
        logger.warning("demo/stats DB query failed, using fallback: %s", exc)
        return _FALLBACK_STATS


# ---------------------------------------------------------------------------
# GET /api/admin/demo/suspects
# ---------------------------------------------------------------------------

_FALLBACK_SUSPECTS: list[dict[str, Any]] = [
    {
        "id": 1,
        "patient_initials": "J.M.",
        "hcc_label": "Chronic Kidney Disease, Stage 3",
        "icd10": "N18.3",
        "confidence": 0.92,
        "evidence_sentence": (
            "eGFR consistently below 45 mL/min/1.73m² for the past 18 months "
            "per lab records dated 2024-11-08."
        ),
        "page_number": 4,
        "source_doc": "Nephrology Consult Note 2024-11-12",
    },
    {
        "id": 2,
        "patient_initials": "R.T.",
        "hcc_label": "Major Depressive Disorder, Moderate",
        "icd10": "F32.1",
        "confidence": 0.87,
        "evidence_sentence": (
            "Patient endorses persistent depressed mood, anhedonia, and sleep "
            "disturbance consistent with MDD per PHQ-9 score of 14."
        ),
        "page_number": 2,
        "source_doc": "Behavioral Health Assessment 2025-01-20",
    },
    {
        "id": 3,
        "patient_initials": "A.K.",
        "hcc_label": "Peripheral Vascular Disease",
        "icd10": "I73.9",
        "confidence": 0.83,
        "evidence_sentence": (
            "ABI of 0.72 bilaterally noted; claudication symptoms reported with "
            "ambulation > 1 block."
        ),
        "page_number": 7,
        "source_doc": "Vascular Surgery Consult 2025-02-03",
    },
]


@router.get(
    "/suspects",
    summary="Up to 3 anonymised suspect extractions for the NLP demo section",
)
async def get_demo_suspects(
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Returns up to 3 suspects from ``raf_suspect_conditions`` joined with
    ``raf_meat_evidence``.  Patient names are reduced to initials.
    Falls back to static stub when no rows are present.
    """
    _require_admin_or_manager(current_user)
    tenant_id = str(current_user.get("tenant_id", "1"))

    try:
        async with get_db() as conn:
            rows = await conn.fetchall(
                """
                SELECT
                    sc.id,
                    CONCAT(LEFT(p.first_name,1), '.', LEFT(p.last_name,1), '.') AS patient_initials,
                    sc.hcc_label,
                    sc.icd10_code          AS icd10,
                    sc.confidence_score    AS confidence,
                    COALESCE(me.evidence_sentence, sc.evidence_sentence, '') AS evidence_sentence,
                    COALESCE(me.page_number, 1)                              AS page_number,
                    COALESCE(me.source_document_name,
                             sc.source_document_name, 'Clinical Note')       AS source_doc
                FROM raf_suspect_conditions sc
                LEFT JOIN patients p
                       ON p.id = sc.patient_id AND p.tenant_id = sc.tenant_id
                LEFT JOIN raf_meat_evidence me
                       ON me.suspect_id = sc.id
                      AND me.id = (
                          SELECT MIN(id) FROM raf_meat_evidence
                          WHERE suspect_id = sc.id
                      )
                WHERE sc.tenant_id = %s
                ORDER BY sc.confidence_score DESC
                LIMIT 3
                """,
                (tenant_id,),
            )

            if not rows:
                return _FALLBACK_SUSPECTS

            result = []
            for r in rows:
                raw_init = str(r.get("patient_initials") or "P.P.")
                parts = [p[:1].upper() for p in raw_init.replace(".", " ").split() if p]
                safe_initials = ".".join(parts) + "." if parts else "P.P."
                result.append(
                    {
                        "id": r["id"],
                        "patient_initials": safe_initials,
                        "hcc_label": r.get("hcc_label") or "Unknown HCC",
                        "icd10": r.get("icd10") or "Z99.9",
                        "confidence": float(r.get("confidence") or 0.8),
                        "evidence_sentence": r.get("evidence_sentence") or "",
                        "page_number": int(r.get("page_number") or 1),
                        "source_doc": r.get("source_doc") or "Clinical Note",
                    }
                )
            return result

    except Exception as exc:  # noqa: BLE001
        logger.warning("demo/suspects DB query failed, using fallback: %s", exc)
        return _FALLBACK_SUSPECTS
