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
"""
from __future__ import annotations

import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CMS RADV extrapolation constants
# ---------------------------------------------------------------------------
# CMS extrapolates each sampled error across the contract's enrolled
# population.  Public guidance places the contract-level extrapolation
# multiplier in the 50-60× range depending on payment year and sample
# methodology — the codebase uses 55× as the canonical mid-point.  Held
# in ONE place so the simulator + record persistence agree.
CMS_EXTRAPOLATION_MULTIPLIER = 55.0

# Average per-HCC payment used when a record is undefensible.  This is the
# CY-2026 commonly cited $11K-per-HCC midpoint.  Adjust here, not per-call.
AVG_HCC_PAYMENT_DOLLARS = 11_000.0

SampleMethod = Literal["random", "stratified_hcc", "high_risk_first"]


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def _candidate_patients(
    *, tenant_id: str, payment_year: int
) -> list[dict[str, Any]]:
    """Return all (patient_id, [hcc_codes], raw_raf_score) tuples for the
    tenant + payment year combination.

    A "candidate" is any patient with at least one HCC submitted in the
    payment year (raf_patient_hcc.measurement_year = payment_year).
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

    candidates: list[dict[str, Any]] = []
    for r in rows:
        csv = (r.get("hcc_codes_csv") or "").strip()
        hcc_codes = sorted({c.strip() for c in csv.split(",") if c.strip()}) if csv else []
        if not hcc_codes:
            continue
        candidates.append(
            {
                "patient_id": int(r["patient_id"]),
                "hcc_codes":  hcc_codes,
                "raf_score":  float(r.get("raf_score") or 0.0),
            }
        )
    return candidates


def _sample(
    candidates: list[dict[str, Any]],
    *,
    sample_size: int,
    method: SampleMethod,
) -> list[dict[str, Any]]:
    """Apply the requested sampling strategy.

    - random:           shuffle, take N
    - stratified_hcc:   bucket by primary HCC, draw proportionally
    - high_risk_first:  sort by raf_score desc, take N
    """
    if not candidates:
        return []
    if sample_size >= len(candidates):
        return list(candidates)

    if method == "high_risk_first":
        return sorted(candidates, key=lambda c: -c["raf_score"])[:sample_size]

    if method == "stratified_hcc":
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in candidates:
            primary = c["hcc_codes"][0] if c["hcc_codes"] else "_unknown_"
            buckets[primary].append(c)
        # proportional allocation
        total = len(candidates)
        picked: list[dict[str, Any]] = []
        for hcc, bucket in buckets.items():
            quota = max(1, round(sample_size * len(bucket) / total))
            random.shuffle(bucket)
            picked.extend(bucket[:quota])
        random.shuffle(picked)
        return picked[:sample_size]

    # default: random
    return random.sample(candidates, sample_size)


# ---------------------------------------------------------------------------
# CRUD — runs + records
# ---------------------------------------------------------------------------


def create_audit_run(
    *,
    tenant_id: str,
    name: str,
    payment_year: int,
    sample_size: int,
    sample_method: SampleMethod,
    created_by_user_id: int,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new audit run and seed it with sampled records."""
    if sample_size <= 0:
        raise ValueError("sample_size must be > 0")
    if sample_size > 5_000:
        raise ValueError("sample_size cannot exceed 5000")

    candidates = _candidate_patients(tenant_id=tenant_id, payment_year=payment_year)
    sampled = _sample(candidates, sample_size=sample_size, method=sample_method)

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_radv_audit_runs
                (tenant_id, name, payment_year, sample_size, sample_method,
                 status, created_by, notes)
            VALUES (%s, %s, %s, %s, %s, 'prep', %s, %s)
            """,
            (tenant_id, name, payment_year, sample_size, sample_method,
             created_by_user_id, notes),
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


def list_audit_runs(*, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return run headers + per-run counts for the tenant."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                r.id, r.name, r.payment_year, r.sample_size,
                r.sample_method, r.status, r.created_by,
                r.assumed_fail_rate, r.notes, r.created_at, r.updated_at,
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
    """Coder-side update of a single record.  Recomputes exposure $."""
    allowed_evidence = {"pending", "complete", "missing_meat", "chart_requested"}
    allowed_decision = {"pending", "defensible", "undefensible", "needs_remediation"}
    if evidence_status and evidence_status not in allowed_evidence:
        raise ValueError(f"invalid evidence_status: {evidence_status}")
    if final_decision and final_decision not in allowed_decision:
        raise ValueError(f"invalid final_decision: {final_decision}")

    # Compute exposure: only undefensible records contribute.
    # Per CMS extrapolation: each error × multiplier × avg payment.
    exposure_dollars: float = 0.0
    if final_decision == "undefensible":
        exposure_dollars = AVG_HCC_PAYMENT_DOLLARS * CMS_EXTRAPOLATION_MULTIPLIER
    elif final_decision == "needs_remediation":
        # half-weight — coder hasn't given up yet
        exposure_dollars = (AVG_HCC_PAYMENT_DOLLARS * CMS_EXTRAPOLATION_MULTIPLIER) / 2

    with raf_cursor() as cur:
        # Verify record is in this run + tenant.
        cur.execute(
            """
            SELECT rec.id FROM raf_radv_audit_records rec
            JOIN raf_radv_audit_runs r ON r.id = rec.audit_run_id
            WHERE rec.id = %s AND rec.audit_run_id = %s AND r.tenant_id = %s
            """,
            (record_id, run_id, tenant_id),
        )
        if not cur.fetchone():
            raise ValueError("record not found in this run/tenant")

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
) -> dict[str, Any]:
    """Run the CMS extrapolation simulator.

    `assumed_fail_rate` is a coder-supplied 0..1 probability that any
    record in the sample would fail.  The simulator returns:

      - observed_exposure_dollars  — sum of persisted record decisions
        (undefensible × full multiplier).  This is the floor.
      - simulated_exposure_dollars — what TOTAL exposure would be if the
        assumed fail rate applied to every sampled record.
    """
    if not (0.0 <= assumed_fail_rate <= 1.0):
        raise ValueError("assumed_fail_rate must be in [0,1]")

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT sample_size, payment_year FROM raf_radv_audit_runs
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

        # Persist the last assumed rate so reload shows the same value.
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

    simulated_failures = total * assumed_fail_rate
    simulated_exposure = (
        simulated_failures
        * AVG_HCC_PAYMENT_DOLLARS
        * CMS_EXTRAPOLATION_MULTIPLIER
    )

    return {
        "run_id": run_id,
        "payment_year": run["payment_year"],
        "sample_size": run["sample_size"],
        "total_records": total,
        "observed_undefensible": undefensible,
        "observed_exposure_dollars": round(observed_exposure, 2),
        "assumed_fail_rate": assumed_fail_rate,
        "simulated_failures": round(simulated_failures, 2),
        "simulated_exposure_dollars": round(simulated_exposure, 2),
        "extrapolation_multiplier": CMS_EXTRAPOLATION_MULTIPLIER,
        "avg_hcc_payment_dollars": AVG_HCC_PAYMENT_DOLLARS,
        "methodology_note": (
            "CMS extrapolates each sampled error across the contract; "
            f"the {CMS_EXTRAPOLATION_MULTIPLIER:.0f}× midpoint reflects "
            "contract-level enrolment scaling."
        ),
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
        # In a real deploy this would be an S3 presigned URL; for MVP we
        # emit a synthetic path that the FE can show as a download.
        "evidence_package_url": f"/api/radv/audit-runs/{run_id}/manifest.json",
    }
    return manifest
