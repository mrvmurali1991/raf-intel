"""
EDPS / CMS MAO-004 feedback ingest service.

Parses the CMS Medicare Advantage Organization (MAO) 004 response report —
the CMS reply telling a plan which encounter-derived RAF hits were accepted
or rejected by EDPS — into the local ``raf_edps_feedback`` table so the
RAF Reconciliation UI can render a real ``accepted_raf`` instead of the
"waiting for EDPS feedback" placeholder.

For the first cut we accept a simplified CSV with header::

    patient_id,measurement_year,accepted_raf,accepted_hcc_codes,rejected_hcc_codes,response_received_at

Where ``accepted_hcc_codes`` and ``rejected_hcc_codes`` are pipe- or
semicolon-separated HCC code lists (e.g. ``"19|108|136"``). The
fixed-width CMS MAO-004 binary format is intentionally NOT supported yet —
a follow-up will plug a fixed-width parser in via ``parse_mao004_fixed``.

All rows are written tenant-scoped via ``raf_cursor()`` and upsert on
``(patient_id, measurement_year, tenant_id)``: the newest response for a
given patient/year wins, while keeping older rows for audit history.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# Header contract for the simplified MAO-004 CSV. Keep in sync with the
# router's upload docstring so coders see the exact column names.
EDPS_CSV_COLUMNS: tuple[str, ...] = (
    "patient_id",
    "measurement_year",
    "accepted_raf",
    "accepted_hcc_codes",
    "rejected_hcc_codes",
    "response_received_at",
)


@dataclass
class EDPSIngestResult:
    """Summary of one CSV ingest call."""

    rows_total: int = 0
    rows_upserted: int = 0
    rows_failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_total": self.rows_total,
            "rows_upserted": self.rows_upserted,
            "rows_failed": self.rows_failed,
            "errors": self.errors[:50],
        }


def _split_hcc_list(raw: str | None) -> list[int]:
    """Split a pipe/semicolon/comma-delimited HCC code list into ints.

    Empty/blank string returns an empty list. Non-numeric tokens are
    silently dropped — MAO-004 lines occasionally include trailing
    annotations like ``"19*"`` that we ignore. We deduplicate while
    preserving first-seen order so the JSON stored in the DB is stable.
    """
    if not raw:
        return []
    out: list[int] = []
    seen: set[int] = set()
    # Accept any of |, ;, , as a separator so callers don't have to
    # normalise the file before upload.
    tokens = (
        raw.replace(";", "|")
        .replace(",", "|")
        .split("|")
    )
    for tok in tokens:
        t = tok.strip()
        if not t:
            continue
        # Strip a trailing asterisk or whitespace that MAO-004 sometimes
        # uses for "accepted-with-warnings" rows.
        t = t.rstrip("*").strip()
        try:
            code = int(float(t))
        except (TypeError, ValueError):
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _parse_response_dt(raw: str | None) -> datetime | None:
    """Parse a response timestamp. Accepts ISO-8601 or common CMS formats."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Try a few formats so coders can paste the field from Excel without
    # having to reformat.
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    logger.debug("edps_ingest: could not parse response_received_at=%r", raw)
    return None


def parse_mao004_csv(content: bytes | str) -> list[dict[str, Any]]:
    """Parse a simplified MAO-004 CSV blob into validated row dicts.

    Returns one dict per data row using the canonical
    :data:`EDPS_CSV_COLUMNS` keys. Rows that lack ``patient_id`` or
    ``measurement_year`` are skipped (with a warning) — they have no
    primary-key target to upsert to.

    The HCC lists are returned as ``list[int]`` (already parsed); the
    timestamp is returned as :class:`datetime` or ``None``; the
    ``accepted_raf`` value is returned as ``float`` or ``None``.
    """
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    else:
        text = content

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []

    # Normalise headers (strip BOM whitespace, lowercase) so a copy-pasted
    # CMS file with stray spaces still parses.
    norm_headers = [(h or "").strip().lower() for h in reader.fieldnames]
    missing = [c for c in EDPS_CSV_COLUMNS if c not in norm_headers]
    if missing:
        raise ValueError(
            f"EDPS CSV missing required column(s): {', '.join(missing)}. "
            f"Expected header: {','.join(EDPS_CSV_COLUMNS)}"
        )

    rows: list[dict[str, Any]] = []
    for raw in reader:
        # csv.DictReader keys mirror the original header casing — re-key
        # with the normalised header so downstream code uses a single shape.
        norm: dict[str, Any] = {}
        for orig_key, value in raw.items():
            if orig_key is None:
                continue
            norm[(orig_key or "").strip().lower()] = value

        try:
            pid_raw = (norm.get("patient_id") or "").strip()
            year_raw = (norm.get("measurement_year") or "").strip()
            if not pid_raw or not year_raw:
                continue
            pid = int(float(pid_raw))
            year = int(float(year_raw))
        except (TypeError, ValueError):
            continue

        accepted_raf: float | None = None
        ar_raw = (norm.get("accepted_raf") or "").strip()
        if ar_raw:
            try:
                accepted_raf = float(ar_raw)
            except ValueError:
                accepted_raf = None

        rows.append(
            {
                "patient_id": pid,
                "measurement_year": year,
                "accepted_raf": accepted_raf,
                "accepted_hcc_codes": _split_hcc_list(norm.get("accepted_hcc_codes")),
                "rejected_hcc_codes": _split_hcc_list(norm.get("rejected_hcc_codes")),
                "response_received_at": _parse_response_dt(
                    norm.get("response_received_at")
                ),
            }
        )
    return rows


