"""
hcc_hierarchy.py

CMS V24 / V28 HCC hierarchy (trumping) logic for RAF Intelligence.

CMS HCC models define hierarchy groups where a more-severe HCC suppresses
("trumps") less-severe HCCs in the same clinical family.  A patient scored
for HCC 17 (Diabetes with Acute Complications) must not also be scored for
HCC 18 or HCC 19 — they are redundant and would overstate RAF.

This module provides:

  apply_hierarchy(patient_hccs)
      Pure-Python function that marks is_trumped / trumped_by_hcc on a list
      of patient HCC dicts.  No I/O.  Safe to call from calculators, tests,
      or background jobs.

  apply_hierarchy_to_patient(patient_id, measurement_year, tenant_id, model_version)
      Reads raf_patient_hcc from MySQL, calls apply_hierarchy(), and writes
      the is_trumped / trumped_by_hcc columns back.

Design notes
------------
- Hierarchy chains are stored as ordered lists (most-severe → least-severe).
  Any HCC that has a more-severe sibling present in the same patient's record
  is marked as trumped.
- The same rules are used regardless of whether the patient has V24 or V28
  HCC codes.  The V24 hierarchy shipped with CMS software is a strict subset
  of the V28 rules for the condition families that were present in V24; both
  sets are included here and the caller can pass model_version to restrict to
  a specific set if needed.
- This service deliberately does NOT re-compute the RAF score.  Score
  recalculation is the responsibility of raf/calculator.py after hierarchy is
  applied.
- The hcc_hierarchy_rules DB table remains the authoritative source for the
  *calculator*; this module's embedded dict is the authoritative source for
  the *patient_hcc stamping* use case.  Both encode the same CMS rules.

Complete V24 / V28 Hierarchy Groups (source: CMS HCC Software V24/V28 docs)
-------------------------------------------------------------------
Each tuple is a chain ordered most-severe → least-severe.  When any member
is present, all less-severe members in the same chain are suppressed.
"""

from __future__ import annotations

import logging

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CMS V24 Hierarchy chains — (most_severe, ..., least_severe)
# Every entry in position i+1..n is trumped by every entry in position 0..i.
# ---------------------------------------------------------------------------

# Source: CMS 2024 HCC Model Software User Guide, Appendix – HCC Hierarchies
# Each inner tuple lists HCC codes from MOST severe to LEAST severe.
V24_HIERARCHY_CHAINS: list[tuple[int, ...]] = [
    # Cancer / Tumors
    (8, 9, 10, 11, 12),
    # Diabetes
    (17, 18, 19),
    # Liver conditions
    (27, 28, 29, 80),
    # Blood / Hematological
    (46, 48),
    # Substance use disorders
    (54, 55, 56),
    # Psychosis / Psychiatric
    (57, 58, 59, 60),
    # Neurological
    (70, 71, 72, 73),
    # Cardiac arrest
    (82, 83, 84),
    # Congestive heart failure / AMI / heart disease
    (85, 86, 87, 88),
    # CVD / cerebrovascular
    (99, 100),
    # Vascular disease
    (107, 108),
    # Respiratory / COPD
    (111, 112),
    # Renal / Kidney disease
    (134, 135, 136, 137, 138),
]

# V28 hierarchy chains.
#
# Historical note: this module previously hard-coded ~12 chains based on CMS
# documentation.  That list was incomplete (CMS V28 defines hierarchy
# relationships for 58 parent HCCs spanning the full 26-family model) and
# introduced silent gaps where more-severe HCCs would fail to dominate their
# less-severe descendants — e.g. the 17→23 cancer chain, the 276→280 cancer
# chain, and the 379→383 chain were all missing.
#
# To guarantee parity with CMS, we now derive V28 chains from the
# coefficient-provider's bundled hierarchy tables (hccinfhir ships the CMS
# CY2026 hierarchy file).  A small hard-coded fallback is retained so the
# module still imports cleanly if hccinfhir is unavailable (e.g. in lint-only
# environments).
def _load_v28_chains_from_hccinfhir() -> list[tuple[int, ...]] | None:
    """Return V28 chains derived from the CMS hierarchy bundled with hccinfhir.

    hccinfhir exposes ``hierarchies_default`` as ``{(hcc, model): {trumped}}``.
    We flatten that into 2-tuples ``(parent, child)``; ``_build_lookup`` below
    produces the correct transitive closure regardless of whether the chains
    are expressed as long tuples or pair-wise edges.
    """
    try:
        from hccinfhir.defaults import hierarchies_default
    except Exception:  # pragma: no cover — hccinfhir always installed in prod
        logger.debug("swallowed exception", exc_info=True)
        return None
    chains: list[tuple[int, ...]] = []
    for (hcc, model), trumped in hierarchies_default.items():
        if "V28" not in model:
            continue
        try:
            parent = int(hcc)
        except (TypeError, ValueError):
            continue
        for child in trumped:
            try:
                chains.append((parent, int(child)))
            except (TypeError, ValueError):
                continue
    return chains or None


