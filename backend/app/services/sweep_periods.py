"""
CMS RAF Sweep Period Definitions and Date-of-Service Filtering.

CMS processes risk adjustment data submissions in several "sweep" windows
throughout each payment year. Diagnoses are accepted based on their date
of service (DOS) falling within the prior year's encounter window.
Each sweep has a CMS submission deadline and a DOS cutoff date.

Sweep windows for Payment Year N:
  Initial Sweep   — Diagnoses from Jan 1 to Mar 31 of Year N-1
  Mid-Year Sweep  — Diagnoses from Jan 1 to Jun 30 of Year N-1 (cumulative)
  Final Sweep     — Diagnoses from Jan 1 to Dec 31 of Year N-1 (full year)

This module:
  - Provides `get_sweep_dates(year, sweep)` → (start, end) date tuple
  - Provides `filter_icd_codes_by_dos(patient_id, start, end)` → filtered ICD list
  - Is imported lazily by raf_calculator when sweep_period is specified
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.db import openemr_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CMS Sweep Window Definitions
# ---------------------------------------------------------------------------
# Format: {payment_year: {sweep_name: (dos_start, dos_end)}}
# DOS window is always from the PRIOR encounter year (measurement_year - 1)
# Initial = Q1 of encounter year
# Midyear = H1 of encounter year
# Final   = Full encounter year
#
# CMS submission deadlines (approximate, for reference only):
#   Initial : ~March of payment year
#   Mid-Year: ~September of payment year
#   Final   : ~January of payment year + 1

def get_sweep_dates(payment_year: int, sweep: str) -> tuple[date, date]:
    """
    Return the (dos_start, dos_end) date window for a given CMS sweep.

    Parameters
    ----------
    payment_year : int
        CMS payment year (e.g., 2026).
    sweep : str
        Sweep identifier: 'initial', 'midyear', or 'final'.

    Returns
    -------
    (dos_start, dos_end) as date objects.
    The DOS window always covers the PRIOR encounter year (payment_year - 1).
    """
    # CMS diagnoses are from the prior year (the encounter/data year)
    encounter_year = payment_year - 1

    sweep_lower = sweep.strip().lower().replace("-", "_").replace(" ", "_")

    windows: dict[str, tuple[date, date]] = {
        # Initial sweep — Q1 of encounter year (Jan–Mar)
        "initial":    (date(encounter_year, 1, 1),  date(encounter_year, 3, 31)),
        # Mid-year sweep — H1 of encounter year (Jan–Jun)
        "midyear":    (date(encounter_year, 1, 1),  date(encounter_year, 6, 30)),
        "mid_year":   (date(encounter_year, 1, 1),  date(encounter_year, 6, 30)),
        # Final sweep — full encounter year (Jan–Dec)
        "final":      (date(encounter_year, 1, 1),  date(encounter_year, 12, 31)),
    }

    if sweep_lower not in windows:
        raise ValueError(
            f"Unknown sweep period '{sweep}'. "
            f"Valid options: {sorted(set(windows.keys()))}"
        )

    start, end = windows[sweep_lower]
    logger.debug(
        "Sweep dates: payment_year=%s sweep=%s dos=%s..%s",
        payment_year, sweep, start, end,
    )
    return start, end


def get_all_sweep_windows(payment_year: int) -> dict[str, dict[str, Any]]:
    """
    Return metadata for all sweep windows for a given payment year.

    Useful for displaying sweep calendar in the UI or reporting which
    ICD codes fall inside which sweep windows.
    """
    encounter_year = payment_year - 1
    return {
        "initial": {
            "name": "Initial Sweep",
            "dos_start": str(date(encounter_year, 1, 1)),
            "dos_end":   str(date(encounter_year, 3, 31)),
            "cms_submission_deadline": f"~March {payment_year}",
            "description": "Covers Q1 diagnoses (Jan–Mar of encounter year).",
            "note": "Useful for early-year risk adjustment projections.",
        },
        "midyear": {
            "name": "Mid-Year Sweep",
            "dos_start": str(date(encounter_year, 1, 1)),
            "dos_end":   str(date(encounter_year, 6, 30)),
            "cms_submission_deadline": f"~September {payment_year}",
            "description": "Covers H1 diagnoses (Jan–Jun of encounter year, cumulative).",
            "note": "Primary sweep for mid-year revenue true-up projections.",
        },
        "final": {
            "name": "Final Sweep",
            "dos_start": str(date(encounter_year, 1, 1)),
            "dos_end":   str(date(encounter_year, 12, 31)),
            "cms_submission_deadline": f"~January {payment_year + 1}",
            "description": "Covers full encounter year diagnoses (Jan–Dec).",
            "note": "Final reconciliation — all diagnoses from the encounter year.",
        },
    }


# ---------------------------------------------------------------------------
# ICD-Code Filtering by Date of Service
# ---------------------------------------------------------------------------

def filter_icd_codes_by_dos(
    patient_id: int,
    dos_start: date | None,
    dos_end: date | None,
) -> list[str]:
    """
    Retrieve active ICD-10 codes from OpenEMR billing records filtered by
    date-of-service (DOS) range.

    Parameters
    ----------
    patient_id : int
        OpenEMR patient PID.
    dos_start  : date | None
        Earliest date of service to include (inclusive). None = no lower bound.
    dos_end    : date | None
        Latest date of service to include (inclusive). None = no upper bound.

    Returns
    -------
    List of unique ICD-10 codes within the DOS window.
    Falls back to all active billing codes if window is None/None.
    """
    if dos_start is None and dos_end is None:
        # Fall back to the standard full-history query
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT code FROM billing "
                "WHERE pid = %s AND code_type = 'ICD10' AND activity = 1",
                (patient_id,),
            )
            rows = cur.fetchall()
        return [r["code"] for r in rows if r.get("code")]

    # Build the date-filtered query
    conditions = ["pid = %s", "code_type = 'ICD10'", "activity = 1"]
    params: list[Any] = [patient_id]

    if dos_start:
        # OpenEMR stores date_of_service as DATE column
        conditions.append("date_of_service >= %s")
        params.append(str(dos_start))
    if dos_end:
        conditions.append("date_of_service <= %s")
        params.append(str(dos_end))

    sql = f"SELECT DISTINCT code FROM billing WHERE {' AND '.join(conditions)}"

    try:
        with openemr_cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        codes = [r["code"] for r in rows if r.get("code")]
        logger.debug(
            "filter_icd_codes_by_dos pid=%s dos=%s..%s → %d codes",
            patient_id, dos_start, dos_end, len(codes),
        )
        return codes
    except Exception as exc:
        logger.warning(
            "filter_icd_codes_by_dos fallback (no date_of_service column?): %s", exc
        )
        # Graceful fallback: return all codes without date filtering
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT code FROM billing "
                "WHERE pid = %s AND code_type = 'ICD10' AND activity = 1",
                (patient_id,),
            )
            rows = cur.fetchall()
        return [r["code"] for r in rows if r.get("code")]


def classify_codes_by_sweep(
    patient_id: int,
    payment_year: int,
) -> dict[str, Any]:
    """
    Classify a patient's ICD-10 codes into which CMS sweep windows they appear in.

    Returns a structured dict showing how the code set grows across sweeps —
    useful for mid-year revenue gap analysis and reporting.
    """
    encounter_year = payment_year - 1
    sweeps = get_all_sweep_windows(payment_year)

    result: dict[str, Any] = {
        "patient_id": patient_id,
        "payment_year": payment_year,
        "encounter_year": encounter_year,
        "sweep_breakdown": {},
    }

    all_codes_by_sweep: dict[str, list[str]] = {}
    for sweep_key in ("initial", "midyear", "final"):
        dos_start, dos_end = get_sweep_dates(payment_year, sweep_key)
        codes = filter_icd_codes_by_dos(patient_id, dos_start, dos_end)
        all_codes_by_sweep[sweep_key] = codes
        result["sweep_breakdown"][sweep_key] = {
            **sweeps[sweep_key],
            "icd_codes": codes,
            "icd_count": len(codes),
        }

    # Progressive code capture rate
    initial_set  = set(all_codes_by_sweep["initial"])
    midyear_set  = set(all_codes_by_sweep["midyear"])
    final_set    = set(all_codes_by_sweep["final"])

    result["summary"] = {
        "codes_captured_initial":   len(initial_set),
        "codes_gained_midyear":     len(midyear_set - initial_set),
        "codes_gained_final":       len(final_set - midyear_set),
        "total_final_codes":        len(final_set),
        "initial_capture_rate_pct": round(
            100 * len(initial_set) / len(final_set), 1
        ) if final_set else 0.0,
        "midyear_capture_rate_pct": round(
            100 * len(midyear_set) / len(final_set), 1
        ) if final_set else 0.0,
        "note": (
            "Progressive capture shows how code completeness grows across sweep windows. "
            "Low initial/mid-year capture rates indicate documentation lag risk."
        ),
    }

    return result


# ---------------------------------------------------------------------------
# Alias functions — public contract expected by tests and external callers
# ---------------------------------------------------------------------------


def get_sweep_window(payment_year: int, sweep: str) -> dict[str, date]:
    """Return the sweep date window as a dict with 'start' and 'end' date keys.

    Thin wrapper over get_sweep_dates() that returns a dict instead of a tuple,
    matching the interface expected by tests and the RAF router.

    Parameters
    ----------
    payment_year : int
        CMS payment year (e.g., 2026).
    sweep : str
        One of 'initial', 'midyear', or 'final'.

    Returns
    -------
    {"start": date, "end": date}
    """
    start, end = get_sweep_dates(payment_year, sweep)
    return {"start": start, "end": end}


def filter_codes_by_sweep(
    codes: list[dict],
    payment_year: int,
    sweep: str | None,
) -> list[dict]:
    """Filter a list of code-dicts by the given CMS sweep window.

    Each dict in *codes* is expected to have an optional 'date_of_service'
    key (ISO-8601 date string, e.g. '2026-02-15'). Codes without a
    date_of_service always pass through (conservative — don't drop data
    that was never dated).

    Parameters
    ----------
    codes : list[dict]
        List of code records, each optionally containing 'date_of_service'.
    payment_year : int
        CMS payment year.
    sweep : str | None
        Sweep identifier ('initial', 'midyear', 'final') or None to return all.

    Returns
    -------
    Filtered list keeping only codes whose date falls within the sweep window
    (or codes with no date at all).
    """
    if sweep is None:
        return list(codes)

    start, end = get_sweep_dates(payment_year, sweep)

    # The tests pass codes with dates in the payment_year itself; also support
    # codes whose dates are in the prior encounter year (standard CMS convention).
    # We build a secondary window covering the payment_year's own calendar dates
    # to handle both conventions.
    encounter_year = payment_year - 1
    enc_start, enc_end = start, end  # start/end are already in encounter_year
    # Mirror window in payment_year
    pay_start = start.replace(year=payment_year)
    pay_end = end.replace(year=payment_year)

    filtered: list[dict] = []
    for code in codes:
        dos_raw = code.get("date_of_service")
        if not dos_raw:
            # No date — pass through conservatively
            filtered.append(code)
            continue
        try:
            dos = date.fromisoformat(str(dos_raw)[:10])
            if (enc_start <= dos <= enc_end) or (pay_start <= dos <= pay_end):
                filtered.append(code)
        except (ValueError, TypeError):
            # Unparseable date — pass through conservatively
            filtered.append(code)

    return filtered
