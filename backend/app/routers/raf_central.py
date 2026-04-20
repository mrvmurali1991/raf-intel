"""
RAF Central — unified per-patient intelligence endpoint.

Returns a single JSON payload that drives the RAF Central COG panel embedded
in OpenEMR (and the standalone Next.js panel). Fans out to the existing
services rather than duplicating their logic:

  - get_raf_breakdown         → raf_score + hcc_details + meat_status per HCC
  - get_suspects_for_patient  → suspect conditions w/ confidence
  - get_patient_gaps          → prior-year HCCs missing this year
  - settings.cms_revenue_per_raf_point → financial impact

Per-section failures are logged but do NOT fail the whole response; each
section degrades to an empty / zero state so the UI can render what it has.

Endpoints
---------
GET  /api/raf-central/{pid}                      – unified panel payload
POST /api/raf-central/{pid}/actions/accept-suspect
POST /api/raf-central/{pid}/actions/dismiss-suspect
POST /api/raf-central/{pid}/actions/mark-meat-reviewed
POST /api/raf-central/{pid}/actions/add-assessment-note
POST /api/raf-central/{pid}/actions/upgrade-code
POST /api/raf-central/{pid}/actions/recalculate
POST /api/raf-central/{pid}/actions/order-lab
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_permission
from app.cache import cache_get, cache_set, cache_delete_pattern
from app.config import settings
from app.db import openemr_cursor, raf_cursor
from app.services.cache_strategy import get_active_connection_id
from app.services.openemr_connector import (
    get_patient,
    push_medical_problem,
    push_prescription,
    push_procedure_order,
)
from app.services.raf.calculator import calculate_raf_score, get_raf_breakdown
from app.services.recapture_gap_service import get_patient_gaps
from app.services.suspect_engine import (
    accept_suspect,
    dismiss_suspect,
    get_suspects_for_patient,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/raf-central", tags=["raf-central"])

# 2-minute panel cache — same TTL as get_raf_breakdown to avoid stale deltas.
_PANEL_CACHE_TTL_SEC = 120

# HCC-label lookup from hccinfhir (same source as /api/raf router uses)
try:
    from hccinfhir.defaults import labels_default as _labels_default
except ImportError:  # pragma: no cover — hccinfhir missing would break everything
    _labels_default = {}

_V28_MODEL = "CMS-HCC Model V28"


def _hcc_label(hcc_code: str) -> str:
    code = str(hcc_code).replace("HCC", "").strip()
    return _labels_default.get((code, _V28_MODEL)) or f"HCC {code}"


# ---------------------------------------------------------------------------
# Response models — tight contract for the RAF Central UI
# ---------------------------------------------------------------------------


class LiveRAFBar(BaseModel):
    current: float
    prior_year: float | None = None
    delta: float | None = None
    hcc_count: int
    model_segment: str
    model_version: str
    year: int


class MEATGap(BaseModel):
    patient_hcc_id: int | None = None
    hcc: str
    icd10_codes: list[str]
    label: str
    coefficient: float
    status: Literal["COMPLETE", "PARTIAL", "MISSING", "NOT_COMPLIANT"]
    gaps: dict[str, bool]


class SuspectCard(BaseModel):
    id: int
    hcc: int
    icd10: str
    label: str
    confidence: float
    evidence_type: str
    trigger: str
    status: str


class RecaptureCard(BaseModel):
    id: int
    hcc: str
    icd10: str
    label: str
    prior_year: int
    current_year: int
    revenue_at_risk: float
    last_encounter_date: str | None = None


class CodingOptCard(BaseModel):
    current_icd10: str
    current_label: str
    suggested_icd10: str
    suggested_label: str
    raf_impact: float
    source: str = "rule"


class AuditReadiness(BaseModel):
    meat_compliance_pct: float
    hccs_compliant: int
    hccs_total: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]


class FinancialImpact(BaseModel):
    current_raf: float
    projected_raf: float
    current_annual: float
    projected_annual: float
    pmpm_delta: float
    annual_delta: float
    revenue_per_raf_point: float


class RAFCentralPayload(BaseModel):
    patient_id: int
    measurement_year: int
    generated_at: str
    raf_score: LiveRAFBar
    meat_gaps: list[MEATGap]
    suspects: list[SuspectCard]
    recapture: list[RecaptureCard]
    coding_opt: list[CodingOptCard]
    audit_readiness: AuditReadiness
    financial_impact: FinancialImpact


# ---------------------------------------------------------------------------
# Section builders — each returns an empty / zero payload on failure.
# ---------------------------------------------------------------------------


def _meat_status_to_gaps(status: str) -> tuple[str, dict[str, bool]]:
    """Translate a single `meat_status` string into per-letter booleans.

    The canonical `raf_patient_hcc.meat_status` column stores one of:
    ``complete`` | ``partial`` | ``missing``. We fan it out into 4 booleans
    for the UI so it can render per-letter dots even when we only have the
    aggregate. For fine-grained per-letter evidence, ``raf_meat_evidence``
    carries monitor/evaluate/assess/treat columns; we fall back to that when
    possible (via `_fetch_meat_letters`).
    """
    s = (status or "missing").lower()
    if s == "complete":
        return "COMPLETE", {"monitor": True, "evaluate": True, "assess": True, "treat": True}
    if s == "partial":
        return "PARTIAL", {"monitor": True, "evaluate": True, "assess": False, "treat": False}
    return "MISSING", {"monitor": False, "evaluate": False, "assess": False, "treat": False}


def _fetch_meat_letters(patient_id: int, year: int, tenant_id: str) -> dict[str, dict[str, bool]]:
    """Return per-HCC letter-level MEAT coverage keyed by hcc_code string.

    Scans raf_meat_evidence joined to raf_patient_hcc for the most recent
    evidence row per HCC. Missing → zeros. Non-existent table → zeros.
    """
    out: dict[str, dict[str, bool]] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT ph.hcc_code,
                       MAX(CASE WHEN ev.meat_monitoring IS NOT NULL AND ev.meat_monitoring != '' THEN 1 ELSE 0 END) AS m,
                       MAX(CASE WHEN ev.meat_evaluation IS NOT NULL AND ev.meat_evaluation != '' THEN 1 ELSE 0 END) AS e,
                       MAX(CASE WHEN ev.meat_assessment IS NOT NULL AND ev.meat_assessment != '' THEN 1 ELSE 0 END) AS a,
                       MAX(CASE WHEN ev.meat_treatment  IS NOT NULL AND ev.meat_treatment  != '' THEN 1 ELSE 0 END) AS t
                FROM raf_patient_hcc ph
                LEFT JOIN raf_meat_evidence ev ON ev.patient_hcc_id = ph.id
                WHERE ph.patient_id = %s AND ph.measurement_year = %s AND ph.tenant_id = %s
                GROUP BY ph.hcc_code
                """,
                (patient_id, year, tenant_id),
            )
            for row in cur.fetchall():
                out[str(row["hcc_code"])] = {
                    "monitor": bool(row.get("m")),
                    "evaluate": bool(row.get("e")),
                    "assess":   bool(row.get("a")),
                    "treat":    bool(row.get("t")),
                }
    except Exception as exc:
        logger.debug("meat letter fetch failed pid=%s: %s", patient_id, exc)
    return out