_V28_FALLBACK_CHAINS: list[tuple[int, ...]] = [
    # Minimal fallback — preserved so the module imports even when hccinfhir
    # is absent.  These are the pre-2026 chains that predated the derive-from-
    # hccinfhir approach.
    (17, 18, 19, 20),
    (35, 36, 37, 38),
    (27, 28, 29, 80),
    (221, 222, 223, 224, 225, 226, 227),
    (326, 327, 328, 329),
    (310, 311),
    (107, 108),
    (99, 100),
    (46, 48),
    (135, 136, 137, 138, 139),
    (151, 152, 153, 154, 155),
    (180, 181, 182, 183),
]

V28_HIERARCHY_CHAINS: list[tuple[int, ...]] = (
    _load_v28_chains_from_hccinfhir() or _V28_FALLBACK_CHAINS
)

# ---------------------------------------------------------------------------
# Combined lookup structures built from the chains above
# ---------------------------------------------------------------------------

def _build_lookup(
    chains: list[tuple[int, ...]],
) -> dict[int, list[int]]:
    """Return {hcc: [list of HCCs that trump it]} for the given chain set.

    For each chain element at index i, every element at index < i is a
    trumping HCC.  The returned dict maps each potentially-trumped HCC to the
    full set of HCCs that would trump it if present.
    """
    trumped_by: dict[int, list[int]] = {}
    for chain in chains:
        for i, hcc in enumerate(chain):
            if i == 0:
                continue  # Most severe — nothing trumps it
            trumpers = list(chain[:i])
            if hcc not in trumped_by:
                trumped_by[hcc] = []
            for t in trumpers:
                if t not in trumped_by[hcc]:
                    trumped_by[hcc].append(t)
    return trumped_by


# Pre-built lookups — created once at import time
_V24_TRUMPED_BY: dict[int, list[int]] = _build_lookup(V24_HIERARCHY_CHAINS)
_V28_TRUMPED_BY: dict[int, list[int]] = _build_lookup(V28_HIERARCHY_CHAINS)

# Combined lookup (covers both V24 and V28 numbers simultaneously)
_ALL_CHAINS = V24_HIERARCHY_CHAINS + [
    c for c in V28_HIERARCHY_CHAINS if c not in V24_HIERARCHY_CHAINS
]
_ALL_TRUMPED_BY: dict[int, list[int]] = _build_lookup(_ALL_CHAINS)


def _get_trumped_by_lookup(model_version: str | None) -> dict[int, list[int]]:
    """Return the correct trumped-by lookup for the requested model version."""
    if model_version is None:
        return _ALL_TRUMPED_BY
    mv = model_version.upper().strip()
    if mv in ("V24", "CMS-HCC MODEL V24"):
        return _V24_TRUMPED_BY
    if mv in ("V28", "CMS-HCC MODEL V28"):
        return _V28_TRUMPED_BY
    logger.debug(
        "hcc_hierarchy: unknown model_version %r — using combined V24+V28 rules",
        model_version,
    )
    return _ALL_TRUMPED_BY


# ---------------------------------------------------------------------------
# Public API — pure function (no I/O)
# ---------------------------------------------------------------------------

