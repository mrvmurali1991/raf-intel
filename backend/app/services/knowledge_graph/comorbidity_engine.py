"""
HCC Comorbidity Patterns Engine.
================================

Closes the marquee gap from the RAF feature audit:

    "Can't flag 'diabetic + retinopathy + nephropathy = uncontrolled with
    complications HCC 18, not HCC 19.'"

The engine evaluates curated rules stored in `kg_comorbidity_patterns` against
a patient's evidence set (existing HCCs + ICD-10 codes + ATC drug classes +
LOINC labs).  Each rule has AND-semantics over its `required_evidence` JSON
buckets:

    {
      "hccs":                 ["19", "108"],
      "icds":                 ["E11.9", "H35"],
      "atc_codes":            ["A10A", "N05AH02"],
      "loinc_with_threshold": [{"loinc": "33914-3", "op": "<", "value": 60}]
    }

A pattern matches when every listed fact is present.  Each match returns the
output HCC, the (optional) HCC it upgrades from, the confidence, and an
*evidence chain* listing exactly which patient facts triggered the rule.

Public API
----------
* `evaluate_patient(patient_id, year=2026)` — pull patient evidence from the
  RAF + OpenEMR databases and run all active patterns against it.
* `evaluate_evidence_set(evidence)` — same, but with an in-memory evidence
  dict.  Used by the suspect engine and by tests.
* `get_patterns_for_hcc(hcc_code)` — reverse lookup (which patterns produce
  this HCC, which upgrade to it?).

Notes
-----
* Codes are normalised to uppercase and stripped of dots before comparison.
* ICD codes match by prefix (so a rule listing ``H35`` is satisfied by
  ``H35.00``, ``H3500``, ``H3531`` etc.).  This mirrors the way CMS publishes
  V28 categories — the "diabetic retinopathy" group covers everything under
  H35.x.
* ATC codes match by prefix as well (so ``A10A`` covers all insulins).
* LOINC entries support ``>``, ``<``, ``>=``, ``<=``, ``=``.  Multiple rows
  for the same LOINC count as ANY (the most-recent value passing the
  threshold satisfies the rule).
* The engine NEVER hallucinates — every pattern has a `source` column and
  most have a `source_url` linking to the CMS V28 spec or AHA Coding Clinic
  entry.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db import raf_cursor
from app.services import openemr_connector as emr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Code normalisation helpers
# ---------------------------------------------------------------------------

def _norm_icd(code: str | None) -> str:
    """ICD-10 codes are stored both as 'E11.9' and 'E119' in different tables."""
    if not code:
        return ""
    return code.replace(".", "").strip().upper()


def _norm_hcc(code: str | int | None) -> str:
    """HCCs may be stored as int, '19', 'HCC19', 'HCC 19'."""
    if code is None:
        return ""
    s = str(code).strip().upper()
    if s.startswith("HCC"):
        s = s[3:].strip()
    return s.lstrip("0") or s  # strip leading zeros but keep '0' if all-zero


def _norm_atc(code: str | None) -> str:
    if not code:
        return ""
    return code.strip().upper()


def _norm_loinc(code: str | None) -> str:
    if not code:
        return ""
    return code.strip().upper()


# ---------------------------------------------------------------------------
# Threshold operator table
# ---------------------------------------------------------------------------

_THRESHOLD_OPS: dict[str, Any] = {
    ">":  lambda v, t: v > t,
    "<":  lambda v, t: v < t,
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    "=":  lambda v, t: v == t,
    "==": lambda v, t: v == t,
}


# ---------------------------------------------------------------------------
# Evidence-set helpers
# ---------------------------------------------------------------------------

def _icd_prefix_match(rule_code: str, patient_codes: set[str]) -> str | None:
    """Return the matching patient code (or None).  Both inputs already normalised."""
    rule = rule_code.strip().upper().replace(".", "")
    if not rule:
        return None
    # exact first
    if rule in patient_codes:
        return rule
    # prefix scan (rule is a category, patient codes are leaves)
    for pc in patient_codes:
        if pc.startswith(rule):
            return pc
    return None


def _atc_prefix_match(rule_code: str, patient_codes: set[str]) -> str | None:
    rule = rule_code.strip().upper()
    if not rule:
        return None
    if rule in patient_codes:
        return rule
    for pc in patient_codes:
        if pc.startswith(rule):
            return pc
    return None


def _hcc_match(rule_code: str, patient_codes: set[str]) -> str | None:
    rule = _norm_hcc(rule_code)
    return rule if rule in patient_codes else None


def _loinc_threshold_match(
    rule: dict[str, Any],
    labs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the satisfying lab row (or None)."""
    target = _norm_loinc(rule.get("loinc"))
    op = (rule.get("op") or ">").strip()
    threshold = rule.get("value")
    if not target or threshold is None or op not in _THRESHOLD_OPS:
        return None

    try:
        threshold_f = float(threshold)
    except (TypeError, ValueError):
        return None

    cmp_fn = _THRESHOLD_OPS[op]
    for lab in labs:
        code = _norm_loinc(lab.get("loinc") or lab.get("result_code"))
        if code != target:
            continue
        try:
            value = float(str(lab.get("value")).replace(",", "").strip())
        except (TypeError, ValueError, AttributeError):
            continue
        if cmp_fn(value, threshold_f):
            return {
                "loinc": code,
                "value": value,
                "op": op,
                "threshold": threshold_f,
                "date": lab.get("date"),
            }
    return None


