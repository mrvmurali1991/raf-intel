"""
Suspect enrichment — populate `meat_completeness` and `trumped_by_hcc` on
`raf_suspect_conditions.evidence_detail` JSON so the panel-builder (which
already extracts these fields from `evidence_detail`) can surface the
trumped-badge and the MEAT-aware sort in the frontend.

Why this exists
---------------
At the time the suspect engine writes a row, neither signal is computed:

* **meat_completeness** is derived from `raf_meat_evidence`, which is
  populated by a downstream MEAT-extraction job (sometimes the same scan,
  sometimes async). Without enrichment, the value is silently NULL and the
  UI falls back to "Net-new" for every suspect, defeating the MEAT-aware
  sort entirely (patient-safety review #6).

* **trumped_by_hcc** is computed at panel-render time by
  `raf_central._fetch_trumped_map` and is therefore correct in the rendered
  payload, but it is NOT persisted onto the suspect row. Persisting it
  lets downstream consumers (bulk exports, audit, analytics) see the same
  trumping decision the UI uses, and it makes the panel response cache-able
  without re-running the cross-join on every read.

Public API
----------
* :func:`enrich_suspects_for_patient` — recompute and persist both signals
  for every open suspect of a patient/year. Idempotent; safe to call
  repeatedly after each suspect scan.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


def _to_hcc_int(raw: Any) -> int | None:
    """Coerce a HCC representation (e.g. ``"HCC 85"``, ``85``, ``"85"``) to int.

    Returns ``None`` for unparseable values so callers can skip the row instead
    of writing a bogus 0 to ``trumped_by_hcc``.
    """
    if raw is None:
        return None
    try:
        return int(str(raw).replace("HCC", "").strip() or 0) or None
    except (ValueError, TypeError):
        return None


def enrich_suspects_for_patient(
    patient_id: int,
    tenant_id: str,
    year: int | None = None,
) -> int:
    """Recompute and persist `meat_completeness` and `trumped_by_hcc` onto
    every ``raf_suspect_conditions`` row for *(patient_id, year, tenant_id)*.

    Returns the number of rows actually updated. Rows whose enrichment values
    are unchanged from what is already on disk are still re-written (we use
    ``JSON_SET`` for atomicity); MySQL's affected-rows reporting drives the
    count.

    Safety / behaviour
    ------------------
    * Tenant scope is *required* — passing an empty tenant raises
      ``ValueError`` to avoid cross-tenant bleed-through.
    * If MEAT data has not yet been extracted for a given HCC, the row's
      ``meat_completeness`` slot stays NULL (panel-builder treats NULL as
      "Net-new", which is the correct fallback for unscored suspects).
    * The trumped lookup is best-effort — failures inside
      ``_fetch_trumped_map`` (DB hiccup, missing hierarchy table) are
      swallowed there and we proceed with an empty map.
    """
    if not tenant_id:
        raise ValueError(
            "enrich_suspects_for_patient requires tenant_id; refusing to "
            "enrich without tenant scope (cross-tenant data leakage risk)."
        )

    year = year or date.today().year

    # Lazy imports to avoid circular dependency: raf_central imports
    # suspect_engine; enriching at suspect-scan time would otherwise re-pull
    # raf_central at module-import which pulls suspect_engine again.
    from app.routers.raf_central import _fetch_trumped_map
    from app.services.meat_evidence_service import calculate_meat_completeness

    # ── 1. MEAT completeness map (hcc_code:int → fraction 0..1) ───────────
    meat_by_hcc: dict[int, float] = {}
    try:
        meat_payload = calculate_meat_completeness(patient_id, year) or {}
        for entry in meat_payload.get("per_hcc") or []:
            hcc_int = _to_hcc_int(entry.get("hcc_code"))
            if hcc_int is None:
                continue
            present_count = sum(
                1 for k in ("m", "e", "a", "t") if bool(entry.get(k))
            )
            meat_by_hcc[hcc_int] = round(present_count / 4.0, 4)
    except Exception as exc:
        logger.warning(
            "enrich_suspects: MEAT lookup failed pid=%s year=%s: %s",
            patient_id, year, exc,
        )

    # ── 2. Trumped map (subordinate hcc → dominant hcc) ───────────────────
    try:
        trumped_map = _fetch_trumped_map(patient_id, year, tenant_id) or {}
    except Exception as exc:
        logger.warning(
            "enrich_suspects: trumped lookup failed pid=%s year=%s: %s",
            patient_id, year, exc,
        )
        trumped_map = {}

    # ── 3. Iterate rows, persist enrichments ──────────────────────────────
    updated = 0
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, suspect_hcc
              FROM raf_suspect_conditions
             WHERE patient_id = %s
               AND measurement_year = %s
               AND tenant_id = %s
            """,
            (patient_id, year, tenant_id),
        )
        rows = cur.fetchall() or []

        for row in rows:
            row_id = row["id"]
            hcc_int = _to_hcc_int(row.get("suspect_hcc"))
            if hcc_int is None:
                continue

            meat_pct = meat_by_hcc.get(hcc_int)  # may be None
            trumped_by = trumped_map.get(hcc_int)  # may be None

            # JSON_SET treats NULL the same way it treats a real value (stores
            # the JSON null literal); we keep that — `_build_suspects` checks
            # `isinstance(mc, (int, float))` and so will correctly ignore a
            # null-valued slot.
            cur.execute(
                """
                UPDATE raf_suspect_conditions
                   SET evidence_detail = JSON_SET(
                           COALESCE(evidence_detail, JSON_OBJECT()),
                           '$.meat_completeness', CAST(%s AS JSON),
                           '$.trumped_by_hcc',    CAST(%s AS JSON)
                       ),
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (
                    json.dumps(meat_pct),     # → 'null' or '0.75'
                    json.dumps(trumped_by),   # → 'null' or '85'
                    row_id,
                ),
            )
            if cur.rowcount > 0:
                updated += 1

    logger.info(
        "enrich_suspects pid=%s year=%s tenant=%s → %d/%d rows updated "
        "(meat_hits=%d, trumped_hits=%d)",
        patient_id, year, tenant_id, updated, len(rows),
        len(meat_by_hcc), len(trumped_map),
    )
    return updated
