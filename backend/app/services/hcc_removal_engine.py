"""
HCC Removal Candidate Engine - Two-Way Coding (RADV defense).

Counterpart to ``suspect_engine``.  The suspect engine flags HCCs that the
chart supports but billing has *not* coded (revenue opportunity).  This engine
flags HCCs that billing *has* coded but the chart does NOT support with MEAT
evidence (RADV audit risk - CMS may claw back the associated payments).

Pipeline per patient::

    1. get_coded_hccs(patient_id, year)
         pulls all rows from raf_patient_hcc that are not trumped
    2. For each coded HCC:
         a) Look at raf_meat_evidence for that patient_hcc_id - if any
            encounter shows ANY MEAT element present, the HCC is supported.
         b) If no stored MEAT (or it is empty), invoke
            gemini_service.extract_meat_evidence against the patient's
            combined clinical text for the HCC's primary ICD-10.
         c) If Gemini also returns ``meat_score == 0`` AND
            ``sufficient_for_hcc`` is False, flag as a removal candidate.
    3. Persist results to hcc_removal_candidates with status='pending'
       (ON DUPLICATE KEY UPDATE so re-scans refresh confidence/evidence
       without losing review history of accepted/dismissed rows).

Status flow mirrors the suspect engine, using the wording the migration
chose:  ``pending`` -> (``dismissed`` | ``removed``).  ``removed`` is the
two-way analogue of ``accepted``.

Tenancy
-------
The raf_patient_hcc table does not (yet) carry tenant_id.  We resolve a
tenant_id via a lightweight resolver that callers can override; the default
implementation returns 'default' so the engine works on the current single-
tenant schema while remaining ready for the multi-tenant rollout.

This module deliberately does NOT modify raf_patient_hcc, raf_scores,
raf_calculator, or score_persistence.  Confirming a removal in this engine
only marks the candidate row as ``status='removed'`` - the actual deletion of
the HCC and re-calculation of RAF is a separate workflow (out of scope).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Callable

from app.db import raf_cursor
from app.services import openemr_connector as emr
from app.services.meat_evidence_service import get_meat_for_hcc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tenant resolver (override-able)
# ---------------------------------------------------------------------------

def _default_tenant_resolver(patient_id: int) -> str:
    """Resolve the tenant_id for a patient.

    The current schema does not store tenant_id on raf_patient_hcc, so this
    default returns 'default'.  Tests and future RBAC code can monkey-patch
    or supply a custom callable to ``generate_removal_candidates``.
    """
    return "default"


# ---------------------------------------------------------------------------
# Step 1: Read coded HCCs
# ---------------------------------------------------------------------------

def get_coded_hccs(patient_id: int, year: int = 2026) -> list[dict[str, Any]]:
    """Return all currently-coded HCCs for the patient/year.

    Excludes rows where ``is_trumped = 1`` because those HCCs are already
    suppressed by the V28 hierarchy and produce no RAF, so they cannot be
    "removed" in the audit sense.

    Returned dict shape::

        {
            "patient_hcc_id":   int,
            "patient_id":       int,
            "measurement_year": int,
            "hcc_code":         str,        # always normalised to "HCC<n>"
            "hcc_code_int":     int,        # raw SMALLINT value
            "icd10_codes":      list[str],  # parsed from JSON column
            "primary_icd10":    str,        # first code, '' if none
            "encounter_ids":    list[int],
            "raf_coefficient":  float,
            "meat_status":      "complete" | "partial" | "missing",
        }
    """
    sql = """
        SELECT
            id                   AS patient_hcc_id,
            patient_id,
            measurement_year,
            hcc_code,
            icd10_codes,
            source_encounter_ids,
            raf_coefficient,
            meat_status
        FROM raf_patient_hcc
        WHERE patient_id       = %s
          AND measurement_year = %s
          AND is_trumped       = 0
        ORDER BY hcc_code
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (patient_id, year))
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_coded_hccs failed pid=%s year=%s: %s", patient_id, year, exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        icd_codes = _parse_json_list(row.get("icd10_codes"))
        enc_ids = _parse_json_list(row.get("source_encounter_ids"))
        hcc_int = int(row["hcc_code"])
        out.append({
            "patient_hcc_id":   int(row["patient_hcc_id"]),
            "patient_id":       int(row["patient_id"]),
            "measurement_year": int(row["measurement_year"]),
            "hcc_code":         f"HCC{hcc_int}",
            "hcc_code_int":     hcc_int,
            "icd10_codes":      icd_codes,
            "primary_icd10":    icd_codes[0] if icd_codes else "",
            "encounter_ids":    [int(e) for e in enc_ids if str(e).isdigit() or isinstance(e, int)],
            "raf_coefficient":  float(row.get("raf_coefficient") or 0.0),
            "meat_status":      str(row.get("meat_status") or "missing"),
        })
    return out


