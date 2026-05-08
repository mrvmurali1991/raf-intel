# DISCLAIMER: This module calculates CMS-HCC risk adjustment scores using the
# hccinfhir library. Not CMS-validated. For informational/analytics use only.
"""
Auto-score service — per-patient RAF calculation entrypoint.

Provides a single reusable function:

    score_patient(local_pid, model_version, payment_year) -> dict

that wraps the existing calculate_raf_score engine, persists to raf_scores,
and returns a compact summary dict suitable for automated pipelines and APIs.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from app.db import raf_cursor
from app.services.raf.calculator import calculate_raf_score

logger = logging.getLogger(__name__)


def _resolve_tenant_id(local_pid: int) -> str | None:
    """Return the tenant_id for a patient, or None if not found."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT tenant_id FROM patients WHERE id = %s LIMIT 1",
                (local_pid,),
            )
            row = cur.fetchone()
            if row:
                return row["tenant_id"]
    except Exception as exc:
        logger.warning("auto_score._resolve_tenant_id pid=%s: %s", local_pid, exc)
    return None


def score_patient(
    local_pid: int,
    model_version: str = "V28",
    payment_year: int = 2026,
) -> dict[str, Any]:
    """Compute and persist the RAF score for a single patient.

    Parameters
    ----------
    local_pid:      patients.id in the RAF Intelligence database.
    model_version:  "V28" (default), "V24", or "blended".
                    Mapped to the lowercase keys expected by calculate_raf_score.
    payment_year:   CMS payment year (default 2026).

    Returns
    -------
    dict with keys:
        raf_score, hcc_count, hcc_codes, demographic_score,
        disease_score, model_version, payment_year

    Returns {} on any error (exception is logged with full traceback).

    Idempotency
    -----------
    The underlying _upsert_raf_score uses ON DUPLICATE KEY UPDATE so
    re-running for the same (patient_id, measurement_year, score_type)
    updates the row — no duplicates are created.
    """
    # Normalise model_version to the lowercase key expected by calculator
    mv_map = {"V28": "v28", "V24": "v24", "BLENDED": "blended"}
    mv_key = mv_map.get(model_version.upper(), "v28")

    try:
        tenant_id = _resolve_tenant_id(local_pid)
        if tenant_id is None:
            logger.error(
                "auto_score.patient_not_found",
                extra={"pid": local_pid},
            )
            return {}

        result = calculate_raf_score(
            patient_id=local_pid,
            measurement_year=payment_year,
            model_version=mv_key,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            require_meat=False,  # auto-score includes all confirmed diagnoses
        )

        if not result:
            logger.warning(
                "auto_score.empty_result",
                extra={"pid": local_pid, "payment_year": payment_year},
            )
            return {}

        raf_score: float = round(
            float(result.get("payment_raf") or result.get("raf_score") or 0.0), 4
        )
        final_hcc_list: list = result.get("final_hcc_list") or result.get("hcc_list") or []
        hcc_count: int = len(final_hcc_list)
        hcc_codes: list[str] = [str(h) for h in final_hcc_list]
        demographic_score: float = round(float(result.get("demographic_score") or 0.0), 4)
        disease_score: float = round(float(result.get("disease_score") or 0.0), 4)
        actual_model: str = str(result.get("model_version") or model_version)

        summary: dict[str, Any] = {
            "raf_score": raf_score,
            "hcc_count": hcc_count,
            "hcc_codes": hcc_codes,
            "demographic_score": demographic_score,
            "disease_score": disease_score,
            "model_version": actual_model,
            "payment_year": payment_year,
        }

        logger.info(
            "auto_score.scored",
            extra={
                "pid": local_pid,
                "raf": raf_score,
                "hcc_count": hcc_count,
                "model_version": actual_model,
                "payment_year": payment_year,
            },
        )
        return summary

    except Exception:
        logger.error(
            "auto_score.error pid=%s payment_year=%s\n%s",
            local_pid,
            payment_year,
            traceback.format_exc(),
        )
        return {}
