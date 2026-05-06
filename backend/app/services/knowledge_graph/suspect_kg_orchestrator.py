"""
Suspect KG Orchestrator — KG-first suspect detection with LLM augmentation.

Pipeline (per patient, per measurement year):

    1. KG deterministic pass:
       kg_lookup_service.patient_full_inference(patient_id) returns HCC
       candidates with the full evidence chain (rules, comorbidities,
       drug-class signals, lab signals, specialty routing).

    2. Suspect persistence:
       Each KG candidate is upserted to raf_suspect_conditions, tagged
       with one of evidence_type IN
           ('kg_rule', 'kg_comorbidity', 'kg_drug_class',
            'kg_lab_signal', 'kg_specialty')
       and the full reasoning chain serialised into evidence_detail
       (stored as TEXT JSON, per the schema constraint in the task).

    3. LLM augmentation:
       For chart text the KG could not classify decisively, the existing
       Gemini suspect path is invoked.  KG candidates are passed to it as
       CONTEXT — Gemini's job becomes "verify + find additional", not
       "find from scratch".  Pure-LLM finds are tagged 'llm'.

    4. Conflict resolution:
       If KG and LLM both fire on the same (patient, year, hcc), KG's
       deterministic citation is kept primary and the LLM-derived chart
       quote is appended into evidence_detail.llm_corroboration.

    5. Calibration:
       Demographic (age + sex + dual-eligibility) and provider-specialty
       multipliers are applied to produce final_confidence.

Graceful degradation
--------------------
None of the sibling KG primitives is imported at module top-level.  Each
phase is wrapped in try/except so a missing kg_lookup_service module
falls through to legacy detection cleanly with a structured warning log
— never a crash.

Public API
----------
    run_kg_first_detection(patient_id, year=2026, tenant_id=1) -> list[dict]
        Full pipeline.  Returns persisted suspects with audit chain.

    get_evidence_chain(suspect_id) -> dict
        Reconstruct the KG attribution chain for a single suspect.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterable

from app.db import raf_cursor
from app.services.knowledge_graph import calibration_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence-type tags
# ---------------------------------------------------------------------------

KG_EVIDENCE_TYPES: tuple[str, ...] = (
    "kg_rule",
    "kg_comorbidity",
    "kg_drug_class",
    "kg_lab_signal",
    "kg_specialty",
)

LEGACY_EVIDENCE_TYPES: tuple[str, ...] = (
    "lab_legacy",
    "rx_legacy",
)

LLM_EVIDENCE_TYPE: str = "llm"

ALL_EVIDENCE_TYPES: tuple[str, ...] = (
    *KG_EVIDENCE_TYPES,
    LLM_EVIDENCE_TYPE,
    *LEGACY_EVIDENCE_TYPES,
)


# ---------------------------------------------------------------------------
# Sibling-service shims (lazy + defensive)
# ---------------------------------------------------------------------------

def _kg_lookup_service():
    """
    Return the sibling kg_lookup_service module if it is installed in
    this worktree.  Returns None when missing — caller must fall back.
    """
    try:
        from app.services.knowledge_graph import kg_lookup_service  # type: ignore
        return kg_lookup_service
    except Exception as exc:  # pragma: no cover — degradation path
        logger.warning("kg_lookup_service unavailable: %s", exc)
        return None


def _drug_class_reasoner():
    try:
        from app.services.knowledge_graph import drug_class_reasoner  # type: ignore
        return drug_class_reasoner
    except Exception as exc:  # pragma: no cover
        logger.warning("drug_class_reasoner unavailable: %s", exc)
        return None


def _specialty_router():
    try:
        from app.services.knowledge_graph import specialty_router  # type: ignore
        return specialty_router
    except Exception as exc:  # pragma: no cover
        logger.warning("specialty_router unavailable: %s", exc)
        return None


def _gemini_suspect_runner():
    """
    Return a callable that yields LLM-derived suspect candidates given
    chart text + KG context.  Adapts to whichever module name the
    Gemini pipeline currently lives under.
    """
    for mod_path in (
        "app.services.ai_pipeline.ai_suspect_pipeline",
        "app.services.skill_pipeline",
        "app.services._legacy.gemini_service",
    ):
        try:
            mod = __import__(mod_path, fromlist=["*"])
        except Exception:
            continue
        for fn_name in (
            "run_kg_assisted_suspect_pass",
            "run_suspect_pass",
            "run_pipeline",
        ):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                return fn, mod_path, fn_name
    return None, None, None


# ---------------------------------------------------------------------------
# Demographic + specialty calibration tables
# ---------------------------------------------------------------------------

# Coarse multipliers applied to the KG's raw confidence.  These are
# intentionally conservative: the KG already does most of the heavy
# lifting (rule + comorbidity priors).  The job here is small nudges
# based on patient + provider context.

_DEMOGRAPHIC_RULES = (
    # Dual-eligible elderly women have substantially higher CKD priors
    {
        "match": lambda d: (
            (d.get("age") or 0) >= 75
            and (d.get("sex") or "").upper().startswith("F")
            and bool(d.get("dual_eligible"))
        ),
        "hcc_prefix": ("CKD", "HCC32", "HCC326", "HCC327", "HCC329"),
        "multiplier": 1.4,
        "reason": "Elderly female + dual-eligible → CKD prior boost",
    },
    {
        "match": lambda d: (d.get("age") or 0) >= 65 and bool(d.get("dual_eligible")),
        "hcc_prefix": ("HCC18", "HCC19", "HCC37", "HCC38"),
        "multiplier": 1.2,
        "reason": "Senior + dual-eligible → DM/CKD prior boost",
    },
    {
        "match": lambda d: (
            d.get("age") is not None and 0 < int(d.get("age") or 0) < 50
        ),
        "hcc_prefix": ("HCC85", "HCC86", "HCC87", "HCC88"),  # CHF group
        "multiplier": 0.85,
        "reason": "Younger patient → CHF prior dampened",
    },
)

_SPECIALTY_RULES = {
    # provider specialty (lower-cased) → {hcc_prefix: multiplier}
    "cardiology":     {"hcc_prefix": ("HCC85", "HCC86", "HCC87", "HCC88", "HCC96"), "multiplier": 1.25},
    "cardiologist":   {"hcc_prefix": ("HCC85", "HCC86", "HCC87", "HCC88", "HCC96"), "multiplier": 1.25},
    "nephrology":     {"hcc_prefix": ("HCC326", "HCC327", "HCC329", "HCC32"),       "multiplier": 1.30},
    "endocrinology":  {"hcc_prefix": ("HCC18", "HCC19", "HCC37", "HCC38"),          "multiplier": 1.20},
    "psychiatry":     {"hcc_prefix": ("HCC151", "HCC152", "HCC155"),                 "multiplier": 1.20},
    "oncology":       {"hcc_prefix": ("HCC11", "HCC12", "HCC17"),                    "multiplier": 1.15},
}


# ---------------------------------------------------------------------------
# Public API — run_kg_first_detection
# ---------------------------------------------------------------------------

def run_kg_first_detection(
    patient_id: int,
    year: int = 2026,
    tenant_id: int = 1,
    *,
    chart_text: str | None = None,
    patient_demographics: dict[str, Any] | None = None,
    provider_specialty: str | None = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """
    Run the full KG-first → LLM-augmentation pipeline for *patient_id*.

    Returns
    -------
    list[dict]
        Each entry contains the merged candidate plus a fully-populated
        ``evidence_detail`` audit-chain dict.  When *persist* is True the
        candidates are upserted into raf_suspect_conditions and the
        returned dict's ``id`` field is set.
    """
    logger.info(
        "run_kg_first_detection start patient_id=%s year=%s tenant_id=%s",
        patient_id, year, tenant_id,
    )

    # 1. KG deterministic pass -------------------------------------------
    kg_candidates = _kg_pass(patient_id, year)

    # 2. LLM augmentation (verify + find additional) ---------------------
    llm_candidates = _llm_pass(
        patient_id=patient_id,
        chart_text=chart_text,
        kg_candidates=kg_candidates,
    )

    # 3. Conflict resolution ---------------------------------------------
    merged = _merge_kg_and_llm(kg_candidates, llm_candidates)

    # 4. Calibration ------------------------------------------------------
    demo = patient_demographics or _load_demographics(patient_id, year)
    specialty = provider_specialty or demo.get("provider_specialty")
    calibrated = [
        _apply_calibration(c, demo, specialty)
        for c in merged
    ]

    # 5. Persist ---------------------------------------------------------
    if persist:
        _persist_suspects(calibrated, patient_id=patient_id, year=year, tenant_id=tenant_id)

    logger.info(
        "run_kg_first_detection done patient_id=%s kg=%d llm=%d merged=%d",
        patient_id, len(kg_candidates), len(llm_candidates), len(calibrated),
    )
    return calibrated


# ---------------------------------------------------------------------------
# Phase 1 — KG deterministic pass
# ---------------------------------------------------------------------------

def _kg_pass(patient_id: int, year: int) -> list[dict[str, Any]]:
    """
    Call the sibling kg_lookup_service.patient_full_inference and
    normalise the result into orchestrator-shaped candidates.

    Each output candidate has::

        {
            "suspect_hcc":   "HCC18",
            "suspect_icd10": "E11.65",
            "evidence_type": "kg_rule" | "kg_comorbidity" | ...,
            "raw_confidence": 0.82,
            "evidence_detail": {<full chain>},
        }
    """
    svc = _kg_lookup_service()
    if svc is None or not hasattr(svc, "patient_full_inference"):
        logger.info(
            "_kg_pass: kg_lookup_service.patient_full_inference unavailable; "
            "skipping KG phase for patient_id=%s",
            patient_id,
        )
        return []

    try:
        raw = svc.patient_full_inference(patient_id, measurement_year=year) or []
    except TypeError:
        # Older signature without the year kwarg
        try:
            raw = svc.patient_full_inference(patient_id) or []
        except Exception as exc:
            logger.warning("KG patient_full_inference failed pid=%s: %s", patient_id, exc)
            return []
    except Exception as exc:
        logger.warning("KG patient_full_inference errored pid=%s: %s", patient_id, exc)
        return []

    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        candidates.append(_normalize_kg_candidate(item))

    return candidates


def _normalize_kg_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """
    Coerce a kg_lookup_service candidate dict into the orchestrator's
    canonical shape, regardless of which exact keys the sibling agent
    emitted.
    """
    hcc = (
        item.get("suspect_hcc")
        or item.get("hcc")
        or item.get("hcc_code")
        or ""
    )
    icd = (
        item.get("suspect_icd10")
        or item.get("icd10")
        or item.get("icd_code")
        or item.get("primary_icd10")
        or ""
    )
    et = item.get("evidence_type")
    if et not in KG_EVIDENCE_TYPES:
        # Map free-form classification strings onto the canonical tag set
        kind = (item.get("kind") or item.get("source") or "").lower()
        et = {
            "rule":         "kg_rule",
            "comorbidity":  "kg_comorbidity",
            "drug_class":   "kg_drug_class",
            "drug":         "kg_drug_class",
            "rx":           "kg_drug_class",
            "lab":          "kg_lab_signal",
            "lab_signal":   "kg_lab_signal",
            "specialty":    "kg_specialty",
        }.get(kind, "kg_rule")

    raw_conf = item.get("raw_confidence")
    if raw_conf is None:
        raw_conf = item.get("confidence_score")
    if raw_conf is None:
        raw_conf = item.get("confidence", 0.65)
    try:
        raw_conf = float(raw_conf)
    except (TypeError, ValueError):
        raw_conf = 0.65

    detail = item.get("evidence_detail") or _default_evidence_detail(item)

    return {
        "suspect_hcc": str(hcc).strip().upper(),
        "suspect_icd10": str(icd).strip().upper().replace(".", ""),
        "evidence_type": et,
        "raw_confidence": raw_conf,
        "evidence_detail": detail,
    }


def _default_evidence_detail(item: dict[str, Any]) -> dict[str, Any]:
    """Build an evidence-detail skeleton from sparse KG output."""
    return {
        "kg_rule_id": item.get("rule_id"),
        "rule_source": item.get("rule_source") or "CMS-V28",
        "rule_citation": item.get("rule_citation") or "",
        "trigger_evidence": item.get("trigger_evidence") or [],
        "comorbidity_upgrades": item.get("comorbidity_upgrades") or [],
        "drug_class_inference": item.get("drug_class_inference"),
        "demographic_multiplier": 1.0,
        "specialty_multiplier": 1.0,
        "final_confidence": None,
        "llm_corroboration": None,
    }


# ---------------------------------------------------------------------------
# Phase 2 — LLM augmentation
# ---------------------------------------------------------------------------

def _llm_pass(
    *,
    patient_id: int,
    chart_text: str | None,
    kg_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Run the existing Gemini suspect path with KG candidates as context.

    Returns a list of LLM-only candidates already shaped like KG
    candidates so they can flow into the merge step uniformly.
    """
    if not chart_text:
        return []

    fn, mod_path, fn_name = _gemini_suspect_runner()
    if fn is None:
        logger.info(
            "_llm_pass: no Gemini suspect runner found; skipping LLM phase pid=%s",
            patient_id,
        )
        return []

    kg_context = [
        {
            "suspect_hcc": c["suspect_hcc"],
            "suspect_icd10": c["suspect_icd10"],
            "evidence_type": c["evidence_type"],
            "raw_confidence": c["raw_confidence"],
        }
        for c in kg_candidates
    ]

    try:
        raw = fn(
            chart_text,
            patient_id=patient_id,
            kg_context=kg_context,
        ) or {}
    except TypeError:
        # Fallback — older runners take only chart_text (e.g. run_pipeline)
        try:
            raw = fn(chart_text) or {}
        except Exception as exc:
            logger.warning("LLM suspect runner %s.%s failed: %s", mod_path, fn_name, exc)
            return []
    except Exception as exc:
        logger.warning("LLM suspect runner %s.%s errored: %s", mod_path, fn_name, exc)
        return []

    raw_suspects: list[dict[str, Any]]
    if isinstance(raw, dict):
        raw_suspects = (
            raw.get("suspect_conditions")
            or raw.get("suspects")
            or []
        )
    elif isinstance(raw, list):
        raw_suspects = raw
    else:
        raw_suspects = []

    out: list[dict[str, Any]] = []
    for r in raw_suspects:
        if not isinstance(r, dict):
            continue
        hcc = str(r.get("hcc") or r.get("suspect_hcc") or "").strip().upper()
        icd = str(r.get("icd10") or r.get("suspect_icd10") or "").strip().upper().replace(".", "")
        if not hcc and not icd:
            continue
        try:
            conf = float(r.get("confidence") or r.get("confidence_score") or 0.6)
        except (TypeError, ValueError):
            conf = 0.6
        out.append({
            "suspect_hcc": hcc,
            "suspect_icd10": icd,
            "evidence_type": LLM_EVIDENCE_TYPE,
            "raw_confidence": conf,
            "evidence_detail": {
                "kg_rule_id": None,
                "rule_source": "LLM",
                "rule_citation": "",
                "trigger_evidence": [],
                "comorbidity_upgrades": [],
                "drug_class_inference": None,
                "demographic_multiplier": 1.0,
                "specialty_multiplier": 1.0,
                "final_confidence": None,
                "llm_corroboration": {
                    "chart_quote": (r.get("evidence") or r.get("note_snippet") or "")[:500],
                    "condition": r.get("condition") or r.get("description") or "",
                },
            },
        })
    return out