# ---------------------------------------------------------------------------
# Step 2: Check MEAT support for one HCC
# ---------------------------------------------------------------------------

def check_meat_support(
    patient_id: int,
    hcc: dict[str, Any],
    note_text: str | None = None,
    *,
    gemini_extract_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Determine whether the chart documents MEAT evidence for ``hcc``.

    Strategy
    --------
    1. Cheap path: read ``raf_meat_evidence`` for the patient_hcc_id.  If at
       least one row has any of meat_m/e/a/t_present == 1, the HCC is
       supported.  We capture the most recent supported encounter date.
    2. Authoritative path: if no stored MEAT (or all four columns empty),
       call ``gemini_service.extract_meat_evidence`` against the patient's
       combined chart text using the HCC's primary ICD-10.  This re-runs the
       extractor "in reverse": instead of finding new diagnoses, it asks
       whether evidence exists for a *known* one.

    Parameters
    ----------
    patient_id:
        OpenEMR pid - used only for logging and chart fetch fallback.
    hcc:
        Element from ``get_coded_hccs(...)``.  Must contain at least
        ``patient_hcc_id``, ``hcc_code``, and ``primary_icd10``.
    note_text:
        Pre-fetched chart text.  Pass it in to avoid re-querying OpenEMR
        per-HCC.  If omitted, the function will fetch it on demand.
    gemini_extract_fn:
        Optional injection point for ``extract_meat_evidence`` to keep this
        module testable without importing the Gemini SDK.  Defaults to the
        legacy ``gemini_service.extract_meat_evidence``.

    Returns
    -------
    dict with keys::

        supported                bool
        confidence_unsupported   float  # 0.0 (definitely supported) - 1.0 (no evidence)
        evidence_snippets        list[str]
        last_supported_date      str | None  # ISO date or None
        meat_score               int    # 0-4
        source                   "stored" | "gemini" | "no-chart"
        reason                   str    # short human explanation
    """
    patient_hcc_id = int(hcc.get("patient_hcc_id") or 0)
    hcc_label = str(hcc.get("hcc_code") or "")
    primary_icd = str(hcc.get("primary_icd10") or "")

    # ---------- Stored MEAT ----------
    stored_supported = False
    last_supported: str | None = None
    snippets: list[str] = []
    best_score = 0

    if patient_hcc_id:
        try:
            rows = get_meat_for_hcc(patient_hcc_id)
        except Exception as exc:
            logger.warning(
                "check_meat_support: get_meat_for_hcc failed pid=%s hcc=%s: %s",
                patient_id, hcc_label, exc,
            )
            rows = []

        for row in rows:
            present_count = sum(int(bool(row.get(k))) for k in (
                "meat_m_present", "meat_e_present", "meat_a_present", "meat_t_present",
            ))
            if present_count == 0:
                continue
            stored_supported = True
            best_score = max(best_score, present_count)

            enc_date = row.get("encounter_date")
            iso = enc_date.isoformat() if hasattr(enc_date, "isoformat") else str(enc_date or "")
            if iso and (last_supported is None or iso > last_supported):
                last_supported = iso

            for col in ("meat_m", "meat_e", "meat_a", "meat_t"):
                val = (row.get(col) or "").strip() if isinstance(row.get(col), str) else ""
                if val and val not in snippets:
                    snippets.append(val[:280])

        if stored_supported:
            return {
                "supported":              True,
                "confidence_unsupported": 0.0,
                "evidence_snippets":      snippets[:5],
                "last_supported_date":    last_supported,
                "meat_score":             best_score,
                "source":                 "stored",
                "reason":                 f"{best_score}/4 MEAT elements present in stored evidence",
            }

    # ---------- Gemini fallback ----------
    if note_text is None:
        try:
            note_text = emr.get_all_clinical_text(patient_id) or ""
        except Exception as exc:
            logger.warning(
                "check_meat_support: chart fetch failed pid=%s: %s", patient_id, exc,
            )
            note_text = ""

    if not (note_text or "").strip():
        # No chart at all - we cannot prove support exists.  Treat as
        # unsupported but with reduced confidence so the clinician knows the
        # finding came from a missing-data condition rather than positive
        # evidence of overcoding.
        return {
            "supported":              False,
            "confidence_unsupported": 0.6,
            "evidence_snippets":      [],
            "last_supported_date":    None,
            "meat_score":             0,
            "source":                 "no-chart",
            "reason":                 "No clinical notes available for this patient",
        }

    if not primary_icd:
        # Without an ICD anchor we cannot run the focused extractor; fall
        # back to a soft signal driven only by stored MEAT presence.
        return {
            "supported":              False,
            "confidence_unsupported": 0.5,
            "evidence_snippets":      [],
            "last_supported_date":    None,
            "meat_score":             0,
            "source":                 "no-chart",
            "reason":                 f"No representative ICD-10 stored for {hcc_label}; cannot verify MEAT",
        }

    if gemini_extract_fn is None:
        gemini_extract_fn = _resolve_default_extractor()

    if gemini_extract_fn is None:
        # Gemini service unavailable; fail-open (no removal candidate) and
        # surface the reason so callers know they need to wire it up.
        logger.warning(
            "check_meat_support: gemini extractor unavailable pid=%s hcc=%s; "
            "skipping MEAT recheck",
            patient_id, hcc_label,
        )
        return {
            "supported":              True,
            "confidence_unsupported": 0.0,
            "evidence_snippets":      [],
            "last_supported_date":    None,
            "meat_score":             0,
            "source":                 "stub",
            "reason":                 "Gemini MEAT extractor not available - assuming supported (fail-open)",
        }

    try:
        gem = gemini_extract_fn(
            note_text=note_text,
            diagnosis=hcc_label,
            icd10_code=primary_icd,
        )
    except Exception as exc:
        logger.warning(
            "check_meat_support: Gemini call failed pid=%s hcc=%s: %s",
            patient_id, hcc_label, exc,
        )
        # On Gemini error, fail-open (do not flag for removal) and surface
        # the reason in the response.
        return {
            "supported":              True,
            "confidence_unsupported": 0.0,
            "evidence_snippets":      [],
            "last_supported_date":    None,
            "meat_score":             0,
            "source":                 "gemini-error",
            "reason":                 f"Gemini extraction failed: {exc}",
        }

    if not isinstance(gem, dict):
        return {
            "supported":              True,
            "confidence_unsupported": 0.0,
            "evidence_snippets":      [],
            "last_supported_date":    None,
            "meat_score":             0,
            "source":                 "gemini-error",
            "reason":                 "Gemini returned malformed response - assuming supported",
        }

    score = int(gem.get("meat_score") or 0)
    sufficient = bool(gem.get("sufficient_for_hcc", score >= 1))

    meat_block = gem.get("meat") or {}
    if isinstance(meat_block, dict):
        for key in ("monitoring", "evaluation", "assessment", "treatment"):
            v = meat_block.get(key)
            if isinstance(v, str) and v.strip():
                snippets.append(v.strip()[:280])

    if sufficient:
        return {
            "supported":              True,
            "confidence_unsupported": 0.0,
            "evidence_snippets":      snippets[:5],
            "last_supported_date":    None,
            "meat_score":             score,
            "source":                 "gemini",
            "reason":                 f"Gemini found {score}/4 MEAT elements supporting {hcc_label}",
        }

    # Unsupported: confidence ramps from 0.85 (some weak evidence) to 1.0
    # (literally no MEAT element).
    confidence_unsupported = 1.0 if score == 0 else max(0.6, 1.0 - 0.1 * score)
    return {
        "supported":              False,
        "confidence_unsupported": round(confidence_unsupported, 4),
        "evidence_snippets":      snippets[:5],
        "last_supported_date":    None,
        "meat_score":             score,
        "source":                 "gemini",
        "reason": (
            f"Gemini found 0/4 MEAT elements for {hcc_label} ({primary_icd}) in chart"
            if score == 0 else
            f"Gemini found only {score}/4 MEAT elements; insufficient for HCC {hcc_label}"
        ),
    }


# ---------------------------------------------------------------------------
# Step 3: Generate + persist removal candidates
# ---------------------------------------------------------------------------

def generate_removal_candidates(
    patient_id: int,
    year: int = 2026,
    *,
    tenant_resolver: Callable[[int], str] = _default_tenant_resolver,
    gemini_extract_fn: Callable[..., dict[str, Any]] | None = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """Run the full removal scan for a patient.

    Iterates every coded HCC and checks MEAT support; any HCC without
    sufficient evidence is upserted into ``hcc_removal_candidates``.

    Parameters
    ----------
    patient_id:
        OpenEMR pid.
    year:
        Measurement year (defaults to 2026 to match the rest of the system).
    tenant_resolver:
        Callable mapping patient_id -> tenant_id; allows tests / multi-tenant
        callers to override the default 'default' resolver.
    gemini_extract_fn:
        Optional injection of the MEAT extractor (used to keep tests free
        of the Gemini SDK).
    persist:
        If True (default), write candidates to the DB.  Pass False for
        dry-run / preview mode.

    Returns
    -------
    list of dicts shaped like the API response::

        {
            "id":                  int | None,   # row id when persisted
            "patient_id":          int,
            "tenant_id":           str,
            "measurement_year":    int,
            "hcc_code":            int,
            "hcc_label":           str,          # "HCC<n>"
            "icd10":               str,
            "patient_hcc_id":      int,
            "confidence":          float,
            "reason":              str,
            "evidence_snippets":   list[str],
            "last_supported_date": str | None,
            "status":              "pending",
        }
    """
    tenant_id = tenant_resolver(patient_id) or "default"

    coded = get_coded_hccs(patient_id, year)
    if not coded:
        logger.info(
            "generate_removal_candidates: no coded HCCs for pid=%s year=%s",
            patient_id, year,
        )
        return []

    # Pre-fetch chart text once to avoid N round-trips
    try:
        chart_text = emr.get_all_clinical_text(patient_id) or ""
    except Exception as exc:
        logger.warning("chart fetch failed pid=%s: %s", patient_id, exc)
        chart_text = ""

    candidates: list[dict[str, Any]] = []
    for hcc in coded:
        support = check_meat_support(
            patient_id,
            hcc,
            note_text=chart_text or None,
            gemini_extract_fn=gemini_extract_fn,
        )
        if support["supported"]:
            continue

        evidence_blob = {
            "source":              support["source"],
            "meat_score":          support["meat_score"],
            "snippets":            support["evidence_snippets"],
            "scanned_at":          datetime.utcnow().isoformat(timespec="seconds"),
            "primary_icd10":       hcc["primary_icd10"],
            "all_icd10":           hcc["icd10_codes"],
            "scanned_encounters":  hcc["encounter_ids"],
            "raf_coefficient":     hcc["raf_coefficient"],
            "stored_meat_status":  hcc["meat_status"],
        }

        candidate = {
            "id":                  None,
            "patient_id":          patient_id,
            "tenant_id":           tenant_id,
            "measurement_year":    year,
            "hcc_code":            hcc["hcc_code_int"],
            "hcc_label":           hcc["hcc_code"],
            "icd10":               hcc["primary_icd10"],
            "patient_hcc_id":      hcc["patient_hcc_id"],
            "confidence":          support["confidence_unsupported"],
            "reason":              support["reason"],
            "evidence":            evidence_blob,
            "evidence_snippets":   support["evidence_snippets"],
            "last_supported_date": support["last_supported_date"],
            "status":              "pending",
        }

        if persist:
            row_id = _upsert_candidate(candidate)
            candidate["id"] = row_id

        candidates.append(candidate)

    logger.info(
        "generate_removal_candidates pid=%s year=%s tenant=%s -> %d/%d HCCs flagged",
        patient_id, year, tenant_id, len(candidates), len(coded),
    )
    return candidates


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _upsert_candidate(candidate: dict[str, Any]) -> int | None:
    """Insert (or refresh) a removal candidate row.

    The unique key (tenant_id, patient_id, measurement_year, hcc_code) means
    re-running a scan refreshes confidence/evidence/reason but never creates
    a duplicate row.  We deliberately do NOT reset status on update so that
    a previously dismissed/removed candidate stays in its reviewed state.
    """
    sql = """
        INSERT INTO hcc_removal_candidates (
            patient_id, tenant_id, measurement_year, hcc_code, icd10,
            patient_hcc_id, confidence, reason, evidence,
            last_supported_date, status, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, 'pending', NOW(), NOW()
        )
        ON DUPLICATE KEY UPDATE
            icd10               = VALUES(icd10),
            patient_hcc_id      = VALUES(patient_hcc_id),
            confidence          = VALUES(confidence),
            reason              = VALUES(reason),
            evidence            = VALUES(evidence),
            last_supported_date = VALUES(last_supported_date),
            updated_at          = NOW()
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (
                candidate["patient_id"],
                candidate["tenant_id"],
                candidate["measurement_year"],
                candidate["hcc_code"],
                candidate["icd10"] or "",
                candidate["patient_hcc_id"],
                float(candidate["confidence"]),
                candidate["reason"] or "",
                json.dumps(candidate.get("evidence") or {}),
                candidate.get("last_supported_date"),
            ))
            cur.execute(
                """
                SELECT id FROM hcc_removal_candidates
                WHERE tenant_id = %s
                  AND patient_id = %s
                  AND measurement_year = %s
                  AND hcc_code = %s
                """,
                (
                    candidate["tenant_id"],
                    candidate["patient_id"],
                    candidate["measurement_year"],
                    candidate["hcc_code"],
                ),
            )
            row = cur.fetchone()
            return int(row["id"]) if row else None
    except Exception as exc:
        logger.error(
            "_upsert_candidate failed pid=%s hcc=%s: %s",
            candidate.get("patient_id"), candidate.get("hcc_code"), exc,
        )
        return None


