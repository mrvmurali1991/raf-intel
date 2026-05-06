"""
Specialty-specific HCC priors.

A cardiologist's panel has a different HCC mix than a primary-care panel.
A patient seen by a cardiologist with "chest pain" has a much higher
prior probability of CHF / AFib / AMI / valvular disease than the same
patient seen by a generalist.  This module models that.

Tables
------
kg_specialty_hcc_priors  - canonical_specialty + hcc_code -> prior_weight
kg_specialty_aliases     - free-text raw specialty -> canonical specialty

Public API
----------
canonicalize(raw_specialty)                     -> str
get_priors_for_specialty(specialty)             -> list[dict]
apply_specialty_prior(specialty, hcc, base)     -> dict
compute_provider_calibrated_priors(provider_id) -> dict
top_n_likely_hccs(specialty, n)                 -> list[dict]

The service is read-mostly; all writes happen through the seed script.
Returned values use plain ``float`` and ``str`` (no Decimal) so they are
JSON-serialisable directly from FastAPI.
"""
from __future__ import annotations

import logging
import re
from difflib import get_close_matches
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default multiplier used when no specialty-specific prior is defined.
#: A value of 1.0 means "no adjustment vs baseline".
BASELINE_PRIOR_WEIGHT: float = 1.0

#: Minimum similarity ratio for fuzzy alias matching (0.0 - 1.0).
_FUZZY_MATCH_CUTOFF: float = 0.78

#: Specialties known to be valid canonical names.  Used as the haystack for
#: fuzzy matches when no row in kg_specialty_aliases matches.  Kept in code
#: (and not loaded dynamically) so canonicalize() works even on an empty DB.
KNOWN_CANONICAL_SPECIALTIES: tuple[str, ...] = (
    "Internal Medicine",
    "Family Medicine",
    "Geriatrics",
    "Cardiology",
    "Nephrology",
    "Pulmonology",
    "Endocrinology",
    "Psychiatry",
    "Oncology",
    "Gastroenterology",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise_raw(raw: str) -> str:
    """Trim, collapse whitespace.  Case is preserved for display but the
    DB lookup uses LOWER() so callers do not need to worry about case."""
    if not raw:
        return ""
    return _WHITESPACE_RE.sub(" ", raw.strip())


def _normalise_hcc(hcc_code: str | int) -> str:
    """Strip leading 'HCC' and whitespace.  The priors table stores the
    bare numeric / alphanumeric HCC code (e.g. '226', '136'), matching how
    it is stored elsewhere in this codebase."""
    s = str(hcc_code).strip().upper()
    if s.startswith("HCC"):
        s = s[3:].strip()
    # Strip any leading zeros so '019' and '19' compare equal.
    s = s.lstrip("0") or "0"
    return s


# ---------------------------------------------------------------------------
# canonicalize
# ---------------------------------------------------------------------------

def canonicalize(raw_specialty: str) -> str:
    """
    Resolve a raw specialty string to its canonical form.

    Resolution order:
      1. Exact match in kg_specialty_aliases (case-insensitive).
      2. Exact match against KNOWN_CANONICAL_SPECIALTIES (case-insensitive).
      3. Fuzzy match (difflib) against canonical names + alias raw values.

    Returns the original (whitespace-normalised) input if nothing matched,
    so downstream callers always get a non-empty string for a non-empty input.
    """
    cleaned = _normalise_raw(raw_specialty)
    if not cleaned:
        return ""

    lowered = cleaned.lower()

    # 1) DB alias table (case-insensitive)
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT canonical_specialty
                FROM kg_specialty_aliases
                WHERE LOWER(raw_specialty) = %s
                LIMIT 1
                """,
                (lowered,),
            )
            row = cur.fetchone()
            if row:
                return row["canonical_specialty"]
    except Exception as exc:  # pragma: no cover — DB unreachable in CI
        logger.warning("canonicalize: alias lookup failed for %r: %s", cleaned, exc)

    # 2) Direct match against the in-code canonical list
    for canonical in KNOWN_CANONICAL_SPECIALTIES:
        if canonical.lower() == lowered:
            return canonical

    # 3) Fuzzy match — try canonical names first, then any other alias rows
    haystack = list(KNOWN_CANONICAL_SPECIALTIES)
    canonical_by_lower: dict[str, str] = {c.lower(): c for c in KNOWN_CANONICAL_SPECIALTIES}

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT raw_specialty, canonical_specialty
                FROM kg_specialty_aliases
                """
            )
            for r in cur.fetchall() or []:
                haystack.append(r["raw_specialty"])
                canonical_by_lower[r["raw_specialty"].lower()] = r["canonical_specialty"]
    except Exception as exc:  # pragma: no cover
        logger.debug("canonicalize: alias scan failed: %s", exc)

    matches = get_close_matches(cleaned, haystack, n=1, cutoff=_FUZZY_MATCH_CUTOFF)
    if matches:
        match = matches[0]
        return canonical_by_lower.get(match.lower(), match)

    # 4) Give up — return the cleaned original so callers can still log it
    return cleaned


