"""Chart-chase workflow orchestrator (production-grade).

State machine
-------------
requested → assigned → in_progress → received → indexed → coded → closed
        \\─→ cancelled  (terminal from any state)

Each transition is recorded in `cc_events_v2` and emits an immutable-audit
event so the chain-of-custody is fully reconstructable.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from app.db import raf_cursor
from app.services.audit_logger import log_phi_access

logger = logging.getLogger(__name__)

# State machine — allowed transitions
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "requested":   {"assigned", "cancelled"},
    "assigned":    {"in_progress", "cancelled"},
    "in_progress": {"received", "cancelled"},
    "received":    {"indexed", "cancelled"},
    "indexed":     {"coded", "cancelled"},
    "coded":       {"closed"},
    "closed":      set(),
    "cancelled":   set(),
}

REASON_CODES = {
    "MEAT_missing",
    "V28_validation",
    "RADV_sample",
    "HEDIS_gap",
    "AWV_documentation",
    "MAO_004_reject",
    "other",
}

VALID_VENDORS = {
    "ciox", "direct_trust", "fax", "internal", "patient_portal", "on_site",
}

# Priority → SLA in hours
SLA_HOURS = {1: 24, 2: 48, 3: 72, 4: 168, 5: 336, 6: 504, 7: 672, 8: 840, 9: 1008}


# ---------- Helpers ----------

def _emit_event(
    request_id: int,
    event_type: str,
    actor_user_id: int | None,
    payload: dict | None = None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO cc_events_v2
                 (request_id, event_type, actor_user_id, payload)
               VALUES (%s, %s, %s, %s)""",
            (
                request_id,
                event_type[:64],
                actor_user_id,
                json.dumps(payload) if payload else None,
            ),
        )