# ---------------------------------------------------------------------------
# Read APIs
# ---------------------------------------------------------------------------

def list_candidates(
    patient_id: int | None = None,
    *,
    tenant_id: str = "default",
    status: str = "pending",
    year: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List removal candidates with optional filters.  Always tenant-scoped."""
    where = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if patient_id is not None:
        where.append("patient_id = %s")
        params.append(patient_id)
    if status and status != "all":
        where.append("status = %s")
        params.append(status)
    if year is not None:
        where.append("measurement_year = %s")
        params.append(year)

    sql = f"""
        SELECT *
        FROM hcc_removal_candidates
        WHERE {' AND '.join(where)}
        ORDER BY confidence DESC, created_at DESC
        LIMIT %s
    """
    params.append(int(limit))

    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_serialize_candidate(r) for r in rows]
    except Exception as exc:
        logger.error("list_candidates failed: %s", exc)
        return []


def get_candidate(candidate_id: int, *, tenant_id: str = "default") -> dict[str, Any] | None:
    """Fetch one candidate, scoped to tenant."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM hcc_removal_candidates
                WHERE id = %s AND tenant_id = %s
                """,
                (candidate_id, tenant_id),
            )
            row = cur.fetchone()
        return _serialize_candidate(row) if row else None
    except Exception as exc:
        logger.error("get_candidate id=%s: %s", candidate_id, exc)
        return None


# ---------------------------------------------------------------------------
# Review actions
# ---------------------------------------------------------------------------

def dismiss_candidate(
    candidate_id: int,
    reviewed_by: str,
    notes: str = "",
    *,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Mark a candidate as dismissed (clinician keeps the HCC)."""
    return _set_status(
        candidate_id,
        "dismissed",
        reviewed_by=reviewed_by,
        notes=notes,
        tenant_id=tenant_id,
    )


def confirm_removal(
    candidate_id: int,
    reviewed_by: str,
    notes: str = "",
    *,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Mark a candidate as removed (clinician confirms the HCC is unsupported).

    NOTE: this only updates the workflow status.  Actually deleting the HCC
    from raf_patient_hcc and re-running the RAF calc is intentionally left
    to a separate workflow so this engine never touches the protected
    calculator/score-persistence code paths.
    """
    return _set_status(
        candidate_id,
        "removed",
        reviewed_by=reviewed_by,
        notes=notes,
        tenant_id=tenant_id,
    )


def _set_status(
    candidate_id: int,
    new_status: str,
    *,
    reviewed_by: str,
    notes: str,
    tenant_id: str,
) -> dict[str, Any]:
    if new_status not in {"pending", "dismissed", "removed"}:
        raise ValueError(f"Invalid status '{new_status}'")
    if not reviewed_by:
        raise ValueError("reviewed_by is required")

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE hcc_removal_candidates
                SET status       = %s,
                    reviewed_by  = %s,
                    reviewed_at  = NOW(),
                    review_notes = %s,
                    updated_at   = NOW()
                WHERE id = %s AND tenant_id = %s
                """,
                (new_status, reviewed_by, notes or None, candidate_id, tenant_id),
            )
            if cur.rowcount == 0:
                raise ValueError(
                    f"Candidate {candidate_id} not found in tenant '{tenant_id}'"
                )
            cur.execute(
                "SELECT * FROM hcc_removal_candidates WHERE id = %s",
                (candidate_id,),
            )
            row = cur.fetchone()
        logger.info(
            "removal candidate %s -> %s by %s", candidate_id, new_status, reviewed_by,
        )
        return _serialize_candidate(row) or {}
    except ValueError:
        raise
    except Exception as exc:
        logger.error("_set_status id=%s -> %s: %s", candidate_id, new_status, exc)
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _serialize_candidate(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
            out[k] = float(v)
        else:
            out[k] = v
    if isinstance(out.get("evidence"), str):
        try:
            out["evidence"] = json.loads(out["evidence"])
        except json.JSONDecodeError:
            pass
    if "hcc_code" in out:
        try:
            out["hcc_label"] = f"HCC{int(out['hcc_code'])}"
        except (TypeError, ValueError):
            out["hcc_label"] = str(out["hcc_code"])
    return out


def _resolve_default_extractor() -> Callable[..., dict[str, Any]] | None:
    """Lazily import the legacy gemini_service.extract_meat_evidence.

    Imported lazily so that importing this engine module does not pull in
    the Gemini SDK during tests / cold startup.
    """
    try:
        from app.services._legacy.gemini_service import extract_meat_evidence
        return extract_meat_evidence
    except Exception as exc:  # pragma: no cover - SDK absence path
        logger.warning("gemini_service.extract_meat_evidence unavailable: %s", exc)
        return None