# ---------------------------------------------------------------------------
# get_priors_for_specialty
# ---------------------------------------------------------------------------

def get_priors_for_specialty(specialty: str) -> list[dict[str, Any]]:
    """
    Return all active HCC priors for *specialty*.

    The input is canonicalised first so callers can pass raw EHR values.
    Each row contains: hcc_code, prior_weight, panel_prevalence_pct,
    source, notes.
    """
    canonical = canonicalize(specialty)
    if not canonical:
        return []

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT hcc_code, prior_weight, panel_prevalence_pct, source, notes
            FROM kg_specialty_hcc_priors
            WHERE specialty = %s AND is_active = 1
            ORDER BY prior_weight DESC, hcc_code ASC
            """,
            (canonical,),
        )
        rows = cur.fetchall() or []

    return [
        {
            "specialty": canonical,
            "hcc_code": str(r["hcc_code"]),
            "prior_weight": float(r["prior_weight"]),
            "panel_prevalence_pct": (
                float(r["panel_prevalence_pct"])
                if r["panel_prevalence_pct"] is not None
                else None
            ),
            "source": r["source"],
            "notes": r.get("notes"),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# apply_specialty_prior
# ---------------------------------------------------------------------------

def apply_specialty_prior(
    specialty: str,
    hcc_code: str | int,
    base_score: float,
) -> dict[str, Any]:
    """
    Multiply *base_score* by the specialty-specific prior weight for
    *hcc_code* and return the adjusted score together with reasoning.

    A missing (specialty, hcc_code) pair yields prior_weight = 1.0 so
    callers always get a sensible fallback.

    Returned dict::

        {
            "specialty":        "Nephrology",       # canonicalised
            "hcc_code":         "138",
            "base_score":       0.50,
            "prior_weight":     8.0,
            "adjusted_score":   4.0,
            "applied":          True,
            "source":           "curated",
            "reason":           "Nephrology panel: 8.00x baseline for HCC 138 ...",
        }
    """
    canonical = canonicalize(specialty)
    norm_hcc = _normalise_hcc(hcc_code)

    weight = BASELINE_PRIOR_WEIGHT
    source: str | None = None
    notes: str | None = None
    applied = False

    if canonical and norm_hcc:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT prior_weight, source, notes
                FROM kg_specialty_hcc_priors
                WHERE specialty = %s AND hcc_code = %s AND is_active = 1
                LIMIT 1
                """,
                (canonical, norm_hcc),
            )
            row = cur.fetchone()
            if row:
                weight = float(row["prior_weight"])
                source = row["source"]
                notes = row.get("notes")
                applied = True

    base = float(base_score)
    adjusted = round(base * weight, 6)

    if applied:
        reason = (
            f"{canonical} panel: {weight:.2f}x baseline for HCC {norm_hcc} "
            f"(source: {source})"
        )
    else:
        reason = (
            f"No specialty prior for ({canonical or 'unknown'}, HCC {norm_hcc}); "
            f"using baseline weight {BASELINE_PRIOR_WEIGHT:.2f}x"
        )

    return {
        "specialty": canonical,
        "hcc_code": norm_hcc,
        "base_score": base,
        "prior_weight": weight,
        "adjusted_score": adjusted,
        "applied": applied,
        "source": source,
        "notes": notes,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# top_n_likely_hccs
# ---------------------------------------------------------------------------

def top_n_likely_hccs(specialty: str, n: int = 10) -> list[dict[str, Any]]:
    """
    Return the *n* HCCs with the highest prior weight for *specialty*.

    These are the conditions an AWV / chart-prep workflow should
    proactively look for when the patient is seen by this specialty.
    """
    if n <= 0:
        return []

    canonical = canonicalize(specialty)
    if not canonical:
        return []

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT hcc_code, prior_weight, panel_prevalence_pct, source, notes
            FROM kg_specialty_hcc_priors
            WHERE specialty = %s AND is_active = 1
            ORDER BY prior_weight DESC, panel_prevalence_pct DESC, hcc_code ASC
            LIMIT %s
            """,
            (canonical, int(n)),
        )
        rows = cur.fetchall() or []

    return [
        {
            "specialty": canonical,
            "hcc_code": str(r["hcc_code"]),
            "prior_weight": float(r["prior_weight"]),
            "panel_prevalence_pct": (
                float(r["panel_prevalence_pct"])
                if r["panel_prevalence_pct"] is not None
                else None
            ),
            "source": r["source"],
            "notes": r.get("notes"),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# compute_provider_calibrated_priors
# ---------------------------------------------------------------------------

def compute_provider_calibrated_priors(provider_id: int) -> dict[str, Any]:
    """
    Return the full calibrated HCC prior set for *provider_id*.

    Looks up the provider's free-text specialty in the ``providers`` table,
    canonicalises it, and returns every active prior row plus the top-10
    most-likely HCCs for that specialty.

    The shape is::

        {
            "provider_id": 17,
            "raw_specialty": "Cards",
            "canonical_specialty": "Cardiology",
            "prior_count": 25,
            "priors": [...],
            "top_likely": [...]
        }

    If the provider does not exist or has no specialty recorded, the
    response still returns an empty priors list rather than raising —
    upstream callers can choose how to fall back.
    """
    raw_specialty: str | None = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT specialty FROM providers WHERE id = %s LIMIT 1",
                (int(provider_id),),
            )
            row = cur.fetchone()
            if row:
                raw_specialty = row.get("specialty")
    except Exception as exc:
        # The providers table may not exist in every environment (e.g. unit
        # tests against a schema-only DB).  Surface the error in logs but
        # still return a structured response.
        logger.warning(
            "compute_provider_calibrated_priors: providers lookup failed for id=%s: %s",
            provider_id,
            exc,
        )

    canonical = canonicalize(raw_specialty or "")
    priors = get_priors_for_specialty(canonical) if canonical else []
    top_likely = top_n_likely_hccs(canonical, n=10) if canonical else []

    return {
        "provider_id": int(provider_id),
        "raw_specialty": raw_specialty,
        "canonical_specialty": canonical or None,
        "prior_count": len(priors),
        "priors": priors,
        "top_likely": top_likely,
    }


# ---------------------------------------------------------------------------
# Convenience: bulk apply (used by the AWV ranker integration helper)
# ---------------------------------------------------------------------------

def apply_priors_to_scores(
    specialty: str,
    scored_hccs: list[dict[str, Any]],
    *,
    score_key: str = "score",
    out_key: str = "specialty_adjusted_score",
) -> list[dict[str, Any]]:
    """
    Annotate every entry in *scored_hccs* with a specialty-adjusted score.

    Each input dict must contain ``hcc_code`` and the field named by
    ``score_key`` (default ``"score"``).  The function returns a *new* list
    of shallow-copied dicts with two extra fields::

        {
            ...,
            "<out_key>":   <adjusted score>,
            "specialty_prior": {prior_weight, applied, source, ...},
        }

    Inputs are not mutated.  Used by the AWV-prioritisation integration
    helper but exposed publicly so other rankers can re-use it.
    """
    canonical = canonicalize(specialty)
    out: list[dict[str, Any]] = []
    for entry in scored_hccs:
        new_entry = dict(entry)
        base = float(new_entry.get(score_key, 0.0) or 0.0)
        applied = apply_specialty_prior(
            canonical or specialty,
            new_entry.get("hcc_code", ""),
            base,
        )
        new_entry[out_key] = applied["adjusted_score"]
        new_entry["specialty_prior"] = {
            k: applied[k]
            for k in ("specialty", "prior_weight", "applied", "source", "reason")
        }
        out.append(new_entry)
    # Sort highest adjusted score first to keep downstream UI ordering sane
    out.sort(key=lambda e: e.get(out_key, 0.0), reverse=True)
    return out
