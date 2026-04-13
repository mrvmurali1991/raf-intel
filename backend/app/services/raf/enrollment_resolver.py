# DISCLAIMER: This module is part of the CMS-HCC RAF calculation engine.
# Not CMS-validated. For informational purposes only.
"""
Enrollment resolution and model-segment determination.

Handles:
  - OREC / dual-eligibility lookup from raf_patient_demographics
  - OpenEMR enrollment data fetch (via openemr_connector)
  - Priority-based resolution: api_override > OpenEMR > RAF DB > default
  - CMS-HCC model segment routing (CNA/CND/CFA/CFD/CPA/CPD/INS/NE_*/ESRD_*)
  - New Enrollee and ESRD segment helpers
"""

from __future__ import annotations

import logging
from typing import Any

from app.db import raf_cursor
from app.services.raf.icd_formatter import (
    _ESRD_DIALYSIS_CODES,
    _ESRD_FUNCTIONING_GRAFT_CODES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Segment → prefix mapping (same prefixes apply to both V24 and V28)
# ---------------------------------------------------------------------------

_SEGMENT_TO_PREFIX: dict[str, str] = {
    # Standard community/institutional segments
    "CNA": "CNA_",
    "CND": "CND_",
    "CFA": "CFA_",
    "CFD": "CFD_",
    "CPA": "CPA_",
    "CPD": "CPD_",
    "INS": "INS_",
    # New Enrollee segments (demographic-only — hccinfhir uses NE prefix)
    "NE": "NE_",
    "NE_CNA": "NE_",
    "NE_CND": "NE_",
    "NE_CFA": "NE_",
    "NE_CFD": "NE_",
    "NE_CPA": "NE_",
    "NE_CPD": "NE_",
    # ESRD segments
    "ESRD_DLY": "ESRD_",  # ESRD Dialysis (OREC=2 on active dialysis)
    "ESRD_FG": "ESRD_",  # ESRD Functioning Graft (post-transplant, functioning)
    "ESRD_NE": "ESRD_NE_",  # ESRD New Enrollee
}


def determine_model_segment(
    age: int,
    is_dual: bool = False,
    dual_type: str = "non_dual",
    is_institutional: bool = False,
    orec: str = "0",
    enrollment_months: int = 12,
    icd_codes: list[str] | None = None,
    # ── alias parameters (accepted by tests and callers that use different names) ──
    dual_status: str | None = None,  # alias for dual_type
    sex: str | None = None,          # informational alias (not used in segment logic)
    institutional: bool | None = None,  # alias for is_institutional
) -> str:
    """
    Determine the correct CMS-HCC model segment for a beneficiary.

    CMS-HCC model segments (applies to both V24 and V28):
      CNA      - Community, Non-dual, Aged (age >= 65, not on Medicaid)
      CND      - Community, Non-dual, Disabled (age < 65 with disability, OREC = 1)
      CFA      - Community, Full-dual, Aged (age >= 65, full Medicaid)
      CFD      - Community, Full-dual, Disabled (age < 65, full Medicaid)
      CPA      - Community, Partial-dual, Aged (age >= 65, partial Medicaid buy-in)
      CPD      - Community, Partial-dual, Disabled (age < 65, partial Medicaid buy-in)
      INS      - Institutional (SNF / long-term nursing facility resident)
      NE_*     - New Enrollee variant (< 12 months Part B) — demographic-only
      ESRD_DLY - ESRD on dialysis (OREC=2)
      ESRD_FG  - ESRD Functioning Graft (post-transplant, active kidney)
      ESRD_NE  - ESRD New Enrollee
    """
    # Resolve aliases: caller may pass dual_status/institutional instead of dual_type/is_institutional
    if dual_status is not None:
        dual_type = dual_status
    if institutional is not None:
        is_institutional = institutional
    # -----------------------------------------------------------------------
    # ESRD Routing — OREC 2 (ESRD) or 3 (Disabled+ESRD)
    # When OREC indicates ESRD, detect dialysis vs functioning graft from ICD codes
    # -----------------------------------------------------------------------
    _orec = str(orec or "0").strip()
    if _orec in ("2", "3"):
        codes_to_check: set[str] = {
            c.strip().upper().replace(".", "") for c in (icd_codes or [])
        }

        has_graft = bool(codes_to_check & _ESRD_FUNCTIONING_GRAFT_CODES)
        has_dialysis = bool(codes_to_check & _ESRD_DIALYSIS_CODES)

        if enrollment_months < 12:
            return "ESRD_NE"
        if has_graft and not has_dialysis:
            return "ESRD_FG"
        return "ESRD_DLY"  # Default ESRD = dialysis (most common)

    # -----------------------------------------------------------------------
    # New Enrollee routing — < 12 months Part B coverage → demographic-only
    # -----------------------------------------------------------------------
    if enrollment_months < 12:
        # Map to NE variant of the base segment for proper demo coefficient lookup
        if is_institutional:
            return "NE_CNA"  # Institutional NE treated as CNA-NE for demo scoring
        aged = age >= 65
        dt = (dual_type or "non_dual").lower()
        if dt in ("full", "full_dual"):
            return "NE_CFA" if aged else "NE_CFD"
        if dt in ("partial", "partial_dual"):
            return "NE_CPA" if aged else "NE_CPD"
        return "NE_CNA" if aged else "NE_CND"

    # -----------------------------------------------------------------------
    # Standard segment routing
    # -----------------------------------------------------------------------
    if is_institutional:
        return "INS"

    aged = age >= 65
    dt = (dual_type or "non_dual").lower()

    if dt in ("full", "full_dual"):
        return "CFA" if aged else "CFD"
    if dt in ("partial", "partial_dual"):
        return "CPA" if aged else "CPD"

    if aged:
        return "CNA"
    if _orec != "1":
        logger.warning(
            "Patient under 65 with OREC=%s (expected 1 for disabled). Defaulting to CND.",
            _orec,
        )
    return "CND"


def _is_new_enrollee(model_segment: str) -> bool:
    """Return True if this segment is a New Enrollee variant (demographic-only)."""
    return model_segment.startswith("NE_") or model_segment == "NE"


def _is_esrd(model_segment: str) -> bool:
    """Return True if this segment is an ESRD variant."""
    return model_segment.startswith("ESRD_")


def _get_enrollment_from_raf_db(
    patient_id: int, measurement_year: int, tenant_id: Any
) -> dict[str, Any] | None:
    """
    Look up stored OREC / dual-eligibility from raf_patient_demographics.
    """
    if tenant_id is None:
        raise ValueError(
            "_get_enrollment_from_raf_db: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid: Any = tenant_id
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT dual_type, orec, institutional
                FROM raf_patient_demographics
                WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s
                LIMIT 1
                """,
                (patient_id, measurement_year, tid),
            )
            row = cur.fetchone()
        if row:
            return {
                "dual_status": row.get("dual_type") or "non_dual",
                "orec": str(row.get("orec") or "0"),
                "institutional": bool(row.get("institutional", False)),
                "source": "raf_db",
            }
    except Exception as exc:
        logger.debug("_get_enrollment_from_raf_db pid=%s: %s", patient_id, exc)
    return None


def _resolve_enrollment(
    patient_id: int,
    age: int,
    institutional: bool,
    dual_status: str | None,
    enrollment_override: dict[str, Any] | None,
    measurement_year: int,
    tenant_id: Any,
) -> tuple[str, str, bool, str]:
    """
    Resolve dual_type, orec, institutional flag, and enrollment_source.

    Priority: enrollment_override > dual_status param > OpenEMR > RAF DB > default.

    Returns: (dual_type, orec, institutional, enrollment_source)
    """
    if enrollment_override:
        _dual_type = enrollment_override.get("dual_status") or "non_dual"
        _orec = str(enrollment_override.get("orec", "0"))
        _institutional = bool(enrollment_override.get("institutional", False))
        return _dual_type, _orec, _institutional, "api_override"

    if dual_status is not None:
        _orec = "1" if age < 65 else "0"
        return dual_status, _orec, institutional, "api_override"

    openemr_info: dict[str, Any] | None = None
    try:
        from app.services.openemr_connector import get_patient_enrollment_info

        openemr_info = get_patient_enrollment_info(patient_id)
    except Exception as exc:
        logger.warning(
            "RAF calc pid=%s — get_patient_enrollment_info failed (%s), will check RAF DB",
            patient_id,
            exc,
        )

    if openemr_info and openemr_info.get("source") not in (None, "default"):
        return (
            openemr_info["dual_status"],
            openemr_info["orec"],
            openemr_info["institutional"],
            "openemr_derived",
        )

    raf_db_info = _get_enrollment_from_raf_db(
        patient_id, measurement_year, tenant_id=tenant_id
    )
    if raf_db_info:
        return (
            raf_db_info["dual_status"],
            raf_db_info["orec"],
            raf_db_info["institutional"],
            "raf_db",
        )

    _orec = "1" if age < 65 else "0"
    logger.warning(
        "RAF calc pid=%s — no enrollment data; defaulting to %s (dual=non_dual orec=%s)",
        patient_id,
        "CND" if age < 65 else "CNA",
        _orec,
    )
    return "non_dual", _orec, institutional, "default_cna"