# ---------------------------------------------------------------------------
# Phase 3 — Conflict resolution / merge
# ---------------------------------------------------------------------------

def _merge_kg_and_llm(
    kg_candidates: list[dict[str, Any]],
    llm_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge KG and LLM candidates by suspect_hcc.

    Rules
    -----
    * KG candidate is always primary when both fire on the same HCC.
    * LLM chart-quote is appended into ``evidence_detail.llm_corroboration``.
    * LLM-only candidates (HCC not present in KG output) are kept and
      tagged with evidence_type='llm'.
    * Multiple KG candidates for the same HCC keep the highest
      raw_confidence and append the others into a 'related_kg' list.
    """
    by_hcc: dict[str, dict[str, Any]] = {}

    # First pass: KG (deterministic, primary)
    for c in kg_candidates:
        key = c["suspect_hcc"] or c["suspect_icd10"]
        if not key:
            continue
        existing = by_hcc.get(key)
        if existing is None:
            by_hcc[key] = dict(c)  # shallow copy
            by_hcc[key]["evidence_detail"] = dict(c.get("evidence_detail") or {})
            continue
        # Keep highest-confidence KG candidate; preserve the other in related_kg
        if c["raw_confidence"] > existing["raw_confidence"]:
            related = existing.get("evidence_detail", {}).get("related_kg") or []
            related.append({
                "evidence_type": existing["evidence_type"],
                "raw_confidence": existing["raw_confidence"],
                "evidence_detail": existing.get("evidence_detail"),
            })
            by_hcc[key] = dict(c)
            by_hcc[key]["evidence_detail"] = dict(c.get("evidence_detail") or {})
            by_hcc[key]["evidence_detail"]["related_kg"] = related
        else:
            related = existing["evidence_detail"].setdefault("related_kg", [])
            related.append({
                "evidence_type": c["evidence_type"],
                "raw_confidence": c["raw_confidence"],
                "evidence_detail": c.get("evidence_detail"),
            })

    # Second pass: LLM
    for c in llm_candidates:
        key = c["suspect_hcc"] or c["suspect_icd10"]
        if not key:
            continue
        existing = by_hcc.get(key)
        llm_corroboration = (c.get("evidence_detail") or {}).get("llm_corroboration")
        if existing is not None:
            # KG-primary; append LLM as supporting context only
            existing["evidence_detail"]["llm_corroboration"] = llm_corroboration
            existing.setdefault("supporting_evidence_types", []).append(LLM_EVIDENCE_TYPE)
        else:
            # Pure-LLM candidate
            by_hcc[key] = dict(c)
            by_hcc[key]["evidence_detail"] = dict(c.get("evidence_detail") or {})

    return list(by_hcc.values())


# ---------------------------------------------------------------------------
# Phase 4 — Calibration
# ---------------------------------------------------------------------------

def _apply_calibration(
    candidate: dict[str, Any],
    patient_demographics: dict[str, Any] | None,
    provider_specialty: str | None,
) -> dict[str, Any]:
    """
    Apply demographic + specialty multipliers to *candidate*.

    Mutates and returns *candidate*.  The multipliers and the resulting
    final_confidence are written back into evidence_detail so that the
    audit chain can show exactly how the score was derived.
    """
    demo = patient_demographics or {}
    detail = candidate.setdefault("evidence_detail", {})

    demo_mult = 1.0
    demo_reasons: list[str] = []
    for rule in _DEMOGRAPHIC_RULES:
        try:
            if not rule["match"](demo):
                continue
        except Exception:
            continue
        if _hcc_matches_prefix(candidate["suspect_hcc"], rule["hcc_prefix"]):
            demo_mult *= rule["multiplier"]
            demo_reasons.append(rule["reason"])

    spec_mult = 1.0
    spec_reasons: list[str] = []
    if provider_specialty:
        rule = _SPECIALTY_RULES.get(provider_specialty.strip().lower())
        if rule and _hcc_matches_prefix(candidate["suspect_hcc"], rule["hcc_prefix"]):
            spec_mult *= rule["multiplier"]
            spec_reasons.append(
                f"Specialty {provider_specialty} → {rule['multiplier']}x"
            )

    raw = float(candidate.get("raw_confidence") or 0.0)
    final = raw * demo_mult * spec_mult
    if final > 0.99:
        final = 0.99
    if final < 0.01 and raw > 0:
        final = 0.01

    detail["demographic_multiplier"] = demo_mult
    detail["demographic_reasons"] = demo_reasons
    detail["specialty_multiplier"] = spec_mult
    detail["specialty_reasons"] = spec_reasons
    detail["final_confidence"] = round(final, 4)

    # Platt-scaled confidence — load the persisted (a, b) from the KG
    # calibration artefact and squash the demographic/specialty-adjusted
    # final score.  When the artefact is missing the loader returns the
    # identity params (1.0, 0.0); we detect that and pass calibrated ==
    # final so the frontend chip reads "Raw" rather than "Calibrated".
    a, b = calibration_service.load_calibration()
    if calibration_service.is_identity(a, b):
        calibrated = final
    else:
        calibrated = round(calibration_service.apply_calibration(final, a, b), 4)

    detail["calibration_a"] = a
    detail["calibration_b"] = b
    detail["calibrated_confidence"] = calibrated

    candidate["confidence_score"] = round(final, 4)
    # Surface raw + calibrated alongside confidence_score so the frontend
    # can render both values.  raw_confidence is already on the candidate
    # (set by _normalize_kg_candidate / _llm_pass) — we keep it untouched.
    candidate["calibrated_confidence"] = calibrated
    return candidate


def _hcc_matches_prefix(hcc: str, prefixes: Iterable[str]) -> bool:
    """Return True when *hcc* starts with any of the configured prefixes."""
    if not hcc:
        return False
    h = hcc.upper()
    return any(h.startswith(p.upper()) for p in prefixes)


# ---------------------------------------------------------------------------
# Phase 5 — Persistence
# ---------------------------------------------------------------------------

def _persist_suspects(
    suspects: list[dict[str, Any]],
    *,
    patient_id: int,
    year: int,
    tenant_id: int = 1,
) -> int:
    """
    Upsert each suspect into raf_suspect_conditions, dedup'd on
    (patient_id, suspect_hcc, measurement_year).

    Returns the number of rows successfully written / updated.
    """
    if not suspects:
        return 0

    written = 0
    for s in suspects:
        try:
            rid = _upsert_one(s, patient_id=patient_id, year=year, tenant_id=tenant_id)
            if rid is not None:
                s["id"] = rid
                written += 1
        except Exception as exc:
            logger.error(
                "_persist_suspects upsert failed pid=%s hcc=%s: %s",
                patient_id, s.get("suspect_hcc"), exc,
            )
    return written


def _upsert_one(
    suspect: dict[str, Any],
    *,
    patient_id: int,
    year: int,
    tenant_id: int = 1,
) -> int | None:
    """
    Insert-or-update a single suspect row.  Dedup key is
    (patient_id, measurement_year, suspect_hcc).
    """
    hcc = (suspect.get("suspect_hcc") or "").strip().upper()
    icd = (suspect.get("suspect_icd10") or "").strip().upper()
    et = suspect.get("evidence_type") or "kg_rule"
    score = float(suspect.get("confidence_score") or suspect.get("raw_confidence") or 0.0)
    detail_json = json.dumps(suspect.get("evidence_detail") or {}, default=_json_default)

    sql = """
        INSERT INTO raf_suspect_conditions
            (patient_id, measurement_year, suspect_hcc, suspect_icd10,
             evidence_type, evidence_detail, confidence_score, status,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            suspect_icd10    = VALUES(suspect_icd10),
            evidence_type    = VALUES(evidence_type),
            evidence_detail  = VALUES(evidence_detail),
            confidence_score = GREATEST(confidence_score, VALUES(confidence_score)),
            updated_at       = NOW()
    """
    params = (
        patient_id, year, hcc, icd,
        et, detail_json, score,
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            cur.execute(
                """
                SELECT id FROM raf_suspect_conditions
                WHERE patient_id = %s
                  AND measurement_year = %s
                  AND suspect_hcc = %s
                LIMIT 1
                """,
                (patient_id, year, hcc),
            )
            row = cur.fetchone()
        return row["id"] if row else None
    except Exception as exc:
        # Some deployments don't have a unique constraint on
        # (patient_id, year, hcc); emulate dedup via UPDATE-or-INSERT.
        logger.warning(
            "_upsert_one: ON DUPLICATE KEY path failed (%s); using manual dedup", exc,
        )
        return _manual_upsert(
            patient_id=patient_id, year=year, hcc=hcc, icd=icd,
            et=et, score=score, detail_json=detail_json, tenant_id=tenant_id,
        )


def _manual_upsert(
    *,
    patient_id: int,
    year: int,
    hcc: str,
    icd: str,
    et: str,
    score: float,
    detail_json: str,
    tenant_id: int,
) -> int | None:
    """Fallback path when ON DUPLICATE KEY isn't available (no unique idx)."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, confidence_score FROM raf_suspect_conditions
                WHERE patient_id = %s
                  AND measurement_year = %s
                  AND suspect_hcc = %s
                LIMIT 1
                """,
                (patient_id, year, hcc),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE raf_suspect_conditions
                    SET suspect_icd10 = %s,
                        evidence_type = %s,
                        evidence_detail = %s,
                        confidence_score = GREATEST(confidence_score, %s),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (icd, et, detail_json, score, existing["id"]),
                )
                return existing["id"]
            cur.execute(
                """
                INSERT INTO raf_suspect_conditions
                    (patient_id, measurement_year, suspect_hcc, suspect_icd10,
                     evidence_type, evidence_detail, confidence_score, status,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', NOW(), NOW())
                """,
                (patient_id, year, hcc, icd, et, detail_json, score),
            )
            cur.execute("SELECT LAST_INSERT_ID() AS lid")
            row = cur.fetchone()
        return row["lid"] if row else None
    except Exception as exc:
        logger.error("_manual_upsert failed pid=%s hcc=%s: %s", patient_id, hcc, exc)
        return None


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


# ---------------------------------------------------------------------------
# Demographics loader
# ---------------------------------------------------------------------------

def _load_demographics(patient_id: int, year: int) -> dict[str, Any]:
    """
    Best-effort load of patient demographics + provider context for the
    calibration phase.  Returns an empty dict on any error so calibration
    becomes a pass-through.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT age_years, sex, dual_eligible, lis, esrd
                FROM raf_patient_demographics
                WHERE patient_id = %s
                  AND measurement_year = %s
                LIMIT 1
                """,
                (patient_id, year),
            )
            row = cur.fetchone() or {}
    except Exception as exc:
        logger.debug("_load_demographics pid=%s: %s", patient_id, exc)
        return {}

    return {
        "age": row.get("age_years"),
        "sex": row.get("sex"),
        "dual_eligible": bool(row.get("dual_eligible")),
        "lis": bool(row.get("lis")),
        "esrd": bool(row.get("esrd")),
    }


# ---------------------------------------------------------------------------
# Public API — get_evidence_chain
# ---------------------------------------------------------------------------

def get_evidence_chain(suspect_id: int) -> dict[str, Any]:
    """
    Load a single suspect row and return its full evidence chain.

    Useful for the frontend "why" panel.  The returned dict contains the
    persisted suspect plus the parsed ``evidence_detail`` JSON.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT * FROM raf_suspect_conditions WHERE id = %s",
                (suspect_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("get_evidence_chain id=%s: %s", suspect_id, exc)
        raise

    if not row:
        raise ValueError(f"Suspect {suspect_id} not found")

    detail_raw = row.get("evidence_detail")
    if isinstance(detail_raw, str):
        try:
            detail = json.loads(detail_raw)
        except json.JSONDecodeError:
            detail = {"_raw": detail_raw}
    elif isinstance(detail_raw, dict):
        detail = detail_raw
    else:
        detail = {}

    confidence_score = float(row.get("confidence_score") or 0.0)

    # Re-derive raw + calibrated from the persisted detail blob when
    # available; fall back to confidence_score when older rows lack the
    # calibration fields.  The detail's calibrated_confidence was written
    # by _apply_calibration at insert time.
    raw_confidence = (
        detail.get("raw_confidence")
        if isinstance(detail, dict) else None
    )
    if raw_confidence is None:
        # Older rows: confidence_score IS the raw + post-mult value.
        raw_confidence = confidence_score
    calibrated_confidence = (
        detail.get("calibrated_confidence")
        if isinstance(detail, dict) else None
    )
    if calibrated_confidence is None:
        # Run Platt on demand for legacy rows so the API stays consistent.
        a, b = calibration_service.load_calibration()
        if calibration_service.is_identity(a, b):
            calibrated_confidence = confidence_score
        else:
            calibrated_confidence = round(
                calibration_service.apply_calibration(confidence_score, a, b), 4
            )

    return {
        "id": row.get("id"),
        "patient_id": row.get("patient_id"),
        "measurement_year": row.get("measurement_year"),
        "suspect_hcc": row.get("suspect_hcc"),
        "suspect_icd10": row.get("suspect_icd10"),
        "evidence_type": row.get("evidence_type"),
        "confidence_score": confidence_score,
        "raw_confidence": float(raw_confidence),
        "calibrated_confidence": float(calibrated_confidence),
        "status": row.get("status"),
        "evidence_chain": detail,
    }


# ---------------------------------------------------------------------------
# Distribution helpers (for reporting / acceptance)
# ---------------------------------------------------------------------------

def get_evidence_type_distribution(
    patient_id: int | None = None,
    year: int | None = None,
) -> dict[str, int]:
    """
    Return a count of suspects grouped by evidence_type.  Optionally
    filtered to a single patient and / or measurement year.
    """
    where: list[str] = []
    params: list[Any] = []
    if patient_id is not None:
        where.append("patient_id = %s")
        params.append(patient_id)
    if year is not None:
        where.append("measurement_year = %s")
        params.append(year)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT evidence_type, COUNT(*) AS n
        FROM raf_suspect_conditions
        {where_sql}
        GROUP BY evidence_type
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_evidence_type_distribution failed: %s", exc)
        return {}

    return {r["evidence_type"]: int(r["n"]) for r in rows if r.get("evidence_type")}