def apply_hierarchy(
    patient_hccs: list[dict],
    model_version: str | None = None,
) -> list[dict]:
    """Mark is_trumped / trumped_by_hcc on each HCC record for a single patient.

    This is a **pure function** — it does not read from or write to the
    database.  It mutates each dict in *patient_hccs* in place and also
    returns the list for convenience.

    Args:
        patient_hccs:
            List of dicts, each representing a row from ``raf_patient_hcc``.
            Each dict must have an ``hcc_code`` key (int or str).  The keys
            ``is_trumped`` (bool) and ``trumped_by_hcc`` (str | None) will be
            set or overwritten.
        model_version:
            Optional CMS model version string (``"V24"``, ``"V28"``, or full
            name).  When omitted, combined V24+V28 rules are applied — safe
            for mixed environments.

    Returns:
        The same list (mutated in place) with ``is_trumped`` and
        ``trumped_by_hcc`` populated on every element.

    Example::

        records = [
            {"hcc_code": 17, "patient_id": 1},
            {"hcc_code": 18, "patient_id": 1},
            {"hcc_code": 19, "patient_id": 1},
        ]
        apply_hierarchy(records)
        # records[0]: is_trumped=False, trumped_by_hcc=None
        # records[1]: is_trumped=True,  trumped_by_hcc="17"
        # records[2]: is_trumped=True,  trumped_by_hcc="17"
    """
    trumped_by_lookup = _get_trumped_by_lookup(model_version)

    # Build the set of HCC codes present for this patient (as ints).
    present: set[int] = set()
    for rec in patient_hccs:
        try:
            present.add(int(rec["hcc_code"]))
        except (TypeError, ValueError, KeyError):
            logger.debug(
                "apply_hierarchy: could not parse hcc_code from record %r", rec
            )

    # Reset all records first — ensures idempotency on repeated calls.
    for rec in patient_hccs:
        rec["is_trumped"] = False
        rec["trumped_by_hcc"] = None

    # For each record, check whether any of its trumping HCCs are also present.
    for rec in patient_hccs:
        try:
            hcc_int = int(rec["hcc_code"])
        except (TypeError, ValueError, KeyError):
            continue

        possible_trumpers = trumped_by_lookup.get(hcc_int, [])
        # Use the lowest-numbered (most-severe) trumping HCC that is present.
        active_trumpers = sorted(h for h in possible_trumpers if h in present)
        if active_trumpers:
            rec["is_trumped"] = True
            rec["trumped_by_hcc"] = str(active_trumpers[0])

    return patient_hccs


# ---------------------------------------------------------------------------
# Public API — database-aware function
# ---------------------------------------------------------------------------

