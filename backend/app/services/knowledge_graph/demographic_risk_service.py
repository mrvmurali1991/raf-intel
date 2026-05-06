"""
Demographic risk modulation service.

CMS' RAF segments (CNA / CFA / CPA / ...) are coarse: e.g. a single
"community, full-benefit-dual, aged 65-69" coefficient covers every member
in that bucket regardless of sex, prior comorbidities, or institutional
status.  For SUSPECT-DETECTION PRIORS we want finer modulation —
a 67-year-old female dual-eligible with prior CHF coding has a higher prior
probability of CKD than a 67-year-old male non-dual with no history.

This service computes a modulated prior on top of the existing CMS
coefficient.  It is **never** used by the official RAF calculator — that
remains in ``app.services.raf.calculator`` / ``raf_calculator.py`` and
must report exactly what CMS will pay on.

Usage::

    from app.services.knowledge_graph import demographic_risk_service as drs

    result = drs.compute_modulated_prior(
        hcc_code="138",
        patient_demo={"age": 78, "sex": "F", "dual_status": "dual"},
        prior_hccs=["18"],
    )
    # -> {"base_prior": 0.5, "multiplier": 2.1, "modulated_prior": 1.0,
    #     "factors_applied": [{"factor": "age 75+ conditional on HCC 18", ...}]}

The base prior is the CMS coefficient looked up from
``hcc_raf_coefficients``.  Multipliers are looked up from
``kg_demographic_risk_factors`` and **compounded** when multiple rows
match.  Match logic:

  - ``age``               : ``age_min <= age <= age_max``
  - ``sex``               : NULL row matches everyone, else exact match
  - ``dual_status``       : ``any`` matches everyone, else exact match
  - ``disabled``          : NULL row ignores attribute, else exact match (0/1)
  - ``institutional``     : NULL row ignores attribute, else exact match (0/1)
  - ``conditional_on_hccs``: NULL row is unconditional; else patient must
    have AT LEAST ONE of the listed HCCs in ``prior_hccs``.

Multipliers compound multiplicatively — a 1.4x age/sex factor and a 1.5x
comorbidity factor combine to 2.1x.  This matches how Navina-style
suspect-priors layer evidence: each factor independently shifts the
prior odds.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# CMS V28 default model segment used when patient demo does not specify one.
# Conservative — community, non-dual, aged.
DEFAULT_MODEL_SEGMENT: str = "CNA"

# Coefficient table is curated for model_year 2024.
DEFAULT_COEFFICIENT_YEAR: int = 2024

# When a multiplier compounding result blows up due to bad data, clamp it.
MAX_COMPOUNDED_MULTIPLIER: float = 10.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_hcc(code: Any) -> str:
    """Strip "HCC" prefix / whitespace; return canonical string code."""
    if code is None:
        return ""
    s = str(code).strip().upper()
    if s.startswith("HCC"):
        s = s[3:].strip()
    return s.lstrip("0") or "0"


def _normalise_dual(value: Any) -> str:
    """
    Coerce arbitrary dual_status inputs into one of {"dual", "non_dual", "any"}.

    Accepts True/False, numeric flags, common string variants.  Unknown
    inputs default to "any" so a missing demographic does not over-fire.
    """
    if value is None:
        return "any"
    if isinstance(value, bool):
        return "dual" if value else "non_dual"
    if isinstance(value, (int, float)):
        return "dual" if int(value) == 1 else "non_dual"
    s = str(value).strip().lower()
    if s in ("dual", "full_dual", "partial_dual", "fbd", "pbd", "1", "true", "yes"):
        return "dual"
    if s in ("non_dual", "non-dual", "nondual", "0", "false", "no"):
        return "non_dual"
    return "any"


def _normalise_sex(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in ("M", "MALE"):
        return "M"
    if s in ("F", "FEMALE"):
        return "F"
    if s in ("U", "UNK", "UNKNOWN"):
        return "U"
    return None


def _normalise_bool_flag(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) == 1 else 0
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return 1
    if s in ("0", "false", "no", "n"):
        return 0
    return None


def _parse_conditional_hccs(raw: Any) -> list[str]:
    """JSON column may be returned as str (from MySQL) or already decoded."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [_normalise_hcc(c) for c in raw if c is not None]
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                return [_normalise_hcc(c) for c in decoded if c is not None]
        except (ValueError, TypeError):
            return []
    return []


