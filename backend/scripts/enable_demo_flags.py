"""
Ensure all demo-relevant feature flags are enabled for user_id=1 (admin).

Background
----------
Feature flags live in two places:

1. FEATURE_REGISTRY  (``app/services/feature_flag_service.py``) — the set of
   known flags and their *default* enabled state.  All demo-relevant flags
   default to True, but …

2. ``user_feature_flags`` table — per-user overrides.  If a previous admin
   action (or a past migration / seed run) wrote an override row with
   enabled=0, the registry default is silently ignored.

This script upserts override rows for every demo-relevant flag so that the
admin user (id=1) always resolves them as enabled=1, regardless of what
defaults or prior overrides say.  Re-running is fully idempotent.

Demo scenes covered
-------------------
- Scene 4 — Audit Readiness Card  → recapture_meat_audit
- Scene 5 — Velocity strip        → recapture_decay_curve
            CFO Summary           → recapture_cfo_forecast
            Bonus leaderboard     → recapture_bonus
- Scene 6 — KG Evidence Panel     → kg_evidence_panel
- All scenes — Peer percentile ribbon       → provider_peer_percentile
             — Top 5 HCC opportunities      → provider_top_hcc_opportunities
             — Patient outreach summary     → recapture_outreach

Hard rules enforced here
------------------------
- ``kg_brand_to_generic`` is intentionally NOT included — it is a
  compliance-sensitive opt-in that must remain off by default for all tenants.
- Only user_id=1 (admin) rows are touched.
- ON DUPLICATE KEY UPDATE means a second run is a no-op.

Usage
-----
    APP_ENV=demo python backend/scripts/enable_demo_flags.py

Or inside Docker:
    docker exec -e APP_ENV=demo raf-backend \
        python /app/scripts/enable_demo_flags.py
"""
from __future__ import annotations

import os
import sys

# Allow "python backend/scripts/enable_demo_flags.py" from repo root as well as
# "python /app/scripts/enable_demo_flags.py" from inside the container.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import raf_cursor  # noqa: E402
from app.services.feature_flag_service import FEATURE_REGISTRY  # noqa: E402

# ---------------------------------------------------------------------------
# Flags that MUST be on for the admin demo user.
# Only include flags that exist in FEATURE_REGISTRY.
# ---------------------------------------------------------------------------
DEMO_FLAGS: list[str] = [
    "recapture_meat_audit",        # Scene 4 — Audit Readiness Card
    "recapture_decay_curve",       # Scene 5 — Velocity strip
    "recapture_outreach",          # Scene 5 — Patient outreach summary
    "recapture_cfo_forecast",      # Scene 5 — CFO executive summary
    "recapture_bonus",             # Scene 5 — Coder bonus leaderboard
    "kg_evidence_panel",           # Scene 6 — Knowledge-Graph evidence chips
    "provider_peer_percentile",    # All scenes — Peer percentile ribbon
    "provider_top_hcc_opportunities",  # All scenes — Top 5 HCC opportunities
]

DEMO_USER_ID: int = 1  # admin@raf.health


def _validate_flag_keys() -> None:
    """Fail fast if a key in DEMO_FLAGS was removed from the registry."""
    unknown = [k for k in DEMO_FLAGS if k not in FEATURE_REGISTRY]
    if unknown:
        raise SystemExit(
            f"ERROR: The following keys are in DEMO_FLAGS but missing from "
            f"FEATURE_REGISTRY — update enable_demo_flags.py:\n  {unknown}"
        )


def enable_demo_flags(user_id: int = DEMO_USER_ID) -> list[str]:
    """
    Upsert every demo flag to enabled=1 for *user_id*.

    Returns the list of flag keys that were processed.
    """
    _validate_flag_keys()

    with raf_cursor(dictionary=False) as cursor:
        for key in DEMO_FLAGS:
            cursor.execute(
                """
                INSERT INTO user_feature_flags (user_id, flag_key, enabled)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE enabled = 1
                """,
                (user_id, key),
            )

    return list(DEMO_FLAGS)


def _verify(user_id: int = DEMO_USER_ID) -> dict[str, bool]:
    """Read back the resolved enabled state for every demo flag."""
    from app.services.feature_flag_service import list_flags

    all_flags = list_flags(user_id)
    return {
        f["key"]: f["enabled"]
        for f in all_flags
        if f["key"] in DEMO_FLAGS
    }


def main() -> None:
    processed = enable_demo_flags(DEMO_USER_ID)
    print(f"Upserted {len(processed)} demo feature-flag overrides for user_id={DEMO_USER_ID}:")
    for key in processed:
        print(f"  + {key}")

    states = _verify(DEMO_USER_ID)
    all_on = all(states.values())
    print("\nVerification (resolved state from list_flags):")
    for key, enabled in states.items():
        status = "OK" if enabled else "FAIL"
        print(f"  [{status}] {key} = {enabled}")

    if not all_on:
        failed = [k for k, v in states.items() if not v]
        raise SystemExit(
            f"\nERROR: The following flags still resolve as disabled: {failed}"
        )

    print(f"\nAll {len(processed)} demo flags are enabled for user_id={DEMO_USER_ID}.")
    print("\nTo verify via API (requires a running server):")
    print(
        "  curl -s -H 'Authorization: Bearer <token>' "
        "http://localhost:8000/api/feature-flags | "
        "python3 -m json.tool | grep -A2 'recapture_meat_audit'"
    )


if __name__ == "__main__":
    main()
