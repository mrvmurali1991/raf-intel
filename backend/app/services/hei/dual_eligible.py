"""CMS Health Equity Index — population segmentation.

CMS HEI rewards Medicare Advantage contracts that perform well among
enrollees with social risk factors.  The three HEI risk markers, in priority
order, are:

    1. Dual-eligible (Medicare + full Medicaid benefit)
    2. Low Income Subsidy (LIS) — Part D help with prescription costs
    3. Disability (entitled to Medicare under age 65 due to disability)

Source: CMS-4201-F, "Medicare Program; Contract Year 2024 Policy and
Technical Changes to the MA and Part D Programs", finalized 2023-04-12.
HEI replaces the Reward Factor in Star Rating PY2027 (using MY2025 data).

We expose a single classifier ``classify_patient_segment`` that returns one
of:

    "dual"        - dual-eligible (highest priority)
    "lis"         - LIS without full dual benefit
    "disability"  - Medicare-by-disability without dual or LIS
    "other"       - none of the above

The classifier reads from three patient columns added by Alembic migration
``028_hedis_hei_patient_segmentation``:

    medicaid_eligibility VARCHAR(32) NULL
    lis_flag             TINYINT(1) NOT NULL DEFAULT 0
    disability_flag      TINYINT(1) NOT NULL DEFAULT 0

If the columns do not yet exist on the running DB the classifier falls back
to a deterministic hash of the patient_id so demos remain stable.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable, Literal

from app.db import raf_cursor

logger = logging.getLogger(__name__)


SegmentName = Literal["dual", "lis", "disability", "other"]
SEGMENTS: tuple[SegmentName, ...] = ("dual", "lis", "disability", "other")

# ---------------------------------------------------------------------------
# Schema-introspection — cached on first call
# ---------------------------------------------------------------------------

_HAS_HEI_COLUMNS: bool | None = None


def _hei_columns_present() -> bool:
    """Return True when the patients table has HEI markers columns.

    The result is cached so we don't INFORMATION_SCHEMA on every call.
    """
    global _HAS_HEI_COLUMNS
    if _HAS_HEI_COLUMNS is not None:
        return _HAS_HEI_COLUMNS
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'patients'
                  AND COLUMN_NAME IN ('medicaid_eligibility', 'lis_flag', 'disability_flag')
                """
            )
            row = cur.fetchone()
            n = int(row["n"]) if row else 0
        _HAS_HEI_COLUMNS = n >= 3
    except Exception as exc:
        logger.warning("hei._hei_columns_present: %s", exc)
        _HAS_HEI_COLUMNS = False
    return _HAS_HEI_COLUMNS


def reset_schema_cache() -> None:
    """Force re-introspection of HEI columns (used after a migration)."""
    global _HAS_HEI_COLUMNS
    _HAS_HEI_COLUMNS = None


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

def _deterministic_segment(patient_id: int) -> SegmentName:
    """Return a stable segment label keyed on patient_id.

    Approximates CMS published national prevalence for the MA population:
        dual         ~ 22 %
        lis          ~ 13 %
        disability   ~ 12 %
        other        ~ 53 %

    These percentages are used for the MVP demo only; production must read
    real eligibility/LIS/disability flags from the patients table.
    """
    h = hashlib.sha256(f"hei:{patient_id}".encode()).digest()
    n = int.from_bytes(h[:4], "big") % 100
    if n < 22:
        return "dual"
    if n < 35:
        return "lis"
    if n < 47:
        return "disability"
    return "other"


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------

def classify_patient_segment(patient_id: int, tenant_id: int | None = None) -> SegmentName:
    """Return the HEI segment for a single patient.

    Priority: dual > lis > disability > other.
    """
    if _hei_columns_present():
        try:
            with raf_cursor() as cur:
                if tenant_id is not None:
                    cur.execute(
                        "SELECT medicaid_eligibility, lis_flag, disability_flag "
                        "FROM patients WHERE id = %s AND tenant_id = %s",
                        (patient_id, tenant_id),
                    )
                else:
                    cur.execute(
                        "SELECT medicaid_eligibility, lis_flag, disability_flag "
                        "FROM patients WHERE id = %s",
                        (patient_id,),
                    )
                row = cur.fetchone()
        except Exception as exc:
            logger.warning("classify_patient_segment[%s]: %s", patient_id, exc)
            return _deterministic_segment(patient_id)
        if not row:
            return _deterministic_segment(patient_id)
        medicaid = (row.get("medicaid_eligibility") or "").strip().lower()
        if medicaid in ("full", "dual", "qmb_plus", "smb_plus", "fbde"):
            return "dual"
        if int(row.get("lis_flag") or 0) == 1:
            return "lis"
        if int(row.get("disability_flag") or 0) == 1:
            return "disability"
        return "other"
    return _deterministic_segment(patient_id)


def classify_patients_bulk(
    patient_ids: Iterable[int],
    tenant_id: int | None = None,
) -> dict[int, SegmentName]:
    """Return ``{patient_id: segment}`` for a batch of patients in one query."""
    pids = [int(p) for p in patient_ids]
    if not pids:
        return {}
    if not _hei_columns_present():
        return {pid: _deterministic_segment(pid) for pid in pids}
    placeholders = ",".join(["%s"] * len(pids))
    sql = (
        f"SELECT id, medicaid_eligibility, lis_flag, disability_flag "
        f"FROM patients WHERE id IN ({placeholders})"
    )
    params: list = list(pids)
    if tenant_id is not None:
        sql += " AND tenant_id = %s"
        params.append(tenant_id)
    out: dict[int, SegmentName] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.warning("classify_patients_bulk: %s", exc)
        return {pid: _deterministic_segment(pid) for pid in pids}
    for row in rows:
        pid = int(row["id"])
        medicaid = (row.get("medicaid_eligibility") or "").strip().lower()
        if medicaid in ("full", "dual", "qmb_plus", "smb_plus", "fbde"):
            out[pid] = "dual"
        elif int(row.get("lis_flag") or 0) == 1:
            out[pid] = "lis"
        elif int(row.get("disability_flag") or 0) == 1:
            out[pid] = "disability"
        else:
            out[pid] = "other"
    # Any patients missing from the DB result fall back to deterministic.
    for pid in pids:
        out.setdefault(pid, _deterministic_segment(pid))
    return out
