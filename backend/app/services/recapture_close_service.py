"""
Recapture Close Service
=======================

Smart-close workflow for recapture gaps. Layered on top of (and never modifying)
``recapture_gap_service`` so the original detection/list logic stays intact.

Capabilities
------------
1. ``attribute_orphan_gaps(tenant_id)``
       Backfill ``provider_npi`` for any ``recapture_gaps`` row with NULL
       provider, by looking up ``provider_patient_panel`` → ``providers.npi``.

2. ``smart_close(gap_id, closed_by, evidence_phrase, meat_element,
                 write_to_raf_hcc=True, tenant_id=None)``
       Transactionally:
         a. Mark the gap recaptured + persist evidence + MEAT element + closer.
         b. Optionally INSERT IGNORE a ``raf_patient_hcc`` row for the current
            ``measurement_year`` so the HCC starts counting toward the RAF
            score. Skipped silently if the HCC is already documented.

3. ``bulk_close(gap_ids, closed_by, evidence_phrase, meat_element=None,
                write_to_raf_hcc=True, tenant_id=None)``
       Apply the same evidence to many gaps in one call.

4. ``reopen_gap(gap_id, reopened_by, reason, tenant_id=None)``
       Flip status back to ``open`` when the MEAT support is later judged
       insufficient. Clears resolved_at / resolved_by and stamps reopen audit
       columns.

5. ``get_close_history(tenant_id, year=None, limit=50)``
       Recent recapture closures with closer + evidence quote, for the
       Close-History timeline UI.

The recapture_gaps table is extended via
``backend/migrations/add_recapture_close_columns.sql`` to carry
``evidence_phrase``, ``meat_element``, ``reopened_at``, ``reopened_by``,
``reopen_reason``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)

_ALLOWED_MEAT_ELEMENTS: set[str] = {"M", "E", "A", "T"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _current_year() -> int:
    return _now_utc().year


def _validate_meat_element(meat_element: str | None) -> str | None:
    """Return the MEAT element if valid, else raise ValueError. None is allowed."""
    if meat_element is None:
        return None
    me = meat_element.strip().upper()
    if me not in _ALLOWED_MEAT_ELEMENTS:
        raise ValueError(
            f"Invalid meat_element '{meat_element}'. Allowed: {_ALLOWED_MEAT_ELEMENTS}"
        )
    return me


def _fetch_gap(cursor, gap_id: int, tenant_id: str | None) -> dict[str, Any] | None:
    """Load a gap row scoped to tenant when tenant_id is provided."""
    if tenant_id is not None:
        cursor.execute(
            "SELECT * FROM recapture_gaps WHERE id = %s AND tenant_id = %s",
            (gap_id, tenant_id),
        )
    else:
        cursor.execute("SELECT * FROM recapture_gaps WHERE id = %s", (gap_id,))
    return cursor.fetchone()


# ---------------------------------------------------------------------------
# 1. attribute_orphan_gaps
# ---------------------------------------------------------------------------

def attribute_orphan_gaps(tenant_id: str) -> dict[str, Any]:
    """Backfill ``provider_npi`` on every orphan recapture_gaps row.

    For each row in the tenant whose ``provider_npi IS NULL``, look up the
    patient's first matching ``provider_patient_panel`` entry and copy the
    provider's NPI into the gap row.

    Returns
    -------
        {"checked": int, "updated": int, "still_orphan": int}
    """
    select_sql = """
        SELECT rg.id              AS gap_id,
               rg.patient_id      AS patient_id,
               pr.npi             AS provider_npi
          FROM recapture_gaps rg
          LEFT JOIN provider_patient_panel ppp
                 ON ppp.patient_id = rg.patient_id
          LEFT JOIN providers pr
                 ON pr.id = ppp.provider_id
                AND pr.tenant_id = rg.tenant_id
         WHERE rg.tenant_id   = %s
           AND rg.provider_npi IS NULL
    """

    update_sql = "UPDATE recapture_gaps SET provider_npi = %s WHERE id = %s"

    count_orphan_sql = """
        SELECT COUNT(*) AS c
          FROM recapture_gaps
         WHERE tenant_id = %s
           AND provider_npi IS NULL
    """

    with raf_cursor() as cursor:
        cursor.execute(select_sql, (tenant_id,))
        candidates = cursor.fetchall()

        # Pick the first non-NULL NPI per gap_id (a patient can match many panels).
        best_match: dict[int, str] = {}
        checked: set[int] = set()
        for row in candidates:
            gid = row["gap_id"]
            checked.add(gid)
            npi = row.get("provider_npi")
            if npi and gid not in best_match:
                best_match[gid] = npi

        updated = 0
        for gid, npi in best_match.items():
            cursor.execute(update_sql, (npi, gid))
            updated += cursor.rowcount or 0

        cursor.execute(count_orphan_sql, (tenant_id,))
        still_orphan = int((cursor.fetchone() or {}).get("c") or 0)

    logger.info(
        "attribute_orphan_gaps tenant=%s checked=%d updated=%d still_orphan=%d",
        tenant_id, len(checked), updated, still_orphan,
    )
    return {
        "checked": len(checked),
        "updated": updated,
        "still_orphan": still_orphan,
    }


# ---------------------------------------------------------------------------
# 2. smart_close
# ---------------------------------------------------------------------------

def smart_close(
    gap_id: int,
    closed_by: str,
    evidence_phrase: str,
    meat_element: str | None = None,
    write_to_raf_hcc: bool = True,
    tenant_id: str | None = None,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """Transactionally close a recapture gap with documentation evidence.

    Steps performed inside a single cursor block:
      1. Verify the gap exists (and belongs to the tenant when supplied).
      2. UPDATE recapture_gaps → status='recaptured', resolved_at, resolved_by,
         evidence_phrase, meat_element.
      3. If ``write_to_raf_hcc`` and the HCC is not already in
         raf_patient_hcc for the current year, INSERT a row tagged
         ``source='recapture'``.

    Returns
    -------
        {
            "gap_id": int,
            "status": "recaptured",
            "raf_hcc_inserted": bool,
            "raf_hcc_already_present": bool,
            "measurement_year": int,
        }
    """
    if not evidence_phrase or not evidence_phrase.strip():
        raise ValueError("evidence_phrase is required")
    if not closed_by or not str(closed_by).strip():
        raise ValueError("closed_by is required")

    meat = _validate_meat_element(meat_element)
    year = measurement_year or _current_year()
    now = _now_utc()

    update_sql = """
        UPDATE recapture_gaps
           SET status          = 'recaptured',
               resolved_at     = %s,
               resolved_by     = %s,
               evidence_phrase = %s,
               meat_element    = %s,
               reopened_at     = NULL,
               reopened_by     = NULL,
               reopen_reason   = NULL
         WHERE id = %s
    """

    raf_hcc_inserted = False
    raf_hcc_already_present = False

    with raf_cursor() as cursor:
        gap = _fetch_gap(cursor, gap_id, tenant_id)
        if not gap:
            raise ValueError(f"Gap {gap_id} not found")

        cursor.execute(
            update_sql,
            (now, closed_by, evidence_phrase.strip(), meat, gap_id),
        )

        if write_to_raf_hcc:
            patient_id = gap["patient_id"]
            hcc_code = gap["hcc_code"]
            gap_tenant = gap["tenant_id"]

            # Already coded? Skip — never duplicate.
            cursor.execute(
                """
                SELECT id FROM raf_patient_hcc
                 WHERE patient_id       = %s
                   AND hcc_code         = %s
                   AND measurement_year = %s
                 LIMIT 1
                """,
                (patient_id, hcc_code, year),
            )
            if cursor.fetchone():
                raf_hcc_already_present = True
            else:
                # Use INSERT IGNORE in case a unique constraint races us.
                # ``source='recapture'`` distinguishes these rows for downstream
                # RAF score recalculation.
                try:
                    cursor.execute(
                        """
                        INSERT IGNORE INTO raf_patient_hcc
                            (patient_id, hcc_code, icd10_codes, measurement_year,
                             source, tenant_id, model_version, created_at)
                        VALUES (%s, %s, %s, %s, 'recapture', %s, 'V28', %s)
                        """,
                        (
                            patient_id,
                            hcc_code,
                            _json_array_or_empty(gap.get("icd10_code")),
                            year,
                            gap_tenant,
                            now,
                        ),
                    )
                    raf_hcc_inserted = (cursor.rowcount or 0) > 0
                except Exception as exc:
                    # Schema may legitimately differ in some test envs; never
                    # let the close fail because of an HCC write.
                    logger.warning(
                        "smart_close: raf_patient_hcc insert skipped gap_id=%s: %s",
                        gap_id, exc,
                    )
                    raf_hcc_inserted = False

    logger.info(
        "smart_close gap_id=%s by=%s meat=%s raf_hcc_inserted=%s already=%s year=%s",
        gap_id, closed_by, meat, raf_hcc_inserted, raf_hcc_already_present, year,
    )

    return {
        "gap_id": gap_id,
        "status": "recaptured",
        "raf_hcc_inserted": raf_hcc_inserted,
        "raf_hcc_already_present": raf_hcc_already_present,
        "measurement_year": year,
    }


def _json_array_or_empty(icd: Any) -> str:
    """Render a single ICD-10 code as a JSON array string for raf_patient_hcc.icd10_codes.

    raf_patient_hcc.icd10_codes is a JSON column; we always store an array.
    """
    import json as _json
    if not icd:
        return _json.dumps([])
    if isinstance(icd, list):
        return _json.dumps(icd)
    return _json.dumps([str(icd)])


# ---------------------------------------------------------------------------
# 3. bulk_close
# ---------------------------------------------------------------------------

def bulk_close(
    gap_ids: Iterable[int],
    closed_by: str,
    evidence_phrase: str,
    meat_element: str | None = None,
    write_to_raf_hcc: bool = True,
    tenant_id: str | None = None,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """Close many gaps with shared evidence.

    Loops ``smart_close`` per id so each gap gets identical audit treatment.
    Failures on individual gaps are collected, never abort the batch — so a
    single missing-id does not block the rest of the close action.
    """
    ids = [int(g) for g in gap_ids if g is not None]
    if not ids:
        return {"closed": 0, "raf_hcc_inserted": 0, "errors": [], "results": []}

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    closed = 0
    raf_hcc_inserted = 0

    for gid in ids:
        try:
            r = smart_close(
                gap_id=gid,
                closed_by=closed_by,
                evidence_phrase=evidence_phrase,
                meat_element=meat_element,
                write_to_raf_hcc=write_to_raf_hcc,
                tenant_id=tenant_id,
                measurement_year=measurement_year,
            )
            results.append(r)
            closed += 1
            if r.get("raf_hcc_inserted"):
                raf_hcc_inserted += 1
        except Exception as exc:
            logger.warning("bulk_close: gap_id=%s failed: %s", gid, exc)
            errors.append({"gap_id": gid, "error": str(exc)})

    return {
        "closed": closed,
        "raf_hcc_inserted": raf_hcc_inserted,
        "errors": errors,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 4. reopen_gap
# ---------------------------------------------------------------------------

def reopen_gap(
    gap_id: int,
    reopened_by: str,
    reason: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Flip a closed gap back to 'open' (e.g. when MEAT support is challenged).

    The original close audit (resolved_at/by, evidence_phrase, meat_element)
    is cleared, and the reopen audit columns (reopened_at/by/reason) are
    stamped so the timeline can show "X opened it back up because Y."
    """
    if not reason or not reason.strip():
        raise ValueError("reason is required")
    if not reopened_by or not str(reopened_by).strip():
        raise ValueError("reopened_by is required")

    update_sql = """
        UPDATE recapture_gaps
           SET status          = 'open',
               resolved_at     = NULL,
               resolved_by     = NULL,
               evidence_phrase = NULL,
               meat_element    = NULL,
               reopened_at     = %s,
               reopened_by     = %s,
               reopen_reason   = %s
         WHERE id = %s
    """

    with raf_cursor() as cursor:
        gap = _fetch_gap(cursor, gap_id, tenant_id)
        if not gap:
            raise ValueError(f"Gap {gap_id} not found")
        cursor.execute(
            update_sql,
            (_now_utc(), reopened_by, reason.strip(), gap_id),
        )

    logger.info("reopen_gap gap_id=%s by=%s", gap_id, reopened_by)
    return {"gap_id": gap_id, "status": "open"}


