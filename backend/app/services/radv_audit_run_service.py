"""
RADV Audit-Run Service (Gap #3 — Audit Defense Workflow)
========================================================

Powers ``backend/app/routers/radv_audit.py`` — the CMS RADV mock-audit
workflow.  Distinct from ``radv_audit_service.py`` (which is per-patient
trail / MEAT compliance) — this module owns the *run* concept:

  - sample N patients for a payment-year mock audit
  - persist per-record decisions
  - simulate revenue exposure with CMS extrapolation
  - generate an MAO-004 reject re-submission batch
  - export evidence bundle

All SQL goes through ``raf_cursor`` — no ORM (project convention).

Compliance notes (2024/2025 CMS Final Rules)
--------------------------------------------
- CMS RADV requires stratification by enrollee/HCC-risk decile, with a
  fixed 201-record sample per contract.  The ``stratified_raf_decile``
  method implements this.
- CMS extrapolation uses the FFS Adjuster and contract
  enrollment-weighted projection (Feb 2023 Final Rule).
  ``compute_extrapolated_exposure`` implements this; the legacy 55×
  multiplier is retained for backward compatibility with runs created
  before members_enrolled was captured, flagged as ``methodology: legacy_v1``.
"""
from __future__ import annotations

import json
import logging
import math
import random
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema capability probe — cached at first use.
#
# Migrations 033 (members_enrolled/ffs_adjuster/extrapolation_methodology)
# and 036 (lcb_dollars) may not yet be applied in every environment.
# _has_v2_columns() returns True only when all three v2 columns are present,
# allowing the service to degrade gracefully on older schemas.
# ---------------------------------------------------------------------------
_V2_COLUMNS_PRESENT: bool | None = None  # None = not yet probed


