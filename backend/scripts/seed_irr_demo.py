"""Seed demo data so Cohen's kappa is computable on /api/recapture/audit-readiness.

Usage::
    docker exec raf-backend python /app/scripts/seed_irr_demo.py

Behaviour
---------
1. If ``recapture_gaps`` does not exist, refuse to run (pre-migration state —
   apply the recapture + meat-audit migrations first).
2. If the table has < 20 rows, insert 20 demo rows tagged with
   ``audit_notes='IRR_DEMO'`` so they can be cleaned up later.
3. For ~85 % of those rows, set both ``primary_coder_label`` and
   ``secondary_coder_label`` to ``accept``; for the remainder, set primary
   to ``accept`` and secondary to ``reject`` (a realistic disagreement
   pattern).  This produces a kappa around 0.6–0.7 — the "acceptable" band.
4. Idempotent — safe to re-run; existing demo rows are upserted, no
   duplicates produced.

Tags every row with ``audit_notes='IRR_DEMO'`` so an operator can purge with::
    DELETE FROM recapture_gaps WHERE audit_notes = 'IRR_DEMO';

Refuses to run unless ``APP_ENV`` is ``development`` or ``demo`` — production
demo seeds belong in a separate workflow with explicit confirmation.
"""
from __future__ import annotations

import os
import random
import sys
from typing import Any

# Make ``app`` package importable when run as a script inside the backend
# container's /app directory.
sys.path.insert(0, "/app")

from app.db import raf_cursor  # noqa: E402

DEMO_TAG = "IRR_DEMO"
TARGET_LABELED_ROWS = 20

# Realistic disagreement rate ~15 % → kappa ~0.65 (acceptable band).
DISAGREE_RATE = 0.15


def _ensure_demo_environment() -> None:
    env = os.environ.get("APP_ENV", "").lower()
    if env not in {"development", "demo", "dev"}:
        raise SystemExit(
            f"Refusing to seed demo data with APP_ENV={env!r}. "
            "Set APP_ENV=development or APP_ENV=demo to proceed."
        )


def _table_exists(cur: Any, name: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (name,),
    )
    return cur.fetchone() is not None