def apply_hierarchy_to_patient(
    patient_id: int,
    measurement_year: int,
    tenant_id: str,
    model_version: str | None = None,
) -> dict:
    """Read raf_patient_hcc, apply hierarchy, write is_trumped / trumped_by_hcc.

    Reads all HCC rows for *(patient_id, measurement_year, tenant_id)*, calls
    :func:`apply_hierarchy` to determine which are trumped, then updates each
    row in-place.  The function is idempotent — calling it multiple times for
    the same patient produces the same result.

    Args:
        patient_id:     Patient PK from the ``patients`` table.
        measurement_year: RAF measurement year (e.g. 2024, 2025, 2026).
        tenant_id:      Tenant identifier (default ``"1"``).
        model_version:  Optional CMS model version string.  When omitted,
                        combined V24+V28 rules are applied.

    Returns:
        Dict with summary keys:
        ``patient_id``, ``measurement_year``, ``total``, ``trumped``,
        ``not_trumped``, ``updated``, ``errors``.
    """
    result: dict = {
        "patient_id": patient_id,
        "measurement_year": measurement_year,
        "total": 0,
        "trumped": 0,
        "not_trumped": 0,
        "updated": 0,
        "errors": 0,
    }

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, hcc_code, is_trumped, trumped_by_hcc
                FROM raf_patient_hcc
                WHERE patient_id = %s
                  AND measurement_year = %s
                  AND tenant_id = %s
                """,
                (patient_id, measurement_year, tenant_id),
            )
            rows: list[dict] = cur.fetchall()

        if not rows:
            logger.debug(
                "apply_hierarchy_to_patient: no HCC rows for pid=%s year=%s tenant=%s",
                patient_id, measurement_year, tenant_id,
            )
            return result

        result["total"] = len(rows)

        # Capture original DB values BEFORE apply_hierarchy mutates the dicts.
        originals: dict[int, tuple[bool, str | None]] = {
            row["id"]: (bool(row.get("is_trumped")), row.get("trumped_by_hcc"))
            for row in rows
        }

        # Apply pure-logic hierarchy (mutates dicts in place).
        apply_hierarchy(rows, model_version=model_version)

        # Persist changes — only update rows whose values actually changed.
        errors = 0
        updated = 0
        try:
            with raf_cursor() as cur:
                for row in rows:
                    row_id = row["id"]
                    new_trumped = bool(row["is_trumped"])
                    new_trumped_by = row.get("trumped_by_hcc")

                    old_trumped, old_trumped_by = originals.get(row_id, (False, None))

                    # Skip rows that did not change to avoid unnecessary writes.
                    if new_trumped == old_trumped and new_trumped_by == old_trumped_by:
                        continue

                    try:
                        cur.execute(
                            """
                            UPDATE raf_patient_hcc
                               SET is_trumped     = %s,
                                   trumped_by_hcc = %s,
                                   updated_at     = NOW()
                             WHERE id = %s
                            """,
                            (
                                1 if new_trumped else 0,
                                new_trumped_by,
                                row_id,
                            ),
                        )
                        updated += 1
                    except Exception as exc:
                        logger.error(
                            "apply_hierarchy_to_patient: failed to update row id=%s: %s",
                            row_id, exc,
                        )
                        errors += 1
        except Exception as exc:
            logger.error(
                "apply_hierarchy_to_patient: failed to open cursor for updates pid=%s: %s",
                patient_id, exc,
            )
            errors += result["total"]

        result["trumped"] = sum(1 for r in rows if r["is_trumped"])
        result["not_trumped"] = result["total"] - result["trumped"]
        result["updated"] = updated
        result["errors"] = errors

        logger.info(
            "apply_hierarchy_to_patient pid=%s year=%s tenant=%s: "
            "total=%d trumped=%d updated=%d errors=%d",
            patient_id, measurement_year, tenant_id,
            result["total"], result["trumped"], result["updated"], result["errors"],
        )

    except Exception as exc:
        logger.exception(
            "apply_hierarchy_to_patient: unexpected error pid=%s year=%s: %s",
            patient_id, measurement_year, exc,
        )
        result["errors"] += 1

    return result


def apply_hierarchy_to_all_patients(
    measurement_year: int,
    tenant_id: str,
    model_version: str | None = None,
) -> dict:
    """Apply hierarchy stamping to every patient for a measurement year.

    Intended for batch jobs (nightly sweeps, post-import pipelines).  Fetches
    the distinct patient IDs with HCC rows for the given year and calls
    :func:`apply_hierarchy_to_patient` for each one.

    Args:
        measurement_year: RAF measurement year.
        tenant_id:        Tenant identifier.
        model_version:    Optional CMS model version string.

    Returns:
        Dict with aggregate keys: ``patients``, ``total_hccs``,
        ``total_trumped``, ``total_updated``, ``total_errors``.
    """
    aggregate = {
        "patients": 0,
        "total_hccs": 0,
        "total_trumped": 0,
        "total_updated": 0,
        "total_errors": 0,
    }

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT patient_id
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                  AND tenant_id = %s
                ORDER BY patient_id
                """,
                (measurement_year, tenant_id),
            )
            patient_ids: list[int] = [r["patient_id"] for r in cur.fetchall()]
    except Exception as exc:
        logger.exception(
            "apply_hierarchy_to_all_patients: failed to fetch patient list: %s", exc
        )
        return aggregate

    aggregate["patients"] = len(patient_ids)
    logger.info(
        "apply_hierarchy_to_all_patients: processing %d patients for year=%s tenant=%s",
        len(patient_ids), measurement_year, tenant_id,
    )

    for pid in patient_ids:
        res = apply_hierarchy_to_patient(
            patient_id=pid,
            measurement_year=measurement_year,
            tenant_id=tenant_id,
            model_version=model_version,
        )
        aggregate["total_hccs"] += res.get("total", 0)
        aggregate["total_trumped"] += res.get("trumped", 0)
        aggregate["total_updated"] += res.get("updated", 0)
        aggregate["total_errors"] += res.get("errors", 0)

    logger.info(
        "apply_hierarchy_to_all_patients complete: year=%s tenant=%s "
        "patients=%d hccs=%d trumped=%d updated=%d errors=%d",
        measurement_year, tenant_id,
        aggregate["patients"], aggregate["total_hccs"],
        aggregate["total_trumped"], aggregate["total_updated"], aggregate["total_errors"],
    )
    return aggregate


