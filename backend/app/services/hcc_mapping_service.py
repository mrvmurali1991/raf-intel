"""
hcc_mapping_service.py

Single canonical source of truth for ICD-10 → HCC mapping in RAF Intelligence.

ALL application code that needs to map ICD-10 codes to HCC condition categories
MUST use this module rather than querying the ``hcc_icd10_crosswalk`` database
table directly or calling hccinfhir data structures ad-hoc.

Design rationale
----------------
Two historical code paths produced HCC mappings independently:

1. ``encounter_normalization_service._build_icd10_hcc_map()``
   Read the ``hcc_icd10_crosswalk`` database table — a static snapshot that
   could silently lag behind CMS model updates (e.g., V24 → V28 transition).

2. ``raf_calculator`` / ``hccinfhir_utils``
   Called the ``hccinfhir`` library directly at calculation time.

When those two sources disagreed a patient could be assigned different HCC
codes depending on which code path ran — a $5K–$25K per-member-per-year
revenue risk. This module eliminates that divergence by making ``hccinfhir``
the single authoritative mapping engine for the entire application.

The ``hcc_icd10_crosswalk`` table still exists and is supported for caching
and reporting purposes.  ``refresh_crosswalk_table()`` can regenerate it from
hccinfhir at any time, and ``reconcile_crosswalk()`` will surface any rows
that have drifted.  Neither function is consulted during scoring.

Public API
----------
map_icd10_to_hcc(icd10_code, model_version) -> dict | None
    Authoritative single-code lookup.

map_icd10_batch(icd10_codes, model_version) -> dict[str, dict]
    Authoritative batch lookup; preferred for ETL loops.

refresh_crosswalk_table(tenant_id)
    Regenerate ``hcc_icd10_crosswalk`` from hccinfhir (reporting/caching only).

reconcile_crosswalk(tenant_id) -> list[dict]
    Detect rows in ``hcc_icd10_crosswalk`` that disagree with hccinfhir.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.hccinfhir_utils import (
    lookup_hcc,
    lookup_hcc_batch,
    get_hcc_label,
    get_hcc_coefficient as _get_hcc_coefficient_raw,
    DEFAULT_MODEL,
)
from app.db import get_raf_db, raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model version helpers
# ---------------------------------------------------------------------------

# Map the short version strings used throughout the app to hccinfhir ModelName
# strings.  Extend this dict when new models are added.
_MODEL_VERSION_MAP: dict[str, str] = {
    "V28": "CMS-HCC Model V28",
    "V24": "CMS-HCC Model V24",
    # Allow callers to pass the full name through unchanged.
    "CMS-HCC Model V28": "CMS-HCC Model V28",
    "CMS-HCC Model V24": "CMS-HCC Model V24",
}


def _resolve_model(model_version: str) -> str:
    """Translate a short model version string to the hccinfhir ModelName.

    Raises ValueError if the version is not recognised, so callers get an
    immediate, actionable error rather than a silent wrong-model lookup.
    """
    resolved = _MODEL_VERSION_MAP.get(model_version)
    if resolved is None:
        raise ValueError(
            f"Unknown model_version {model_version!r}. "
            f"Valid values: {sorted(_MODEL_VERSION_MAP)}"
        )
    return resolved


# ---------------------------------------------------------------------------
# Authoritative mapping functions (hccinfhir as the single source of truth)
# ---------------------------------------------------------------------------

def map_icd10_to_hcc(
    icd10_code: str,
    model_version: str = "V28",
) -> Optional[dict]:
    """Map a single ICD-10 code to its HCC condition category using hccinfhir.

    This is the authoritative lookup for the entire application.  Do NOT use
    the ``hcc_icd10_crosswalk`` table to make scoring decisions; use this
    function instead.

    Args:
        icd10_code: ICD-10-CM code, e.g. ``"E1169"`` or ``"E11.69"``.
                    Normalised to uppercase with the dot removed before lookup,
                    matching the format CMS publishes.
        model_version: Short model version string.  Accepted values:
                       ``"V28"`` (default, current CMS model) or ``"V24"``.

    Returns:
        ``None`` if the code does not map to any HCC in the requested model.

        Otherwise a dict with keys:

        ``icd10_code``
            Normalised input code (str).
        ``hcc_code``
            Primary HCC condition category number as a string, e.g. ``"37"``.
            When a code maps to multiple CCs the lowest-numbered one is
            returned here for compatibility with the ``normalized_diagnoses``
            schema (single ``hcc_code`` column).  All mapped CCs are
            available in ``hcc_codes``.
        ``hcc_codes``
            Full list of CC numbers this ICD-10 maps to (list[str]).
        ``model_version``
            Short model version string, e.g. ``"V28"`` (str).
        ``model``
            Full hccinfhir model name string (str).
    """
    model = _resolve_model(model_version)
    # Normalise input to CMS publication format: strip dots, uppercase.
    # hccinfhir keys dx_to_cc by dot-less codes (e.g. "E119" not "E11.9"),
    # so dotted inputs like "E11.9" would silently return no mapping here.
    normalised = icd10_code.strip().upper().replace(".", "")
    result = lookup_hcc(normalised, model=model)  # type: ignore[arg-type]

    if not result["maps_to_hcc"]:
        return None

    hcc_codes: list[str] = result["hcc_codes"]
    return {
        "icd10_code": result["icd10_code"],
        "hcc_code": hcc_codes[0],       # primary (lowest-numbered CC)
        "hcc_codes": hcc_codes,
        "model_version": model_version,
        "model": model,
    }


def map_icd10_batch(
    icd10_codes: list[str],
    model_version: str = "V28",
) -> dict[str, dict]:
    """Map a list of ICD-10 codes to HCC mappings using hccinfhir.

    Preferred for ETL loops where many codes are processed in one pass —
    avoids the per-call overhead of repeated ``map_icd10_to_hcc`` invocations
    while keeping the same hccinfhir engine as the authoritative source.

    Args:
        icd10_codes: List of ICD-10-CM codes.
        model_version: Short model version string (default ``"V28"``).

    Returns:
        Dict keyed by the normalised ICD-10 code.  Codes that do not map to
        any HCC are **omitted** from the result so callers can use
        ``result.get(code, {})`` to get an empty dict for non-mapping codes.

        Each value has the same structure as ``map_icd10_to_hcc()``.
    """
    model = _resolve_model(model_version)
    # Normalise every input to the dot-less uppercase CMS format before
    # hitting hccinfhir so callers can pass either "E11.9" or "E119".
    normalised_inputs = [c.strip().upper().replace(".", "") for c in icd10_codes]
    raw_results = lookup_hcc_batch(normalised_inputs, model=model)  # type: ignore[arg-type]

    mapping: dict[str, dict] = {}
    for result in raw_results:
        if not result["maps_to_hcc"]:
            continue
        hcc_codes: list[str] = result["hcc_codes"]
        normalised_code: str = result["icd10_code"]
        mapping[normalised_code] = {
            "icd10_code": normalised_code,
            "hcc_code": hcc_codes[0],
            "hcc_codes": hcc_codes,
            "model_version": model_version,
            "model": model,
        }

    return mapping


# ---------------------------------------------------------------------------
# HCC metadata helpers
# ---------------------------------------------------------------------------

def get_hcc_description(
    hcc_code: int,
    model_version: str = "V28",
) -> str:
    """Return the human-readable description for an HCC condition category.

    Args:
        hcc_code: HCC condition category number as an integer, e.g. ``37``.
        model_version: Short model version string.  Accepted values:
                       ``"V28"`` (default) or ``"V24"``.

    Returns:
        Label string, or an empty string if the HCC code is not found in the
        requested model.
    """
    model = _resolve_model(model_version)
    return get_hcc_label(str(hcc_code), model=model)  # type: ignore[arg-type]


# CMS demographic segment prefixes supported by hccinfhir.
# Segment codes follow the CMS payment model naming convention.
_SEGMENT_TO_PREFIX: dict[str, str] = {
    # Community Non-Dual
    "CNA": "CNA_",   # Community Non-Dual Aged
    "CND": "CND_",   # Community Non-Dual Disabled
    # Community Full Dual
    "CFA": "CFA_",   # Community Full-Benefit Dual Aged
    "CFD": "CFD_",   # Community Full-Benefit Dual Disabled
    # Community Partial Dual
    "CPA": "CPA_",   # Community Partial-Benefit Dual Aged
    "CPD": "CPD_",   # Community Partial-Benefit Dual Disabled
    # Institutional / New Enrollee
    "INS": "INS_",   # Institutional
    "NE":  "NE_",    # New Enrollee (non-dual)
    "SNPNE": "SNPNE_",  # SNP New Enrollee
    # Allow callers to pass the full prefix string unchanged.
    "CNA_": "CNA_",
    "CND_": "CND_",
    "CFA_": "CFA_",
    "CFD_": "CFD_",
    "CPA_": "CPA_",
    "CPD_": "CPD_",
    "INS_": "INS_",
    "NE_":  "NE_",
}


def get_hcc_coefficient(
    hcc_code: int,
    model_version: str = "V28",
    segment: str = "CNA",
) -> float:
    """Return the RAF coefficient for an HCC code under a demographic segment.

    Args:
        hcc_code: HCC condition category number as an integer, e.g. ``37``.
        model_version: Short model version string.  Accepted values:
                       ``"V28"`` (default) or ``"V24"``.
        segment: CMS demographic segment code (default ``"CNA"`` —
                 Community Non-Dual Aged).  Supported values:

                 ``"CNA"``   Community Non-Dual Aged
                 ``"CND"``   Community Non-Dual Disabled
                 ``"CFA"``   Community Full-Benefit Dual Aged
                 ``"CFD"``   Community Full-Benefit Dual Disabled
                 ``"CPA"``   Community Partial-Benefit Dual Aged
                 ``"CPD"``   Community Partial-Benefit Dual Disabled
                 ``"INS"``   Institutional
                 ``"NE"``    New Enrollee

    Returns:
        Coefficient as a float, or ``0.0`` if the HCC / segment combo is not
        found in the requested model.

    Raises:
        ValueError: If ``model_version`` or ``segment`` is not recognised.
    """
    model = _resolve_model(model_version)
    prefix = _SEGMENT_TO_PREFIX.get(segment.upper())
    if prefix is None:
        raise ValueError(
            f"Unknown segment {segment!r}. "
            f"Valid values: {sorted(k for k in _SEGMENT_TO_PREFIX if '_' not in k or k.endswith('_'))}"
        )
    return _get_hcc_coefficient_raw(str(hcc_code), model=model, prefix=prefix)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Crosswalk table maintenance (caching / reporting only — NOT authoritative)
# ---------------------------------------------------------------------------

def refresh_crosswalk_table(tenant_id: str) -> dict:
    """Regenerate the ``hcc_icd10_crosswalk`` table from hccinfhir.

    The crosswalk table exists for quick SQL joins and reporting dashboards.
    Its content is now DERIVED from hccinfhir rather than being an
    independently maintained data set, so it can never silently disagree with
    the authoritative engine.

    This function should be called:
    - After a hccinfhir library upgrade (new CMS model year).
    - On first environment setup when the table is empty.
    - Periodically via a maintenance job as a safety measure.

    The function is **idempotent**: rows are upserted via
    ``ON DUPLICATE KEY UPDATE`` so it is safe to call multiple times.

    Args:
        tenant_id: Tenant identifier (currently unused in the crosswalk table
                   schema, but accepted for forward-compatibility).

    Returns:
        Dict with ``inserted`` and ``errors`` counts.
    """
    from hccinfhir.defaults import dx_to_cc_default  # local import to avoid circular

    inserted = errors = 0

    with raf_cursor() as cur:
        # Collect all unique (icd10_code, cc, model_name) triples from hccinfhir.
        rows_to_upsert: list[tuple[str, str, str]] = []
        for (icd10_code, model_name), cc_set in dx_to_cc_default.items():
            # Translate full model name back to short version for the table.
            short_version = next(
                (k for k, v in _MODEL_VERSION_MAP.items()
                 if v == model_name and len(k) <= 4),  # prefer "V28" over full name
                model_name,
            )
            for cc in cc_set:
                rows_to_upsert.append((icd10_code, cc, short_version))

        try:
            cur.executemany(
                """
                INSERT INTO hcc_icd10_crosswalk (icd10_code, hcc_code, model_version)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    hcc_code      = VALUES(hcc_code),
                    model_version = VALUES(model_version)
                """,
                rows_to_upsert,
            )
            inserted = len(rows_to_upsert)
        except Exception as exc:
            logger.error(
                "refresh_crosswalk_table: batch upsert failed — %s", exc,
            )
            errors = len(rows_to_upsert)

    logger.info(
        "refresh_crosswalk_table [tenant=%s]: upserted=%d errors=%d",
        tenant_id, inserted, errors,
    )
    return {"inserted": inserted, "errors": errors}


def reconcile_crosswalk(tenant_id: str) -> list[dict]:
    """Compare the ``hcc_icd10_crosswalk`` table against hccinfhir.

    Detects rows in the database table whose ``hcc_code`` or ``model_version``
    disagrees with what hccinfhir would return for the same ICD-10 code, and
    codes present in the table that hccinfhir no longer recognises.

    This function does NOT modify any data.  Use ``refresh_crosswalk_table()``
    to fix divergences.

    Args:
        tenant_id: Tenant identifier (accepted for forward-compatibility).

    Returns:
        List of dicts describing divergences.  Empty list means the table is
        in sync with hccinfhir.  Each dict has keys:

        ``icd10_code``
            The code that differs (str).
        ``db_hcc_code``
            HCC code stored in the database (str | None).
        ``db_model_version``
            Model version stored in the database (str | None).
        ``hccinfhir_hcc_codes``
            List of CC codes hccinfhir returns for this code (list[str]).
        ``hccinfhir_model_version``
            Short model version key resolved by hccinfhir (str | None).
        ``divergence_type``
            One of ``"missing_in_hccinfhir"``, ``"missing_in_db"``,
            or ``"hcc_mismatch"``.
    """
    divergences: list[dict] = []

    with raf_cursor() as cur:
        cur.execute(
            "SELECT icd10_code, hcc_code, model_version FROM hcc_icd10_crosswalk"
        )
        db_rows = cur.fetchall()

    if not db_rows:
        logger.info("reconcile_crosswalk [tenant=%s]: crosswalk table is empty", tenant_id)
        return []

    # Group db rows by icd10_code for efficient comparison.
    db_map: dict[str, dict] = {
        row["icd10_code"]: row for row in db_rows
    }

    # Batch-lookup all db codes against hccinfhir.
    hccinfhir_map = map_icd10_batch(list(db_map.keys()))

    for icd10_code, db_row in db_map.items():
        hccinfhir_entry = hccinfhir_map.get(icd10_code)

        if hccinfhir_entry is None:
            # Code is in the db table but hccinfhir no longer maps it.
            divergences.append(
                {
                    "icd10_code": icd10_code,
                    "db_hcc_code": db_row["hcc_code"],
                    "db_model_version": db_row["model_version"],
                    "hccinfhir_hcc_codes": [],
                    "hccinfhir_model_version": None,
                    "divergence_type": "missing_in_hccinfhir",
                }
            )
            continue

        db_hcc = str(db_row["hcc_code"] or "").strip()
        hccinfhir_codes: list[str] = hccinfhir_entry["hcc_codes"]

        if db_hcc not in hccinfhir_codes:
            divergences.append(
                {
                    "icd10_code": icd10_code,
                    "db_hcc_code": db_hcc,
                    "db_model_version": db_row["model_version"],
                    "hccinfhir_hcc_codes": hccinfhir_codes,
                    "hccinfhir_model_version": hccinfhir_entry["model_version"],
                    "divergence_type": "hcc_mismatch",
                }
            )

    logger.info(
        "reconcile_crosswalk [tenant=%s]: checked=%d divergences=%d",
        tenant_id, len(db_map), len(divergences),
    )
    return divergences