def _has_v2_columns() -> bool:
    """Return True if migration 033 columns exist on raf_radv_audit_runs."""
    global _V2_COLUMNS_PRESENT
    if _V2_COLUMNS_PRESENT is not None:
        return _V2_COLUMNS_PRESENT
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'raf_radv_audit_runs'
                  AND COLUMN_NAME IN ('members_enrolled', 'ffs_adjuster',
                                      'extrapolation_methodology')
                """
            )
            row = cur.fetchone()
            _V2_COLUMNS_PRESENT = bool(row and int(row.get("cnt") or 0) == 3)
    except Exception as exc:
        logger.warning("radv: v2-column probe failed (%s); assuming absent", exc)
        _V2_COLUMNS_PRESENT = False
    return _V2_COLUMNS_PRESENT


def _has_lcb_column() -> bool:
    """Return True if migration 036 lcb_dollars column exists."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'raf_radv_audit_runs'
                  AND COLUMN_NAME  = 'lcb_dollars'
                """
            )
            row = cur.fetchone()
            return bool(row and int(row.get("cnt") or 0) == 1)
    except Exception as exc:
        logger.warning("radv: lcb_dollars probe failed (%s); assuming absent", exc)
        return False


# ---------------------------------------------------------------------------
# Legacy extrapolation constants — kept for backward compatibility only.
# New runs should supply members_enrolled and use compute_extrapolated_exposure.
# ---------------------------------------------------------------------------
_LEGACY_EXTRAPOLATION_MULTIPLIER = 55.0
# _LEGACY_AVG_HCC_PAYMENT_DOLLARS removed — use revenue_per_raf_point() from
# app.services.raf.revenue_constants (single source of truth).

# CMS 2023 Final Rule FFS Adjuster default
CMS_FFS_ADJUSTER_DEFAULT = 0.97

# Per-member-per-month benchmark (PMPM) used in FFS Adjuster methodology.
# This is an internal heuristic; adjust per contract if needed.
CMS_PMPM_BENCHMARK = 1_100.0

SampleMethod = Literal["random", "stratified_hcc", "stratified_raf_decile", "high_risk_first"]


# ---------------------------------------------------------------------------
# FFS Adjuster extrapolation (CMS 2023 Final Rule methodology)
# ---------------------------------------------------------------------------


def compute_extrapolated_exposure(
    failed_records: int,
    sample_size: int,
    members_enrolled: int,
    avg_per_member_per_month_dollars: float = CMS_PMPM_BENCHMARK,
    audit_period_months: int = 12,
    ffs_adjuster: float = CMS_FFS_ADJUSTER_DEFAULT,
) -> dict[str, Any]:
    """Compute extrapolated dollar exposure using FFS Adjuster methodology.

    IMPORTANT: This is an internal heuristic informed by CMS FFS Adjuster
    methodology — not an official CMS extrapolation.  Results should be
    reviewed by a certified coder before use in audit defense.

    Formula
    -------
    extrapolation_factor       = members_enrolled / sample_size
    base_exposure_per_failure  = avg_per_member_per_month * audit_period_months
    projected_dollar_exposure  = failed_records
                                 * extrapolation_factor
                                 * base_exposure_per_failure
                                 * ffs_adjuster

    Parameters
    ----------
    failed_records:
        Number of sampled records adjudicated as undefensible.
    sample_size:
        Actual number of records in the sample (denominator for
        extrapolation_factor).  Must be > 0.
    members_enrolled:
        Total contract enrollment for the audit period.
    avg_per_member_per_month_dollars:
        PMPM benchmark (default: $1,100 internal heuristic).
    audit_period_months:
        Length of the audit period in months (default: 12).
    ffs_adjuster:
        CMS FFS Adjuster value (default: 0.97 per Feb 2023 Final Rule).
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be > 0")
    if members_enrolled <= 0:
        raise ValueError("members_enrolled must be > 0")
    if not (0.0 < ffs_adjuster <= 1.0):
        raise ValueError("ffs_adjuster must be in (0, 1]")

    extrapolation_factor = members_enrolled / sample_size
    base_per_failure = avg_per_member_per_month_dollars * audit_period_months
    projected = failed_records * extrapolation_factor * base_per_failure * ffs_adjuster

    # Wilson score interval lower bound (CMS Feb-2023 Final Rule, 90 FR 1944).
    # Provides a statistically defensible floor error-rate for audit defense.
    # z = 1.6449 corresponds to 95% one-sided confidence (5th percentile).
    _WILSON_Z = 1.6449  # 95% one-sided
    confidence_level = 0.95
    n = sample_size
    p_hat = failed_records / n if n > 0 else 0.0
    z2 = _WILSON_Z ** 2
    wilson_denom = 1 + z2 / n
    wilson_centre = (p_hat + z2 / (2 * n)) / wilson_denom
    wilson_half = (_WILSON_Z * math.sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n))) / wilson_denom
    lcb_rate = max(wilson_centre - wilson_half, 0.0)
    lcb_projected = lcb_rate * extrapolation_factor * base_per_failure * ffs_adjuster

    return {
        "extrapolated_exposure_dollars": round(projected, 2),
        "lower_confidence_bound_dollars": round(lcb_projected, 2),
        "confidence_level": confidence_level,
        "extrapolation_factor": round(extrapolation_factor, 4),
        "ffs_adjuster": ffs_adjuster,
        "failed_records": failed_records,
        "sample_size": sample_size,
        "members_enrolled": members_enrolled,
        "avg_per_member_per_month_dollars": avg_per_member_per_month_dollars,
        "audit_period_months": audit_period_months,
        "methodology": "ffs_adjuster_with_wilson_lcb_v1",
        "methodology_note": (
            "Internal heuristic informed by CMS FFS Adjuster methodology "
            "(Feb 2023 Final Rule) — not an official CMS extrapolation. "
            "lower_confidence_bound_dollars uses Wilson score interval "
            "(95% one-sided, z=1.6449) for audit-defense floor pricing."
        ),
    }


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def _candidate_patients(
    *, tenant_id: str, payment_year: int
) -> list[dict[str, Any]]:
    """Return all (patient_id, [hcc_codes], raf_score, highest_raf_hcc) tuples
    for the tenant + payment year combination.

    A "candidate" is any patient with at least one HCC submitted in the
    payment year (raf_patient_hcc.measurement_year = payment_year).
    highest_raf_hcc is the HCC code with the maximum raf_value for this
    patient/year; used by stratified_hcc for CMS-compliant stratification.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.id                                AS patient_id,
                GROUP_CONCAT(DISTINCT rph.hcc_code) AS hcc_codes_csv,
                COALESCE(MAX(rs.raf_score), 0.0)    AS raf_score
            FROM patients p
            JOIN raf_patient_hcc rph
              ON  rph.patient_id       = p.id
              AND rph.measurement_year = %s
            LEFT JOIN raf_scores rs
              ON  rs.patient_id       = p.id
              AND rs.measurement_year = %s
            WHERE p.tenant_id = %s
              AND p.is_active = 1
            GROUP BY p.id
            """,
            (payment_year, payment_year, tenant_id),
        )
        rows = cur.fetchall() or []

        # Fetch highest-RAF-value HCC per patient for this year.
        cur.execute(
            """
            SELECT
                rph.patient_id,
                rph.hcc_code,
                rph.raf_value
            FROM raf_patient_hcc rph
            JOIN patients p ON p.id = rph.patient_id
            WHERE p.tenant_id = %s
              AND rph.measurement_year = %s
              AND p.is_active = 1
            ORDER BY rph.patient_id, rph.raf_value DESC
            """,
            (tenant_id, payment_year),
        )
        hcc_rows = cur.fetchall() or []

    # Build highest-RAF HCC lookup per patient.
    highest_raf_hcc: dict[int, str] = {}
    for hr in hcc_rows:
        pid = int(hr["patient_id"])
        if pid not in highest_raf_hcc:
            highest_raf_hcc[pid] = hr["hcc_code"]

    candidates: list[dict[str, Any]] = []
    for r in rows:
        csv = (r.get("hcc_codes_csv") or "").strip()
        hcc_codes = sorted({c.strip() for c in csv.split(",") if c.strip()}) if csv else []
        if not hcc_codes:
            continue
        pid = int(r["patient_id"])
        candidates.append(
            {
                "patient_id":      pid,
                "hcc_codes":       hcc_codes,
                "raf_score":       float(r.get("raf_score") or 0.0),
                "highest_raf_hcc": highest_raf_hcc.get(pid, hcc_codes[0]),
            }
        )
    return candidates