# ---------------------------------------------------------------------------
# Core: pattern evaluator
# ---------------------------------------------------------------------------

def _coerce_required_evidence(raw: Any) -> dict[str, list]:
    """Tolerate JSON stored as str OR already-decoded dict."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _pattern_matches(
    pattern: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    """Evaluate a single pattern with AND-semantics over required_evidence buckets.

    Returns ``(matched, evidence_chain)`` — the chain is a list of dicts
    describing exactly which patient facts satisfied each required item.
    Order: hccs → icds → atc_codes → loinc_with_threshold.
    """
    required = _coerce_required_evidence(pattern.get("required_evidence"))
    if not required:
        return False, []

    chain: list[dict[str, Any]] = []

    icd_set: set[str] = {_norm_icd(c) for c in evidence.get("icds", []) if c}
    hcc_set: set[str] = {_norm_hcc(c) for c in evidence.get("hccs", []) if c is not None}
    atc_set: set[str] = {_norm_atc(c) for c in evidence.get("atc_codes", []) if c}
    labs: list[dict[str, Any]] = list(evidence.get("labs", []) or [])

    # 1. HCCs
    for code in required.get("hccs", []) or []:
        hit = _hcc_match(code, hcc_set)
        if not hit:
            return False, []
        chain.append({"type": "hcc", "rule": _norm_hcc(code), "matched": hit, "source": "raf_patient_hcc"})

    # 2. ICDs
    for code in required.get("icds", []) or []:
        hit = _icd_prefix_match(code, icd_set)
        if not hit:
            return False, []
        chain.append({"type": "icd", "rule": code, "matched": hit, "source": "billing"})

    # 3. ATC drug classes
    for code in required.get("atc_codes", []) or []:
        hit = _atc_prefix_match(code, atc_set)
        if not hit:
            return False, []
        chain.append({"type": "atc", "rule": code, "matched": hit, "source": "prescriptions"})

    # 4. LOINC thresholds
    for rule in required.get("loinc_with_threshold", []) or []:
        if not isinstance(rule, dict):
            return False, []
        hit = _loinc_threshold_match(rule, labs)
        if not hit:
            return False, []
        chain.append({
            "type": "loinc",
            "rule": rule,
            "matched": hit,
            "source": "procedure_result",
        })

    return True, chain


# ---------------------------------------------------------------------------
# DB access — load patterns
# ---------------------------------------------------------------------------

def _load_active_patterns() -> list[dict[str, Any]]:
    sql = """
        SELECT id, pattern_name, description, required_evidence,
               output_hcc, output_icd10, upgrades_from_hcc,
               confidence, source, source_url, model_version
        FROM kg_comorbidity_patterns
        WHERE is_active = 1
        ORDER BY id
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("comorbidity_engine: load patterns failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        r["required_evidence"] = _coerce_required_evidence(r.get("required_evidence"))
        out.append(r)
    return out


def get_patterns_for_hcc(hcc_code: str) -> list[dict[str, Any]]:
    """All patterns whose `output_hcc` or `upgrades_from_hcc` equals *hcc_code*."""
    target = _norm_hcc(hcc_code)
    if not target:
        return []
    sql = """
        SELECT id, pattern_name, description, required_evidence,
               output_hcc, output_icd10, upgrades_from_hcc,
               confidence, source, source_url, model_version, is_active
        FROM kg_comorbidity_patterns
        WHERE (output_hcc = %s OR upgrades_from_hcc = %s)
        ORDER BY id
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (target, target))
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_patterns_for_hcc(%s) failed: %s", hcc_code, exc)
        return []
    for r in rows:
        r["required_evidence"] = _coerce_required_evidence(r.get("required_evidence"))
    return rows


def get_pattern(pattern_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT id, pattern_name, description, required_evidence,
               output_hcc, output_icd10, upgrades_from_hcc,
               confidence, source, source_url, model_version, is_active,
               created_at
        FROM kg_comorbidity_patterns
        WHERE id = %s
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (pattern_id,))
            row = cur.fetchone()
    except Exception as exc:
        logger.error("get_pattern(%s) failed: %s", pattern_id, exc)
        return None
    if not row:
        return None
    row["required_evidence"] = _coerce_required_evidence(row.get("required_evidence"))
    return row


def list_patterns(hcc_code: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    where = []
    args: list[Any] = []
    if active_only:
        where.append("is_active = 1")
    if hcc_code:
        where.append("(output_hcc = %s OR upgrades_from_hcc = %s)")
        target = _norm_hcc(hcc_code)
        args.extend([target, target])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT id, pattern_name, description, required_evidence,
               output_hcc, output_icd10, upgrades_from_hcc,
               confidence, source, source_url, model_version, is_active
        FROM kg_comorbidity_patterns
        {where_sql}
        ORDER BY output_hcc, id
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("list_patterns failed: %s", exc)
        return []
    for r in rows:
        r["required_evidence"] = _coerce_required_evidence(r.get("required_evidence"))
    return rows


# ---------------------------------------------------------------------------
# Patient evidence assembly
# ---------------------------------------------------------------------------

def _patient_hccs(patient_id: int, year: int | None) -> list[str]:
    try:
        with raf_cursor() as cur:
            if year:
                cur.execute(
                    "SELECT DISTINCT hcc_code FROM raf_patient_hcc "
                    "WHERE patient_id = %s AND measurement_year = %s",
                    (patient_id, year),
                )
            else:
                cur.execute(
                    "SELECT DISTINCT hcc_code FROM raf_patient_hcc WHERE patient_id = %s",
                    (patient_id,),
                )
            rows = cur.fetchall()
        return [_norm_hcc(r.get("hcc_code")) for r in rows if r.get("hcc_code") is not None]
    except Exception as exc:
        logger.warning("_patient_hccs pid=%s: %s", patient_id, exc)
        return []


def _patient_icds(patient_id: int) -> list[str]:
    try:
        rows = emr.get_billing_codes(patient_id)
    except Exception as exc:
        logger.warning("_patient_icds pid=%s: %s", patient_id, exc)
        return []
    return [_norm_icd(r.get("code")) for r in rows if r.get("code")]


def _patient_atc_codes(patient_id: int) -> list[str]:
    """Resolve ATC drug classes for the patient's active prescriptions.

    Strategy:
      1. Pull RxNorm-coded prescriptions via the existing connector.
      2. JOIN to `raf_rxnorm_atc` if that crosswalk is loaded.
      3. Any ATC values stored directly on the prescription row are also
         honoured (some installs already populate this).
    """
    try:
        meds = emr.get_medications(patient_id)
    except Exception as exc:
        logger.warning("_patient_atc_codes pid=%s med fetch: %s", patient_id, exc)
        return []

    atcs: set[str] = set()
    rxnorms: list[str] = []
    for m in meds or []:
        rx = str(m.get("rxnorm_drugcode") or "").strip()
        if rx:
            rxnorms.append(rx)
        # honour any direct ATC field
        atc = str(m.get("atc_code") or m.get("atc") or "").strip().upper()
        if atc:
            atcs.add(atc)

    if rxnorms:
        try:
            with raf_cursor() as cur:
                placeholders = ",".join(["%s"] * len(rxnorms))
                cur.execute(
                    f"SELECT DISTINCT atc_code FROM raf_rxnorm_atc "
                    f"WHERE rxnorm_code IN ({placeholders})",
                    tuple(rxnorms),
                )
                for r in cur.fetchall():
                    if r.get("atc_code"):
                        atcs.add(str(r["atc_code"]).strip().upper())
        except Exception as exc:
            # Crosswalk table is optional; degrade gracefully.
            logger.debug("_patient_atc_codes: crosswalk unavailable (%s)", exc)
    return sorted(atcs)


def _patient_labs(patient_id: int) -> list[dict[str, Any]]:
    try:
        labs = emr.get_labs(patient_id)
    except Exception as exc:
        logger.warning("_patient_labs pid=%s: %s", patient_id, exc)
        return []
    out: list[dict[str, Any]] = []
    for lab in labs or []:
        out.append({
            "loinc": _norm_loinc(lab.get("result_code")),
            "value": lab.get("value"),
            "date":  lab.get("date"),
            "name":  lab.get("result_text"),
        })
    return out


def assemble_patient_evidence(patient_id: int, year: int | None = None) -> dict[str, Any]:
    """Pull all evidence buckets for a patient.  Used by `evaluate_patient`."""
    return {
        "hccs":      _patient_hccs(patient_id, year),
        "icds":      _patient_icds(patient_id),
        "atc_codes": _patient_atc_codes(patient_id),
        "labs":      _patient_labs(patient_id),
    }


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------

def evaluate_evidence_set(
    evidence: dict[str, Any],
    patterns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run every active pattern against an in-memory evidence dict.

    Parameters
    ----------
    evidence
        ``{"hccs": [...], "icds": [...], "atc_codes": [...], "labs": [...]}``
    patterns
        Optional pre-loaded list (avoids a DB round-trip in tests / batch).
    """
    if patterns is None:
        patterns = _load_active_patterns()

    matches: list[dict[str, Any]] = []
    for p in patterns:
        ok, chain = _pattern_matches(p, evidence)
        if not ok:
            continue
        matches.append({
            "pattern_id":     p.get("id"),
            "pattern_name":   p.get("pattern_name"),
            "description":    p.get("description"),
            "output_hcc":     _norm_hcc(p.get("output_hcc")),
            "output_icd10":   p.get("output_icd10"),
            "upgrades_from":  _norm_hcc(p.get("upgrades_from_hcc")) if p.get("upgrades_from_hcc") else None,
            "confidence":     float(p.get("confidence") or 0.8),
            "source":         p.get("source"),
            "source_url":     p.get("source_url"),
            "model_version":  p.get("model_version") or "V28",
            "evidence_chain": chain,
        })
    # Most-confident first; ties broken by upgrades-first then by output HCC.
    matches.sort(key=lambda m: (-m["confidence"], 0 if m["upgrades_from"] else 1, m["output_hcc"]))
    return matches


def evaluate_patient(patient_id: int, year: int = 2026) -> list[dict[str, Any]]:
    """Run every active pattern against a real patient.

    Returns the list of matches.  Each match contains the output HCC, what
    HCC it upgrades from (if any), confidence, source attribution and the
    full evidence chain.
    """
    evidence = assemble_patient_evidence(patient_id, year=year)
    matches = evaluate_evidence_set(evidence)
    logger.info(
        "comorbidity_engine: pid=%s year=%s matched %d patterns",
        patient_id, year, len(matches),
    )
    # Annotate every match with patient context for downstream consumers.
    for m in matches:
        m["patient_id"] = patient_id
        m["measurement_year"] = year
    return matches


__all__ = [
    "assemble_patient_evidence",
    "evaluate_patient",
    "evaluate_evidence_set",
    "get_patterns_for_hcc",
    "get_pattern",
    "list_patterns",
    "_pattern_matches",
]