def _row_matches(
    row: dict[str, Any],
    *,
    age: int | None,
    sex: str | None,
    dual_status: str,
    disabled: int | None,
    institutional: int | None,
    prior_hccs_normalised: set[str],
) -> bool:
    """Return True iff the row's filter columns are satisfied by the patient."""
    # Age range
    if age is not None:
        try:
            age_min = int(row.get("age_min") or 0)
            age_max = int(row.get("age_max") or 120)
            if not (age_min <= age <= age_max):
                return False
        except (TypeError, ValueError):
            return False
    # Sex (NULL row -> matches anyone; else exact match required)
    row_sex = row.get("sex")
    if row_sex is not None and sex is not None and row_sex != sex:
        return False
    # Dual status: "any" row matches anyone; else must equal patient
    row_dual = (row.get("dual_status") or "any").lower()
    if row_dual not in ("any", "") and row_dual != dual_status:
        return False
    # Disabled flag.  Row NULL = applies to anyone; row 0/1 requires the
    # patient to have that exact value.  When the row REQUIRES a specific
    # value but the patient demographic is missing, the row does NOT match
    # (we never fire a constrained row on unknown demographics).
    row_disabled = row.get("disabled")
    if row_disabled is not None:
        if disabled is None or int(row_disabled) != disabled:
            return False
    # Institutional flag — same semantics as disabled.
    row_inst = row.get("institutional")
    if row_inst is not None:
        if institutional is None or int(row_inst) != institutional:
            return False
    # Comorbidity condition: NULL = unconditional, else need overlap
    cond = _parse_conditional_hccs(row.get("conditional_on_hccs"))
    if cond:
        if not prior_hccs_normalised:
            return False
        if not any(c in prior_hccs_normalised for c in cond):
            return False
    return True


def _format_factor_label(row: dict[str, Any]) -> str:
    """Human-readable label for a matched factor row, used in factors_applied."""
    parts: list[str] = []
    age_min = row.get("age_min")
    age_max = row.get("age_max")
    if age_min is not None and age_max is not None:
        if int(age_max) >= 120:
            parts.append(f"age {int(age_min)}+")
        elif int(age_min) <= 0:
            parts.append(f"age <= {int(age_max)}")
        else:
            parts.append(f"age {int(age_min)}-{int(age_max)}")
    if row.get("sex"):
        parts.append(f"sex={row['sex']}")
    dual = (row.get("dual_status") or "any").lower()
    if dual not in ("any", ""):
        parts.append(dual)
    if row.get("disabled") is not None:
        parts.append(f"disabled={int(row['disabled'])}")
    if row.get("institutional") is not None:
        parts.append(f"institutional={int(row['institutional'])}")
    cond = _parse_conditional_hccs(row.get("conditional_on_hccs"))
    if cond:
        parts.append("conditional_on_hccs=[" + ",".join(cond) + "]")
    return ", ".join(parts) or "unconditional"


# ---------------------------------------------------------------------------
# Coefficient lookup (re-used by raf_forecast - kept private here to avoid
# circular imports).
# ---------------------------------------------------------------------------

def _baseline_cms_coefficient(
    hcc_code: str,
    *,
    model_segment: str,
    model_year: int,
) -> float:
    """
    Look up the official CMS RAF coefficient for the (hcc, segment, year)
    triple.  Returns 0.0 when no row exists.

    This is the BASELINE prior — the modulated prior is this value times the
    compounded multiplier from kg_demographic_risk_factors.
    """
    try:
        int_code = int(_normalise_hcc(hcc_code))
    except ValueError:
        return 0.0
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT coefficient
                FROM hcc_raf_coefficients
                WHERE hcc_code      = %s
                  AND model_segment = %s
                  AND model_year    = %s
                LIMIT 1
                """,
                (int_code, model_segment, model_year),
            )
            row = cur.fetchone()
        if row and row.get("coefficient") is not None:
            return float(row["coefficient"])
    except Exception as exc:
        logger.debug(
            "_baseline_cms_coefficient hcc=%s seg=%s yr=%s: %s",
            hcc_code, model_segment, model_year, exc,
        )
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_risk_factors(hcc_code: str) -> list[dict[str, Any]]:
    """
    Return every active demographic risk factor row for the given HCC.

    Used by the inspect-able admin UI / unit tests.  Inactive rows are
    excluded.  conditional_on_hccs is decoded to a real Python list.
    """
    code = _normalise_hcc(hcc_code)
    if not code:
        return []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, hcc_code, age_min, age_max, sex, dual_status,
                       disabled, institutional, prior_multiplier,
                       conditional_on_hccs, source, source_notes,
                       is_active, created_at
                FROM kg_demographic_risk_factors
                WHERE hcc_code = %s AND is_active = 1
                ORDER BY id
                """,
                (code,),
            )
            rows = list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning("get_risk_factors hcc=%s failed: %s", code, exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": int(r["id"]),
            "hcc_code": r["hcc_code"],
            "age_min": int(r["age_min"]) if r.get("age_min") is not None else None,
            "age_max": int(r["age_max"]) if r.get("age_max") is not None else None,
            "sex": r.get("sex"),
            "dual_status": r.get("dual_status") or "any",
            "disabled": int(r["disabled"]) if r.get("disabled") is not None else None,
            "institutional": int(r["institutional"]) if r.get("institutional") is not None else None,
            "prior_multiplier": float(r["prior_multiplier"] or 1.0),
            "conditional_on_hccs": _parse_conditional_hccs(r.get("conditional_on_hccs")),
            "source": r.get("source") or "",
            "source_notes": r.get("source_notes") or "",
            "is_active": bool(r.get("is_active", 1)),
        })
    return out