def _sample_stratified_raf_decile(patients: list[dict], n: int) -> list[dict]:
    """CMS-compliant RAF-decile stratified sampling.

    Sorts patients by raf_score, divides into 10 equal deciles (ranked 0..9),
    then allocates quota across deciles.  For n=201, the top decile (decile 9)
    receives the extra record.  Hard cap: never returns more than n records.

    Parameters
    ----------
    patients:
        Full candidate list (must have 'raf_score' field).
    n:
        Target sample size (CMS default: 201).
    """
    if not patients:
        return []
    if n >= len(patients):
        return list(patients)[:n]

    sorted_pts = sorted(patients, key=lambda c: c["raf_score"])
    total = len(sorted_pts)
    num_deciles = 10

    # Assign decile index (0 = lowest RAF, 9 = highest RAF).
    deciles: list[list[dict]] = [[] for _ in range(num_deciles)]
    for i, p in enumerate(sorted_pts):
        decile_idx = min(int(i * num_deciles / total), num_deciles - 1)
        deciles[decile_idx].append(p)

    base_quota = n // num_deciles        # e.g. 201 // 10 = 20
    remainder = n - base_quota * num_deciles  # e.g. 201 - 200 = 1

    picked: list[dict] = []
    for idx, bucket in enumerate(deciles):
        # Extra record(s) go to the top decile(s) (highest risk, CMS priority).
        quota = base_quota + (1 if idx >= num_deciles - remainder else 0)
        quota = min(quota, len(bucket))
        random.shuffle(bucket)
        picked.extend(bucket[:quota])

    random.shuffle(picked)
    return picked[:n]  # hard cap


def _sample(
    candidates: list[dict[str, Any]],
    *,
    sample_size: int,
    method: SampleMethod,
) -> list[dict[str, Any]]:
    """Apply the requested sampling strategy.

    - random:                  shuffle, take N
    - stratified_hcc:          bucket by highest-RAF HCC, draw proportionally
    - stratified_raf_decile:   CMS-compliant RAF-decile stratification
    - high_risk_first:         sort by raf_score desc, take N

    All paths enforce a hard cap of sample_size via return sample[:n].
    """
    if not candidates:
        return []
    if sample_size >= len(candidates):
        return list(candidates)[:sample_size]

    if method == "high_risk_first":
        result = sorted(candidates, key=lambda c: -c["raf_score"])[:sample_size]
        return result[:sample_size]

    if method == "stratified_raf_decile":
        return _sample_stratified_raf_decile(candidates, sample_size)

    if method == "stratified_hcc":
        # Stratify by highest-RAF HCC (not alphabetically-first HCC).
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in candidates:
            primary = c.get("highest_raf_hcc") or (c["hcc_codes"][0] if c["hcc_codes"] else "_unknown_")
            buckets[primary].append(c)
        total = len(candidates)
        picked: list[dict[str, Any]] = []
        for hcc, bucket in buckets.items():
            quota = max(1, round(sample_size * len(bucket) / total))
            random.shuffle(bucket)
            picked.extend(bucket[:quota])
        random.shuffle(picked)
        return picked[:sample_size]  # hard cap

    # default: random
    result = random.sample(candidates, sample_size)
    return result[:sample_size]  # hard cap


