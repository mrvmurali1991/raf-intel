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
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_permission
from app.cache import cache_delete_pattern, cache_get, cache_set
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.config import settings
from app.db import openemr_cursor, raf_cursor
from app.rate_limit import limiter
from app.services.cache_strategy import get_active_connection_id
from app.services.celery_tasks import task_refresh_meat_for_patient
from app.services.edps_ingest import get_accepted_raf
from app.services.fhir_problem_list import (
    push_problem_list_condition,
    reconcile_condition,
)
from app.services.immutable_audit import emit_audit_event
from app.services.openemr_connector import (
    get_patient,
    push_medical_problem,
    push_prescription,
    push_procedure_order,
)
from app.services.patient_service import patient_is_accessible
from app.services.raf.calculator import calculate_raf_score, get_raf_breakdown
from app.services.recapture_gap_service import get_patient_gaps
from app.services.suspect_engine import (
    accept_suspect,
    dismiss_suspect,
    get_suspects_for_patient,
    restore_suspect,
)

logger = logging.getLogger(__name__)


def _require_patient_access(
    pid: int,
    tenant_id: str,
    *,
    current_user: dict | None = None,
    action: str = "view",
    resource: str = "raf_central",
) -> None:
    """Raise 404 if *pid* is not accessible to *tenant_id*; emit PHI audit log.

    Guards action endpoints that take `pid` from the URL so a caller in
    tenant A cannot drive side-effects (EMR writes, cache invalidation,
    MEAT inserts) against tenant B's patient by supplying the pid in the
    path and one of their own suspect_ids in the body.  Also emits a
    :func:`log_phi_access` record so every raf-central patient touch
    leaves a HIPAA §164.312(b) audit trail.
    """
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    if not patient_is_accessible(pid, tenant_id):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")
    try:
        from app.services.audit_logger import log_phi_access
        user = "unknown"
        if current_user:
            user = current_user.get("email") or current_user.get("sub") or "unknown"
        log_phi_access(
            action=action,
            resource=resource,
            patient_id=pid,
            user=user,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # never let audit logging break the request path
        logger.debug("raf_central audit log failed for pid=%s: %s", pid, exc)


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
    # Gap #12 — sentence-level MEAT evidence so the UI can render the
    # exact proving sentence under each M/E/A/T chip (RAAPID / Keebler /
    # Reveleer EVE parity).  Populated by the LLM extractor in
    # ``app.services.meat_evidence_extractor``; ``None`` when no
    # evidence has been captured yet.
    evidence: dict[str, Any] | None = None


class SuspectCard(BaseModel):
    id: int
    hcc: int
    icd10: str
    label: str
    confidence: float
    evidence_type: str
    trigger: str
    status: str
    # Hierarchy + completeness signals — surfaced so the UI can disable
    # Accept on a suspect that V28 will trump at scoring time and so the
    # MEAT-completeness fraction can drive prioritization instead of raw
    # coefficient (patient-safety review #6, #7).
    trumped_by_hcc: int | None = None
    meat_completeness: float | None = None
    # Canonical specialty bucket (cardiology / nephrology / endocrinology /
    # pulmonology / oncology / behavioral / general) derived from the HCC
    # code via app.services.specialty_routing. The UI uses this to filter
    # suspects to whatever the viewing clinician owns — a nephrologist sees
    # CKD-related suspects first, a cardiologist sees CHF first, etc.
    # ("ForeSee" specialty-aware routing pattern.)
    specialty: str = "general"


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
    # CMS-accepted RAF from the most recent MAO-004 EDPS response, when
    # available. ``None`` means "still waiting for EDPS feedback" — the
    # RAF Reconciliation card renders a distinct placeholder in that case.
    accepted_raf: float | None = None
    # RAF value that was on the 837 / EDPS submission when CMS replied.
    # ``None`` means CMS has not replied yet for this pid + PY.
    submitted_raf: float | None = None
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


def _fetch_meat_letters(
    patient_id: int, year: int, tenant_id: str
) -> tuple[
    dict[str, dict[str, bool]],
    dict[str, int | None],
    dict[str, dict[str, Any]],
]:
    """Return per-HCC MEAT coverage + patient_hcc_id map + evidence snippets.

    Three-tuple return:
      * ``letter_map``    — ``{hcc_code: {monitor, evaluate, assess, treat}}``
      * ``hcc_id_map``    — ``{hcc_code: patient_hcc_id | None}``
      * ``evidence_map``  — ``{hcc_code: {<letter>_text, <letter>_offsets,
                                          source_encounter_id, source_date,
                                          icd10}}``  (Gap #12)

    Single JOIN query selects the most-recent ``raf_meat_evidence`` row per
    patient_hcc row alongside the aggregated presence booleans, so the
    frontend can render evidence sentences under each MEAT chip without
    issuing a follow-up request.

    If the new offset columns (Alembic 030) are not yet present the query
    falls back to selecting only the text columns — the offsets default
    to ``None`` in that case.
    """
    letter_map: dict[str, dict[str, bool]] = {}
    hcc_id_map: dict[str, int | None] = {}
    evidence_map: dict[str, dict[str, Any]] = {}

    # Detect presence of Alembic-030 columns up front so a stale schema
    # doesn't trip the query.
    _have_offsets = False
    _have_source_enc = False
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name   = 'raf_meat_evidence'
                """
            )
            cols = {str(r["column_name"]).lower() for r in cur.fetchall() or []}
        _have_offsets = "meat_m_offsets" in cols
        _have_source_enc = "source_encounter_id" in cols
    except Exception:
        pass

    # Build the optional column lists. The latest_id sub-query gives us
    # the most-recent evidence row per patient_hcc id; we LEFT-JOIN back
    # to that row to pull text snippets / offsets in one shot.
    extra_select_parts: list[str] = []
    extra_group_parts: list[str] = []
    if _have_offsets:
        for c in ("meat_m_offsets", "meat_e_offsets", "meat_a_offsets", "meat_t_offsets"):
            extra_select_parts.append(f"lev.{c}")
            extra_group_parts.append(f"lev.{c}")
    if _have_source_enc:
        extra_select_parts.append("lev.source_encounter_id")
        extra_group_parts.append("lev.source_encounter_id")

    extra_select_sql = (", " + ", ".join(extra_select_parts)) if extra_select_parts else ""
    extra_group_sql = (", " + ", ".join(extra_group_parts)) if extra_group_parts else ""

    sql = f"""
        SELECT ph.id          AS patient_hcc_id,
               ph.hcc_code,
               ph.icd10_codes,
               MAX(COALESCE(ev.meat_m_present, CASE WHEN ev.meat_m IS NOT NULL AND ev.meat_m != '' THEN 1 ELSE 0 END)) AS m,
               MAX(COALESCE(ev.meat_e_present, CASE WHEN ev.meat_e IS NOT NULL AND ev.meat_e != '' THEN 1 ELSE 0 END)) AS e,
               MAX(COALESCE(ev.meat_a_present, CASE WHEN ev.meat_a IS NOT NULL AND ev.meat_a != '' THEN 1 ELSE 0 END)) AS a,
               MAX(COALESCE(ev.meat_t_present, CASE WHEN ev.meat_t IS NOT NULL AND ev.meat_t != '' THEN 1 ELSE 0 END)) AS t,
               lev.meat_m AS meat_m_text,
               lev.meat_e AS meat_e_text,
               lev.meat_a AS meat_a_text,
               lev.meat_t AS meat_t_text,
               lev.encounter_id  AS evidence_encounter_id,
               lev.encounter_date AS evidence_encounter_date
               {extra_select_sql}
        FROM raf_patient_hcc ph
        LEFT JOIN raf_meat_evidence ev ON ev.patient_hcc_id = ph.id
        LEFT JOIN (
            SELECT me.*
            FROM raf_meat_evidence me
            JOIN (
                SELECT patient_hcc_id, MAX(id) AS max_id
                FROM raf_meat_evidence
                GROUP BY patient_hcc_id
            ) latest ON latest.max_id = me.id
        ) lev ON lev.patient_hcc_id = ph.id
        WHERE ph.patient_id = %s AND ph.measurement_year = %s AND ph.tenant_id = %s
        GROUP BY ph.id, ph.hcc_code, ph.icd10_codes,
                 lev.meat_m, lev.meat_e, lev.meat_a, lev.meat_t,
                 lev.encounter_id, lev.encounter_date
                 {extra_group_sql}
    """

    rows: list[dict[str, Any]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (patient_id, year, tenant_id))
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.debug("meat letter fetch failed pid=%s: %s", patient_id, exc)

    # ---- HCCs needing lazy LLM extraction (no evidence text yet AND at
    # least one note in the year).  We extract opportunistically so the
    # UI gets sentences on subsequent loads; the heavy lifting is gated
    # behind a feature flag because Gemini calls cost real money.
    needs_extract: list[tuple[int, str, str]] = []  # (phcc_id, hcc_code, icd10)

    for row in rows:
        code = str(row["hcc_code"])
        phcc_id = int(row["patient_hcc_id"]) if row.get("patient_hcc_id") is not None else None
        letter_map[code] = {
            "monitor": bool(row.get("m")),
            "evaluate": bool(row.get("e")),
            "assess":   bool(row.get("a")),
            "treat":    bool(row.get("t")),
        }
        hcc_id_map[code] = phcc_id

        # Decode JSON-typed offset columns if present.
        def _decode_offset(val: Any) -> list[int] | None:
            if val is None:
                return None
            if isinstance(val, list):
                return val
            try:
                import json as _json
                parsed = _json.loads(val)
                return parsed if isinstance(parsed, list) else None
            except Exception:
                return None

        # Parse icd10_codes — JSON array or comma string.
        raw_icds = row.get("icd10_codes")
        icd_list: list[str] = []
        if isinstance(raw_icds, list):
            icd_list = [str(x).strip() for x in raw_icds if x]
        elif isinstance(raw_icds, str):
            s = raw_icds.strip()
            if s.startswith("["):
                import json as _json
                try:
                    parsed = _json.loads(s)
                    if isinstance(parsed, list):
                        icd_list = [str(x).strip() for x in parsed if x]
                except Exception:
                    pass
            if not icd_list:
                icd_list = [c.strip() for c in s.split(",") if c.strip()]

        ev_text = {
            "monitor": row.get("meat_m_text"),
            "evaluate": row.get("meat_e_text"),
            "assess":  row.get("meat_a_text"),
            "treat":   row.get("meat_t_text"),
        }
        any_text = any(v for v in ev_text.values())
        if any_text or row.get("evidence_encounter_id") is not None:
            evidence_map[code] = {
                "monitor_text":  ev_text["monitor"],
                "evaluate_text": ev_text["evaluate"],
                "assess_text":   ev_text["assess"],
                "treat_text":    ev_text["treat"],
                "monitor_offsets":  _decode_offset(row.get("meat_m_offsets")) if _have_offsets else None,
                "evaluate_offsets": _decode_offset(row.get("meat_e_offsets")) if _have_offsets else None,
                "assess_offsets":   _decode_offset(row.get("meat_a_offsets")) if _have_offsets else None,
                "treat_offsets":    _decode_offset(row.get("meat_t_offsets")) if _have_offsets else None,
                "source_encounter_id": (
                    int(row["source_encounter_id"])
                    if _have_source_enc and row.get("source_encounter_id") is not None
                    else (int(row["evidence_encounter_id"])
                          if row.get("evidence_encounter_id") is not None else None)
                ),
                "source_date": (
                    row["evidence_encounter_date"].isoformat()
                    if hasattr(row.get("evidence_encounter_date"), "isoformat")
                    else (str(row["evidence_encounter_date"])
                          if row.get("evidence_encounter_date") else None)
                ),
                "icd10": icd_list[0] if icd_list else "",
            }

        # Queue for lazy extraction when (a) there's no evidence text AND
        # (b) we have a patient_hcc_id AND (c) the patient is documented
        # (skip empty HCC rows). We don't *know* there are notes here —
        # the extractor itself handles the empty-notes case gracefully.
        if phcc_id and not any_text and icd_list:
            needs_extract.append((phcc_id, code, icd_list[0]))

    # ------------------------------------------------------------------
    # Lazy LLM extraction — fire-and-forget for HCCs that are missing
    # evidence text. Gated by ``settings.lazy_meat_extraction`` so we
    # never blow up the dashboard latency budget during a demo.
    # ------------------------------------------------------------------
    if needs_extract:
        try:
            from app.config import settings as _settings
            _enabled = bool(getattr(_settings, "lazy_meat_extraction", False))
        except Exception:
            _enabled = False
        if _enabled:
            try:
                from app.services.meat_evidence_extractor import (
                    extract_meat_evidence_for_hcc,
                    persist_meat_evidence,
                )
                for phcc_id, code, icd in needs_extract[:3]:  # cap per request
                    try:
                        ev = extract_meat_evidence_for_hcc(
                            patient_id=patient_id,
                            hcc_code=code,
                            icd10=icd,
                            measurement_year=year,
                            tenant_id=tenant_id,
                        )
                        if ev.letters_present() > 0:
                            persist_meat_evidence(
                                patient_hcc_id=phcc_id,
                                evidence=ev,
                                measurement_year=year,
                            )
                    except Exception as _exc:
                        logger.debug("lazy meat extract failed phcc=%s: %s", phcc_id, _exc)
            except Exception as exc:
                logger.debug("lazy meat extraction unavailable: %s", exc)

    return letter_map, hcc_id_map, evidence_map


def _fetch_patient_hcc_id(patient_id: int, year: int, hcc_code: str, tenant_id: str) -> int | None:
    """Return the raf_patient_hcc.id so the UI can target a specific row.

    DEPRECATED — prefer ``_fetch_meat_letters`` which returns the
    ``patient_hcc_id`` alongside MEAT letters in a single JOIN query, avoiding
    the N+1 pattern this function creates when called in a loop.  Retained only
    for callers outside ``_build_raf_section``.
    """
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
    except Exception as e:
        logger.warning(
            "patient_hcc_id lookup failed pid=%s year=%s hcc=%s: %s",
            patient_id, year, hcc_code, e, exc_info=True,
        )
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
    except Exception as e:
        logger.warning("prior-year raf lookup failed: %s", e, exc_info=True)

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

    # MEAT gaps — one card per HCC in the breakdown.
    # Single JOIN query returns both letter-level MEAT coverage AND patient_hcc_id,
    # eliminating the N+1 pattern from calling _fetch_patient_hcc_id per HCC.
    letter_map, hcc_id_map, evidence_map = _fetch_meat_letters(pid, year, tenant_id)
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
        # patient_hcc_id resolution — three-tier fallback to guarantee the
        # MEAT attestation buttons on this card render with a real id:
        #   1. _fetch_meat_letters JOIN map (covers most patients)
        #   2. meat_completeness blob if the engine attached one
        #   3. Direct per-row lookup against raf_patient_hcc as a last resort
        # Without these fallbacks every Mark-reviewed / Order Lab / Start
        # Treatment button on the panel is rendered with patient_hcc_id=null
        # and silently no-ops (PCP-review #1).
        meat_completeness = hcc.get("meat_completeness") or {}
        resolved_hcc_id = hcc_id_map.get(code)
        if resolved_hcc_id is None and meat_completeness.get("patient_hcc_id") is not None:
            try:
                resolved_hcc_id = int(meat_completeness["patient_hcc_id"])
            except (ValueError, TypeError):
                resolved_hcc_id = None
        if resolved_hcc_id is None and code:
            resolved_hcc_id = _fetch_patient_hcc_id(pid, year, code, tenant_id)
        meat_gaps.append(
            MEATGap(
                patient_hcc_id=resolved_hcc_id,
                hcc=code,
                icd10_codes=list(hcc.get("icd10_codes") or []),
                label=hcc.get("hcc_label") or _hcc_label(code),
                coefficient=float(hcc.get("coefficient") or 0.0),
                status=actual_status if actual_status != "MISSING" else "NOT_COMPLIANT",
                gaps=letters,
                evidence=evidence_map.get(code) or None,
            )
        )

    return raf_bar, meat_gaps, breakdown


def _fetch_trumped_map(pid: int, year: int, tenant_id: str) -> dict[int, int]:
    """Return {hcc_code: trumped_by_hcc} for any suspect whose HCC would be
    trumped by an HCC already coded on the patient.

    Two sources, merged:
      1. `raf_patient_hcc.is_trumped=1` — rows the scorer has already
         materialized (post-RAF-calculation).
      2. `hcc_hierarchy_rules` cross-joined with the patient's active HCCs
         (no `is_trumped` flag required) — covers the freshness gap where
         a new suspect's hierarchy relationship hasn't been computed yet
         (patient-safety review round-5 blocker #2). Without this, the
         "Trumped by HCC X" badge is silently absent on the most actionable
         (newest) suspects.
    """
    out: dict[int, int] = {}
    try:
        with raf_cursor() as cur:
            # 1) Persisted trumping from the last scoring run.
            cur.execute(
                """
                SELECT hcc_code, trumped_by_hcc
                  FROM raf_patient_hcc
                 WHERE patient_id = %s
                   AND measurement_year = %s
                   AND tenant_id = %s
                   AND is_trumped = 1
                   AND trumped_by_hcc IS NOT NULL
                """,
                (pid, year, tenant_id),
            )
            for r in cur.fetchall() or []:
                try:
                    out[int(r["hcc_code"])] = int(r["trumped_by_hcc"])
                except (ValueError, TypeError):
                    continue

            # 2) Live rules: cross hcc_hierarchy_rules against the patient's
            # currently-active HCCs (whether scored or not). If the patient
            # already carries the dominant HCC of a rule, mark the
            # subordinate as trumped — even if no raf_patient_hcc row yet
            # bears the is_trumped flag.
            cur.execute(
                """
                SELECT DISTINCT hr.hcc_code AS subordinate,
                                hr.trumped_by_hcc AS dominant
                  FROM hcc_hierarchy_rules hr
                  JOIN raf_patient_hcc ph
                    ON ph.hcc_code = hr.trumped_by_hcc
                   AND ph.patient_id = %s
                   AND ph.measurement_year = %s
                   AND ph.tenant_id = %s
                """,
                (pid, year, tenant_id),
            )
            for r in cur.fetchall() or []:
                try:
                    sub = int(r["subordinate"])
                    dom = int(r["dominant"])
                except (ValueError, TypeError):
                    continue
                # Keep the persisted mapping if both sources agree; otherwise
                # this is the live answer.
                out.setdefault(sub, dom)
    except Exception as exc:
        logger.debug("trumped map lookup failed pid=%s: %s", pid, exc)
    return out


def _build_suspects(pid: int, year: int, tenant_id: str) -> list[SuspectCard]:
    """
    Emit one SuspectCard per open suspect for *pid*.

    Label-resolution order (clinical safety):
      1. ICD-10 description from `simple_icd_10_cm` — canonical clinical truth
         (what the chart actually documents).
      2. HCC label from the V28 dictionary — only when (a) ICD-10 is missing
         or unmapped AND (b) hcc_code is non-zero.
      3. Fall back to a generic "Suspect condition" so the UI never shows the
         literal string "HCC " or "HCC 0".

    Reason: prior versions used `_hcc_label(suspect_hcc)` exclusively, which
    produced clinically wrong labels when the engine's HCC assignment did not
    match the ICD-10 (e.g. hcc=111 paired with N18.4 displayed "Hemophilia"
    while the actual ICD codes CKD Stage 4 — PCP-review #2). Accepting on the
    strength of a wrong label would push the wrong diagnosis to the EMR.

    Suspects with hcc=0 AND an unmapped ICD are dropped entirely — they are
    almost always engine artifacts (raw text matches without HCC linkage) and
    surfacing them as "HCC 0" / empty-label cards risks clinician confusion.
    """
    from app.services.icd_validator import (
        get_description as _icd_desc,
        get_hcc_mapping as _icd_to_hcc,
    )
    from app.services.specialty_routing import specialty_for_hcc

    try:
        rows = get_suspects_for_patient(pid, year=year, tenant_id=tenant_id) or []

        # Auto-enrich pre-existing suspect rows whose meat_completeness /
        # trumped_by_hcc was never populated (rows created before A6 wiring
        # landed). This is a one-shot lazy back-fill so the panel never
        # ships a "Confirmed" badge with null MEAT.
        needs_enrich = False
        for _r in rows:
            _ed = _r.get("evidence_detail")
            if isinstance(_ed, dict):
                if _ed.get("meat_completeness") is None and _ed.get("trumped_by_hcc") is None:
                    needs_enrich = True
                    break
        if needs_enrich:
            try:
                from app.services.suspect_enrichment import enrich_suspects_for_patient
                enrich_suspects_for_patient(pid, tenant_id, year=year)
                rows = get_suspects_for_patient(pid, year=year, tenant_id=tenant_id) or []
            except Exception as _enr_exc:
                logger.warning("lazy suspect enrichment failed pid=%s: %s", pid, _enr_exc)
    except Exception as exc:
        logger.error("raf-central: suspects fetch failed pid=%s: %s", pid, exc)
        return []

    trumped_map = _fetch_trumped_map(pid, year, tenant_id)

    trigger_map = {
        "medication": "Medications",
        "lab": "Lab results",
        "historical": "Prior-year HCC",
        "imaging": "Imaging",
        "referral": "Referral",
    }

    out: list[SuspectCard] = []
    for r in rows:
        if (r.get("status") or "").lower() != "open":
            continue
        ev = str(r.get("evidence_type") or "")
        icd10 = str(r.get("suspect_icd10") or "").strip()
        try:
            hcc_int = int(str(r.get("suspect_hcc") or "0").replace("HCC", "").strip() or 0)
        except (ValueError, TypeError):
            hcc_int = 0

        # Resolve a clinically-honest label.
        icd_label = ""
        if icd10:
            try:
                icd_label = (_icd_desc(icd10) or "").strip()
            except Exception:
                icd_label = ""

        # If the engine emitted hcc=0 but the ICD-10 is valid, derive the
        # correct HCC from the CMS-HCC V28 crosswalk so the row carries an
        # HCC code (otherwise the SuspectCard renders "HCC 0" — PCP-review #2
        # finding cluster, hcc=0 + valid ICD case).
        if hcc_int == 0 and icd10:
            try:
                mapping = _icd_to_hcc(icd10)
            except Exception:
                mapping = None
            if mapping and mapping.get("hcc_code"):
                try:
                    hcc_int = int(str(mapping["hcc_code"]).replace("HCC", "").strip() or 0)
                except (ValueError, TypeError):
                    hcc_int = 0

        if icd_label:
            label = icd_label
        elif hcc_int > 0:
            label = _hcc_label(str(hcc_int))
        else:
            # No usable label AND no real HCC — engine artifact, drop the row.
            continue

        # MEAT completeness fraction (0..1) from the engine's evidence_detail
        # if present — used by the frontend to combine clinical-acuity with
        # coefficient when sorting MEAT gaps (patient-safety review #6).
        meat_pct: float | None = None
        ed = r.get("evidence_detail")
        if isinstance(ed, dict):
            mc = ed.get("meat_completeness")
            if isinstance(mc, (int, float)):
                meat_pct = float(mc)

        out.append(
            SuspectCard(
                id=int(r.get("suspect_id") or r.get("id") or 0),
                hcc=hcc_int,
                icd10=icd10,
                label=label,
                confidence=float(r.get("confidence_score") or 0.0),
                evidence_type=ev,
                trigger=trigger_map.get(ev, ev or "—"),
                status=str(r.get("status") or "open"),
                trumped_by_hcc=trumped_map.get(hcc_int),
                meat_completeness=meat_pct,
                specialty=specialty_for_hcc(hcc_int),
            )
        )
    return out


def _build_recapture(pid: int, tenant_id: str) -> list[RecaptureCard]:
    """
    Build the recapture list, deduped by (hcc, icd10) and hydrated with
    last_encounter_date from the encounters table.

    Why dedupe: the upstream get_patient_gaps() returns one row per source
    transaction (claim line / suspect emission), so the same HCC+ICD pair
    can appear 3-4 times. Rendering duplicates quadruple-counts
    revenue-at-risk and confuses clinicians — PCP-review #7, HCC-review #7.

    Why hydrate last_encounter_date: prior versions always returned None,
    leaving the freshness chip blank — PCP-review #6.
    """
    try:
        rows = get_patient_gaps(pid, tenant_id) or []
    except Exception as exc:
        logger.error("raf-central: recapture fetch failed pid=%s: %s", pid, exc)
        return []

    # Two-pass lookup for last_encounter_date:
    # 1) Per-ICD from claims_diagnoses (precise: "last seen for this specific
    #    diagnosis"). Some patients won't have claims data — fall through.
    # 2) Patient-level fallback from normalized_encounters (less precise but
    #    populates SOMETHING so the freshness chip isn't always blank).
    encounter_date_by_icd: dict[str, str] = {}
    last_patient_encounter: str | None = None
    try:
        with raf_cursor() as _ec:
            _ec.execute(
                """
                SELECT cd.icd10_code, MAX(c.service_date) AS last_date
                  FROM claims_diagnoses cd
                  JOIN claims c ON c.id = cd.claim_id
                 WHERE c.patient_id = %s AND c.tenant_id = %s
                 GROUP BY cd.icd10_code
                """,
                (pid, tenant_id),
            )
            for er in _ec.fetchall() or []:
                code = (er.get("icd10_code") or "").strip().upper()
                if code and er.get("last_date"):
                    encounter_date_by_icd[code] = str(er["last_date"])
    except Exception as exc:
        # claims may not be wired for every tenant — fall through silently.
        logger.debug(
            "raf-central recapture: per-ICD claims lookup unavailable: %s", exc
        )

    try:
        with raf_cursor() as _ec:
            _ec.execute(
                """
                SELECT MAX(encounter_date) AS last_date
                  FROM normalized_encounters
                 WHERE patient_id = %s AND tenant_id = %s
                """,
                (pid, tenant_id),
            )
            row = _ec.fetchone()
            if row and row.get("last_date"):
                last_patient_encounter = str(row["last_date"])
    except Exception as exc:
        logger.debug(
            "raf-central recapture: patient encounter lookup unavailable: %s", exc
        )

    seen: set[tuple[str, str]] = set()
    out: list[RecaptureCard] = []
    for r in rows:
        hcc_code = str(r.get("hcc_code") or "")
        icd_code = str(r.get("icd10_code") or "")
        if not hcc_code and not icd_code:
            continue
        key = (hcc_code, icd_code)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            RecaptureCard(
                id=int(r.get("id") or 0),
                hcc=hcc_code,
                icd10=icd_code,
                label=r.get("hcc_description") or _hcc_label(hcc_code),
                prior_year=int(r.get("prior_year") or 0),
                current_year=int(r.get("current_year") or 0),
                revenue_at_risk=float(r.get("raf_impact") or 0.0),
                last_encounter_date=(
                    r.get("last_encounter_date")
                    or encounter_date_by_icd.get(icd_code.upper())
                    or last_patient_encounter
                ),
            )
        )
    return out


def _build_audit(raf_bar: LiveRAFBar, meat_gaps: list[MEATGap]) -> AuditReadiness:
    total = len(meat_gaps)
    compliant = sum(1 for g in meat_gaps if g.status == "COMPLETE")
    pct = round(100.0 * compliant / total, 1) if total else 0.0
    if total == 0 or pct >= 80:
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


def _build_financial(
    raf_bar: LiveRAFBar,
    suspects: list[SuspectCard],
    recapture: list[RecaptureCard],
    accepted_raf: float | None = None,
    submitted_raf: float | None = None,
) -> FinancialImpact:
    """Projected RAF = current + sum(confidence × expected_coef) for open
    suspects + sum of recapture RAF impact. We don't have per-suspect
    coefficients on this endpoint, so we approximate using a conservative
    0.150 per-suspect lift weighted by confidence — matches the V28 median
    coefficient for demographic-adjacent disease categories. Recapture
    revenue is already a dollar figure.

    ``accepted_raf`` is the CMS-acknowledged RAF from the latest MAO-004
    EDPS response (see :mod:`app.services.edps_ingest`). It flows through
    as-is so the RAF Reconciliation card can render a real value instead
    of the "waiting for EDPS feedback" placeholder. ``None`` means CMS
    has not yet replied for this pid + measurement_year.
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
        accepted_raf=accepted_raf,
        # If CMS replied with accepted_raf but we never tracked the exact
        # value-at-submission, fall back to current_raf as the best
        # available proxy for what was sent. Reconciliation card renders
        # "engine X vs CMS Y" using these two numbers.
        submitted_raf=(submitted_raf if submitted_raf is not None else (raf_bar.current if accepted_raf is not None else None)),
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
@limiter.limit("60/minute")
def get_raf_central(
    request: Request,
    pid: int = Path(..., description="OpenEMR patient PID"),
    year: int | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> RAFCentralPayload:
    tenant_id: str | None = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id or "", current_user=current_user)

    measurement_year = year or date.today().year

    # --- Cache lookup ------------------------------------------------------
    acid = get_active_connection_id(tenant_id)
    cache_key = f"raf-central:{tenant_id}:{acid}:{pid}:{measurement_year}"
    cached = cache_get(cache_key)
    if cached is not None:
        try:
            return RAFCentralPayload(**cached)
        except Exception as e:
            logger.warning(
                "raf-central cache deserialise failed pid=%s: %s",
                pid, e, exc_info=True,
            )
            # Cache shape drift — fall through and rebuild.

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

    # --- Fan out (parallelised) --------------------------------------------
    # _build_raf_section, _build_suspects, and _build_recapture are independent
    # I/O-bound calls.  Run them concurrently inside a small ThreadPoolExecutor
    # so total latency is bounded by the slowest single builder, not their sum.
    # Each builder has its own internal error handling and returns empty/zero
    # payloads on failure; exceptions propagate here and are re-raised so the
    # caller receives a 500 rather than a silent partial result.
    _panel_futures: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="panel") as _pool:
        _panel_futures["raf"] = _pool.submit(_build_raf_section, pid, measurement_year, tenant_id)
        _panel_futures["suspects"] = _pool.submit(_build_suspects, pid, measurement_year, tenant_id)
        _panel_futures["recapture"] = _pool.submit(_build_recapture, pid, tenant_id)

        # Collect results — any exception from a sub-builder is re-raised here.
        raf_bar, meat_gaps, _breakdown = _panel_futures["raf"].result()
        suspects = _panel_futures["suspects"].result()
        recapture = _panel_futures["recapture"].result()

    audit = _build_audit(raf_bar, meat_gaps)
    # Pull the CMS-accepted RAF (if any) from raf_edps_feedback so the
    # RAF Reconciliation card can render a real value instead of the
    # "waiting for EDPS feedback" placeholder. Failures degrade to None.
    try:
        accepted_raf = get_accepted_raf(
            patient_id=pid,
            measurement_year=measurement_year,
            tenant_id=str(tenant_id or ""),
        )
    except Exception as exc:  # noqa: BLE001 — never block panel render
        logger.warning("raf-central: EDPS lookup failed pid=%s: %s", pid, exc)
        accepted_raf = None
    financial = _build_financial(raf_bar, suspects, recapture, accepted_raf=accepted_raf)

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
    except Exception as e:
        logger.warning("raf-central cache_set failed pid=%s: %s", pid, e, exc_info=True)

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
    # Force-accept path: bypass the MEAT gate ONLY when the coder
    # explicitly attests they understand the RADV exposure. The frontend
    # collects MRN re-entry + a 20-char reason via AcceptConfirmDialog.
    # Both must be present and valid or the server rejects with 403.
    force_no_meat: bool = Field(
        default=False,
        description="True iff the coder accepted via the Force-Accept (RADV risk) path",
    )
    mrn_confirmation: str | None = Field(
        default=None,
        description="Patient MRN (or last 4 digits) typed by the coder to confirm intent",
    )
    override_reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Free-text RADV-risk reason (>= 20 non-whitespace chars)",
    )
    # NLP write-back attestation — Patient Safety round-2 fix.
    # When push_to_emr=true and the suspect source is 'nlp' with confidence
    # below NLP_MIN_CONFIDENCE_WRITEBACK (0.85), this field must be true to
    # proceed.  It signals a credentialed clinician has reviewed and attested
    # the NLP finding before it is committed to the EMR Problem List.
    meat_signed: bool = Field(
        default=False,
        description=(
            "True iff a credentialed clinician has explicitly attested this "
            "NLP suspect before EMR write-back (required when NLP confidence < 0.85)"
        ),
    )


class DismissSuspectRequest(BaseModel):
    suspect_id: int
    reason: str = "dismissed via raf-central panel"


class RestoreSuspectRequest(BaseModel):
    suspect_id: int
    reason: str | None = None


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
    except Exception as e:
        logger.warning(
            "raf-central cache invalidation failed pid=%s: %s",
            pid, e, exc_info=True,
        )


# Action response models (must be defined before the route decorators that reference them)

class ActionOkResponse(BaseModel):
    ok: bool


class AcceptSuspectResponse(BaseModel):
    ok: bool
    suspect: dict[str, Any]
    pushed_to_emr: bool
    fhir_condition_id: str | None = None
    fhir_reconciled: bool | None = None
    push_method: str | None = None  # "fhir" | "fhir_then_mysql_fallback" | "mysql" | "none"


class DismissSuspectResponse(BaseModel):
    ok: bool
    suspect: dict[str, Any]


class RestoreSuspectResponse(BaseModel):
    ok: bool
    suspect: dict[str, Any]


class MarkMEATReviewedResponse(BaseModel):
    ok: bool
    meat_status: str
    reviewed_by: str


class AddAssessmentNoteResponse(BaseModel):
    ok: bool
    encounter_id: int | None
    author: str


class UpgradeCodeResponse(BaseModel):
    ok: bool
    rows_updated: int


class RecalculateResponse(BaseModel):
    ok: bool
    raf_score: float
    hcc_count: int
    model_segment: str | None
    measurement_year: int


class StartTreatmentResponse(BaseModel):
    status: str
    prescription_id: int
    drug: str


class OrderLabResponse(BaseModel):
    status: str
    procedure_order_id: int | None = None
    suggested_lab_code: str
    reason: str | None = None


class RefreshMEATResponse(BaseModel):
    status: str
    job_id: str


class EnrichSuspectsResponse(BaseModel):
    ok: bool
    enriched: int
    measurement_year: int


@router.post("/{pid}/actions/accept-suspect", response_model=AcceptSuspectResponse)
def action_accept_suspect(
    pid: int,
    body: AcceptSuspectRequest,
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
    _idem: None = Depends(idempotency_key_dependency()),
) -> AcceptSuspectResponse:
    """Accept a suspect HCC condition and optionally push to EMR.

    Supports Idempotency-Key header (24h replay window).
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    _require_patient_access(pid, tenant_id, current_user=current_user)

    # Safety guard: if a clinical-documentation query is still pending on
    # this suspect, refuse the accept. Otherwise the same coder can fire a
    # "please confirm CKD stage" question to the PCP and Accept the
    # suspect five seconds later — the attestation says MEAT is sufficient
    # while the open query admits MEAT is insufficient. Safety review
    # round-N+1 #1. Coders should explicitly close or cancel the query
    # first.
    try:
        with raf_cursor() as _cq_cur:
            _cq_cur.execute(
                """
                SELECT id FROM raf_clinical_queries
                 WHERE suspect_id = %s
                   AND tenant_id = %s
                   AND status = 'pending'
                 LIMIT 1
                """,
                (body.suspect_id, tenant_id),
            )
            pending_query = _cq_cur.fetchone()
    except Exception as exc:
        # Table may not be provisioned in every environment — log and skip.
        logger.debug("clinical-query pre-check unavailable: %s", exc)
        pending_query = None
    if pending_query:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot accept suspect {body.suspect_id} while a documentation "
                f"query (id={pending_query['id']}) is still pending for this "
                "suspect. Close or cancel the query before attesting."
            ),
        )

    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"

    # Server-side MEAT gate — UI cannot be trusted. Fetch the suspect's
    # current meat_status / meat_completeness from raf_suspect_conditions
    # and reject the accept unless one of:
    #   (a) MEAT is present (status != 'missing' AND meat_completeness > 0),
    #   (b) the suspect has an attestation signed already, or
    #   (c) the coder explicitly took the force-accept path with a valid
    #       MRN re-entry + >=20 char reason.
    suspect_meat_ok = False
    suspect_mrn_last4 = None
    suspect_mrn_full = None
    try:
        with raf_cursor() as _meat_cur:
            _meat_cur.execute(
                """
                SELECT sc.evidence_detail,
                       sc.reviewed_at  AS attestation_signed_at,
                       p.mrn           AS mrn
                  FROM raf_suspect_conditions sc
                  JOIN patients p ON p.id = sc.patient_id
                 WHERE sc.id = %s
                   AND sc.patient_id = %s
                """,
                (body.suspect_id, pid),
            )
            _suspect_row = _meat_cur.fetchone()
        if _suspect_row:
            import json as _json
            _ed = _suspect_row.get("evidence_detail")
            if isinstance(_ed, (bytes, bytearray)):
                _ed = _ed.decode("utf-8", errors="ignore")
            if isinstance(_ed, str):
                try:
                    _ed = _json.loads(_ed)
                except Exception:
                    _ed = {}
            _meat_completeness = (_ed or {}).get("meat_completeness") if isinstance(_ed, dict) else None
            _meat_status = (_ed or {}).get("meat_status") if isinstance(_ed, dict) else None
            _attested = _suspect_row.get("attestation_signed_at") is not None
            _mrn = str(_suspect_row.get("mrn") or "").strip()
            suspect_mrn_full = _mrn
            suspect_mrn_last4 = _mrn[-4:] if _mrn else None
            suspect_meat_ok = bool(
                _attested
                or (_meat_completeness is not None and float(_meat_completeness or 0) > 0)
                or (_meat_status and str(_meat_status).lower() not in {"missing", "none", "empty"})
            )
    except Exception as _meat_exc:
        # Fail closed: if we can't determine MEAT status, block the accept
        # unless force_no_meat path was used. This prevents a transient DB
        # error from becoming a billing/RADV escape.
        logger.warning("MEAT gate lookup failed for suspect %s: %s", body.suspect_id, _meat_exc)
        suspect_meat_ok = False

    if not suspect_meat_ok:
        if not body.force_no_meat:
            raise HTTPException(
                status_code=403,
                detail=(
                    "MEAT evidence missing — use the Force Accept path "
                    "(force_no_meat=true) with mrn_confirmation and "
                    "override_reason (>=20 chars) to attest RADV risk."
                ),
            )
        # Validate the force-accept attestation.
        _reason = (body.override_reason or "").strip()
        if len(_reason) < 20:
            raise HTTPException(
                status_code=422,
                detail="override_reason must be at least 20 non-whitespace characters",
            )
        _mrn_in = (body.mrn_confirmation or "").strip()
        # Accept any of: full MRN, last-4 of MRN, or the patient pid (used
        # when MRN is blank in the underlying EMR — verified true for some
        # seeded OpenEMR rows where patient_data.pubpid is empty).
        _accepted_tokens = {t for t in (suspect_mrn_full, suspect_mrn_last4, str(pid)) if t}
        if not _mrn_in or _mrn_in not in _accepted_tokens:
            raise HTTPException(
                status_code=422,
                detail="mrn_confirmation does not match the patient's MRN, last-4, or pid",
            )
        # Emit the force-accept audit BEFORE the mutation so a downstream
        # write failure still leaves the attestation visible in the log.
        import hashlib as _hashlib
        try:
            from app.services.immutable_audit import emit_audit_event
            emit_audit_event(
                "SUSPECT_FORCE_ACCEPTED_NO_MEAT",
                tenant_id=tenant_id,
                actor_user_id=reviewer_user_id,
                subject_type="suspect",
                subject_id=str(body.suspect_id),
                payload={
                    "patient_id": pid,
                    "override_reason": _reason,
                    "mrn_confirmation_hash": _hashlib.sha256(_mrn_in.encode()).hexdigest()[:16],
                },
            )
        except Exception as _audit_exc:
            logger.error("force-accept audit emit failed: %s", _audit_exc)

    result = accept_suspect(body.suspect_id, reviewed_by=reviewer, tenant_id=tenant_id,
                            reviewed_by_user_id=reviewer_user_id)

    # NLP write-back confidence gate — Patient Safety round-2 fix.
    # If the suspect was produced by NLP and its confidence is below
    # NLP_MIN_CONFIDENCE_WRITEBACK (0.85), block the EMR write-back unless
    # meat_signed=true (credentialed clinician attestation).
    if body.push_to_emr:
        _suspect_source = str(result.get("evidence_type") or result.get("source") or "").lower()
        _suspect_confidence = None
        try:
            _suspect_confidence = float(result.get("confidence") or 1.0)
        except (TypeError, ValueError):
            _suspect_confidence = 1.0
        _is_nlp_source = _suspect_source in {"nlp", "note_nlp"}
        if _is_nlp_source:
            from app.services.nlp_suspect_extractor import NLP_MIN_CONFIDENCE_WRITEBACK as _NLP_WB
            if _suspect_confidence < _NLP_WB and not body.meat_signed:
                try:
                    from app.services.immutable_audit import emit_audit_event
                    emit_audit_event(
                        "NLP_WRITEBACK_BLOCKED_LOW_CONFIDENCE",
                        tenant_id=tenant_id,
                        actor_user_id=reviewer_user_id,
                        subject_type="suspect",
                        subject_id=str(body.suspect_id),
                        payload={
                            "suspect_id": body.suspect_id,
                            "confidence": _suspect_confidence,
                            "threshold": _NLP_WB,
                            "patient_id": pid,
                        },
                    )
                except Exception as _audit_exc:
                    logger.error("NLP_WRITEBACK_BLOCKED audit emit failed: %s", _audit_exc)
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "NLP suspect below write-back confidence threshold (0.85). "
                        "Require clinician attestation or higher-confidence evidence."
                    ),
                )

    # EMR write-back: push the accepted ICD to OpenEMR's Problem List.
    # Preferred path is FHIR (works for any R4 server including Epic/Cerner).
    # On failure, fall back to the legacy direct-MySQL ``push_medical_problem``
    # so the demo keeps working even when the FHIR endpoint is unreachable.
    pushed = False
    fhir_condition_id: str | None = None
    fhir_reconciled: bool | None = None
    push_method: str = "none"

    audit_source = (
        "raf_intelligence_force_accept" if body.force else "raf_intelligence_normal_accept"
    )

    if body.push_to_emr:
        suspect_icd = str(result.get("suspect_icd10") or "")
        suspect_label = _hcc_label(str(result.get("suspect_hcc") or ""))
        if suspect_icd:
            # --- FHIR write (preferred) ---
            try:
                fhir_condition_id = push_problem_list_condition(
                    patient_emr_pid=str(pid),
                    icd10_code=suspect_icd,
                    hcc_label=suspect_label,
                    source={
                        "suspect_id": body.suspect_id,
                        "source": audit_source,
                    },
                    tenant_id=tenant_id,
                )
                pushed = True
                push_method = "fhir"
            except Exception as exc:
                logger.warning(
                    "FHIR Condition write failed for pid=%s icd=%s: %s — "
                    "retrying once before MySQL fallback",
                    pid,
                    suspect_icd,
                    exc,
                )
                try:
                    fhir_condition_id = push_problem_list_condition(
                        patient_emr_pid=str(pid),
                        icd10_code=suspect_icd,
                        hcc_label=suspect_label,
                        source={
                            "suspect_id": body.suspect_id,
                            "source": audit_source,
                        },
                        tenant_id=tenant_id,
                    )
                    pushed = True
                    push_method = "fhir"
                except Exception as exc2:
                    logger.warning(
                        "FHIR Condition retry failed for pid=%s icd=%s: %s — "
                        "using direct-MySQL fallback",
                        pid,
                        suspect_icd,
                        exc2,
                    )
                    pushed = push_medical_problem(pid, suspect_label, suspect_icd)
                    push_method = (
                        "fhir_then_mysql_fallback" if pushed else "fhir_then_failed"
                    )

            # --- Audit + reconcile, only if we have a FHIR id ---
            if fhir_condition_id:
                try:
                    emit_audit_event(
                        "SUSPECT_PUSHED_TO_EHR_VIA_FHIR",
                        tenant_id=tenant_id,
                        actor_user_id=reviewer_user_id,
                        subject_type="patient",
                        subject_id=pid,
                        payload={
                            "patient_pid": pid,
                            "icd10": suspect_icd,
                            "hcc": str(result.get("suspect_hcc") or ""),
                            "hcc_label": suspect_label,
                            "fhir_condition_id": fhir_condition_id,
                            "source": audit_source,
                            "suspect_id": body.suspect_id,
                        },
                    )
                except Exception as audit_exc:
                    logger.warning(
                        "SUSPECT_PUSHED_TO_EHR_VIA_FHIR audit emit failed: %s",
                        audit_exc,
                    )

                # Reconcile: confirm the new code is now on the FHIR Problem List
                try:
                    fhir_reconciled = reconcile_condition(
                        patient_emr_pid=str(pid),
                        icd10_code=suspect_icd,
                        tenant_id=tenant_id,
                    )
                except Exception as rec_exc:
                    logger.warning(
                        "FHIR reconcile error for pid=%s icd=%s: %s",
                        pid,
                        suspect_icd,
                        rec_exc,
                    )
                    fhir_reconciled = False

                if fhir_reconciled is False:
                    try:
                        emit_audit_event(
                            "SUSPECT_FHIR_RECONCILE_MISMATCH",
                            tenant_id=tenant_id,
                            actor_user_id=reviewer_user_id,
                            subject_type="patient",
                            subject_id=pid,
                            payload={
                                "patient_pid": pid,
                                "icd10": suspect_icd,
                                "fhir_condition_id": fhir_condition_id,
                                "source": audit_source,
                                "suspect_id": body.suspect_id,
                                "note": (
                                    "Condition was POSTed successfully but a "
                                    "follow-up GET /Condition?subject=Patient/{pid} "
                                    "did not return the new ICD-10 code."
                                ),
                            },
                        )
                    except Exception as audit_exc2:
                        logger.warning(
                            "SUSPECT_FHIR_RECONCILE_MISMATCH audit emit failed: %s",
                            audit_exc2,
                        )
        else:
            logger.info(
                "Skipping EMR write-back for suspect=%s: no ICD-10 on result",
                body.suspect_id,
            )

    _invalidate_panel_cache(pid, tenant_id)
    accept_response = AcceptSuspectResponse(
        ok=True,
        suspect=result,
        pushed_to_emr=pushed,
        fhir_condition_id=fhir_condition_id,
        fhir_reconciled=fhir_reconciled,
        push_method=push_method,
    )
    store_idempotent_response(request, response, accept_response.model_dump())
    return accept_response


@router.post("/{pid}/actions/dismiss-suspect", response_model=DismissSuspectResponse)
def action_dismiss_suspect(
    pid: int,
    body: DismissSuspectRequest,
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
    _idem: None = Depends(idempotency_key_dependency()),
) -> DismissSuspectResponse:
    """Dismiss a suspect HCC condition with an optional reason.

    Supports Idempotency-Key header (24h replay window).
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"
    result = dismiss_suspect(
        body.suspect_id,
        reason=body.reason,
        reviewed_by=reviewer,
        tenant_id=tenant_id,
        reviewed_by_user_id=reviewer_user_id,
    )
    _invalidate_panel_cache(pid, tenant_id)
    dismiss_resp = DismissSuspectResponse(ok=True, suspect=result)
    store_idempotent_response(request, response, dismiss_resp.model_dump())
    return dismiss_resp


@router.post("/{pid}/actions/restore-suspect", response_model=RestoreSuspectResponse)
def action_restore_suspect(
    pid: int,
    body: RestoreSuspectRequest,
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
    _idem: None = Depends(idempotency_key_dependency()),
) -> RestoreSuspectResponse:
    """Restore a previously dismissed suspect back to ``status='open'``.

    Backs the "Restore" action button on the dismiss-success toast. Mirrors
    the ``action_dismiss_suspect`` contract: tenant guard, patient access
    check, panel cache invalidation, and Idempotency-Key support (24h replay
    window).  Emits an immutable ``SUSPECT_RESTORED`` audit event so the
    chain shows dismiss → restore as two linked operations.
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

    _uid = current_user.get("id")
    reviewer_user_id: int | None = int(_uid) if _uid is not None else None
    reviewer = current_user.get("email") or current_user.get("sub") or "raf-central"

    try:
        result = restore_suspect(
            body.suspect_id,
            reason=body.reason,
            reviewed_by=reviewer,
            tenant_id=tenant_id,
            reviewed_by_user_id=reviewer_user_id,
        )
    except ValueError as exc:
        # Either the suspect doesn't exist, belongs to another tenant, or is
        # not currently dismissed.  Surface as 404 — never reveal whether a
        # row exists in a different tenant scope.
        raise HTTPException(status_code=404, detail=str(exc))

    _invalidate_panel_cache(pid, tenant_id)

    # Immutable audit event — non-fatal if it fails so the user-facing
    # restore still succeeds (consistent with the audit-emit pattern used by
    # accept_suspect_endpoint in routers/suspects.py).
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            "SUSPECT_RESTORED",
            tenant_id=tenant_id,
            actor_user_id=reviewer_user_id,
            subject_type="suspect",
            subject_id=str(body.suspect_id),
            payload={
                "patient_id": pid,
                "reason": (body.reason or "").strip() or None,
                "actor_email": current_user.get("email") or "unknown",
            },
        )
    except Exception as exc:
        logger.warning(
            "action_restore_suspect: immutable audit emit failed for "
            "SUSPECT_RESTORED suspect_id=%s: %s",
            body.suspect_id, exc,
        )

    restore_resp = RestoreSuspectResponse(ok=True, suspect=result)
    store_idempotent_response(request, response, restore_resp.model_dump())
    return restore_resp


@router.post("/{pid}/actions/mark-meat-reviewed", response_model=MarkMEATReviewedResponse)
def action_mark_meat_reviewed(
    pid: int,
    body: MarkMEATReviewedRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> MarkMEATReviewedResponse:
    """Insert a raf_meat_evidence row and bump patient_hcc.meat_status.

    This is the endpoint backing the "Mark Reviewed" button in the MEAT
    card. It does NOT write to OpenEMR — MEAT evidence is our-side audit
    documentation, not EMR content.
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

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
                    (patient_hcc_id, encounter_date, encounter_id,
                     meat_m, meat_e, meat_a, meat_t,
                     meat_m_present, meat_e_present, meat_a_present, meat_t_present,
                     completeness_score)
                VALUES (%s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    body.patient_hcc_id, today,
                    body.monitor_note, body.evaluate_note, body.assess_note, body.treat_note,
                    1 if body.monitor_note else 0,
                    1 if body.evaluate_note else 0,
                    1 if body.assess_note else 0,
                    1 if body.treat_note else 0,
                    sum(1 for n in (body.monitor_note, body.evaluate_note, body.assess_note, body.treat_note) if n) / 4.0,
                ),
            )
            # Roll up status from ALL evidence rows for this HCC so previously
            # documented letters (from earlier encounters) are not lost. A letter
            # is considered documented if ANY row has a non-null note for it.
            # COALESCE handles both schema shapes (modern *_present flags + the
            # raw text columns) so this query survives schema drift.
            cur.execute(
                """
                SELECT
                    MAX(COALESCE(meat_m_present, CASE WHEN meat_m IS NOT NULL AND meat_m <> '' THEN 1 ELSE 0 END)) AS m,
                    MAX(COALESCE(meat_e_present, CASE WHEN meat_e IS NOT NULL AND meat_e <> '' THEN 1 ELSE 0 END)) AS e,
                    MAX(COALESCE(meat_a_present, CASE WHEN meat_a IS NOT NULL AND meat_a <> '' THEN 1 ELSE 0 END)) AS a,
                    MAX(COALESCE(meat_t_present, CASE WHEN meat_t IS NOT NULL AND meat_t <> '' THEN 1 ELSE 0 END)) AS t
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
        raise HTTPException(status_code=500, detail="MEAT write failed")

    _invalidate_panel_cache(pid, tenant_id)
    return MarkMEATReviewedResponse(ok=True, meat_status=status, reviewed_by=reviewer)


@router.post("/{pid}/actions/add-assessment-note", response_model=AddAssessmentNoteResponse)
def action_add_assessment_note(
    pid: int,
    body: AddAssessmentNoteRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> AddAssessmentNoteResponse:
    """Append clinician-authored assessment text to the current encounter's
    SOAP note. Falls back to inserting a new `form_soap` row when no
    encounter_id is provided.
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

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
        raise HTTPException(status_code=500, detail="EMR note write failed")

    _invalidate_panel_cache(pid, tenant_id)
    return AddAssessmentNoteResponse(ok=True, encounter_id=body.encounter_id, author=reviewer)


@router.post("/{pid}/actions/upgrade-code", response_model=UpgradeCodeResponse)
def action_upgrade_code(
    pid: int,
    body: UpgradeCodeRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> UpgradeCodeResponse:
    """Replace a less-specific ICD on an encounter's billing row with a
    more-specific one. Updates OpenEMR `billing.code` + `code_text`.
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

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
        raise HTTPException(status_code=500, detail="code upgrade failed")

    if affected == 0:
        raise HTTPException(
            status_code=404,
            detail=f"no matching billing row for encounter={body.encounter_id} code={body.from_icd10}",
        )

    _invalidate_panel_cache(pid, tenant_id)
    return UpgradeCodeResponse(ok=True, rows_updated=affected)


@router.post("/{pid}/actions/recalculate", response_model=RecalculateResponse)
def action_recalculate(
    pid: int,
    year: int | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> RecalculateResponse:
    """Force a full RAF recalc for this patient (drops caches, re-runs the
    engine, persists the new score). Use after a writeback action to
    surface the new RAF value in the panel.
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

    measurement_year = year or date.today().year
    _invalidate_panel_cache(pid, tenant_id)

    result = calculate_raf_score(
        patient_id=pid,
        measurement_year=measurement_year,
        tenant_id=tenant_id,
    )
    return RecalculateResponse(
        ok=True,
        raf_score=float(result.get("raf_score") or 0.0),
        hcc_count=int(result.get("hcc_count") or 0),
        model_segment=result.get("model_segment"),
        measurement_year=measurement_year,
    )


@router.post(
    "/{pid}/actions/enrich-suspects",
    response_model=EnrichSuspectsResponse,
)
def action_enrich_suspects(
    pid: int,
    year: int | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> EnrichSuspectsResponse:
    """Recompute and persist ``meat_completeness`` and ``trumped_by_hcc``
    onto every open suspect row for this patient.

    Necessary because the suspect engine writes rows before the MEAT
    extractor has populated ``raf_meat_evidence`` for the year, which
    leaves the panel's MEAT-aware sort and trumped-badge unlit on
    production data. The scan hook in
    :func:`run_full_suspect_scan` already calls the same service, but
    this endpoint exists for manual re-enrichment (e.g. after a MEAT
    refresh or hierarchy-rules update without re-running the full scan).
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

    measurement_year = year or date.today().year

    from app.services.suspect_enrichment import enrich_suspects_for_patient

    try:
        n = enrich_suspects_for_patient(pid, tenant_id, year=measurement_year)
    except Exception as exc:
        logger.exception("enrich-suspects failed pid=%s tenant=%s", pid, tenant_id)
        raise HTTPException(
            status_code=500,
            detail=f"Suspect enrichment failed: {exc}",
        )

    # Invalidate the panel cache so the very next GET /api/raf-central/{pid}
    # reads the freshly-enriched evidence_detail. Without this the UI would
    # keep showing "Net-new" until the cache TTL expired.
    _invalidate_panel_cache(pid, tenant_id)

    return EnrichSuspectsResponse(
        ok=True,
        enriched=n,
        measurement_year=measurement_year,
    )


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


@router.post("/{pid}/actions/start-treatment", response_model=StartTreatmentResponse)
def action_start_treatment(
    pid: int,
    body: StartTreatmentRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> StartTreatmentResponse:
    """Write a new prescription into OpenEMR to satisfy a MEAT-Treatment gap."""
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

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

    return StartTreatmentResponse(status="ok", prescription_id=int(rx_id), drug=drug)


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


@router.post("/{pid}/actions/order-lab", response_model=OrderLabResponse)
def action_order_lab(
    pid: int,
    body: OrderLabRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> OrderLabResponse:
    """Place a lab order in OpenEMR to close a MEAT 'Monitoring' gap."""
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

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
        raise HTTPException(status_code=500, detail="order-lab write failed")

    if order_id is None:
        from app.db import NoActiveEMRConnection  # local import — avoid cycle
        try:
            with openemr_cursor() as _cur:
                pass
        except NoActiveEMRConnection:
            return OrderLabResponse(
                status="skipped",
                reason="no emr configured",
                suggested_lab_code=lab_code,
            )
        except Exception as e:
            logger.warning(
                "order-lab emr precheck failed pid=%s: %s",
                pid, e, exc_info=True,
            )
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
    return OrderLabResponse(
        status="ok",
        procedure_order_id=int(order_id),
        suggested_lab_code=lab_code,
    )


# ---------------------------------------------------------------------------
# Why? — explainability drill-down for a single suspect
# ---------------------------------------------------------------------------


class ContributingSignal(BaseModel):
    source: Literal["medication", "lab", "history", "nlp", "note", "other"]
    label: str
    value: str | None = None
    timestamp: str | None = None


class ClinicalRuleAdjustment(BaseModel):
    rule_id: str
    rule_name: str
    explanation: str
    confidence_delta: float
    failed: bool


class ExplainResponse(BaseModel):
    suspect_id: int
    patient_id: int
    suspect_icd10: str
    suspect_hcc: str
    confidence: float
    evidence_type: str
    contributing_signals: list[ContributingSignal]
    summary: str
    # Optional drill-down fields read by frontend ExplainPanel. When the
    # backend has no data for a given suspect these stay None / empty and
    # the corresponding UI section renders nothing (was silently dead UI
    # before — frontend declared the fields but backend never returned
    # them, so the "stale evidence" / "negated/hypothetical" / "clinical-
    # rule adjustments" panels never appeared).
    clinical_rule_adjustments: list[ClinicalRuleAdjustment] | None = None
    context_classification: str | None = None
    evidence_date: str | None = None


def _parse_evidence_detail_raw(evidence_detail: Any) -> Any:
    """Return the parsed Python representation of evidence_detail (dict / list
    / str) regardless of whether it was stored as a JSON string, bytes, or
    already-decoded structure. Returns ``None`` when input is empty.
    Centralised so the explain endpoint can read both contributing signals
    AND drill-down fields (context, evidence_date, rule adjustments) from a
    single parse pass.
    """
    import json as _json

    if evidence_detail in (None, "", "null"):
        return None
    raw: Any = evidence_detail
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            return _json.loads(raw)
        except Exception:
            return raw
    return raw


def _extract_context_classification(raw: Any) -> str | None:
    """Pull the ConText classification (negated / hypothetical / historical /
    family / resolved / positive) from the evidence_detail blob. The clinical
    NLP layer writes this under one of several keys depending on which engine
    produced the suspect. Returns ``None`` when no context flag is recorded —
    callers MUST treat None as "unknown", NOT "positive"."""
    if not isinstance(raw, dict):
        return None
    for key in ("context_classification", "context", "polarity", "modifier"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            v = val.strip().lower()
            # Normalise to the literal frontend ExplainPanel expects.
            mapping = {
                "neg": "negated",
                "negation": "negated",
                "negated": "negated",
                "hist": "historical",
                "history": "historical",
                "historical": "historical",
                "hypo": "hypothetical",
                "hypothetical": "hypothetical",
                "family": "family",
                "family_history": "family",
                "fhx": "family",
                "resolved": "resolved",
                "positive": "positive",
                "current": "positive",
            }
            return mapping.get(v, v)
    return None


def _extract_evidence_date(raw: Any) -> str | None:
    """Find the most recent ISO-8601 date in the evidence_detail blob so the
    UI can render the stale-evidence banner. Walks common keys without
    assuming a particular shape (each engine writes a slightly different
    layout)."""
    if raw is None:
        return None
    candidates: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                lk = k.lower() if isinstance(k, str) else ""
                if lk in ("date", "evidence_date", "encounter_date", "service_date",
                          "specimen_date", "collected_at", "timestamp", "ts",
                          "last_seen", "observed_at"):
                    if isinstance(v, str) and v.strip():
                        candidates.append(v.strip())
                elif isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(node, list):
            for it in node:
                _walk(it)

    _walk(raw)
    if not candidates:
        return None
    # Prefer the lexicographically maximum (ISO-8601 dates sort correctly).
    # Drop obviously non-ISO entries (length < 4) and pick the newest.
    iso = [c for c in candidates if len(c) >= 4]
    if not iso:
        return None
    return max(iso)


def _extract_clinical_rule_adjustments(raw: Any) -> list["ClinicalRuleAdjustment"]:
    """Pull rule adjustments (e.g. 'eGFR > 60 → downgrade CKD suspect') from
    the evidence_detail blob if the engine recorded them. Empty list when
    the suspect was emitted without rule introspection (most legacy rows)."""
    if not isinstance(raw, dict):
        return []
    adjustments = (
        raw.get("clinical_rule_adjustments")
        or raw.get("rule_adjustments")
        or raw.get("rules")
        or []
    )
    if not isinstance(adjustments, list):
        return []
    out: list[ClinicalRuleAdjustment] = []
    for entry in adjustments:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                ClinicalRuleAdjustment(
                    rule_id=str(entry.get("rule_id") or entry.get("id") or ""),
                    rule_name=str(entry.get("rule_name") or entry.get("name") or ""),
                    explanation=str(entry.get("explanation") or entry.get("reason") or ""),
                    confidence_delta=float(entry.get("confidence_delta") or entry.get("delta") or 0.0),
                    failed=bool(entry.get("failed")),
                )
            )
        except (ValueError, TypeError):
            continue
    return out


def _decompose_evidence_detail(
    evidence_detail: Any,
    evidence_type: str,
) -> list[ContributingSignal]:
    """Best-effort parse of raf_suspect_conditions.evidence_detail JSON into
    a typed list of ContributingSignal rows. The blob shape varies per
    engine (meds/labs/history/nlp) — we accept a few common layouts.
    """
    raw = _parse_evidence_detail_raw(evidence_detail)
    if raw is None:
        return []
    if isinstance(raw, str):
        # Was non-JSON string — surface as single "other" signal.
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
            # Label resolution: prefer named fields. When the entire dict is
            # a single-key wrapper like {"detail": "..."} or {"summary": "..."}
            # walk into that single value rather than stringifying the dict
            # (the prior `str(item)[:120]` fallback produced ugly drawer rows
            # like `{'detail': 'eGFR declined fro` — PCP-review #3).
            label = (
                item.get("label")
                or item.get("name")
                or item.get("drug")
                or item.get("medication")
                or item.get("test")
                or item.get("code")
                or item.get("icd")
                or item.get("snippet")
                or item.get("detail")
                or item.get("description")
                or item.get("summary")
                or item.get("text")
                or src_as_label
            )
            if label is None:
                # Last resort: surface a single readable string value from
                # the dict, not the dict's repr.
                str_vals = [str(v) for v in item.values() if isinstance(v, (str, int, float))]
                label = str_vals[0] if str_vals else "(no detail)"
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
    _require_patient_access(pid, tenant_id, current_user=current_user)

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

    raw_blob = _parse_evidence_detail_raw(row.get("evidence_detail"))
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

    # Populate the three RADV-critical drill-down fields the frontend
    # ExplainPanel already renders banners for. Before this wiring the panel
    # silently dropped negated-evidence warnings, stale-evidence warnings,
    # and rule-adjustment chips — see patient-safety review findings #1, #3,
    # and #7. None of these are required (older suspects predate the engine
    # writing them), so they stay nullable in the schema.
    return ExplainResponse(
        suspect_id=int(row["id"]),
        patient_id=int(row["patient_id"]),
        suspect_icd10=str(row.get("suspect_icd10") or ""),
        suspect_hcc=str(row.get("suspect_hcc") or ""),
        confidence=float(row.get("confidence_score") or 0.0),
        evidence_type=str(row.get("evidence_type") or ""),
        contributing_signals=signals,
        summary=summary,
        context_classification=_extract_context_classification(raw_blob),
        evidence_date=_extract_evidence_date(raw_blob),
        clinical_rule_adjustments=_extract_clinical_rule_adjustments(raw_blob) or None,
    )


# ---------------------------------------------------------------------------
# Refresh MEAT — rule-based extractor across all notes for this patient
# ---------------------------------------------------------------------------

class RefreshMEATRequest(BaseModel):
    max_days_lookback: int = 365
    year: int | None = None


@router.post("/{pid}/actions/refresh-meat", status_code=202, response_model=RefreshMEATResponse)
def action_refresh_meat(
    pid: int,
    body: RefreshMEATRequest | None = None,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "write")),
) -> RefreshMEATResponse:
    """Enqueue MEAT extraction for this patient as a background Celery task.

    Returns HTTP 202 immediately with ``{status: "queued", job_id: <task_id>}``
    so the request completes in milliseconds instead of blocking for the
    multi-second MEAT extraction run.

    Polling follow-up (frontend concern):
        The frontend should poll ``GET /api/jobs/{job_id}`` until the job
        reaches SUCCEEDED/FAILED status, then refresh the RAF Central panel
        (``GET /api/raf-central/{pid}``) to reflect the updated MEAT evidence.
        This is tracked separately in the frontend backlog.

    Previously this endpoint ran ``run_auto_meat_for_patient`` synchronously
    in the request path, which could take 5–30 seconds for patients with many
    notes and HCCs, blocking a FastAPI threadpool worker for the full duration.
    """
    tenant_id = current_user.get("tenant_id")
    _require_patient_access(pid, tenant_id, current_user=current_user)

    req = body or RefreshMEATRequest()
    try:
        task = task_refresh_meat_for_patient.apply_async(
            kwargs={
                "tenant_id": tenant_id,
                "patient_id": pid,
                "year": req.year,
                "max_days_lookback": req.max_days_lookback,
            },
            queue="default",
        )
    except Exception as exc:
        logger.exception("refresh-meat enqueue failed pid=%s", pid)
        raise HTTPException(status_code=500, detail="Failed to enqueue MEAT refresh")

    logger.info(
        "refresh-meat: enqueued task_id=%s pid=%s tenant=%s year=%s",
        task.id, pid, tenant_id, req.year,
    )
    return RefreshMEATResponse(status="queued", job_id=task.id)
