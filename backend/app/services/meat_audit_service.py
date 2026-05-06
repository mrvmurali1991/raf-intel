"""
MEAT Audit Service — dual-coder review workflow + audit-readiness scoring.

CMS RADV audits scrutinise whether each recaptured HCC has documented MEAT
evidence (Monitor / Evaluate / Assess / Treat).  Without dual-coder sign-off
plus a captured MEAT phrase, big plans flag the program as audit-risky.

This module owns the workflow state machine on ``recapture_gaps``::

    draft ──► primary_coded ──► review_pending ──► approved
                                              └─► rejected ──► primary_coded

Submission to review is automatic-only for "high-revenue" gaps OR gaps that
are >1 year old (older claims are statistically more audit-prone).  Lower-
risk gaps may be approved by a single coder unless the caller explicitly
requests dual sign-off.

Public API
----------
record_primary_evidence(gap_id, coder_id, phrase, meat_element, source_url=None, notes=None, tenant_id)
submit_for_review(gap_id, coder_id, tenant_id)
approve_review(gap_id, secondary_coder_id, notes=None, tenant_id)
reject_review(gap_id, secondary_coder_id, reason, tenant_id)
get_review_queue(tenant_id, status='review_pending')
compute_audit_readiness(tenant_id)

All writes go through a tenant_id guard so a coder cannot mutate another
tenant's row.  ``coder_id`` comes from ``auth.get_current_user()['id']`` at
the router layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — review-queue selection thresholds
# ---------------------------------------------------------------------------

# Gaps ≥ this revenue automatically require dual-coder review.
HIGH_REVENUE_THRESHOLD: float = 5000.00

# Gaps whose underlying chart documentation is older than this many days are
# considered statistically audit-prone — RADV looks back ~12 months.
OLD_GAP_DAYS: int = 365


_VALID_MEAT_ELEMENTS = {"M", "E", "A", "T", "MULTI"}

# The columns we serialise out of recapture_gaps for queue / readiness queries.
# Listed once to avoid copy-paste drift.
_AUDIT_COLUMNS = """
    rg.id,
    rg.patient_id,
    rg.tenant_id,
    rg.hcc_code,
    rg.icd10_code,
    rg.prior_year,
    rg.current_year,
    rg.status,
    rg.last_encounter_date,
    rg.provider_npi,
    rg.revenue_impact,
    rg.created_at,
    rg.updated_at,
    rg.evidence_phrase,
    rg.evidence_source_url,
    rg.meat_element,
    rg.primary_coder_id,
    rg.primary_coded_at,
    rg.secondary_coder_id,
    rg.secondary_approved_at,
    rg.audit_status,
    rg.audit_notes
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalise datetime/date fields to ISO strings for JSON serialisation."""
    if row is None:
        return None
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _fetch_gap(cursor, gap_id: int, tenant_id: str) -> dict[str, Any] | None:
    cursor.execute(
        f"SELECT {_AUDIT_COLUMNS} FROM recapture_gaps rg "
        "WHERE rg.id = %s AND rg.tenant_id = %s",
        (gap_id, tenant_id),
    )
    return cursor.fetchone()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. record_primary_evidence
# ---------------------------------------------------------------------------


def record_primary_evidence(
    gap_id: int,
    coder_id: int,
    phrase: str,
    meat_element: str,
    source_url: str | None = None,
    notes: str | None = None,
    tenant_id: str = "1",
) -> dict[str, Any]:
    """Attach MEAT evidence to a gap and mark it primary-coded.

    Writes ``evidence_phrase / evidence_source_url / meat_element /
    primary_coder_id / primary_coded_at`` and transitions ``audit_status``
    to ``primary_coded``.

    Parameters
    ----------
    gap_id, tenant_id   — row + tenant guard.
    coder_id            — users.id of the primary coder (current_user["id"]).
    phrase              — quoted text from the chart note (free-text).
    meat_element        — one of ``M / E / A / T / MULTI``.
    source_url          — optional deep-link / FHIR DocumentReference URL.
    notes               — optional free-text notes (appended to audit_notes).

    Returns
    -------
    dict   — the updated gap row (datetimes ISO-formatted).

    Raises
    ------
    ValueError          — invalid meat_element, blank phrase, or unknown gap.
    """
    if not phrase or not phrase.strip():
        raise ValueError("phrase must be non-empty")
    elem = (meat_element or "").upper().strip()
    if elem not in _VALID_MEAT_ELEMENTS:
        raise ValueError(
            f"meat_element must be one of {sorted(_VALID_MEAT_ELEMENTS)}; got {meat_element!r}"
        )

    now = _now_utc()
    update_sql = """
        UPDATE recapture_gaps
           SET evidence_phrase     = %s,
               evidence_source_url = %s,
               meat_element        = %s,
               primary_coder_id    = %s,
               primary_coded_at    = %s,
               audit_status        = 'primary_coded',
               audit_notes         = COALESCE(NULLIF(%s, ''), audit_notes)
         WHERE id = %s AND tenant_id = %s
    """

    with raf_cursor() as cur:
        cur.execute(
            update_sql,
            (
                phrase.strip(),
                source_url,
                elem,
                coder_id,
                now,
                notes,
                gap_id,
                tenant_id,
            ),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Gap {gap_id} not found for tenant {tenant_id}")

        row = _fetch_gap(cur, gap_id, tenant_id)

    logger.info(
        "meat_audit.record_primary_evidence gap_id=%s coder=%s element=%s",
        gap_id, coder_id, elem,
    )
    return _row_to_dict(row) or {}


# ---------------------------------------------------------------------------
# 2. submit_for_review
# ---------------------------------------------------------------------------


def _gap_requires_review(gap: dict[str, Any]) -> bool:
    """Return True if the gap is high-revenue OR > OLD_GAP_DAYS old."""
    revenue = float(gap.get("revenue_impact") or 0.0)
    if revenue >= HIGH_REVENUE_THRESHOLD:
        return True

    # Compare in UTC; tolerate naive datetimes by treating them as UTC.
    created = gap.get("created_at")
    if isinstance(created, datetime):
        cutoff = _now_utc() - timedelta(days=OLD_GAP_DAYS)
        created_aware = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        if created_aware < cutoff:
            return True
    return False


def submit_for_review(
    gap_id: int,
    coder_id: int,
    tenant_id: str = "1",
) -> dict[str, Any]:
    """Move a gap into review_pending if it qualifies for dual-coder review.

    Qualifies when revenue_impact ≥ HIGH_REVENUE_THRESHOLD OR the gap was
    created more than OLD_GAP_DAYS ago.  Lower-risk gaps stay in
    ``primary_coded`` and the caller may mark them ``approved`` directly via
    ``approve_review`` (which still records secondary_coded_at = primary_coded_at
    when secondary_coder_id == primary_coder_id).

    Returns the updated gap dict.  The ``review_required`` key tells the
    UI whether dual sign-off is mandatory.
    """
    with raf_cursor() as cur:
        gap = _fetch_gap(cur, gap_id, tenant_id)
        if gap is None:
            raise ValueError(f"Gap {gap_id} not found for tenant {tenant_id}")
        if gap["audit_status"] not in ("primary_coded", "rejected"):
            raise ValueError(
                f"Gap {gap_id} cannot be submitted from audit_status="
                f"{gap['audit_status']!r}; must be primary_coded or rejected"
            )
        if not gap.get("evidence_phrase"):
            raise ValueError(
                f"Gap {gap_id} has no evidence_phrase; record evidence before submit"
            )

        required = _gap_requires_review(gap)
        new_status = "review_pending" if required else "primary_coded"

        cur.execute(
            "UPDATE recapture_gaps SET audit_status = %s WHERE id = %s AND tenant_id = %s",
            (new_status, gap_id, tenant_id),
        )

        gap = _fetch_gap(cur, gap_id, tenant_id)

    out = _row_to_dict(gap) or {}
    out["review_required"] = required
    logger.info(
        "meat_audit.submit_for_review gap_id=%s coder=%s required=%s",
        gap_id, coder_id, required,
    )
    return out


# ---------------------------------------------------------------------------
# 3. approve_review
# ---------------------------------------------------------------------------


def approve_review(
    gap_id: int,
    secondary_coder_id: int,
    notes: str | None = None,
    tenant_id: str = "1",
) -> dict[str, Any]:
    """Approve a review_pending gap as the secondary coder.

    Sets ``secondary_coder_id``, ``secondary_approved_at``, transitions
    ``audit_status`` to ``approved``.  The secondary coder MUST differ from
    the primary coder — same-person sign-off is rejected.
    """
    now = _now_utc()
    with raf_cursor() as cur:
        gap = _fetch_gap(cur, gap_id, tenant_id)
        if gap is None:
            raise ValueError(f"Gap {gap_id} not found for tenant {tenant_id}")
        if gap["audit_status"] not in ("review_pending", "primary_coded"):
            raise ValueError(
                f"Gap {gap_id} cannot be approved from audit_status="
                f"{gap['audit_status']!r}"
            )
        if gap.get("primary_coder_id") and int(gap["primary_coder_id"]) == int(secondary_coder_id):
            raise ValueError(
                "Secondary coder must differ from primary coder for dual sign-off"
            )

        cur.execute(
            """
            UPDATE recapture_gaps
               SET secondary_coder_id     = %s,
                   secondary_approved_at  = %s,
                   audit_status           = 'approved',
                   audit_notes            = CASE
                       WHEN %s IS NULL OR %s = '' THEN audit_notes
                       WHEN audit_notes IS NULL THEN %s
                       ELSE CONCAT(audit_notes, '\n', %s)
                   END
             WHERE id = %s AND tenant_id = %s
            """,
            (secondary_coder_id, now, notes, notes, notes, notes, gap_id, tenant_id),
        )
        gap = _fetch_gap(cur, gap_id, tenant_id)

    logger.info(
        "meat_audit.approve_review gap_id=%s secondary=%s",
        gap_id, secondary_coder_id,
    )
    return _row_to_dict(gap) or {}


# ---------------------------------------------------------------------------
# 4. reject_review
# ---------------------------------------------------------------------------


def reject_review(
    gap_id: int,
    secondary_coder_id: int,
    reason: str,
    tenant_id: str = "1",
) -> dict[str, Any]:
    """Reject a review_pending gap; flips audit_status back to ``rejected``.

    Stores the reviewer's reason in ``audit_notes`` (appending if existing).
    The primary coder can then update evidence and re-submit.
    """
    if not reason or not reason.strip():
        raise ValueError("reason must be non-empty when rejecting a review")

    with raf_cursor() as cur:
        gap = _fetch_gap(cur, gap_id, tenant_id)
        if gap is None:
            raise ValueError(f"Gap {gap_id} not found for tenant {tenant_id}")
        if gap["audit_status"] != "review_pending":
            raise ValueError(
                f"Gap {gap_id} cannot be rejected from audit_status="
                f"{gap['audit_status']!r}"
            )

        cur.execute(
            """
            UPDATE recapture_gaps
               SET audit_status      = 'rejected',
                   secondary_coder_id = %s,
                   audit_notes       = CASE
                       WHEN audit_notes IS NULL THEN %s
                       ELSE CONCAT(audit_notes, '\n[REJECT] ', %s)
                   END
             WHERE id = %s AND tenant_id = %s
            """,
            (secondary_coder_id, f"[REJECT] {reason.strip()}", reason.strip(), gap_id, tenant_id),
        )
        gap = _fetch_gap(cur, gap_id, tenant_id)

    logger.info(
        "meat_audit.reject_review gap_id=%s secondary=%s",
        gap_id, secondary_coder_id,
    )
    return _row_to_dict(gap) or {}


# ---------------------------------------------------------------------------
# 5. get_review_queue
# ---------------------------------------------------------------------------


def get_review_queue(
    tenant_id: str,
    status: str = "review_pending",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return gaps awaiting (or in) the requested workflow state.

    Joins to ``users`` to surface the primary coder's name + email so the
    reviewer can see who attached the evidence.  Falls back gracefully when
    primary_coder_id is null.
    """
    sql = f"""
        SELECT
            {_AUDIT_COLUMNS},
            CONCAT(COALESCE(pt.first_name, ''), ' ', COALESCE(pt.last_name, '')) AS patient_name,
            up.full_name AS primary_coder_name,
            up.email     AS primary_coder_email,
            us.full_name AS secondary_coder_name,
            us.email     AS secondary_coder_email
        FROM recapture_gaps rg
        LEFT JOIN patients pt ON pt.id = rg.patient_id AND pt.tenant_id = rg.tenant_id
        LEFT JOIN users up    ON up.id = rg.primary_coder_id
        LEFT JOIN users us    ON us.id = rg.secondary_coder_id
        WHERE rg.tenant_id   = %s
          AND rg.audit_status = %s
        ORDER BY rg.revenue_impact DESC, rg.created_at ASC
        LIMIT %s
    """
    with raf_cursor() as cur:
        cur.execute(sql, (tenant_id, status, limit))
        rows = cur.fetchall() or []

    return [_row_to_dict(r) or {} for r in rows]