# ---------------------------------------------------------------------------
# CRUD — runs + records
# ---------------------------------------------------------------------------


def create_audit_run(
    *,
    tenant_id: str,
    name: str,
    payment_year: int,
    sample_size: int = 201,
    sample_method: SampleMethod,
    created_by_user_id: int,
    notes: str | None = None,
    members_enrolled: int | None = None,
    ffs_adjuster: float | None = None,
) -> dict[str, Any]:
    """Create a new audit run and seed it with sampled records.

    Default sample_size is 201 per CMS RADV 2024 Final Rule.
    members_enrolled and ffs_adjuster are used for FFS Adjuster extrapolation;
    if absent the run falls back to legacy 55x math (methodology: legacy_v1).
    """
    if sample_size <= 0:
        raise ValueError("sample_size must be > 0")
    if sample_size > 5_000:
        raise ValueError("sample_size cannot exceed 5000")

    candidates = _candidate_patients(tenant_id=tenant_id, payment_year=payment_year)
    sampled = _sample(candidates, sample_size=sample_size, method=sample_method)

    with raf_cursor() as cur:
        if _has_v2_columns():
            cur.execute(
                """
                INSERT INTO raf_radv_audit_runs
                    (tenant_id, name, payment_year, sample_size, sample_method,
                     status, created_by, notes, members_enrolled, ffs_adjuster,
                     extrapolation_methodology)
                VALUES (%s, %s, %s, %s, %s, 'prep', %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id, name, payment_year, sample_size, sample_method,
                    created_by_user_id, notes,
                    members_enrolled,
                    ffs_adjuster if ffs_adjuster is not None else CMS_FFS_ADJUSTER_DEFAULT,
                    "ffs_adjuster_v1" if members_enrolled else "legacy_v1",
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO raf_radv_audit_runs
                    (tenant_id, name, payment_year, sample_size, sample_method,
                     status, created_by, notes)
                VALUES (%s, %s, %s, %s, %s, 'prep', %s, %s)
                """,
                (
                    tenant_id, name, payment_year, sample_size, sample_method,
                    created_by_user_id, notes,
                ),
            )
        run_id = cur.lastrowid

        if sampled:
            params = [
                (
                    run_id,
                    tenant_id,
                    rec["patient_id"],
                    json.dumps(rec["hcc_codes"]),
                )
                for rec in sampled
            ]
            cur.executemany(
                """
                INSERT INTO raf_radv_audit_records
                    (audit_run_id, tenant_id, patient_id, sampled_hcc_codes)
                VALUES (%s, %s, %s, %s)
                """,
                params,
            )

    return get_audit_run(run_id, tenant_id=tenant_id)


def _has_audit_runs_table() -> bool:
    """Return True if raf_radv_audit_runs exists (migration 030 applied)."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'raf_radv_audit_runs'
                """
            )
            row = cur.fetchone()
            return bool(row and int(row.get("cnt") or 0) > 0)
    except Exception as exc:
        logger.warning("radv: table existence probe failed (%s); assuming absent", exc)
        return False


def list_audit_runs(*, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return run headers + per-run counts for the tenant.

    Returns an empty list when migration 030 has not yet been applied to the
    target schema, so the endpoint returns 200 {runs: []} instead of 500.
    """
    if not _has_audit_runs_table():
        logger.warning("radv: raf_radv_audit_runs table absent — migration 030 not yet applied")
        return []

    # v2 columns (migration 033) are optional — omit them when absent so the
    # query doesn't fail on schemas that haven't run that migration yet.
    v2_cols = (
        ", r.members_enrolled, r.ffs_adjuster, r.extrapolation_methodology"
        if _has_v2_columns()
        else ""
    )
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                r.id, r.name, r.payment_year, r.sample_size,
                r.sample_method, r.status, r.created_by,
                r.assumed_fail_rate, r.notes, r.created_at, r.updated_at
                {v2_cols},
                COUNT(rec.id)                                           AS record_count,
                SUM(rec.final_decision = 'defensible')                  AS defensible_count,
                SUM(rec.final_decision = 'undefensible')                AS undefensible_count,
                SUM(rec.final_decision = 'needs_remediation')           AS remediation_count,
                COALESCE(SUM(rec.extrapolated_exposure_dollars), 0)     AS total_exposure_dollars
            FROM raf_radv_audit_runs r
            LEFT JOIN raf_radv_audit_records rec ON rec.audit_run_id = r.id
            WHERE r.tenant_id = %s
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT %s
            """,
            (tenant_id, int(limit)),
        )
        return cur.fetchall() or []