def upsert_edps_rows(
    rows: Iterable[dict[str, Any]],
    *,
    tenant_id: str,
) -> EDPSIngestResult:
    """Insert one ``raf_edps_feedback`` row per parsed CSV row.

    We INSERT (not UPDATE) so the table preserves the full response
    history; the GET endpoint and the raf_central join both pick the
    latest row via ``ORDER BY response_received_at DESC, ingested_at DESC``.

    Each row is written inside its own try/except so a bad row does not
    abort the whole batch — failures are collected into
    :class:`EDPSIngestResult`.``errors`` and surfaced to the caller.
    """
    result = EDPSIngestResult()
    sql = (
        "INSERT INTO raf_edps_feedback "
        "(patient_id, measurement_year, tenant_id, accepted_raf, "
        " accepted_hcc_codes, rejected_hcc_codes, response_received_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )

    with raf_cursor() as cur:
        for row in rows:
            result.rows_total += 1
            try:
                cur.execute(
                    sql,
                    (
                        int(row["patient_id"]),
                        int(row["measurement_year"]),
                        str(tenant_id),
                        # accepted_raf comes through as float|None; MySQL
                        # DECIMAL(8,4) handles the rounding.
                        row.get("accepted_raf"),
                        json.dumps(row.get("accepted_hcc_codes") or []),
                        json.dumps(row.get("rejected_hcc_codes") or []),
                        row.get("response_received_at"),
                    ),
                )
                result.rows_upserted += 1
            except Exception as exc:  # noqa: BLE001 — row-level isolation
                result.rows_failed += 1
                result.errors.append(
                    f"patient_id={row.get('patient_id')!r} year={row.get('measurement_year')!r}: {exc}"
                )
                logger.warning(
                    "edps_ingest: row insert failed pid=%s year=%s err=%s",
                    row.get("patient_id"),
                    row.get("measurement_year"),
                    exc,
                )
    return result


def get_latest_feedback(
    patient_id: int,
    measurement_year: int,
    tenant_id: str,
) -> dict[str, Any] | None:
    """Return the newest EDPS feedback row for a pid+year+tenant, or None.

    "Newest" is decided first by ``response_received_at`` (the CMS-stamped
    time) and falls back to ``ingested_at`` when CMS did not supply a
    timestamp. JSON columns are decoded into Python lists so callers do
    not have to deal with the wire format.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, patient_id, measurement_year, tenant_id,
                   accepted_raf, accepted_hcc_codes, rejected_hcc_codes,
                   response_received_at, ingested_at
              FROM raf_edps_feedback
             WHERE patient_id = %s
               AND measurement_year = %s
               AND tenant_id = %s
             ORDER BY COALESCE(response_received_at, ingested_at) DESC,
                      id DESC
             LIMIT 1
            """,
            (int(patient_id), int(measurement_year), str(tenant_id)),
        )
        row = cur.fetchone()
    if not row:
        return None

    out = dict(row)
    # mysql-connector returns DECIMAL as Decimal; coerce to float for JSON.
    if out.get("accepted_raf") is not None:
        try:
            out["accepted_raf"] = float(out["accepted_raf"])
        except (TypeError, ValueError):
            out["accepted_raf"] = None

    for col in ("accepted_hcc_codes", "rejected_hcc_codes"):
        val = out.get(col)
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8")
        if isinstance(val, str):
            try:
                out[col] = json.loads(val)
            except json.JSONDecodeError:
                out[col] = []
        elif val is None:
            out[col] = []

    for col in ("response_received_at", "ingested_at"):
        if hasattr(out.get(col), "isoformat"):
            out[col] = out[col].isoformat()

    return out


def get_accepted_raf(
    patient_id: int,
    measurement_year: int,
    tenant_id: str,
) -> float | None:
    """Lightweight helper used by the RAF Central payload builder.

    Returns just the ``accepted_raf`` scalar from the newest feedback row,
    or ``None`` when CMS has not yet responded. Returning ``None`` (rather
    than raising) lets the panel render a "waiting for EDPS" tile without
    a try/except in the hot path.
    """
    with raf_cursor() as cur:
        try:
            cur.execute(
                """
                SELECT accepted_raf
                  FROM raf_edps_feedback
                 WHERE patient_id = %s
                   AND measurement_year = %s
                   AND tenant_id = %s
                 ORDER BY COALESCE(response_received_at, ingested_at) DESC,
                          id DESC
                 LIMIT 1
                """,
                (int(patient_id), int(measurement_year), str(tenant_id)),
            )
            row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001 — never block panel render
            logger.warning(
                "edps_ingest: accepted_raf lookup failed pid=%s year=%s: %s",
                patient_id,
                measurement_year,
                exc,
            )
            return None
    if not row:
        return None
    val = row.get("accepted_raf") if isinstance(row, dict) else row[0]
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