# ---------------------------------------------------------------------------
# 5. get_close_history
# ---------------------------------------------------------------------------

def get_close_history(
    tenant_id: str,
    year: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recently closed recapture gaps for the close-history timeline.

    Args:
        tenant_id: tenant scope
        year:      optional ``current_year`` filter (e.g. 2026)
        limit:     max rows to return

    Returns the same shape as ``list_gaps`` plus the closer name and a
    truncated evidence preview, ordered by ``resolved_at DESC``.
    """
    params: list[Any] = [tenant_id]
    year_clause = ""
    if year is not None:
        year_clause = "AND rg.current_year = %s"
        params.append(year)

    limit = max(1, min(int(limit), 500))
    params.append(limit)

    sql = f"""
        SELECT
            rg.id,
            rg.patient_id,
            rg.tenant_id,
            rg.hcc_code,
            rg.icd10_code,
            rg.prior_year,
            rg.current_year,
            rg.status,
            rg.provider_npi,
            rg.revenue_impact,
            rg.resolved_at,
            rg.resolved_by,
            rg.evidence_phrase,
            rg.meat_element,
            rg.reopened_at,
            rg.reopened_by,
            CONCAT(COALESCE(pt.first_name, ''), ' ',
                   COALESCE(pt.last_name, ''))               AS patient_name
          FROM recapture_gaps rg
          LEFT JOIN patients pt
                 ON pt.id = rg.patient_id
                AND pt.tenant_id = rg.tenant_id
         WHERE rg.tenant_id   = %s
           AND rg.status      = 'recaptured'
           AND rg.resolved_at IS NOT NULL
           {year_clause}
         ORDER BY rg.resolved_at DESC
         LIMIT %s
    """

    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for k in ("resolved_at", "reopened_at"):
            v = item.get(k)
            if v and hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        # Patient name fallback
        pn = (item.get("patient_name") or "").strip()
        item["patient_name"] = pn or "Unknown"
        out.append(item)
    return out