def get_audit_run(run_id: int, *, tenant_id: str) -> dict[str, Any]:
    """Return a run + every record (with patient demographics)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM raf_radv_audit_runs
            WHERE id = %s AND tenant_id = %s
            """,
            (run_id, tenant_id),
        )
        run = cur.fetchone()
        if not run:
            raise ValueError(f"audit run {run_id} not found")

        cur.execute(
            """
            SELECT
                rec.*,
                p.first_name, p.last_name, p.mrn, p.dob
            FROM raf_radv_audit_records rec
            LEFT JOIN patients p ON p.id = rec.patient_id
            WHERE rec.audit_run_id = %s
            ORDER BY rec.id ASC
            """,
            (run_id,),
        )
        records_raw = cur.fetchall() or []

    records: list[dict[str, Any]] = []
    for r in records_raw:
        try:
            hcc_codes = json.loads(r.get("sampled_hcc_codes") or "[]")
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            hcc_codes = []
        records.append({**r, "sampled_hcc_codes": hcc_codes})

    run["records"] = records
    run["summary"] = _summarize_records(records)
    return run


def _summarize_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    defensible = undefensible = needs_remediation = pending = 0
    total_exposure = 0.0
    for r in records:
        total += 1
        decision = r.get("final_decision") or "pending"
        if decision == "defensible":
            defensible += 1
        elif decision == "undefensible":
            undefensible += 1
        elif decision == "needs_remediation":
            needs_remediation += 1
        else:
            pending += 1
        total_exposure += float(r.get("extrapolated_exposure_dollars") or 0)
    return {
        "total_records":      total,
        "defensible":         defensible,
        "undefensible":       undefensible,
        "needs_remediation":  needs_remediation,
        "pending":            pending,
        "total_exposure_dollars": round(total_exposure, 2),
    }