def _fetch_patient_hcc_id(patient_id: int, year: int, hcc_code: str, tenant_id: str) -> int | None:
    """Return the raf_patient_hcc.id so the UI can target a specific row."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id FROM raf_patient_hcc
                WHERE patient_id = %s AND measurement_year = %s
                  AND hcc_code = %s AND tenant_id = %s
                LIMIT 1
                """,
                (patient_id, year, hcc_code, tenant_id),
            )
            row = cur.fetchone()
            return int(row["id"]) if row else None
    except Exception:
        return None


def _build_raf_section(pid: int, year: int, tenant_id: str) -> tuple[LiveRAFBar, list[MEATGap], dict[str, Any]]:
    """Return (raf_bar, meat_gaps, raw_breakdown). raw_breakdown is used by
    other sections to avoid re-querying the RAF engine.
    """
    try:
        breakdown = get_raf_breakdown(pid, year=year, tenant_id=tenant_id) or {}
    except Exception as exc:
        logger.error("raf-central: breakdown fetch failed pid=%s: %s", pid, exc)
        breakdown = {}

    # Prior-year RAF — separate lookup, best-effort
    prior_raf: float | None = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT final_raf FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s
                ORDER BY calculated_at DESC LIMIT 1
                """,
                (pid, year - 1, tenant_id),
            )
            r = cur.fetchone()
            if r:
                prior_raf = float(r["final_raf"] or 0) or None
    except Exception:
        pass

    current_raf = float(breakdown.get("raf_score") or breakdown.get("final_raf") or 0.0)
    delta = round(current_raf - prior_raf, 4) if prior_raf is not None else None

    raf_bar = LiveRAFBar(
        current=current_raf,
        prior_year=prior_raf,
        delta=delta,
        hcc_count=int(breakdown.get("hcc_count") or 0),
        model_segment=str(breakdown.get("model_segment") or "CNA"),
        model_version=str(breakdown.get("model_version") or "v28"),
        year=year,
    )

    # MEAT gaps — one card per HCC in the breakdown
    letter_map = _fetch_meat_letters(pid, year, tenant_id)
    meat_gaps: list[MEATGap] = []
    for hcc in breakdown.get("hcc_details") or []:
        code = str(hcc.get("hcc_code") or hcc.get("hcc") or "")
        status, fallback_letters = _meat_status_to_gaps(hcc.get("meat_status") or "missing")
        letters = letter_map.get(code, fallback_letters)
        # Recompute aggregate status from actual letters if we have them.
        actual_status = status
        if code in letter_map:
            trues = sum(1 for v in letters.values() if v)
            actual_status = "COMPLETE" if trues == 4 else ("PARTIAL" if trues else "MISSING")
        meat_gaps.append(
            MEATGap(
                patient_hcc_id=_fetch_patient_hcc_id(pid, year, code, tenant_id),
                hcc=code,
                icd10_codes=list(hcc.get("icd10_codes") or []),
                label=hcc.get("hcc_label") or _hcc_label(code),
                coefficient=float(hcc.get("coefficient") or 0.0),
                status=actual_status if actual_status != "MISSING" else "NOT_COMPLIANT",
                gaps=letters,
            )
        )

    return raf_bar, meat_gaps, breakdown


def _build_suspects(pid: int, year: int, tenant_id: str) -> list[SuspectCard]:
    try:
        rows = get_suspects_for_patient(pid, year=year, tenant_id=tenant_id) or []
    except Exception as exc:
        logger.error("raf-central: suspects fetch failed pid=%s: %s", pid, exc)
        return []

    out: list[SuspectCard] = []
    for r in rows:
        if (r.get("status") or "").lower() != "open":
            continue
        ev = str(r.get("evidence_type") or "")
        trigger_map = {
            "medication": "Medications",
            "lab": "Lab results",
            "historical": "Prior-year HCC",
            "imaging": "Imaging",
            "referral": "Referral",
        }
        out.append(
            SuspectCard(
                id=int(r.get("suspect_id") or r.get("id") or 0),
                hcc=int(str(r.get("suspect_hcc") or "0").replace("HCC", "").strip() or 0),
                icd10=str(r.get("suspect_icd10") or ""),
                label=_hcc_label(str(r.get("suspect_hcc") or "")),
                confidence=float(r.get("confidence_score") or 0.0),
                evidence_type=ev,
                trigger=trigger_map.get(ev, ev or "—"),
                status=str(r.get("status") or "open"),
            )
        )
    return out


def _build_recapture(pid: int, tenant_id: str) -> list[RecaptureCard]:
    try:
        rows = get_patient_gaps(pid, tenant_id) or []
    except Exception as exc:
        logger.error("raf-central: recapture fetch failed pid=%s: %s", pid, exc)
        return []

    out: list[RecaptureCard] = []
    for r in rows:
        out.append(
            RecaptureCard(
                id=int(r.get("id") or 0),
                hcc=str(r.get("hcc_code") or ""),
                icd10=str(r.get("icd10_code") or ""),
                label=r.get("hcc_description") or _hcc_label(str(r.get("hcc_code") or "")),
                prior_year=int(r.get("prior_year") or 0),
                current_year=int(r.get("current_year") or 0),
                revenue_at_risk=float(r.get("raf_impact") or 0.0),
                last_encounter_date=r.get("last_encounter_date"),
            )
        )
    return out


def _build_audit(raf_bar: LiveRAFBar, meat_gaps: list[MEATGap]) -> AuditReadiness:
    total = len(meat_gaps)
    compliant = sum(1 for g in meat_gaps if g.status == "COMPLETE")
    pct = round(100.0 * compliant / total, 1) if total else 0.0
    if total == 0:
        risk = "LOW"
    elif pct >= 80:
        risk = "LOW"
    elif pct >= 40:
        risk = "MEDIUM"
    else:
        risk = "HIGH"
    return AuditReadiness(
        meat_compliance_pct=pct,
        hccs_compliant=compliant,
        hccs_total=total,
        risk_level=risk,
    )


def _build_financial(raf_bar: LiveRAFBar, suspects: list[SuspectCard], recapture: list[RecaptureCard]) -> FinancialImpact:
    """Projected RAF = current + sum(confidence × expected_coef) for open
    suspects + sum of recapture RAF impact. We don't have per-suspect
    coefficients on this endpoint, so we approximate using a conservative
    0.150 per-suspect lift weighted by confidence — matches the V28 median
    coefficient for demographic-adjacent disease categories. Recapture
    revenue is already a dollar figure.
    """
    rev_per_raf = float(settings.cms_revenue_per_raf_point or 11015.04)

    # Projected RAF lift from open suspects: conservative median coef × confidence
    _MEDIAN_V28_COEF = 0.150
    suspect_lift = sum(_MEDIAN_V28_COEF * s.confidence for s in suspects)

    # Recapture lift in RAF points: invert rev_per_raf
    recapture_lift = sum((r.revenue_at_risk / rev_per_raf) for r in recapture) if rev_per_raf else 0.0

    projected = round(raf_bar.current + suspect_lift + recapture_lift, 4)
    current_annual = round(raf_bar.current * rev_per_raf, 2)
    projected_annual = round(projected * rev_per_raf, 2)
    return FinancialImpact(
        current_raf=raf_bar.current,
        projected_raf=projected,
        current_annual=current_annual,
        projected_annual=projected_annual,
        pmpm_delta=round((projected_annual - current_annual) / 12.0, 2),
        annual_delta=round(projected_annual - current_annual, 2),
        revenue_per_raf_point=rev_per_raf,
    )


# ---------------------------------------------------------------------------
# GET /api/raf-central/{pid}
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}",
    response_model=RAFCentralPayload,
    summary="Unified RAF Central panel payload for a single patient",
)
def get_raf_central(
    pid: int = Path(..., description="OpenEMR patient PID"),
    year: int | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> RAFCentralPayload:
    tenant_id: str | None = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    measurement_year = year or date.today().year

    # --- Cache lookup ------------------------------------------------------
    acid = get_active_connection_id(tenant_id)
    cache_key = f"raf-central:{tenant_id}:{acid}:{pid}:{measurement_year}"
    cached = cache_get(cache_key)
    if cached is not None:
        try:
            return RAFCentralPayload(**cached)
        except Exception:
            # Cache shape drift — fall through and rebuild.
            pass

    # --- Cheap patient existence check ------------------------------------
    try:
        patient = get_patient(pid)
        if not patient:
            raise HTTPException(status_code=404, detail=f"patient {pid} not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("raf-central: get_patient failed pid=%s: %s", pid, exc)
        # Continue — OpenEMR may be offline in dev but we still have RAF DB data.

    # --- Fan out -----------------------------------------------------------
    raf_bar, meat_gaps, _breakdown = _build_raf_section(pid, measurement_year, tenant_id)
    suspects = _build_suspects(pid, measurement_year, tenant_id)
    recapture = _build_recapture(pid, tenant_id)
    audit = _build_audit(raf_bar, meat_gaps)
    financial = _build_financial(raf_bar, suspects, recapture)

    payload = RAFCentralPayload(
        patient_id=pid,
        measurement_year=measurement_year,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        raf_score=raf_bar,
        meat_gaps=meat_gaps,
        suspects=suspects,
        recapture=recapture,
        coding_opt=[],  # Phase 2 — rule-driven ICD specificity suggestions
        audit_readiness=audit,
        financial_impact=financial,
    )

    try:
        cache_set(cache_key, payload.model_dump(), ttl=_PANEL_CACHE_TTL_SEC)
    except Exception:
        pass

    return payload


# ---------------------------------------------------------------------------
# Action endpoints — all invalidate the panel cache and (where applicable)
# trigger a RAF recalc via the score_persistence layer.
# ---------------------------------------------------------------------------


class AcceptSuspectRequest(BaseModel):
    suspect_id: int
    push_to_emr: bool = Field(
        default=True,
        description="If true, insert the accepted diagnosis into OpenEMR `lists`",
    )


class DismissSuspectRequest(BaseModel):
    suspect_id: int
    reason: str = "dismissed via raf-central panel"


class MarkMEATReviewedRequest(BaseModel):
    patient_hcc_id: int
    monitor_note: str | None = None
    evaluate_note: str | None = None
    assess_note: str | None = None
    treat_note: str | None = None


class AddAssessmentNoteRequest(BaseModel):
    encounter_id: int | None = None
    hcc_code: str
    icd10: str
    assessment_text: str = Field(
        ...,
        description="Verbatim clinician text to append to the progress note",
    )


class UpgradeCodeRequest(BaseModel):
    encounter_id: int
    from_icd10: str
    to_icd10: str
    raf_impact: float = Field(default=0.0, description="Predicted RAF delta")


def _invalidate_panel_cache(pid: int, tenant_id: str) -> None:
    try:
        cache_delete_pattern(f"raf-central:{tenant_id}:*:{pid}:*")
        cache_delete_pattern(f"raf:breakdown:{pid}:*")
    except Exception:
        pass


@router.post("/{pid}/actions/accept-suspect")
def action_accept_suspect(
    pid: int,
    body: AcceptSuspectRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> dict[str, Any]:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"
    result = accept_suspect(body.suspect_id, reviewed_by=reviewer, tenant_id=tenant_id)

    # EMR write-back: push the accepted ICD to OpenEMR lists as a medical problem
    pushed = False
    if body.push_to_emr:
        suspect_icd = str(result.get("suspect_icd10") or "")
        suspect_label = _hcc_label(str(result.get("suspect_hcc") or ""))
        if suspect_icd:
            pushed = push_medical_problem(pid, suspect_label, suspect_icd)

    _invalidate_panel_cache(pid, tenant_id)
    return {"ok": True, "suspect": result, "pushed_to_emr": pushed}


@router.post("/{pid}/actions/dismiss-suspect")
def action_dismiss_suspect(
    pid: int,
    body: DismissSuspectRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> dict[str, Any]:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"
    result = dismiss_suspect(
        body.suspect_id,
        reason=body.reason,
        reviewed_by=reviewer,
        tenant_id=tenant_id,
    )
    _invalidate_panel_cache(pid, tenant_id)
    return {"ok": True, "suspect": result}


@router.post("/{pid}/actions/mark-meat-reviewed")
def action_mark_meat_reviewed(
    pid: int,
    body: MarkMEATReviewedRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Insert a raf_meat_evidence row and bump patient_hcc.meat_status.

    This is the endpoint backing the "Mark Reviewed" button in the MEAT
    card. It does NOT write to OpenEMR — MEAT evidence is our-side audit
    documentation, not EMR content.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"
    today = date.today()

    # Require at least one actual note — guards against the frontend sending
    # an empty payload to flip status without clinician attestation.
    if not any((body.monitor_note, body.evaluate_note, body.assess_note, body.treat_note)):
        raise HTTPException(status_code=400, detail="At least one MEAT attestation note is required")

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_meat_evidence
                    (patient_hcc_id, encounter_date,
                     meat_monitoring, meat_evaluation, meat_assessment, meat_treatment,
                     reviewed_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    body.patient_hcc_id, today,
                    body.monitor_note, body.evaluate_note, body.assess_note, body.treat_note,
                    reviewer,
                ),
            )
            # Roll up status from ALL evidence rows for this HCC so previously
            # documented letters (from earlier encounters) are not lost. A letter
            # is considered documented if ANY row has a non-null note for it.
            cur.execute(
                """
                SELECT
                    MAX(CASE WHEN meat_monitoring IS NOT NULL AND meat_monitoring <> '' THEN 1 ELSE 0 END) AS m,
                    MAX(CASE WHEN meat_evaluation IS NOT NULL AND meat_evaluation <> '' THEN 1 ELSE 0 END) AS e,
                    MAX(CASE WHEN meat_assessment IS NOT NULL AND meat_assessment <> '' THEN 1 ELSE 0 END) AS a,
                    MAX(CASE WHEN meat_treatment  IS NOT NULL AND meat_treatment  <> '' THEN 1 ELSE 0 END) AS t
                FROM raf_meat_evidence
                WHERE patient_hcc_id = %s
                """,
                (body.patient_hcc_id,),
            )
            row = cur.fetchone() or {}
            trues = sum(int(row.get(k) or 0) for k in ("m", "e", "a", "t"))
            status = "complete" if trues == 4 else ("partial" if trues else "missing")
            cur.execute(
                """
                UPDATE raf_patient_hcc
                SET meat_status = %s, updated_at = NOW()
                WHERE id = %s AND tenant_id = %s
                """,
                (status, body.patient_hcc_id, tenant_id),
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("raf-central mark-meat-reviewed failed pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=f"MEAT write failed: {exc}")

    _invalidate_panel_cache(pid, tenant_id)
    return {"ok": True, "meat_status": status, "reviewed_by": reviewer}


@router.post("/{pid}/actions/add-assessment-note")
def action_add_assessment_note(
    pid: int,
    body: AddAssessmentNoteRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Append clinician-authored assessment text to the current encounter's
    SOAP note. Falls back to inserting a new `form_soap` row when no
    encounter_id is provided.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"

    try:
        with openemr_cursor() as cur:
            if body.encounter_id:
                # OpenEMR SOAP uses form_soap keyed by encounter id. Append a new row.
                cur.execute(
                    """
                    INSERT INTO form_soap
                        (date, pid, user, groupname, authorized, activity, encounter, assessment)
                    VALUES (%s, %s, %s, %s, 1, 1, %s, %s)
                    """,
                    (now_str, pid, reviewer, "Default", body.encounter_id, body.assessment_text),
                )
            else:
                # Write to the patient's problem list as a free-text note instead.
                cur.execute(
                    """
                    INSERT INTO lists (date, type, title, pid, activity, diagnosis, comments)
                    VALUES (%s, 'medical_problem', %s, %s, 1, %s, %s)
                    """,
                    (now_str, _hcc_label(body.hcc_code), pid,
                     f"ICD10:{body.icd10}", body.assessment_text),
                )
    except Exception as exc:
        logger.error("raf-central add-assessment-note failed pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=f"EMR note write failed: {exc}")

    _invalidate_panel_cache(pid, tenant_id)
    return {"ok": True, "encounter_id": body.encounter_id, "author": reviewer}


@router.post("/{pid}/actions/upgrade-code")
def action_upgrade_code(
    pid: int,
    body: UpgradeCodeRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Replace a less-specific ICD on an encounter's billing row with a
    more-specific one. Updates OpenEMR `billing.code` + `code_text`.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                UPDATE billing
                SET code = %s, code_text = %s, modifier = CONCAT(IFNULL(modifier,''), ' [raf-central upgraded]')
                WHERE pid = %s AND encounter = %s AND code = %s AND activity = 1
                """,
                (body.to_icd10, _hcc_label(body.to_icd10), pid, body.encounter_id, body.from_icd10),
            )
            affected = cur.rowcount or 0
    except Exception as exc:
        logger.error("raf-central upgrade-code failed pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=f"code upgrade failed: {exc}")

    if affected == 0:
        raise HTTPException(
            status_code=404,
            detail=f"no matching billing row for encounter={body.encounter_id} code={body.from_icd10}",
        )

    _invalidate_panel_cache(pid, tenant_id)
    return {"ok": True, "rows_updated": affected}


@router.post("/{pid}/actions/recalculate")
def action_recalculate(
    pid: int,
    year: int | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Force a full RAF recalc for this patient (drops caches, re-runs the
    engine, persists the new score). Use after a writeback action to
    surface the new RAF value in the panel.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    measurement_year = year or date.today().year
    _invalidate_panel_cache(pid, tenant_id)

    result = calculate_raf_score(
        patient_id=pid,
        measurement_year=measurement_year,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "raf_score": float(result.get("raf_score") or 0.0),
        "hcc_count": int(result.get("hcc_count") or 0),
        "model_segment": result.get("model_segment"),
        "measurement_year": measurement_year,
    }


# ---------------------------------------------------------------------------
# Start-Treatment action — inline "Prescribe" from a MEAT-T gap card
# ---------------------------------------------------------------------------

# Small hardcoded fallback map (HCC code → default starter therapy) used when
# the client does not supply a suggested drug. Intentionally minimal — real
# drug selection should come from the suspect engine / provider judgment.
_DEFAULT_TREATMENT_BY_HCC: dict[str, dict[str, str]] = {
    # Diabetes — Metformin (first-line, type-2 DM)
    "37": {"drug": "Metformin 500mg", "rxnorm": "6809", "dosage": "500mg BID"},
    "38": {"drug": "Metformin 500mg", "rxnorm": "6809", "dosage": "500mg BID"},
    # CHF — Lisinopril (ACE-I)
    "85": {"drug": "Lisinopril 10mg", "rxnorm": "29046", "dosage": "10mg daily"},
    # CKD — Losartan (ARB, renoprotective)
    "136": {"drug": "Losartan 50mg", "rxnorm": "52175", "dosage": "50mg daily"},
    "137": {"drug": "Losartan 50mg", "rxnorm": "52175", "dosage": "50mg daily"},
}


class StartTreatmentRequest(BaseModel):
    hcc_code: str
    icd10: str
    suggested_drug: str | None = None
    suggested_rxnorm: str | None = None
    dosage: str | None = None


@router.post("/{pid}/actions/start-treatment")
def action_start_treatment(
    pid: int,
    body: StartTreatmentRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Write a new prescription into OpenEMR to satisfy a MEAT-Treatment gap."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    hcc_key = str(body.hcc_code).replace("HCC", "").strip()
    fallback = _DEFAULT_TREATMENT_BY_HCC.get(hcc_key, {})

    drug = body.suggested_drug or fallback.get("drug")
    rxnorm = body.suggested_rxnorm or fallback.get("rxnorm")
    dosage = body.dosage or fallback.get("dosage")

    if not drug or not dosage:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No suggested treatment for HCC {body.hcc_code} "
                "and no drug/dosage supplied"
            ),
        )

    ordered_by = current_user.get("email") or current_user.get("sub") or "raf-central"
    note = f"HCC {body.hcc_code} / ICD-10 {body.icd10}"

    rx_id = push_prescription(
        pid=pid,
        ordered_by=ordered_by,
        drug_name=drug,
        rxnorm_code=rxnorm,
        dosage=dosage,
        note=note,
    )

    if rx_id is None:
        raise HTTPException(
            status_code=502,
            detail="Prescription write failed — no active EMR connection",
        )

    _invalidate_panel_cache(pid, tenant_id)

    return {"status": "ok", "prescription_id": int(rx_id), "drug": drug}


# ---------------------------------------------------------------------------
# Order Lab — inline action wired from the MEAT Gaps card (Monitoring ❌).
# ---------------------------------------------------------------------------

# Keyed by HCC code (string, without the "HCC" prefix).
_HCC_DEFAULT_LAB: dict[str, dict[str, str]] = {
    # Diabetes family (HCC 35-38 in V28) → Hemoglobin A1C
    "35":  {"code": "4548-4",  "name": "Hemoglobin A1c", "code_type": "LOINC"},
    "36":  {"code": "4548-4",  "name": "Hemoglobin A1c", "code_type": "LOINC"},
    "37":  {"code": "4548-4",  "name": "Hemoglobin A1c", "code_type": "LOINC"},
    "38":  {"code": "4548-4",  "name": "Hemoglobin A1c", "code_type": "LOINC"},
    # CHF (HCC 222-226 family) → BNP
    "222": {"code": "30934-4", "name": "BNP",            "code_type": "LOINC"},
    "223": {"code": "30934-4", "name": "BNP",            "code_type": "LOINC"},
    "224": {"code": "30934-4", "name": "BNP",            "code_type": "LOINC"},
    "225": {"code": "30934-4", "name": "BNP",            "code_type": "LOINC"},
    "226": {"code": "30934-4", "name": "BNP",            "code_type": "LOINC"},
    # CKD (HCC 326-329) → eGFR (CKD-EPI)
    "326": {"code": "33914-3", "name": "eGFR",           "code_type": "LOINC"},
    "327": {"code": "33914-3", "name": "eGFR",           "code_type": "LOINC"},
    "328": {"code": "33914-3", "name": "eGFR",           "code_type": "LOINC"},
    "329": {"code": "33914-3", "name": "eGFR",           "code_type": "LOINC"},
}


class OrderLabRequest(BaseModel):
    hcc_code: str
    icd10: str
    suggested_lab_code: str | None = Field(
        default=None,
        description="Explicit lab code to order. Overrides the HCC default map.",
    )
    suggested_lab_name: str | None = Field(
        default=None,
        description="Human-readable lab name paired with suggested_lab_code.",
    )


def _resolve_lab_for_hcc(
    hcc_code: str,
    suggested_code: str | None,
    suggested_name: str | None,
) -> tuple[str, str, str] | None:
    if suggested_code:
        return (
            str(suggested_code),
            str(suggested_name) if suggested_name else str(suggested_code),
            "LOINC",
        )
    key = str(hcc_code).replace("HCC", "").strip()
    entry = _HCC_DEFAULT_LAB.get(key)
    if not entry:
        return None
    return entry["code"], entry["name"], entry["code_type"]


def _log_raf_action(
    tenant_id: str,
    pid: int,
    action: str,
    reviewer: str,
    payload: dict[str, Any],
) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'raf_action_log'")
            if not cur.fetchone():
                return
            import json
            cur.execute(
                """
                INSERT INTO raf_action_log
                    (tenant_id, patient_id, action, reviewed_by, payload_json, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (tenant_id, pid, action, reviewer, json.dumps(payload, default=str)),
            )
    except Exception as exc:
        logger.debug("raf_action_log insert skipped (pid=%s action=%s): %s", pid, action, exc)


@router.post("/{pid}/actions/order-lab")
def action_order_lab(
    pid: int,
    body: OrderLabRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Place a lab order in OpenEMR to close a MEAT 'Monitoring' gap."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"

    resolved = _resolve_lab_for_hcc(
        body.hcc_code, body.suggested_lab_code, body.suggested_lab_name
    )
    if not resolved:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No default lab mapping for HCC {body.hcc_code}. "
                f"Provide suggested_lab_code in the request body."
            ),
        )
    lab_code, lab_name, code_type = resolved

    try:
        order_id = push_procedure_order(
            pid=pid,
            ordered_by=reviewer,
            procedure_code=lab_code,
            procedure_name=lab_name,
            diagnosis_code=body.icd10,
            lab_code_type=code_type,
        )
    except Exception as exc:
        logger.error("order-lab push failed pid=%s hcc=%s: %s", pid, body.hcc_code, exc)
        raise HTTPException(status_code=500, detail=f"order-lab write failed: {exc}")

    if order_id is None:
        from app.db import NoActiveEMRConnection  # local import — avoid cycle
        try:
            with openemr_cursor() as _cur:
                pass
        except NoActiveEMRConnection:
            return {
                "status": "skipped",
                "reason": "no emr configured",
                "suggested_lab_code": lab_code,
            }
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail="order-lab write failed (procedure_order insert returned no id)",
        )

    _log_raf_action(
        tenant_id=tenant_id,
        pid=pid,
        action="order_lab",
        reviewer=reviewer,
        payload={
            "hcc_code": body.hcc_code,
            "icd10": body.icd10,
            "procedure_code": lab_code,
            "procedure_name": lab_name,
            "procedure_order_id": order_id,
        },
    )

    _invalidate_panel_cache(pid, tenant_id)
    return {
        "status": "ok",
        "procedure_order_id": int(order_id),
        "suggested_lab_code": lab_code,
    }


# ---------------------------------------------------------------------------
# Why? — explainability drill-down for a single suspect
# ---------------------------------------------------------------------------


class ContributingSignal(BaseModel):
    source: Literal["medication", "lab", "history", "nlp", "note", "other"]
    label: str
    value: str | None = None
    timestamp: str | None = None


class ExplainResponse(BaseModel):
    suspect_id: int
    patient_id: int
    suspect_icd10: str
    suspect_hcc: str
    confidence: float
    evidence_type: str
    contributing_signals: list[ContributingSignal]
    summary: str


def _decompose_evidence_detail(
    evidence_detail: Any,
    evidence_type: str,
) -> list[ContributingSignal]:
    """Best-effort parse of raf_suspect_conditions.evidence_detail JSON into
    a typed list of ContributingSignal rows. The blob shape varies per
    engine (meds/labs/history/nlp) — we accept a few common layouts.
    """
    import json as _json

    if evidence_detail in (None, "", "null"):
        return []

    raw: Any = evidence_detail
    if isinstance(evidence_detail, (bytes, bytearray)):
        raw = evidence_detail.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except Exception:
            return [ContributingSignal(source="other", label=raw[:200])]

    signals: list[ContributingSignal] = []
    VALID_SOURCES = ("medication", "lab", "history", "nlp", "note", "other")

    def _src_from_type() -> str:
        t = (evidence_type or "").lower()
        if t.startswith("med"):
            return "medication"
        if t.startswith("lab"):
            return "lab"
        if t.startswith("hist") or t.startswith("recap"):
            return "history"
        if t.startswith("nlp") or t.startswith("note"):
            return "nlp"
        return "other"

    default_src = _src_from_type()

    def _push(item: Any) -> None:
        if isinstance(item, dict):
            src_raw = item.get("source")
            if isinstance(src_raw, str) and src_raw in VALID_SOURCES:
                src = src_raw
                src_as_label: str | None = None
            else:
                src = default_src
                src_as_label = (
                    src_raw.strip()
                    if isinstance(src_raw, str) and src_raw.strip()
                    else None
                )
            label = (
                item.get("label")
                or item.get("name")
                or item.get("drug")
                or item.get("medication")
                or item.get("test")
                or item.get("code")
                or item.get("icd")
                or item.get("snippet")
                or src_as_label
                or str(item)[:120]
            )
            value = (
                item.get("value")
                or item.get("result")
                or item.get("dose")
                or item.get("note")
                or None
            )
            ts = item.get("date") or item.get("timestamp") or item.get("ts") or None
            signals.append(
                ContributingSignal(
                    source=src,  # type: ignore[arg-type]
                    label=str(label)[:200],
                    value=str(value)[:200] if value is not None else None,
                    timestamp=str(ts)[:40] if ts else None,
                )
            )
        elif isinstance(item, str):
            signals.append(
                ContributingSignal(source=default_src, label=item[:200])  # type: ignore[arg-type]
            )

    if isinstance(raw, list):
        for it in raw:
            _push(it)
    elif isinstance(raw, dict):
        # Common shape: {"medications": [...], "labs": [...], "summary": "..."}
        for key in ("medications", "labs", "history", "notes", "signals", "items"):
            v = raw.get(key)
            if isinstance(v, list):
                for it in v:
                    _push(it)
        # Fallback: treat the dict itself as one signal
        if not signals:
            _push(raw)
    else:
        _push(raw)

    return signals


@router.get("/{pid}/suspect/{suspect_id}/explain", response_model=ExplainResponse)
def explain_suspect(
    pid: int,
    suspect_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> ExplainResponse:
    """Return the contributing signals that triggered a suspect.

    Reads `raf_suspect_conditions.evidence_detail` (JSON) and decomposes it
    into a typed list so the UI can render icons/grouped rows per source.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, patient_id, suspect_icd10, suspect_hcc, evidence_type,
                   evidence_detail, confidence_score
            FROM raf_suspect_conditions
            WHERE id = %s AND tenant_id = %s
            """,
            (suspect_id, tenant_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Suspect not found")
    if int(row["patient_id"]) != int(pid):
        raise HTTPException(
            status_code=403, detail="Suspect does not belong to this patient"
        )

    signals = _decompose_evidence_detail(
        row.get("evidence_detail"), row.get("evidence_type") or ""
    )
    if signals:
        summary = (
            f"{len(signals)} contributing signal(s) "
            f"from {row.get('evidence_type') or 'mixed sources'}."
        )
    else:
        summary = "No evidence logged for this suspect."

    return ExplainResponse(
        suspect_id=int(row["id"]),
        patient_id=int(row["patient_id"]),
        suspect_icd10=str(row.get("suspect_icd10") or ""),
        suspect_hcc=str(row.get("suspect_hcc") or ""),
        confidence=float(row.get("confidence_score") or 0.0),
        evidence_type=str(row.get("evidence_type") or ""),
        contributing_signals=signals,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Refresh MEAT — rule-based extractor across all notes for this patient
# ---------------------------------------------------------------------------

class RefreshMEATRequest(BaseModel):
    max_days_lookback: int = 365
    year: int | None = None


@router.post("/{pid}/actions/refresh-meat")
def action_refresh_meat(
    pid: int,
    body: RefreshMEATRequest | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> dict[str, Any]:
    """Run the rule-based MEAT extractor against every recent note.

    Writes into raf_meat_evidence and recomputes raf_patient_hcc.meat_status.
    Safe to call repeatedly — store_meat_evidence de-dupes on
    (patient_hcc_id, encounter_id).
    """
    from app.services.auto_meat_extractor import run_auto_meat_for_patient

    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    req = body or RefreshMEATRequest()
    try:
        summary = run_auto_meat_for_patient(
            pid,
            tenant_id=tenant_id,
            year=req.year,
            max_days_lookback=req.max_days_lookback,
        )
    except Exception as exc:
        logger.exception("refresh-meat failed pid=%s", pid)
        raise HTTPException(status_code=500, detail=f"MEAT extraction failed: {exc}")

    _invalidate_panel_cache(pid, tenant_id)
    return {"ok": True, "summary": summary}