# ---------------------------------------------------------------------------
# Utility — seed hcc_hierarchy_rules from the embedded chain definitions
# ---------------------------------------------------------------------------

def seed_hierarchy_rules_from_chains(
    model_year: int = 2024,
    chains: list[tuple[int, ...]] | None = None,
) -> dict:
    """Upsert hcc_hierarchy_rules from the embedded chain definitions.

    Useful for keeping the DB table in sync with this module after a CMS
    model year update.  The table is used by the RAF *calculator*; this module
    uses the embedded dicts directly for patient_hcc stamping.

    Args:
        model_year: Year value to store in the ``model_year`` column.
                    Defaults to 2024 (V28 numbering).
        chains:     Override the chain list.  When omitted, uses
                    V28_HIERARCHY_CHAINS for model_year >= 2024, otherwise
                    V24_HIERARCHY_CHAINS.

    Returns:
        Dict with ``inserted`` and ``skipped`` counts.
    """
    if chains is None:
        chains = V28_HIERARCHY_CHAINS if model_year >= 2024 else V24_HIERARCHY_CHAINS

    inserted = skipped = 0
    # Build the full set of (trumped_hcc, trumping_hcc) pairs
    pairs: list[tuple[int, int]] = []
    for chain in chains:
        for i in range(1, len(chain)):
            trumped_hcc = chain[i]
            for j in range(i):
                trumping_hcc = chain[j]
                pairs.append((trumped_hcc, trumping_hcc))

    try:
        with raf_cursor() as cur:
            for trumped_hcc, trumping_hcc in pairs:
                cur.execute(
                    "SELECT id FROM hcc_hierarchy_rules "
                    "WHERE hcc_code = %s AND trumped_by_hcc = %s AND model_year = %s "
                    "LIMIT 1",
                    (trumped_hcc, trumping_hcc, model_year),
                )
                if cur.fetchone():
                    skipped += 1
                else:
                    cur.execute(
                        "INSERT INTO hcc_hierarchy_rules "
                        "(hcc_code, trumped_by_hcc, model_year) "
                        "VALUES (%s, %s, %s)",
                        (trumped_hcc, trumping_hcc, model_year),
                    )
                    inserted += 1
    except Exception as exc:
        logger.exception("seed_hierarchy_rules_from_chains failed: %s", exc)

    logger.info(
        "seed_hierarchy_rules_from_chains model_year=%s: inserted=%d skipped=%d",
        model_year, inserted, skipped,
    )
    return {"inserted": inserted, "skipped": skipped}


def seed_hierarchy_rules() -> dict:
    """Seed hcc_hierarchy_rules for both V24 (model_year=2020) and V28 (model_year=2024).

    Convenience wrapper intended for startup calls and migration scripts.
    Idempotent — rows that already exist are skipped.

    Returns:
        Dict with aggregate ``inserted`` and ``skipped`` counts across both
        model years, plus a ``by_model`` breakdown.
    """
    v24_result = seed_hierarchy_rules_from_chains(
        model_year=2020, chains=V24_HIERARCHY_CHAINS
    )
    v28_result = seed_hierarchy_rules_from_chains(
        model_year=2024, chains=V28_HIERARCHY_CHAINS
    )
    aggregate = {
        "inserted": v24_result["inserted"] + v28_result["inserted"],
        "skipped": v24_result["skipped"] + v28_result["skipped"],
        "by_model": {
            "v24_model_year_2020": v24_result,
            "v28_model_year_2024": v28_result,
        },
    }
    logger.info(
        "seed_hierarchy_rules: total inserted=%d skipped=%d",
        aggregate["inserted"], aggregate["skipped"],
    )
    return aggregate