def _get_request(tenant_id: str, request_id: int) -> dict | None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM cc_requests_v2 WHERE id=%s AND tenant_id=%s",
            (request_id, tenant_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _due_from_priority(priority: int) -> datetime:
    hrs = SLA_HOURS.get(int(priority), 336)
    return datetime.utcnow() + timedelta(hours=hrs)


# ---------- API ----------

def create_request(
    *,
    tenant_id: str,
    patient_id: int,
    requested_by_user_id: int,
    reason: str,
    reason_detail: str = "",
    date_of_service: str | None = None,
    icd10_codes: list[str] | None = None,
    hcc_codes: list[str] | None = None,
    priority: int = 5,
    assigned_vendor: str | None = None,
) -> dict[str, Any]:
    if reason not in REASON_CODES:
        raise ValueError(f"Invalid reason: {reason}")
    if assigned_vendor and assigned_vendor not in VALID_VENDORS:
        raise ValueError(f"Invalid vendor: {assigned_vendor}")
    if priority < 1 or priority > 9:
        raise ValueError("priority must be 1..9")

    due_at = _due_from_priority(priority)

    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO cc_requests_v2
                 (tenant_id, patient_id, requested_by_user_id, reason,
                  reason_detail, date_of_service, icd10_codes, hcc_codes,
                  priority, assigned_vendor, due_at, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       CASE WHEN %s IS NOT NULL THEN 'assigned' ELSE 'requested' END)""",
            (
                tenant_id, patient_id, requested_by_user_id, reason,
                reason_detail[:1000] if reason_detail else None,
                date_of_service,
                json.dumps(icd10_codes) if icd10_codes else None,
                json.dumps(hcc_codes) if hcc_codes else None,
                priority,
                assigned_vendor,
                due_at,
                assigned_vendor,
            ),
        )
        rid = int(cur.lastrowid)

    _emit_event(
        rid,
        "CHART_CHASE_REQUESTED",
        requested_by_user_id,
        {
            "reason": reason,
            "priority": priority,
            "vendor": assigned_vendor,
        },
    )
    log_phi_access(
        action="CHART_CHASE_REQUESTED",
        resource="cc_requests_v2",
        patient_id=patient_id,
        user=str(requested_by_user_id),
        tenant_id=tenant_id,
    )

    req = _get_request(tenant_id, rid)
    return req or {"id": rid}


def assign(
    tenant_id: str,
    request_id: int,
    vendor: str | None,
    assigned_to_user_id: int | None,
    actor_user_id: int,
) -> dict:
    if vendor and vendor not in VALID_VENDORS:
        raise ValueError(f"Invalid vendor: {vendor}")
    req = _get_request(tenant_id, request_id)
    if not req:
        raise LookupError(f"request {request_id} not found")
    if req["status"] not in ("requested", "assigned"):
        raise ValueError(f"Cannot assign in state {req['status']}")

    with raf_cursor() as cur:
        cur.execute(
            """UPDATE cc_requests_v2
               SET assigned_vendor=%s, assigned_to_user_id=%s, status='assigned'
               WHERE id=%s AND tenant_id=%s""",
            (vendor, assigned_to_user_id, request_id, tenant_id),
        )
    _emit_event(
        request_id, "CHART_CHASE_ASSIGNED", actor_user_id,
        {"vendor": vendor, "to_user_id": assigned_to_user_id},
    )
    return _get_request(tenant_id, request_id) or {}


def transition(
    tenant_id: str,
    request_id: int,
    new_status: str,
    actor_user_id: int,
    note: str = "",
) -> dict:
    if new_status not in ALLOWED_TRANSITIONS:
        raise ValueError(f"Unknown status: {new_status}")
    req = _get_request(tenant_id, request_id)
    if not req:
        raise LookupError(f"request {request_id} not found")
    cur_status = req["status"]
    if new_status not in ALLOWED_TRANSITIONS.get(cur_status, set()):
        raise ValueError(
            f"Illegal transition {cur_status} → {new_status}"
        )

    ts_col_map = {
        "in_progress": None,
        "received": "received_at",
        "indexed": "indexed_at",
        "closed": "closed_at",
    }
    ts_col = ts_col_map.get(new_status)

    with raf_cursor() as cur:
        if ts_col:
            cur.execute(
                f"UPDATE cc_requests_v2 SET status=%s, {ts_col}=NOW() "
                "WHERE id=%s AND tenant_id=%s",
                (new_status, request_id, tenant_id),
            )
        else:
            cur.execute(
                "UPDATE cc_requests_v2 SET status=%s WHERE id=%s AND tenant_id=%s",
                (new_status, request_id, tenant_id),
            )
    _emit_event(
        request_id,
        f"CHART_CHASE_{new_status.upper()}",
        actor_user_id,
        {"from": cur_status, "note": note[:500] if note else None},
    )
    return _get_request(tenant_id, request_id) or {}


def add_document(
    *,
    tenant_id: str,
    request_id: int,
    filename: str,
    mime_type: str,
    size_bytes: int,
    storage_path: str,
    actor_user_id: int,
) -> dict[str, Any]:
    req = _get_request(tenant_id, request_id)
    if not req:
        raise LookupError(f"request {request_id} not found")
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO cc_documents_v2
                 (request_id, tenant_id, filename, mime_type, size_bytes,
                  storage_path, ocr_status)
               VALUES (%s,%s,%s,%s,%s,%s,'pending')""",
            (request_id, tenant_id, filename[:255], mime_type[:64],
             size_bytes, storage_path[:500]),
        )
        doc_id = int(cur.lastrowid)
    _emit_event(
        request_id, "CHART_CHASE_DOCUMENT_UPLOADED", actor_user_id,
        {"document_id": doc_id, "filename": filename, "size": size_bytes},
    )
    # Auto-transition to received on first document upload
    if req["status"] in ("assigned", "in_progress"):
        try:
            if req["status"] == "assigned":
                transition(tenant_id, request_id, "in_progress", actor_user_id,
                           note="first document uploaded")
            transition(tenant_id, request_id, "received", actor_user_id,
                       note="document received")
        except Exception as e:
            logger.warning("auto-transition skipped: %s", e)
    return {"document_id": doc_id, "request_id": request_id,
            "ocr_status": "pending"}