def update_record(
    *,
    run_id: int,
    record_id: int,
    tenant_id: str,
    reviewer_user_id: int,
    evidence_status: str | None = None,
    final_decision: str | None = None,
    reviewer_notes: str | None = None,
) -> dict[str, Any]:
    """Coder-side update of a single record.  Recomputes exposure $.

    Exposure is computed using FFS Adjuster methodology when the parent run
    has members_enrolled set; otherwise falls back to legacy 55x with a
    deprecation warning.

    needs_remediation records are treated the same as undefensible for
    exposure computation — the distinction is that the coder believes the HCC
    may still be salvageable via corrective action; the financial exposure is
    identical until resolved.
    """
    allowed_evidence = {"pending", "complete", "missing_meat", "chart_requested"}
    allowed_decision = {"pending", "defensible", "undefensible", "needs_remediation"}
    if evidence_status and evidence_status not in allowed_evidence:
        raise ValueError(f"invalid evidence_status: {evidence_status}")
    if final_decision and final_decision not in allowed_decision:
        raise ValueError(f"invalid final_decision: {final_decision}")

    with raf_cursor() as cur:
        # Fetch run metadata for exposure computation.
        # v2 columns (migration 033) are optional — fall back to sample_size only
        # when those columns don't exist yet.
        if _has_v2_columns():
            cur.execute(
                """
                SELECT r.members_enrolled, r.ffs_adjuster, r.sample_size,
                       r.extrapolation_methodology
                FROM raf_radv_audit_runs r
                JOIN raf_radv_audit_records rec ON rec.audit_run_id = r.id
                WHERE rec.id = %s AND rec.audit_run_id = %s AND r.tenant_id = %s
                """,
                (record_id, run_id, tenant_id),
            )
        else:
            cur.execute(
                """
                SELECT r.sample_size
                FROM raf_radv_audit_runs r
                JOIN raf_radv_audit_records rec ON rec.audit_run_id = r.id
                WHERE rec.id = %s AND rec.audit_run_id = %s AND r.tenant_id = %s
                """,
                (record_id, run_id, tenant_id),
            )
        run_meta = cur.fetchone()
        if not run_meta:
            raise ValueError("record not found in this run/tenant")

    # Compute per-record exposure.
    # Both 'undefensible' and 'needs_remediation' count as failed — no half-weight.
    # needs_remediation means the coder hasn't resolved it yet; CMS would
    # treat it identically to undefensible until corrective action is verified.
    exposure_dollars: float = 0.0
    if final_decision in ("undefensible", "needs_remediation"):
        members_enrolled = run_meta.get("members_enrolled")
        sample_size = int(run_meta.get("sample_size") or 1)
        if members_enrolled:
            ffs_adj = float(run_meta.get("ffs_adjuster") or CMS_FFS_ADJUSTER_DEFAULT)
            result = compute_extrapolated_exposure(
                failed_records=1,
                sample_size=sample_size,
                members_enrolled=int(members_enrolled),
                ffs_adjuster=ffs_adj,
            )
            exposure_dollars = result["extrapolated_exposure_dollars"]
        else:
            warnings.warn(
                f"audit run {run_id} has no members_enrolled; "
                "falling back to legacy 55x extrapolation (methodology: legacy_v1). "
                "Set members_enrolled on the run for CMS-grade FFS Adjuster math.",
                DeprecationWarning,
                stacklevel=2,
            )
            from app.services.raf.revenue_constants import revenue_per_raf_point as _rev
            exposure_dollars = _rev() * _LEGACY_EXTRAPOLATION_MULTIPLIER

    with raf_cursor() as cur:
        sets: list[str] = ["reviewer_user_id = %s"]
        params: list[Any] = [reviewer_user_id]
        if evidence_status is not None:
            sets.append("evidence_status = %s")
            params.append(evidence_status)
        if final_decision is not None:
            sets.append("final_decision = %s")
            params.append(final_decision)
            sets.append("extrapolated_exposure_dollars = %s")
            params.append(exposure_dollars)
        if reviewer_notes is not None:
            sets.append("reviewer_notes = %s")
            params.append(reviewer_notes)
        params.extend([record_id])

        cur.execute(
            f"UPDATE raf_radv_audit_records SET {', '.join(sets)} WHERE id = %s",
            params,
        )

        # Flip run status to 'reviewing' on the first decision.
        cur.execute(
            """
            UPDATE raf_radv_audit_runs SET status = 'reviewing'
            WHERE id = %s AND status = 'prep'
            """,
            (run_id,),
        )

    return get_record(record_id=record_id, tenant_id=tenant_id)