def compute_modulated_prior(
    hcc_code: str,
    patient_demo: dict[str, Any] | None = None,
    prior_hccs: Iterable[str] | None = None,
    *,
    model_segment: str = DEFAULT_MODEL_SEGMENT,
    model_year: int = DEFAULT_COEFFICIENT_YEAR,
    base_prior_override: float | None = None,
) -> dict[str, Any]:
    """
    Compute the demographically-modulated suspect prior for one HCC.

    Parameters
    ----------
    hcc_code : str
        HCC whose prior is being modulated (e.g. "138" for CKD).
    patient_demo : dict
        Recognised keys: ``age`` (int), ``sex`` ("M"/"F"/"U"),
        ``dual_status`` ("dual"/"non_dual"/"any"), ``disabled`` (0/1),
        ``institutional`` (0/1).  Missing keys are treated as wildcards —
        in that case only rows with NULL/'any' for the missing dimension
        match.
    prior_hccs : iterable of str
        HCCs the patient is already known to carry.  Used to fire
        comorbidity-conditioned multipliers.
    model_segment : str
        CMS model segment for baseline coefficient lookup.  Defaults to
        ``CNA``.
    model_year : int
        Coefficient table model_year.  Defaults to 2024.
    base_prior_override : float, optional
        If provided, skip the DB lookup and use this as the baseline.
        Lets the caller plug in a confidence score / suspect-engine prior
        and have it modulated by the same demographic factors.

    Returns
    -------
    dict::

        {
          "hcc_code": "138",
          "base_prior": 0.500,
          "multiplier": 2.100,
          "modulated_prior": 1.050,
          "model_segment": "CNA",
          "model_year": 2024,
          "factors_applied": [
            {"factor": "age 75+, conditional_on_hccs=[18]",
             "value": 2.1,
             "source": "MEDPAR-2023",
             "id": 17},
            ...
          ],
          "factor_count": 1,
        }

    Missing demographics never raise — they default to a 1.0x multiplier.
    """
    code = _normalise_hcc(hcc_code)
    demo = patient_demo or {}
    age_raw = demo.get("age")
    try:
        age = int(age_raw) if age_raw is not None else None
    except (TypeError, ValueError):
        age = None
    sex = _normalise_sex(demo.get("sex"))
    dual_status = _normalise_dual(demo.get("dual_status"))
    disabled = _normalise_bool_flag(demo.get("disabled"))
    institutional = _normalise_bool_flag(demo.get("institutional"))

    prior_hccs_normalised: set[str] = {
        _normalise_hcc(c) for c in (prior_hccs or []) if c is not None
    }

    # 1. Baseline prior --------------------------------------------------------
    if base_prior_override is not None:
        try:
            base_prior = float(base_prior_override)
        except (TypeError, ValueError):
            base_prior = 0.0
    else:
        base_prior = _baseline_cms_coefficient(
            code,
            model_segment=model_segment,
            model_year=model_year,
        )

    # 2. Match all active rows for this HCC ------------------------------------
    multiplier = 1.0
    factors_applied: list[dict[str, Any]] = []

    for row in get_risk_factors(code):
        # get_risk_factors returns plain dicts already; reuse the same shape
        # for matching.  Cast multiplier columns back to float.
        if not _row_matches(
            row,
            age=age,
            sex=sex,
            dual_status=dual_status,
            disabled=disabled,
            institutional=institutional,
            prior_hccs_normalised=prior_hccs_normalised,
        ):
            continue
        m = float(row.get("prior_multiplier") or 1.0)
        if m <= 0:
            continue
        multiplier *= m
        factors_applied.append({
            "id": row.get("id"),
            "factor": _format_factor_label(row),
            "value": round(m, 4),
            "source": row.get("source", ""),
        })

    # Defensive clamp — bad seed data should never blow up downstream
    if multiplier > MAX_COMPOUNDED_MULTIPLIER:
        logger.warning(
            "compute_modulated_prior hcc=%s clamped multiplier %.4f -> %.4f",
            code, multiplier, MAX_COMPOUNDED_MULTIPLIER,
        )
        multiplier = MAX_COMPOUNDED_MULTIPLIER

    modulated = base_prior * multiplier

    return {
        "hcc_code": code,
        "base_prior": round(base_prior, 4),
        "multiplier": round(multiplier, 4),
        "modulated_prior": round(modulated, 4),
        "model_segment": model_segment,
        "model_year": model_year,
        "factors_applied": factors_applied,
        "factor_count": len(factors_applied),
    }


