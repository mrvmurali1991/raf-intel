"""
Feature flag service.

Single source of truth for the per-user UI feature toggles surfaced on the
``/providers`` page (and any other page that opts in).

Architecture
------------
- Defaults live in ``FEATURE_REGISTRY`` (Python dict, this module).
- Per-user overrides live in the ``user_feature_flags`` table on the RAF DB.
- ``list_flags`` merges the two: registry defaults overridden by stored values.
- ``set_flag`` upserts a single override.
- ``reset_user_flags`` deletes every override for a user (back to defaults).

Adding a new flag
-----------------
1.  Append a ``FeatureFlag`` entry to ``FEATURE_REGISTRY`` below.
2.  Wrap the UI element with ``<FeatureFlag flagKey="...">`` on the frontend.
3.  No DB migration required — the registry IS the schema for "what flags
    exist".  The DB only stores per-user *overrides*.

Tenant note
-----------
Feature flags are per-USER, not per-tenant.  Tenant context still flows through
for audit/log purposes via the standard ``tid = int(tenant_id) if tenant_id is
not None else 1`` pattern, but is never used to scope flag lookup.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry — single source of truth for which flags exist
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeatureFlag:
    """Static metadata describing a single toggle."""

    key: str
    name: str
    description: str
    category: str
    default_enabled: bool = True
    scope: str = "user"  # reserved for future ("user" | "tenant" | "global")

    def to_dict(self, *, enabled: bool) -> dict[str, Any]:
        """Serialise for the API, layering in the resolved enabled-state."""
        d = asdict(self)
        d["enabled"] = bool(enabled)
        return d


# All 9 toggles for the /providers page rebuild.  Other agents will import
# these keys verbatim — keep them stable.
FEATURE_REGISTRY: dict[str, FeatureFlag] = {
    f.key: f
    for f in [
        FeatureFlag(
            key="provider_peer_percentile",
            name="Peer percentile ribbon",
            description=(
                "Shows where this provider ranks against peers in the same "
                "specialty for RAF / recapture metrics."
            ),
            category="Benchmarks",
        ),
        FeatureFlag(
            key="provider_top_hcc_opportunities",
            name="Top 5 HCC opportunities by $",
            description=(
                "Lists the five highest-revenue HCC capture opportunities "
                "across the provider's panel."
            ),
            category="Revenue",
        ),
        FeatureFlag(
            key="provider_yoy_trend",
            name="Year-over-year RAF / recapture trend",
            description=(
                "Time-series chart of RAF score and recapture rate across "
                "the last 24 months."
            ),
            category="Trends",
        ),
        FeatureFlag(
            key="provider_meat_audit_risk",
            name="MEAT audit-risk flag",
            description=(
                "Highlights diagnoses billed without sufficient MEAT "
                "(Monitor / Evaluate / Assess / Treat) documentation."
            ),
            category="Compliance",
        ),
        FeatureFlag(
            key="provider_revenue_breakdown",
            name="Revenue opportunity breakdown pie",
            description=(
                "Pie chart breaking the provider's open revenue opportunity "
                "into HCC / suspect / recapture / MEAT-fix segments."
            ),
            category="Revenue",
        ),
        FeatureFlag(
            key="provider_hcc_gap_drilldown",
            name="Patient-level HCC gap drilldown",
            description=(
                "Per-patient table of currently unbilled HCCs the provider "
                "could recapture in the current year."
            ),
            category="Patients",
        ),
        FeatureFlag(
            key="provider_suspect_hotlist",
            name="Real-time suspect hot-list",
            description=(
                "Live-updating list of high-confidence suspect conditions "
                "for patients on this provider's panel."
            ),
            category="Patients",
        ),
        FeatureFlag(
            key="provider_previsit_briefing",
            name="Pre-visit HCC briefing",
            description=(
                "One-page pre-visit briefing for upcoming appointments — "
                "open HCCs, recapture targets, and MEAT prompts."
            ),
            category="Workflow",
        ),
        FeatureFlag(
            key="provider_pdf_report",
            name="Downloadable provider PDF report",
            description=(
                "Generate a printable PDF summary of the provider scorecard "
                "(RAF, revenue, gaps, MEAT issues)."
            ),
            category="Reports",
        ),
        FeatureFlag(
            key="recapture_meat_audit",
            name="Dual-coder MEAT audit defense",
            description=(
                "RADV audit-readiness gauge, top-5 blockers, IRR tile, and "
                "PDF export of dual-signed gaps."
            ),
            category="Recapture",
        ),
        FeatureFlag(
            key="recapture_decay_curve",
            name="Recapture velocity & decay curve",
            description=(
                "Velocity KPIs (gaps closed per week) and decay-curve chart "
                "showing recapture-rate dynamics across cohorts."
            ),
            category="Recapture",
        ),
        FeatureFlag(
            key="recapture_outreach",
            name="Patient outreach summary",
            description=(
                "Channel-mix breakdown, response-rate cards, and last-touch "
                "metrics for patient outreach efforts."
            ),
            category="Recapture",
        ),
        FeatureFlag(
            key="kg_evidence_panel",
            name="Knowledge-Graph evidence chips & badges",
            description=(
                "Hoverable HCC popovers and evidence-chain badges across "
                "providers, recapture, and suspects pages."
            ),
            category="Knowledge Graph",
        ),
        FeatureFlag(
            key="recapture_cfo_forecast",
            name="CFO executive summary",
            description=(
                "Quarterly $ forecast, top conditions, top providers, and "
                "year-over-year revenue comparison aimed at CFO/CMO review."
            ),
            category="Recapture",
        ),
        FeatureFlag(
            key="recapture_bonus",
            name="Coder bonus leaderboard",
            description=(
                "Per-coder $ recaptured ranking with month-multiplier badges "
                "and gap-level bonus previews."
            ),
            category="Recapture",
        ),
    ]
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_registry() -> dict[str, FeatureFlag]:
    """Return the in-process registry (mainly used by tests)."""
    return FEATURE_REGISTRY


def list_flags(user_id: int) -> list[dict[str, Any]]:
    """
    Return every registered flag, with ``enabled`` resolved by merging
    registry defaults against this user's stored overrides.

    Order is stable: matches the registry insertion order, which lets the UI
    render flags in the order developers chose to register them.
    """
    if user_id is None:
        raise ValueError("user_id is required for feature flag lookup")

    overrides = _load_user_overrides(int(user_id))

    flags: list[dict[str, Any]] = []
    for key, flag in FEATURE_REGISTRY.items():
        enabled = overrides.get(key, flag.default_enabled)
        flags.append(flag.to_dict(enabled=enabled))
    return flags


def get_flag(user_id: int, key: str) -> dict[str, Any] | None:
    """Return a single resolved flag, or None if unknown."""
    flag = FEATURE_REGISTRY.get(key)
    if flag is None:
        return None
    overrides = _load_user_overrides(int(user_id))
    enabled = overrides.get(key, flag.default_enabled)
    return flag.to_dict(enabled=enabled)


def set_flag(user_id: int, key: str, enabled: bool) -> dict[str, Any]:
    """
    Upsert a per-user override.  Returns the resulting resolved flag.

    Raises KeyError if *key* is not in the registry — we refuse to persist
    overrides for unknown flags so a typo does not silently rot in the DB.
    """
    if user_id is None:
        raise ValueError("user_id is required to set a feature flag")
    if key not in FEATURE_REGISTRY:
        raise KeyError(f"Unknown feature flag: {key!r}")

    enabled_int = 1 if enabled else 0
    with raf_cursor(dictionary=False) as cursor:
        cursor.execute(
            """
            INSERT INTO user_feature_flags (user_id, flag_key, enabled)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE enabled = VALUES(enabled)
            """,
            (int(user_id), key, enabled_int),
        )

    logger.info(
        "feature_flag.set user_id=%s key=%s enabled=%s",
        user_id,
        key,
        bool(enabled),
    )
    flag = FEATURE_REGISTRY[key]
    return flag.to_dict(enabled=bool(enabled))


def reset_user_flags(user_id: int) -> int:
    """
    Wipe every override for *user_id*.  Returns the row count deleted.
    Subsequent ``list_flags`` calls fall back to registry defaults.
    """
    if user_id is None:
        raise ValueError("user_id is required to reset feature flags")

    with raf_cursor(dictionary=False) as cursor:
        cursor.execute(
            "DELETE FROM user_feature_flags WHERE user_id = %s",
            (int(user_id),),
        )
        deleted = cursor.rowcount or 0

    logger.info("feature_flag.reset user_id=%s deleted=%s", user_id, deleted)
    return int(deleted)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_user_overrides(user_id: int) -> dict[str, bool]:
    """
    Load the user's stored overrides as ``{flag_key: enabled_bool}``.

    Returns an empty dict on DB failure — feature flags must never break a
    request, so we degrade to "registry defaults only" rather than 500.
    """
    try:
        with raf_cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT flag_key, enabled FROM user_feature_flags WHERE user_id = %s",
                (int(user_id),),
            )
            rows = cursor.fetchall() or []
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning(
            "feature_flag._load_user_overrides failed for user_id=%s: %s",
            user_id,
            exc,
        )
        return {}

    return {
        str(row["flag_key"]): bool(int(row["enabled"]))
        for row in rows
        if row.get("flag_key") is not None
    }


def _registry_keys() -> Iterable[str]:
    """Convenience for tests."""
    return FEATURE_REGISTRY.keys()