def get_record(*, record_id: int, tenant_id: str) -> dict[str, Any]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT rec.*, r.tenant_id AS run_tenant_id
            FROM raf_radv_audit_records rec
            JOIN raf_radv_audit_runs r ON r.id = rec.audit_run_id
            WHERE rec.id = %s AND r.tenant_id = %s
            """,
            (record_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("record not found")
    try:
        row["sampled_hcc_codes"] = json.loads(row.get("sampled_hcc_codes") or "[]")
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        row["sampled_hcc_codes"] = []
    return row


# ---------------------------------------------------------------------------
# Workflow actions
# ---------------------------------------------------------------------------


def simulate_exposure(
    *,
    run_id: int,
    tenant_id: str,
    assumed_fail_rate: float,
    extrapolation_enforced: bool = False,
) -> dict[str, Any]:
    """Run the CMS extrapolation simulator.

    ``assumed_fail_rate`` is a coder-supplied 0..1 probability that any
    record in the sample would fail.

    ``extrapolation_enforced`` — when False (default per Sept 2025 N.D. Tex.
    court ruling that vacated CMS RADV extrapolation provisions), the
    simulated_exposure_dollars equals the direct sample-based exposure only
    (extrapolation_multiplier = 1).  When True, the full FFS Adjuster or
    legacy 55x extrapolation is applied.

    Uses FFS Adjuster methodology when members_enrolled is set on the run;
    falls back to legacy 55x with methodology: legacy_v1 and a log warning.

    Returns
    -------
    - observed_exposure_dollars  — sum of persisted record decisions
    - simulated_exposure_dollars — projected total if assumed_fail_rate
      applied to every sampled record
    - simulated_failures         — total * assumed_fail_rate (always <= total)
    - extrapolation_enforced     — mirrors the input flag
    - direct_exposure_dollars    — sample-only exposure (no multiplier)
    """
    if not (0.0 <= assumed_fail_rate <= 1.0):
        raise ValueError("assumed_fail_rate must be in [0,1]")

    with raf_cursor() as cur:
        # v2 columns (migration 033) are optional — omit them when absent.
        if _has_v2_columns():
            cur.execute(
                """
                SELECT sample_size, payment_year, members_enrolled,
                       ffs_adjuster, extrapolation_methodology
                FROM raf_radv_audit_runs
                WHERE id = %s AND tenant_id = %s
                """,
                (run_id, tenant_id),
            )
        else:
            cur.execute(
                """
                SELECT sample_size, payment_year
                FROM raf_radv_audit_runs
                WHERE id = %s AND tenant_id = %s
                """,
                (run_id, tenant_id),
            )
        run = cur.fetchone()
        if not run:
            raise ValueError("run not found")

        cur.execute(
            """
            SELECT
                COUNT(*)                                          AS total,
                SUM(final_decision = 'undefensible')              AS undefensible,
                SUM(final_decision = 'defensible')                AS defensible,
                SUM(final_decision = 'needs_remediation')         AS needs_remediation,
                COALESCE(SUM(extrapolated_exposure_dollars), 0)   AS observed_dollars
            FROM raf_radv_audit_records
            WHERE audit_run_id = %s
            """,
            (run_id,),
        )
        agg = cur.fetchone() or {}

        cur.execute(
            """
            UPDATE raf_radv_audit_runs SET assumed_fail_rate = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (assumed_fail_rate, run_id, tenant_id),
        )

    total = int(agg.get("total") or 0)
    undefensible = int(agg.get("undefensible") or 0)
    observed_exposure = float(agg.get("observed_dollars") or 0.0)

    # Clamp simulated_failures to total to satisfy assertion simulated_failures <= total.
    simulated_failures = min(total * assumed_fail_rate, total)

    members_enrolled = run.get("members_enrolled")
    sample_size = int(run.get("sample_size") or 1)

    # ------------------------------------------------------------------
    # Direct (sample-based) exposure — no extrapolation.
    # This is the exposure when extrapolation_enforced=False, reflecting
    # the Sept 2025 N.D. Tex. ruling that vacated CMS RADV extrapolation.
    # ------------------------------------------------------------------
    from app.services.raf.revenue_constants import revenue_per_raf_point
    _avg_hcc = revenue_per_raf_point()
    direct_exposure_dollars = round(simulated_failures * _avg_hcc, 2)

    lcb_dollars: float | None = None
    confidence_level: float | None = None
    extrapolation_multiplier: float = 1.0

    if members_enrolled and int(members_enrolled) > 0:
        ffs_adj = float(run.get("ffs_adjuster") or CMS_FFS_ADJUSTER_DEFAULT)
        exp_result = compute_extrapolated_exposure(
            failed_records=int(round(simulated_failures)),
            sample_size=sample_size,
            members_enrolled=int(members_enrolled),
            ffs_adjuster=ffs_adj,
        )
        full_extrapolated_exposure = exp_result["extrapolated_exposure_dollars"]
        lcb_dollars = exp_result.get("lower_confidence_bound_dollars")
        confidence_level = exp_result.get("confidence_level")
        extrapolation_multiplier = float(exp_result.get("extrapolation_factor", 1.0))
        methodology = exp_result["methodology"]
        methodology_note = exp_result["methodology_note"]
    else:
        if extrapolation_enforced:
            logger.warning(
                "radv simulate_exposure: run %s has no members_enrolled; "
                "using legacy 55x extrapolation (methodology: legacy_v1).",
                run_id,
            )
        full_extrapolated_exposure = round(
            simulated_failures * _avg_hcc * _LEGACY_EXTRAPOLATION_MULTIPLIER, 2
        )
        extrapolation_multiplier = _LEGACY_EXTRAPOLATION_MULTIPLIER
        methodology = "legacy_v1"
        methodology_note = (
            "DEPRECATED: legacy 55x multiplier. Set members_enrolled on the "
            "run to use CMS FFS Adjuster methodology."
        )

    # Apply court-ruling switch: when not enforced, cap at direct sample exposure.
    if extrapolation_enforced:
        simulated_exposure = full_extrapolated_exposure
        extrapolation_status_note = (
            "Extrapolation enforced — full CMS FFS Adjuster (or legacy 55x) "
            "multiplier applied."
        )
    else:
        simulated_exposure = direct_exposure_dollars
        extrapolation_status_note = (
            "Disabled per Sept 2025 N.D. Tex. court ruling that vacated CMS RADV "
            "extrapolation provisions (HHS appeal pending, PY2020 audits begin "
            "Feb 2026). Showing direct sample-based exposure only."
        )

    # Persist LCB to the audit run row whenever we have a valid LCB value.
    # Skip if migration 036 (lcb_dollars column) hasn't been applied yet.
    if lcb_dollars is not None and extrapolation_enforced and _has_lcb_column():
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE raf_radv_audit_runs SET lcb_dollars = %s WHERE id = %s AND tenant_id = %s",
                (lcb_dollars, run_id, tenant_id),
            )

    return {
        "run_id": run_id,
        "payment_year": run["payment_year"],
        "sample_size": sample_size,
        "total_records": total,
        "observed_undefensible": undefensible,
        "observed_exposure_dollars": round(observed_exposure, 2),
        "assumed_fail_rate": assumed_fail_rate,
        "simulated_failures": round(simulated_failures, 2),
        # Primary exposure figure — depends on extrapolation_enforced flag.
        "simulated_exposure_dollars": round(simulated_exposure, 2),
        # Always expose both scenarios for stress-test comparison view.
        "direct_exposure_dollars": direct_exposure_dollars,
        "extrapolated_exposure_dollars": round(full_extrapolated_exposure, 2),
        "extrapolation_enforced": extrapolation_enforced,
        "extrapolation_multiplier": round(extrapolation_multiplier, 2),
        "extrapolation_status_note": extrapolation_status_note,
        "lower_confidence_bound_dollars": round(lcb_dollars, 2) if lcb_dollars is not None else None,
        "confidence_level": confidence_level,
        "members_enrolled": members_enrolled,
        "methodology": methodology,
        "methodology_note": methodology_note,
    }