def compute_panel_priors(
    provider_id: int | str,
    year: int,
    hcc_codes: list[str],
) -> dict[str, Any]:
    """
    Bulk modulated-prior computation for a provider's panel.

    For every patient on the provider's panel and every HCC in
    ``hcc_codes`` returns the modulated prior + factor breakdown.  This
    is the entry point used by suspect-engine batch jobs.

    The provider->panel mapping mirrors raf_forecast._provider_panel:
    OpenEMR's ``form_encounter`` is treated as the source of truth until
    a dedicated provider_patients table exists.

    Returns shape::

        {
          "provider_id": 5,
          "year": 2026,
          "patient_count": 12,
          "hcc_codes": ["138", "226"],
          "by_patient": [
            {"patient_id": 101,
             "demo": {"age": 78, "sex": "F", "dual_status": "dual"},
             "priors": {
               "138": {"base_prior": ..., "multiplier": ..., ...},
               "226": {...},
             }},
            ...
          ],
        }
    """
    pids = _provider_panel(provider_id)
    by_patient: list[dict[str, Any]] = []

    for pid in pids:
        demo = _patient_demographics(pid, year)
        prior_hccs = _patient_prior_hccs(pid, year)
        priors: dict[str, Any] = {}
        for hcc in hcc_codes:
            try:
                priors[_normalise_hcc(hcc)] = compute_modulated_prior(
                    hcc_code=hcc,
                    patient_demo=demo,
                    prior_hccs=prior_hccs,
                    model_segment=demo.get("model_segment") or DEFAULT_MODEL_SEGMENT,
                    model_year=year if year >= 2020 else DEFAULT_COEFFICIENT_YEAR,
                )
            except Exception as exc:
                logger.warning(
                    "compute_panel_priors pid=%s hcc=%s failed: %s",
                    pid, hcc, exc,
                )
        by_patient.append({
            "patient_id": pid,
            "demo": demo,
            "priors": priors,
        })

    return {
        "provider_id": provider_id,
        "year": year,
        "patient_count": len(by_patient),
        "hcc_codes": [_normalise_hcc(c) for c in hcc_codes],
        "by_patient": by_patient,
    }


# ---------------------------------------------------------------------------
# Provider/patient helpers (read-only, best-effort)
# ---------------------------------------------------------------------------

def _provider_panel(provider_id: int | str) -> list[int]:
    """Best-effort: resolve a provider's panel via OpenEMR encounters."""
    try:
        from app.db import openemr_cursor
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT pid
                FROM form_encounter
                WHERE provider_id = %s
                """,
                (provider_id,),
            )
            rows = cur.fetchall() or []
        return [int(r["pid"]) for r in rows if r.get("pid") is not None]
    except Exception as exc:
        logger.debug("_provider_panel provider=%s: %s", provider_id, exc)
        return []


def _patient_demographics(patient_id: int, year: int) -> dict[str, Any]:
    """
    Pull stored RAF demographics + age for a patient.  Returns empty dict
    on lookup failure so downstream calls degrade gracefully.
    """
    out: dict[str, Any] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT age_at_year_end, sex, dual_status, disabled,
                       institutional, model_segment
                FROM raf_patient_demographics
                WHERE patient_id = %s AND measurement_year = %s
                LIMIT 1
                """,
                (patient_id, year),
            )
            row = cur.fetchone()
        if row:
            out = {
                "age": row.get("age_at_year_end"),
                "sex": row.get("sex"),
                "dual_status": row.get("dual_status"),
                "disabled": row.get("disabled"),
                "institutional": row.get("institutional"),
                "model_segment": row.get("model_segment"),
            }
    except Exception as exc:
        logger.debug("_patient_demographics pid=%s: %s", patient_id, exc)
    return out


def _patient_prior_hccs(patient_id: int, year: int) -> list[str]:
    """Distinct HCCs the patient was coded with in the prior year."""
    prior = year - 1
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT hcc_code
                FROM raf_patient_hcc
                WHERE patient_id = %s AND measurement_year = %s
                """,
                (patient_id, prior),
            )
            rows = cur.fetchall() or []
        return [_normalise_hcc(r["hcc_code"]) for r in rows if r.get("hcc_code") is not None]
    except Exception as exc:
        logger.debug("_patient_prior_hccs pid=%s: %s", patient_id, exc)
        return []