def _column_exists(cur: Any, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def _insert_demo_rows(cur: Any, n_to_insert: int) -> None:
    sample_hccs = [
        ("E11.65", "19", "Diabetes with hyperglycemia"),
        ("J44.9",  "111", "COPD, unspecified"),
        ("I50.9",  "85", "Heart failure, unspecified"),
        ("N18.4",  "138", "CKD stage 4"),
        ("F03.90", "52", "Dementia, unspecified"),
        ("D63.8",  "48", "Anemia in chronic disease"),
        ("R65.20", "2",  "Severe sepsis"),
        ("Z99.81", "84", "Dependence on supplemental oxygen"),
    ]
    rows: list[tuple] = []
    for i in range(n_to_insert):
        icd, hcc, label = sample_hccs[i % len(sample_hccs)]
        rows.append(
            (
                1,                     # tenant_id
                (i % 8) + 1,           # patient_id (1..8 cycling)
                icd,
                hcc,
                f"{label} (demo)",
                2026,                  # payment_year
                "open",                # status
                f"Patient with documented {label.lower()} per chart note",
                "M",                   # meat_element
                3000.0,                # revenue_impact
                "approved",            # audit_status — counts toward IRR
                999,                   # primary_coder_id (synthetic)
                998,                   # secondary_coder_id
                DEMO_TAG,              # audit_notes — purge marker
            )
        )

    cur.executemany(
        """
        INSERT INTO recapture_gaps (
            tenant_id, patient_id, icd10_code, hcc_code, condition_label,
            payment_year, status, evidence_phrase, meat_element,
            revenue_impact, audit_status, primary_coder_id, secondary_coder_id,
            audit_notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )


def _label_demo_rows(cur: Any) -> dict[str, int]:
    """Apply a deterministic label distribution that produces a meaningful
    Cohen's kappa.  Both raters need variance — if either always picks the
    same label, the chance-agreement baseline equals observed agreement and
    kappa collapses to 0.

    Target distribution over 20 rows:
        12 accept / accept    (both agree the HCC is supportable)
         4 reject / reject    (both agree it isn't)
         2 accept / reject    (primary supportable, secondary disagrees)
         2 reject / accept    (secondary catches an HCC primary missed)

    p_o = 16/20 = 0.80; p_primary_accept = 0.70; p_secondary_accept = 0.70
    p_e = 0.49 + 0.09 = 0.58; kappa = (0.80 - 0.58) / (1 - 0.58) ≈ 0.524
    Lands in the "moderate" band on Landis & Koch — realistic for a healthy
    coding team that catches each other's misses.
    """
    cur.execute(
        f"""
        SELECT id FROM recapture_gaps
        WHERE audit_notes = '{DEMO_TAG}'
        ORDER BY id ASC
        """
    )
    ids = [row["id"] for row in cur.fetchall()]
    if not ids:
        return {"accept_accept": 0, "reject_reject": 0, "accept_reject": 0, "reject_accept": 0}

    rng = random.Random(1234)
    n = len(ids)
    # Mixture proportions for n=20 — scale linearly for other sizes.
    n_aa = round(n * 0.60)
    n_rr = round(n * 0.20)
    n_ar = round(n * 0.10)
    n_ra = n - n_aa - n_rr - n_ar
    pattern: list[tuple[str, str]] = (
        [("accept", "accept")] * n_aa
        + [("reject", "reject")] * n_rr
        + [("accept", "reject")] * n_ar
        + [("reject", "accept")] * n_ra
    )
    rng.shuffle(pattern)

    counts = {"accept_accept": 0, "reject_reject": 0, "accept_reject": 0, "reject_accept": 0}
    for gap_id, (primary, secondary) in zip(ids, pattern):
        # Update the audit_status to keep proportion-agreement in sync with
        # kappa: rows where both labels agree on "accept" stay 'approved';
        # rows where labels disagree flip to 'rejected'; mutual rejections
        # are still 'approved' (the rejection is of the *HCC*, not of the
        # coder's work — both coders agreed).
        if primary == secondary == "accept":
            counts["accept_accept"] += 1
            new_status = "approved"
        elif primary == secondary == "reject":
            counts["reject_reject"] += 1
            new_status = "approved"
        elif primary == "accept" and secondary == "reject":
            counts["accept_reject"] += 1
            new_status = "rejected"
        else:
            counts["reject_accept"] += 1
            new_status = "rejected"
        cur.execute(
            """
            UPDATE recapture_gaps
            SET primary_coder_label = %s,
                secondary_coder_label = %s,
                audit_status = %s,
                primary_coded_at = COALESCE(primary_coded_at, NOW()),
                secondary_approved_at = COALESCE(secondary_approved_at, NOW())
            WHERE id = %s
            """,
            (primary, secondary, new_status, gap_id),
        )
    return counts


def main() -> None:
    _ensure_demo_environment()

    with raf_cursor() as cur:
        if not _table_exists(cur, "recapture_gaps"):
            raise SystemExit(
                "recapture_gaps table not found.  Apply the recapture + "
                "meat-audit migrations before running this seed."
            )
        for col in ("primary_coder_label", "secondary_coder_label", "audit_status"):
            if not _column_exists(cur, "recapture_gaps", col):
                raise SystemExit(
                    f"Missing column recapture_gaps.{col} — apply migration "
                    f"029_recapture_gaps_irr_labels.sql + add_recapture_meat_audit.sql first."
                )

        cur.execute(
            f"SELECT COUNT(*) AS n FROM recapture_gaps WHERE audit_notes = '{DEMO_TAG}'",
        )
        existing = int(cur.fetchone()["n"])
        if existing < TARGET_LABELED_ROWS:
            n_to_add = TARGET_LABELED_ROWS - existing
            print(f"Inserting {n_to_add} demo rows (have {existing}, target {TARGET_LABELED_ROWS})")
            _insert_demo_rows(cur, n_to_add)
        else:
            print(f"Demo rows already present ({existing}) — re-labelling deterministically")

        counts = _label_demo_rows(cur)

    total = sum(counts.values())
    agree = counts["accept_accept"] + counts["reject_reject"]
    agreement_pct = (agree / total * 100.0) if total else 0.0

    print(
        f"Seed complete: {total} labelled pairs "
        f"({counts['accept_accept']} accept/accept, "
        f"{counts['reject_reject']} reject/reject, "
        f"{counts['accept_reject']} accept/reject, "
        f"{counts['reject_accept']} reject/accept). "
        f"Raw agreement: {agreement_pct:.1f}%"
    )
    print("Hit GET /api/recapture/audit-readiness to see the live kappa.")


if __name__ == "__main__":
    main()
