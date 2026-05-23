"""Celery hand-off for non-blocking FHIR Condition write-back.

Default behavior remains synchronous (existing callers unchanged). When
the accept handler sets `async_writeback=True`, the synchronous path
returns 200 immediately and this module dispatches the FHIR POST in the
background via the existing per-tenant circuit breaker.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


def mark_writeback_pending(
    *, tenant_id: str | int, suspect_id: int
) -> None:
    """Synchronously stamp the row with status='pending' before enqueue."""
    with raf_cursor() as cur:
        cur.execute(
            """UPDATE raf_suspect_conditions
               SET fhir_writeback_status='pending',
                   fhir_writeback_async_at=NOW(),
                   fhir_writeback_attempts=COALESCE(fhir_writeback_attempts,0),
                   fhir_writeback_last_error=NULL
               WHERE id=%s AND tenant_id=%s""",
            (int(suspect_id), str(tenant_id)),
        )


def mark_writeback_failed(
    *, tenant_id: str | int, suspect_id: int, error: str
) -> None:
    """Stamp the row with status='failed' + error message.

    Used by the admin replay handler when celery .delay() raises BEFORE
    the worker ever runs — without this, the row would be orphaned in
    'pending' and invisible to list_failed_writebacks.
    """
    with raf_cursor() as cur:
        cur.execute(
            """UPDATE raf_suspect_conditions
               SET fhir_writeback_status='failed',
                   fhir_writeback_last_error=%s
               WHERE id=%s AND tenant_id=%s""",
            (error[:500], int(suspect_id), str(tenant_id)),
        )


def _row(tenant_id: str | int, suspect_id: int) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, patient_id, suspect_icd10, suspect_hcc,
                      fhir_condition_id, fhir_writeback_attempts
               FROM raf_suspect_conditions
               WHERE id=%s AND tenant_id=%s""",
            (int(suspect_id), str(tenant_id)),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def perform_writeback(
    *,
    tenant_id: str | int,
    suspect_id: int,
    meat_signed: bool,
    user_role: str | None,
    user_id: int | None,
) -> dict[str, Any]:
    """Body of the Celery task — kept in a normal module so we can unit-test
    it without spinning Celery."""
    row = _row(tenant_id, suspect_id)
    if not row:
        return {"status": "missing", "suspect_id": suspect_id}

    # Best-effort: increment attempt counter regardless of outcome
    attempts = int(row.get("fhir_writeback_attempts") or 0) + 1
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE raf_suspect_conditions SET fhir_writeback_attempts=%s "
            "WHERE id=%s AND tenant_id=%s",
            (attempts, int(suspect_id), str(tenant_id)),
        )

    try:
        # Lazy import — keeps this module testable without a live FHIR adapter
        from app.services.fhir_problem_list import push_problem_list_condition
        result = push_problem_list_condition(
            patient_emr_pid=str(row["patient_id"]),
            icd10_code=str(row["suspect_icd10"]),
            hcc_label=f"HCC {row['suspect_hcc']}" if row.get("suspect_hcc") else "",
            tenant_id=str(tenant_id),
            suspect_id=int(suspect_id),
            meat_signed=bool(meat_signed),
            user_role=user_role,
            user_id=user_id,
        )
        cond_id = result.get("fhir_condition_id") if isinstance(result, dict) else None
        with raf_cursor() as cur:
            cur.execute(
                """UPDATE raf_suspect_conditions
                   SET fhir_writeback_status='sent',
                       fhir_writeback_last_error=NULL,
                       fhir_condition_id=COALESCE(%s, fhir_condition_id)
                   WHERE id=%s AND tenant_id=%s""",
                (cond_id, int(suspect_id), str(tenant_id)),
            )
        return {"status": "sent", "suspect_id": suspect_id,
                "fhir_condition_id": cond_id, "attempts": attempts}
    except Exception as exc:
        err = str(exc)[:500]
        logger.warning(
            "async FHIR writeback failed suspect_id=%s attempt=%s err=%s",
            suspect_id, attempts, err,
        )
        with raf_cursor() as cur:
            cur.execute(
                """UPDATE raf_suspect_conditions
                   SET fhir_writeback_status='failed',
                       fhir_writeback_last_error=%s
                   WHERE id=%s AND tenant_id=%s""",
                (err, int(suspect_id), str(tenant_id)),
            )
        return {"status": "failed", "suspect_id": suspect_id,
                "error": err, "attempts": attempts}


def get_writeback_status(
    tenant_id: str | int, suspect_id: int
) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id, fhir_writeback_status, fhir_writeback_attempts,
                      fhir_writeback_last_error, fhir_writeback_async_at,
                      fhir_condition_id
               FROM raf_suspect_conditions
               WHERE id=%s AND tenant_id=%s""",
            (int(suspect_id), str(tenant_id)),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_failed_writebacks(
    tenant_id: str | int, limit: int = 100
) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id, patient_id, suspect_icd10,
                      fhir_writeback_attempts, fhir_writeback_last_error,
                      fhir_writeback_async_at
               FROM raf_suspect_conditions
               WHERE tenant_id=%s AND fhir_writeback_status='failed'
               ORDER BY fhir_writeback_async_at DESC
               LIMIT %s""",
            (str(tenant_id), int(limit)),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