def list_requests(
    *,
    tenant_id: str,
    status: str | None = None,
    priority: int | None = None,
    assigned_to_user_id: int | None = None,
    patient_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    where = ["tenant_id=%s"]
    params: list = [tenant_id]
    if status:
        where.append("status=%s")
        params.append(status)
    if priority is not None:
        where.append("priority=%s")
        params.append(priority)
    if assigned_to_user_id is not None:
        where.append("assigned_to_user_id=%s")
        params.append(assigned_to_user_id)
    if patient_id is not None:
        where.append("patient_id=%s")
        params.append(patient_id)
    wsql = " AND ".join(where)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM cc_requests_v2 WHERE {wsql}",
            tuple(params),
        )
        row = cur.fetchone()
        total = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0

        cur.execute(
            f"""SELECT * FROM cc_requests_v2
                WHERE {wsql}
                ORDER BY priority ASC, due_at ASC, id DESC
                LIMIT %s OFFSET %s""",
            tuple(params) + (limit, offset),
        )
        rows = [dict(r) for r in (cur.fetchall() or [])]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "requests": rows,
    }


def get_request_detail(tenant_id: str, request_id: int) -> dict:
    req = _get_request(tenant_id, request_id)
    if not req:
        raise LookupError(f"request {request_id} not found")
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM cc_documents_v2 WHERE request_id=%s ORDER BY uploaded_at",
            (request_id,),
        )
        docs = [dict(r) for r in (cur.fetchall() or [])]
        cur.execute(
            "SELECT * FROM cc_events_v2 WHERE request_id=%s ORDER BY created_at",
            (request_id,),
        )
        events = [dict(r) for r in (cur.fetchall() or [])]
    req["documents"] = docs
    req["events"] = events
    return req


def dashboard(tenant_id: str) -> dict:
    """Funnel counts + median TAT in days."""
    out = {s: 0 for s in [
        "requested", "assigned", "in_progress", "received",
        "indexed", "coded", "closed", "cancelled",
    ]}
    with raf_cursor() as cur:
        cur.execute(
            """SELECT status, COUNT(*) AS n FROM cc_requests_v2
               WHERE tenant_id=%s GROUP BY status""",
            (tenant_id,),
        )
        for row in (cur.fetchall() or []):
            s = row["status"] if isinstance(row, dict) else row[0]
            n = row["n"] if isinstance(row, dict) else row[1]
            out[str(s)] = int(n)

        cur.execute(
            """SELECT AVG(TIMESTAMPDIFF(HOUR, requested_at, closed_at)) AS h
               FROM cc_requests_v2
               WHERE tenant_id=%s AND status='closed' AND closed_at IS NOT NULL""",
            (tenant_id,),
        )
        row = cur.fetchone()
        avg_hours = float(row["h"] if isinstance(row, dict) else row[0]) if row and (
            row["h"] if isinstance(row, dict) else row[0]) is not None else None

        cur.execute(
            """SELECT COUNT(*) AS n FROM cc_requests_v2
               WHERE tenant_id=%s AND status IN ('requested','assigned','in_progress')
                 AND due_at < NOW()""",
            (tenant_id,),
        )
        row = cur.fetchone()
        overdue = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0

    return {
        "tenant_id": tenant_id,
        "by_status": out,
        "total": sum(out.values()),
        "avg_close_hours": round(avg_hours, 1) if avg_hours else None,
        "overdue_count": overdue,
    }


def bulk_create_from_rows(
    *,
    tenant_id: str,
    requested_by_user_id: int,
    rows: list[dict],
) -> dict[str, Any]:
    """Bulk-create requests from a list of {patient_id, reason, date_of_service,
    icd10, hcc, priority} dicts."""
    created: list[int] = []
    errors: list[dict] = []
    for i, r in enumerate(rows):
        try:
            req = create_request(
                tenant_id=tenant_id,
                patient_id=int(r["patient_id"]),
                requested_by_user_id=requested_by_user_id,
                reason=r.get("reason", "RADV_sample"),
                reason_detail=r.get("reason_detail", ""),
                date_of_service=r.get("date_of_service"),
                icd10_codes=r.get("icd10_codes") or r.get("icd10"),
                hcc_codes=r.get("hcc_codes") or r.get("hcc"),
                priority=int(r.get("priority", 5)),
                assigned_vendor=r.get("assigned_vendor"),
            )
            created.append(int(req["id"]))
        except Exception as e:
            errors.append({"row": i, "error": str(e)[:200]})
    return {
        "created_count": len(created),
        "created_ids": created,
        "errors_count": len(errors),
        "errors": errors,
    }
