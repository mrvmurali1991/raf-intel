"""
HCC gap drilldown service.

Given a provider and an HCC code, return the list of patients in the
provider's panel who are MISSING that HCC for the requested measurement
year, enriched with chart-context to help the provider close the gap.

A patient is considered "missing" the HCC for the year when EITHER:
  (a) they have an open suspect (raf_suspect_conditions.status='open')
      whose suspect_hcc matches the requested HCC, OR
  (b) they were coded with the HCC last year (raf_patient_hcc) but have
      not yet been coded for it this year ("recapture due").

Patients who already have the HCC coded for the requested year are
excluded — they are not gaps.

Sort order: confidence DESC, prior_year_coded DESC (highest-leverage
first). Ties break on patient_id ASC for stable pagination.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from app.db import raf_cursor
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hcc_to_int(hcc_code: str | int) -> int | None:
    """Normalize an HCC code to an int (the suspect_hcc column is SMALLINT).

    Accepts both ``"85"`` and ``"HCC85"`` style inputs.
    """
    if hcc_code is None:
        return None
    s = str(hcc_code).strip().upper()
    if s.startswith("HCC"):
        s = s[3:].strip()
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _calc_age(dob: Any, ref: date | None = None) -> int | None:
    """Calculate age in years from a DOB value (date / datetime / str)."""
    if dob is None or dob == "":
        return None
    if isinstance(dob, str):
        try:
            dob_d = date.fromisoformat(dob[:10])
        except ValueError:
            return None
    elif hasattr(dob, "year") and hasattr(dob, "month") and hasattr(dob, "day"):
        dob_d = date(dob.year, dob.month, dob.day)
    else:
        return None
    ref = ref or date.today()
    years = ref.year - dob_d.year - ((ref.month, ref.day) < (dob_d.month, dob_d.day))
    return max(years, 0)


def _truncate(text: str | None, max_len: int = 200) -> str:
    if not text:
        return ""
    text = str(text).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _evidence_snippet(evidence_type: str | None, evidence_detail: Any) -> str:
    """Build a short human-readable snippet from raf_suspect_conditions
    evidence_detail (JSON column) plus the evidence_type tag."""
    if evidence_detail is None:
        return ""
    payload: Any = evidence_detail
    if isinstance(evidence_detail, (bytes, bytearray)):
        try:
            payload = json.loads(evidence_detail.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = evidence_detail.decode("utf-8", errors="ignore")
    elif isinstance(evidence_detail, str):
        try:
            payload = json.loads(evidence_detail)
        except ValueError:
            payload = evidence_detail

    parts: list[str] = []
    if evidence_type:
        parts.append(str(evidence_type).capitalize())

    if isinstance(payload, dict):
        # Common evidence_detail shapes from the suspect engine.
        for key in ("note_excerpt", "summary", "description", "rationale", "value"):
            val = payload.get(key)
            if val:
                parts.append(str(val))
                break
        else:
            # Fall back to first non-empty key/value
            for k, v in payload.items():
                if v not in (None, "", []):
                    parts.append(f"{k}: {v}")
                    break
    elif isinstance(payload, str) and payload:
        parts.append(payload)

    return _truncate(": ".join(parts) if parts else "", max_len=240)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_gap_patients(
    provider_id: int,
    hcc_code: str | int,
    year: int | None = None,
    *,
    tenant_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return the list of panel patients missing ``hcc_code`` in ``year``.

    Each row contains demographics, suspect status, confidence,
    evidence_type, evidence_detail (raw + truncated snippet),
    prior_year_coded flag, and last_encounter_date.

    Sorted by confidence DESC, then prior_year_coded DESC.
    """
    year = year or date.today().year
    hcc_int = _hcc_to_int(hcc_code)
    if hcc_int is None:
        logger.warning("get_gap_patients: invalid hcc_code=%r", hcc_code)
        return []

    # Single-tenant deployment fallback
    tid = int(tenant_id) if tenant_id is not None else 1

    # 1) Pull the provider's active panel (tenant-scoped).
    sf, sp = active_patients_subquery(tid)
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT patient_id
            FROM provider_patient_panel
            WHERE provider_id = %s AND {sf}
            """,
            (provider_id, *sp),
        )
        panel = [int(r["patient_id"]) for r in cur.fetchall()]

    if not panel:
        return []

    placeholders = ", ".join(["%s"] * len(panel))

    # 2) Patients who already have the HCC coded for the requested year.
    #    These are NOT gaps.
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT patient_id
            FROM raf_patient_hcc
            WHERE measurement_year = %s
              AND patient_id IN ({placeholders})
              AND CAST(REPLACE(UPPER(hcc_code), 'HCC', '') AS UNSIGNED) = %s
            """,
            (year, *panel, hcc_int),
        )
        already_coded = {int(r["patient_id"]) for r in cur.fetchall()}

    # 3) Patients with an open suspect for this HCC.
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                patient_id,
                confidence_score,
                evidence_type,
                evidence_detail,
                created_at,
                updated_at
            FROM raf_suspect_conditions
            WHERE status = 'open'
              AND suspect_hcc = %s
              AND patient_id IN ({placeholders})
            """,
            (hcc_int, *panel),
        )
        suspect_rows = {int(r["patient_id"]): r for r in cur.fetchall()}

    # 4) Patients coded with this HCC last year (recapture-due candidates).
    prior_year = year - 1
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT patient_id
            FROM raf_patient_hcc
            WHERE measurement_year = %s
              AND patient_id IN ({placeholders})
              AND CAST(REPLACE(UPPER(hcc_code), 'HCC', '') AS UNSIGNED) = %s
            """,
            (prior_year, *panel, hcc_int),
        )
        prior_year_set = {int(r["patient_id"]) for r in cur.fetchall()}

    # 5) Build the candidate gap set: open-suspect ∪ prior-year-coded,
    #    minus already-coded-this-year.
    candidates = (set(suspect_rows.keys()) | prior_year_set) - already_coded
    if not candidates:
        return []

    # 6) Demographics from the patients VIEW (tenant-scoped).
    cand_list = sorted(candidates)
    cand_ph = ", ".join(["%s"] * len(cand_list))
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, first_name, last_name, dob, sex, mrn
            FROM patients
            WHERE id IN ({cand_ph}) AND tenant_id = %s
            """,
            (*cand_list, str(tid)),
        )
        demo_rows = {int(r["id"]): r for r in cur.fetchall()}

    # 7) Last encounter date from OpenEMR form_encounter (best-effort —
    #    if the join fails we just leave the field null).
    last_enc: dict[int, str] = {}
    try:
        from app.db import openemr_cursor

        with openemr_cursor() as cur:
            cur.execute(
                f"""
                SELECT pid, MAX(date) AS last_date
                FROM form_encounter
                WHERE pid IN ({cand_ph})
                GROUP BY pid
                """,
                tuple(cand_list),
            )
            for r in cur.fetchall():
                pid = int(r.get("pid") or 0)
                if pid:
                    last_enc[pid] = str(r.get("last_date") or "")
    except Exception as exc:  # pragma: no cover — non-fatal
        logger.debug("hcc_gap_drilldown last-encounter lookup failed: %s", exc)

    # 8) Assemble result rows.
    today = date.today()
    results: list[dict[str, Any]] = []
    for pid in cand_list:
        suspect = suspect_rows.get(pid)
        demo = demo_rows.get(pid, {})

        confidence = float(suspect["confidence_score"]) if suspect and suspect.get("confidence_score") is not None else 0.0
        ev_type = (suspect or {}).get("evidence_type")
        ev_detail = (suspect or {}).get("evidence_detail")
        snippet = _evidence_snippet(ev_type, ev_detail)
        prior_coded = pid in prior_year_set
        suspect_status = "open" if suspect else None

        first = (demo.get("first_name") or "").strip()
        last = (demo.get("last_name") or "").strip()
        full_name = (f"{first} {last}".strip()) or f"Patient {pid}"

        dob_val = demo.get("dob")
        results.append(
            {
                "patient_id": pid,
                "patient_name": full_name,
                "first_name": first,
                "last_name": last,
                "mrn": demo.get("mrn") or "",
                "dob": str(dob_val) if dob_val else "",
                "age": _calc_age(dob_val, today),
                "sex": (demo.get("sex") or "").strip() or "Unknown",
                "last_encounter_date": last_enc.get(pid) or None,
                "suspect_status": suspect_status,
                "confidence": round(confidence, 4),
                "evidence_type": ev_type,
                "evidence_detail": ev_detail,
                "evidence_snippet": snippet,
                "top_evidence_snippet": snippet,
                "prior_year_coded": prior_coded,
            }
        )

    # 9) Sort: highest-leverage first.
    results.sort(
        key=lambda r: (
            -float(r["confidence"]),
            0 if r["prior_year_coded"] else 1,
            r["patient_id"],
        )
    )

    return results[: max(1, int(limit))]
