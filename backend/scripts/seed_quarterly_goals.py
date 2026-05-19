"""Seed 3 active Q2-2026 quarterly goals for the demo tenant.

Goals seeded (idempotent — safe to re-run):
  1. RAF Capture Count  — target 250
  2. Revenue Recapture  — target $750,000
  3. Gaps Closed        — target 150

All for period 2026-Q2, tenant_id = '1'.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")
from app.db import raf_cursor  # noqa: E402

TENANT_ID = "1"
PERIOD = "2026-Q2"

GOALS = [
    ("raf_capture_count", 250.00, "RAF Capture Count"),
    ("revenue", 750000.00, "Revenue Recapture"),
    ("gaps_closed", 150.00, "Gaps Closed"),
]


def main() -> None:
    with raf_cursor() as cur:
        for metric, target, label in GOALS:
            # Check if goal already exists for this tenant/period/metric
            cur.execute(
                """
                SELECT id FROM raf_goals
                WHERE tenant_id = %s AND period = %s AND metric = %s
                LIMIT 1
                """,
                (TENANT_ID, PERIOD, metric),
            )
            row = cur.fetchone()
            if row:
                print(f"  [skip] {label} ({metric}) already exists (id={row['id']})")
                continue

            cur.execute(
                """
                INSERT INTO raf_goals (tenant_id, period, metric, target_value, owner_user_id, created_at)
                VALUES (%s, %s, %s, %s, NULL, NOW())
                """,
                (TENANT_ID, PERIOD, metric, target),
            )
            print(f"  [ok]   {label} ({metric}) → target={target}")

    print("Done seeding quarterly goals.")


if __name__ == "__main__":
    main()