# ---------------------------------------------------------------------------
# 6. compute_audit_readiness
# ---------------------------------------------------------------------------


def compute_audit_readiness(tenant_id: str) -> dict[str, Any]:
    """Return audit-readiness metrics for the tenant.

    Output::

        {
            "total_gaps":      int,
            "with_evidence":   int,
            "dual_signed":     int,
            "audit_ready_pct": float (0–100),
            "missing_meat":    [{"gap_id": int, "hcc": str, "patient_id": str,
                                 "reason": str}, ...]   # up to 5
        }

    A gap is considered:
      * with_evidence  — has a non-empty evidence_phrase + meat_element
      * dual_signed    — audit_status = 'approved' AND has both coder ids
      * audit_ready    — dual_signed (the strict definition)
    """
    # primary_coder_label / secondary_coder_label were added in migration 029.
    # We use COALESCE so this query still works on pre-migration instances where
    # the columns may not yet exist — MySQL raises an error on unknown columns,
    # so we fall back gracefully in the except block below.
    sql = """
        SELECT
            id,
            patient_id,
            hcc_code,
            evidence_phrase,
            meat_element,
            audit_status,
            primary_coder_id,
            secondary_coder_id,
            revenue_impact,
            primary_coder_label,
            secondary_coder_label
        FROM recapture_gaps
        WHERE tenant_id = %s
          AND status IN ('open', 'recaptured')
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (tenant_id,))
            rows = cur.fetchall() or []
    except Exception:
        # Fallback: query without the new IRR-label columns (pre-migration instances).
        sql_compat = sql.replace(
            ",\n            primary_coder_label,\n            secondary_coder_label", ""
        )
        with raf_cursor() as cur:
            cur.execute(sql_compat, (tenant_id,))
            rows = cur.fetchall() or []

    total = len(rows)
    with_evidence = 0
    dual_signed = 0
    secondary_approved = 0   # secondary coder agreed with primary
    secondary_rejected = 0   # secondary coder disagreed with primary
    pending_review = 0       # has primary coder but no secondary action yet
    missing: list[dict[str, Any]] = []

    # Pairs of (primary_label, secondary_label) for kappa computation.
    # Only collected for rows where BOTH independent labels are present
    # (migration 029).  Legacy rows where the columns are absent or NULL
    # are excluded from the kappa set and counted under proportion agreement.
    kappa_pairs: list[tuple[str, str]] = []

    for r in rows:
        has_phrase = bool((r.get("evidence_phrase") or "").strip()) and bool(r.get("meat_element"))
        if has_phrase:
            with_evidence += 1
        if (
            r.get("audit_status") == "approved"
            and r.get("primary_coder_id")
            and r.get("secondary_coder_id")
        ):
            dual_signed += 1

        status = r.get("audit_status")
        has_primary = bool(r.get("primary_coder_id"))
        has_secondary = bool(r.get("secondary_coder_id"))
        if has_primary and has_secondary and status == "approved":
            secondary_approved += 1
        elif has_primary and has_secondary and status == "rejected":
            secondary_rejected += 1
        elif has_primary and not has_secondary and status in ("primary_coded", "review_pending"):
            pending_review += 1

        # Collect independent labels for kappa (migration 029).
        p_label = r.get("primary_coder_label")
        s_label = r.get("secondary_coder_label")
        if p_label and s_label:
            kappa_pairs.append((str(p_label), str(s_label)))

        # Surface gaps that block audit-readiness — order by revenue desc later.
        if not has_phrase or r.get("audit_status") != "approved":
            reason_parts: list[str] = []
            if not has_phrase:
                reason_parts.append("no MEAT phrase")
            if r.get("audit_status") != "approved":
                reason_parts.append(f"status={r.get('audit_status') or 'draft'}")
            missing.append(
                {
                    "gap_id": int(r["id"]),
                    "hcc": str(r["hcc_code"]),
                    "patient_id": r.get("patient_id"),
                    "revenue_impact": float(r.get("revenue_impact") or 0.0),
                    "reason": "; ".join(reason_parts),
                }
            )

    # Top-5 by revenue impact (descending) — these are the costliest blockers.
    missing.sort(key=lambda m: -m["revenue_impact"])
    missing_top5 = missing[:5]

    audit_ready_pct = round((dual_signed / total) * 100.0, 2) if total else 0.0

    # ---------------------------------------------------------------------------
    # Inter-rater reliability
    # ---------------------------------------------------------------------------
    # When migration 029 labels are present (kappa_pairs non-empty) we compute
    # full Cohen's kappa with chance correction.  κ = (p_o - p_e) / (1 - p_e)
    # where p_o = observed agreement and p_e = expected agreement by chance
    # (product of marginal frequencies).
    #
    # When no independent labels exist (pre-migration or no gaps reviewed yet)
    # we fall back to the legacy proportion-agreement metric.
    irr_total = secondary_approved + secondary_rejected
    irr_pct = round((secondary_approved / irr_total) * 100.0, 2) if irr_total else None
    irr_band = (
        None if irr_pct is None
        else "excellent" if irr_pct >= 90
        else "acceptable" if irr_pct >= 80
        else "needs_review"
    )

    kappa: float | None = None
    kappa_n = len(kappa_pairs)
    irr_method = "proportion_agreement"

    if kappa_n >= 2:
        # Binary labels: 'accept' or 'reject'
        LABELS = ("accept", "reject")
        # Observed agreement
        agreed = sum(1 for p, s in kappa_pairs if p == s)
        p_o = agreed / kappa_n

        # Marginal frequencies
        def _marginal(side: int, label: str) -> float:
            return sum(1 for pair in kappa_pairs if pair[side] == label) / kappa_n

        p_e = sum(_marginal(0, lbl) * _marginal(1, lbl) for lbl in LABELS)

        if p_e < 1.0:
            raw_kappa = (p_o - p_e) / (1.0 - p_e)
            kappa = round(max(-1.0, min(1.0, raw_kappa)), 4)
        else:
            # Perfect agreement by chance (degenerate) — kappa undefined → None
            kappa = None

        # Kappa band thresholds follow Landis & Koch (1977)
        if kappa is not None:
            irr_band = (
                "almost_perfect" if kappa >= 0.81
                else "substantial" if kappa >= 0.61
                else "moderate" if kappa >= 0.41
                else "fair" if kappa >= 0.21
                else "slight" if kappa >= 0.0
                else "poor"
            )
        irr_method = "cohens_kappa"
        # Publish kappa as agreement_pct-equivalent (×100) so the UI tile
        # can reuse the same rendering path.
        if kappa is not None:
            irr_pct = round(kappa * 100.0, 2)

    return {
        "total_gaps":      total,
        "with_evidence":   with_evidence,
        "dual_signed":     dual_signed,
        "audit_ready_pct": audit_ready_pct,
        "missing_meat":    missing_top5,
        "inter_rater_reliability": {
            "secondary_approved":  secondary_approved,
            "secondary_rejected":  secondary_rejected,
            "pending_review":      pending_review,
            "agreement_pct":       irr_pct,
            "band":                irr_band,
            "method":              irr_method,
            "kappa":               kappa,
            "kappa_n":             kappa_n,
            "note": (
                "Cohen's kappa computed from independent primary/secondary coder "
                "labels (migration 029).  Kappa >= 0.61 = substantial agreement. "
                "Falls back to proportion_agreement when labels are absent."
                if irr_method == "cohens_kappa"
                else "Proportion of secondary-reviewed gaps where the secondary "
                "coder approved (vs rejected) the primary's coding.  Lower "
                "than 80%% suggests training/guideline drift."
            ),
        },
    }


# ---------------------------------------------------------------------------
# 7. get_approved_gaps_for_pdf
# ---------------------------------------------------------------------------


def get_approved_gaps_for_pdf(
    tenant_id: str,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Return all dual-signed gaps for the audit PDF, joined with coder names.

    When ``year`` is provided, restricts to gaps where current_year == year.
    """
    params: list[Any] = [tenant_id]
    year_clause = ""
    if year is not None:
        year_clause = "AND rg.current_year = %s"
        params.append(year)

    sql = f"""
        SELECT
            {_AUDIT_COLUMNS},
            CONCAT(COALESCE(pt.first_name, ''), ' ', COALESCE(pt.last_name, '')) AS patient_name,
            up.full_name AS primary_coder_name,
            up.email     AS primary_coder_email,
            us.full_name AS secondary_coder_name,
            us.email     AS secondary_coder_email
        FROM recapture_gaps rg
        LEFT JOIN patients pt ON pt.id = rg.patient_id AND pt.tenant_id = rg.tenant_id
        LEFT JOIN users up    ON up.id = rg.primary_coder_id
        LEFT JOIN users us    ON us.id = rg.secondary_coder_id
        WHERE rg.tenant_id    = %s
          AND rg.audit_status = 'approved'
          {year_clause}
        ORDER BY rg.patient_id, rg.hcc_code
    """
    with raf_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []

    return [_row_to_dict(r) or {} for r in rows]