def build_resubmission_batch(*, run_id: int, tenant_id: str) -> dict[str, Any]:
    """Generate an MAO-004 re-submission batch for EDPS-rejected HCCs.

    Returns the list of (patient_id, hcc_codes) tuples that the
    submissions service should re-package.  We do NOT mutate the
    submissions tables here — that is the submissions router's job;
    we just produce the deterministic batch manifest.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM raf_radv_audit_runs
            WHERE id = %s AND tenant_id = %s
            """,
            (run_id, tenant_id),
        )
        if not cur.fetchone():
            raise ValueError("run not found")

        cur.execute(
            """
            SELECT id, patient_id, sampled_hcc_codes, reviewer_notes
            FROM raf_radv_audit_records
            WHERE audit_run_id = %s
              AND edps_rejected = 1
              AND final_decision IN ('defensible', 'needs_remediation')
            """,
            (run_id,),
        )
        rows = cur.fetchall() or []

    items: list[dict[str, Any]] = []
    for r in rows:
        try:
            hcc_codes = json.loads(r.get("sampled_hcc_codes") or "[]")
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            hcc_codes = []
        items.append(
            {
                "record_id":   r["id"],
                "patient_id":  r["patient_id"],
                "hcc_codes":   hcc_codes,
                "reviewer_notes": r.get("reviewer_notes"),
            }
        )

    return {
        "run_id": run_id,
        "batch_id": f"radv-resub-{run_id}-{int(datetime.now(timezone.utc).timestamp())}",
        "item_count": len(items),
        "items": items,
        "format": "MAO-004",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def export_run(*, run_id: int, tenant_id: str) -> dict[str, Any]:
    """Stub-export: return a manifest describing the evidence package.

    A real implementation would zip notes + MEAT + audit chain to S3.
    For MVP we just flip status to 'exported' and return a manifest URL
    placeholder that the frontend treats as a download link.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE raf_radv_audit_runs SET status = 'exported'
            WHERE id = %s AND tenant_id = %s
            """,
            (run_id, tenant_id),
        )
        if cur.rowcount == 0:
            raise ValueError("run not found")

        cur.execute(
            """
            SELECT id, patient_id, sampled_hcc_codes, final_decision
            FROM raf_radv_audit_records
            WHERE audit_run_id = %s
            """,
            (run_id,),
        )
        rows = cur.fetchall() or []

    manifest = {
        "run_id": run_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(rows),
        "evidence_package_url": f"/api/radv/audit-runs/{run_id}/manifest.json",
    }
    return manifest
