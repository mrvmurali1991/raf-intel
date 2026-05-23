"""
Patient Matcher — Universal patient identity matching across EMR sources.

Matches external patient records to the internal OpenEMR patient registry
using multiple strategies with configurable confidence thresholds.

Strategies (in priority order):
  1. mrn              — exact MRN match (confidence 1.0)
  2. ssn_last4_dob    — last 4 SSN + exact DOB (confidence 0.95)
  3. name_dob_exact   — exact first + last + DOB (confidence 0.90)
  4. name_dob_fuzzy   — fuzzy name (Levenshtein ≤ 2) + exact DOB (confidence 0.75–0.85)

All match records are persisted to the RAF Intelligence database:
  emr_patient_matches      — confirmed/auto-linked matches
  emr_unmatched_patients   — records that could not be matched, pending review
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Match strategies executed in this priority order.
STRATEGIES = ["mrn", "ssn_last4_dob", "name_dob_exact", "name_dob_fuzzy", "manual"]

AUTO_MATCH_THRESHOLD = 0.95  # Auto-link without human review
REVIEW_THRESHOLD = 0.70  # Suggest for manual review
REJECT_THRESHOLD = 0.50  # Too low — do not suggest



# ---------------------------------------------------------------------------
# Domain object
# ---------------------------------------------------------------------------


class MatchResult:
    """Represents the outcome of a single patient matching attempt."""

    __slots__ = ("external_id", "internal_pid", "confidence", "strategy", "details")

    def __init__(
        self,
        external_id: str,
        internal_pid: int,
        confidence: float,
        strategy: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.external_id = external_id
        self.internal_pid = internal_pid
        self.confidence = confidence
        self.strategy = strategy
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "internal_pid": self.internal_pid,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Levenshtein distance (pure-Python, no dependency)
# ---------------------------------------------------------------------------


def _levenshtein(a: str, b: str) -> int:
    """Compute edit distance between two strings."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _normalize_dob(dob: Any) -> str | None:
    """Return DOB as 'YYYY-MM-DD' string regardless of input type."""
    if dob is None:
        return None
    if isinstance(dob, (date, datetime)):
        return dob.strftime("%Y-%m-%d")
    s = str(dob).strip()
    return s[:10] if len(s) >= 10 else s


# ---------------------------------------------------------------------------
# Individual matching strategies
# ---------------------------------------------------------------------------


def _strategy_mrn(record: dict[str, Any]) -> MatchResult | None:
    """Exact match on medical record number stored in pubpid or patient_data.pubpid."""
    mrn = str(record.get("mrn") or "").strip()
    if not mrn:
        return None

    sql = "SELECT pid FROM patient_data WHERE pubpid = %s LIMIT 1"
    with openemr_cursor() as cur:
        cur.execute(sql, (mrn,))
        row = cur.fetchone()

    if not row:
        return None

    external_id = str(record.get("id") or record.get("patient_id") or mrn)
    return MatchResult(
        external_id=external_id,
        internal_pid=int(row["pid"]),
        confidence=1.0,
        strategy="mrn",
        details={"matched_mrn": mrn},
    )


def _strategy_ssn_last4_dob(record: dict[str, Any]) -> MatchResult | None:
    """Match on last 4 digits of SSN + exact date of birth."""
    ssn4 = str(record.get("ssn_last4") or "").strip()
    dob = _normalize_dob(record.get("dob"))
    if not ssn4 or not dob:
        return None

    # OpenEMR stores SSN in ss column (full SSN); we compare the last 4.
    sql = """
        SELECT pid
        FROM patient_data
        WHERE RIGHT(REPLACE(ss, '-', ''), 4) = %s
          AND DATE(DOB) = %s
        LIMIT 2
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (ssn4, dob))
        rows = cur.fetchall()

    if len(rows) != 1:
        # 0 rows = no match; >1 rows = ambiguous
        return None

    external_id = str(record.get("id") or record.get("patient_id") or ssn4)
    return MatchResult(
        external_id=external_id,
        internal_pid=int(rows[0]["pid"]),
        confidence=0.95,
        strategy="ssn_last4_dob",
        details={"ssn_last4": ssn4, "dob": dob},
    )


def _strategy_name_dob_exact(record: dict[str, Any]) -> MatchResult | None:
    """Exact first name + last name + DOB match (case-insensitive)."""
    first = _normalize_name(record.get("first_name"))
    last = _normalize_name(record.get("last_name"))
    dob = _normalize_dob(record.get("dob"))
    if not first or not last or not dob:
        return None

    sql = """
        SELECT pid
        FROM patient_data
        WHERE LOWER(fname) = %s
          AND LOWER(lname) = %s
          AND DATE(DOB) = %s
        LIMIT 2
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (first, last, dob))
        rows = cur.fetchall()

    if len(rows) != 1:
        return None

    external_id = str(
        record.get("id") or record.get("patient_id") or f"{first}_{last}_{dob}"
    )
    return MatchResult(
        external_id=external_id,
        internal_pid=int(rows[0]["pid"]),
        confidence=0.90,
        strategy="name_dob_exact",
        details={"first_name": first, "last_name": last, "dob": dob},
    )


def _strategy_name_dob_fuzzy(record: dict[str, Any]) -> MatchResult | None:
    """
    Fuzzy name match (Levenshtein distance ≤ 2 on both first and last name)
    combined with an exact DOB.

    Confidence is 0.85 when both distances are 0 (shouldn't happen — that
    would be caught by name_dob_exact), 0.80 when one name has distance 1,
    and 0.75 when distances are higher but still within threshold.
    """
    first = _normalize_name(record.get("first_name"))
    last = _normalize_name(record.get("last_name"))
    dob = _normalize_dob(record.get("dob"))
    if not first or not last or not dob:
        return None

    # Fetch all patients with exact DOB and similar first letter to reduce
    # the candidate pool before Python-side fuzzy scoring.
    sql = """
        SELECT pid, LOWER(fname) AS fname, LOWER(lname) AS lname
        FROM patient_data
        WHERE DATE(DOB) = %s
          AND (LOWER(fname) LIKE %s OR LOWER(lname) LIKE %s)
    """
    first_prefix = first[0] + "%"
    last_prefix = last[0] + "%"
    with openemr_cursor() as cur:
        cur.execute(sql, (dob, first_prefix, last_prefix))
        candidates = cur.fetchall()

    best_pid: int | None = None
    best_d_first = 99
    best_d_last = 99

    for row in candidates:
        d_first = _levenshtein(first, row["fname"])
        d_last = _levenshtein(last, row["lname"])
        if d_first > 2 or d_last > 2:
            continue
        total = d_first + d_last
        best_total = best_d_first + best_d_last
        if total < best_total:
            best_pid = int(row["pid"])
            best_d_first = d_first
            best_d_last = d_last

    if best_pid is None:
        return None

    # Compute confidence based on combined edit distance.
    total_dist = best_d_first + best_d_last
    if total_dist == 0:
        confidence = 0.85
    elif total_dist == 1:
        confidence = 0.82
    elif total_dist == 2:
        confidence = 0.80
    else:
        confidence = 0.75

    external_id = str(
        record.get("id") or record.get("patient_id") or f"{first}_{last}_{dob}"
    )
    return MatchResult(
        external_id=external_id,
        internal_pid=best_pid,
        confidence=confidence,
        strategy="name_dob_fuzzy",
        details={
            "first_name": first,
            "last_name": last,
            "dob": dob,
            "edit_distance_first": best_d_first,
            "edit_distance_last": best_d_last,
        },
    )


_STRATEGY_FNS = {
    "mrn": _strategy_mrn,
    "ssn_last4_dob": _strategy_ssn_last4_dob,
    "name_dob_exact": _strategy_name_dob_exact,
    "name_dob_fuzzy": _strategy_name_dob_fuzzy,
}


def _try_strategy(
    strategy: str,
    record: dict[str, Any],
    emr_connection_id: int,  # noqa: ARG001 — reserved for future per-connection logic
) -> MatchResult | None:
    fn = _STRATEGY_FNS.get(strategy)
    if fn is None:
        return None
    try:
        return fn(record)
    except Exception as exc:
        logger.warning("patient_matcher strategy '%s' raised: %s", strategy, exc)
        return None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _store_match(
    result: MatchResult,
    connection_id: int,
    auto_link: bool,
    matched_by: str | None = None,
) -> None:
    """Upsert a confirmed match into emr_patient_matches."""
    sql = """
        INSERT INTO emr_patient_matches
            (emr_connection_id, external_patient_id, internal_pid,
             match_strategy, confidence_score, auto_linked, matched_by,
             matched_at, external_data)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
        ON DUPLICATE KEY UPDATE
            internal_pid      = VALUES(internal_pid),
            match_strategy    = VALUES(match_strategy),
            confidence_score  = VALUES(confidence_score),
            auto_linked       = VALUES(auto_linked),
            matched_by        = VALUES(matched_by),
            matched_at        = NOW()
    """
    with raf_cursor() as cur:
        cur.execute(
            sql,
            (
                connection_id,
                result.external_id,
                result.internal_pid,
                result.strategy,
                result.confidence,
                1 if auto_link else 0,
                matched_by,
                json.dumps(result.details),
            ),
        )
    logger.debug(
        "Stored match: connection=%s external=%s -> pid=%s (strategy=%s, confidence=%.3f)",
        connection_id,
        result.external_id,
        result.internal_pid,
        result.strategy,
        result.confidence,
    )


def _store_unmatched(
    record: dict[str, Any],
    connection_id: int,
    suggested_pid: int | None = None,
    suggested_confidence: float | None = None,
) -> None:
    """Upsert an unmatched record into emr_unmatched_patients."""

    external_id = str(
        record.get("id") or record.get("patient_id") or record.get("mrn") or ""
    )
    first = str(record.get("first_name") or "")[:150]
    last = str(record.get("last_name") or "")[:150]
    dob = _normalize_dob(record.get("dob"))

    sql = """
        INSERT INTO emr_unmatched_patients
            (emr_connection_id, external_patient_id, external_data,
             first_name, last_name, dob,
             suggested_pid, suggested_confidence, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        ON DUPLICATE KEY UPDATE
            external_data        = VALUES(external_data),
            first_name           = VALUES(first_name),
            last_name            = VALUES(last_name),
            dob                  = VALUES(dob),
            suggested_pid        = VALUES(suggested_pid),
            suggested_confidence = VALUES(suggested_confidence),
            status               = IF(status = 'pending', 'pending', status)
    """
    with raf_cursor() as cur:
        cur.execute(
            sql,
            (
                connection_id,
                external_id,
                json.dumps(record),
                first or None,
                last or None,
                dob,
                suggested_pid,
                suggested_confidence,
            ),
        )
    logger.debug(
        "Stored unmatched: connection=%s external=%s",
        connection_id,
        external_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_patient(
    external_record: dict[str, Any],
    emr_connection_id: int,
    auto_link: bool = True,
) -> MatchResult | None:
    """
    Match an external patient record to an internal OpenEMR patient.

    Tries each strategy in STRATEGIES order.  The first result that meets
    REVIEW_THRESHOLD is stored and returned.  If no strategy reaches
    REVIEW_THRESHOLD, the record is stored as unmatched for human review.

    Args:
        external_record: Dict containing any subset of:
            id / patient_id  — external system's identifier
            mrn              — Medical Record Number
            first_name, last_name
            dob              — date of birth (YYYY-MM-DD, date, or datetime)
            ssn_last4        — last 4 digits of SSN
            sex              — M / F
            phone, email, address  (reserved for future strategies)
        emr_connection_id: ID of the emr_connections record.
        auto_link: When True and confidence >= AUTO_MATCH_THRESHOLD, the
            match is recorded as auto-linked without requiring human review.

    Returns:
        MatchResult when a match at or above REVIEW_THRESHOLD is found,
        None when no suitable match exists (record stored as unmatched).
    """


    best_below_threshold: MatchResult | None = None

    for strategy in STRATEGIES:
        if strategy == "manual":
            continue

        result = _try_strategy(strategy, external_record, emr_connection_id)
        if result is None:
            continue

        if result.confidence >= REVIEW_THRESHOLD:
            effective_auto_link = (
                auto_link and result.confidence >= AUTO_MATCH_THRESHOLD
            )
            _store_match(result, emr_connection_id, effective_auto_link)
            return result

        # Track the best sub-threshold result as a suggestion.
        if result.confidence >= REJECT_THRESHOLD and (
            best_below_threshold is None
            or result.confidence > best_below_threshold.confidence
        ):
            best_below_threshold = result

    # No strategy reached REVIEW_THRESHOLD.
    _store_unmatched(
        external_record,
        emr_connection_id,
        suggested_pid=best_below_threshold.internal_pid
        if best_below_threshold
        else None,
        suggested_confidence=best_below_threshold.confidence
        if best_below_threshold
        else None,
    )
    return None


def get_unmatched_patients(
    connection_id: int,
    limit: int = 50,
    offset: int = 0,
    status: str = "pending",
) -> dict[str, Any]:
    """
    Return unmatched patient records for manual review.

    Args:
        connection_id: emr_connections.id to filter by.
        limit: Maximum rows to return (default 50, max 200).
        offset: Pagination offset.
        status: Filter by status ('pending', 'matched', 'rejected', or 'all').

    Returns:
        Dict with keys: total, limit, offset, items
    """

    limit = min(limit, 200)

    status_clause = "" if status == "all" else "AND status = %s"
    params_count: tuple = (connection_id,)
    params_rows: tuple = (connection_id,)

    if status != "all":
        params_count = (connection_id, status)
        params_rows = (connection_id, status, limit, offset)
    else:
        params_rows = (connection_id, limit, offset)

    count_sql = f"""
        SELECT COUNT(*) AS cnt
        FROM emr_unmatched_patients
        WHERE emr_connection_id = %s {status_clause}
    """
    rows_sql = f"""
        SELECT id, emr_connection_id, external_patient_id,
               external_data, first_name, last_name, dob,
               suggested_pid, suggested_confidence,
               status, reviewed_by, reviewed_at, created_at
        FROM emr_unmatched_patients
        WHERE emr_connection_id = %s {status_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """

    with raf_cursor() as cur:
        cur.execute(count_sql, params_count)
        total = (cur.fetchone() or {}).get("cnt", 0)
        cur.execute(rows_sql, params_rows)
        rows = cur.fetchall()

    items = []
    for row in rows:
        item = dict(row)
        # Deserialize JSON blob if it came back as a string.
        ed = item.get("external_data")
        if isinstance(ed, str):
            try:
                item["external_data"] = json.loads(ed)
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)
        # Normalize date/datetime to strings for JSON serialization.
        for field in ("dob", "reviewed_at", "created_at"):
            v = item.get(field)
            if isinstance(v, (date, datetime)):
                item[field] = v.isoformat()
        items.append(item)

    return {"total": total, "limit": limit, "offset": offset, "items": items}


def manual_match(
    unmatched_id: int,
    internal_pid: int,
    matched_by: str,
) -> dict[str, Any]:
    """
    Manually link an unmatched patient to an internal OpenEMR patient.

    Updates the emr_unmatched_patients row to status='matched' and inserts
    a confirmed row into emr_patient_matches.

    Args:
        unmatched_id: emr_unmatched_patients.id
        internal_pid: Target OpenEMR patient_data.pid
        matched_by: Username of the reviewer performing the linkage.

    Returns:
        Dict describing the newly created match.

    Raises:
        ValueError: When unmatched_id is not found or is not in 'pending' status.
    """


    # Fetch the unmatched record.
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM emr_unmatched_patients WHERE id = %s",
            (unmatched_id,),
        )
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Unmatched patient record {unmatched_id} not found")
    if row["status"] != "pending":
        raise ValueError(
            f"Record {unmatched_id} has status '{row['status']}' — only 'pending' records can be manually matched"
        )

    # Verify the target pid exists in OpenEMR.
    with openemr_cursor() as cur:
        cur.execute(
            "SELECT pid FROM patient_data WHERE pid = %s LIMIT 1", (internal_pid,)
        )
        pid_row = cur.fetchone()
    if not pid_row:
        raise ValueError(f"OpenEMR patient pid={internal_pid} not found")

    connection_id = row["emr_connection_id"]
    external_id = row["external_patient_id"]

    # Build a synthetic MatchResult for storage.
    result = MatchResult(
        external_id=external_id,
        internal_pid=internal_pid,
        confidence=1.0,
        strategy="manual",
        details={"reviewed_by": matched_by, "unmatched_record_id": unmatched_id},
    )
    _store_match(result, connection_id, auto_link=False, matched_by=matched_by)

    # Mark the unmatched record as resolved.
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE emr_unmatched_patients
               SET status = 'matched', reviewed_by = %s, reviewed_at = NOW()
             WHERE id = %s
            """,
            (matched_by, unmatched_id),
        )

    logger.info(
        "Manual match: connection=%s external=%s -> pid=%s by %s",
        connection_id,
        external_id,
        internal_pid,
        matched_by,
    )
    return result.to_dict()


def get_match_stats(connection_id: int) -> dict[str, Any]:
    """
    Return match statistics for a given EMR connection.

    Returns:
        {
          total_matched:   int — rows in emr_patient_matches
          auto_matched:    int — rows where auto_linked = 1
          manual_matched:  int — rows where auto_linked = 0 (strategy = manual)
          unmatched:       int — pending rows in emr_unmatched_patients
          rejected:        int — rejected rows in emr_unmatched_patients
          match_rate:      float — total_matched / (total_matched + unmatched) or 0.0
        }
    """


    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                             AS total_matched,
                SUM(auto_linked = 1)                 AS auto_matched,
                SUM(auto_linked = 0)                 AS manual_matched
            FROM emr_patient_matches
            WHERE emr_connection_id = %s
            """,
            (connection_id,),
        )
        match_row = cur.fetchone() or {}

        cur.execute(
            """
            SELECT
                SUM(status = 'pending')  AS unmatched,
                SUM(status = 'rejected') AS rejected
            FROM emr_unmatched_patients
            WHERE emr_connection_id = %s
            """,
            (connection_id,),
        )
        unmatch_row = cur.fetchone() or {}

    total_matched = int(match_row.get("total_matched") or 0)
    auto_matched = int(match_row.get("auto_matched") or 0)
    manual_matched = int(match_row.get("manual_matched") or 0)
    unmatched = int(unmatch_row.get("unmatched") or 0)
    rejected = int(unmatch_row.get("rejected") or 0)

    total = total_matched + unmatched
    match_rate = round(total_matched / total, 4) if total > 0 else 0.0

    return {
        "connection_id": connection_id,
        "total_matched": total_matched,
        "auto_matched": auto_matched,
        "manual_matched": manual_matched,
        "unmatched": unmatched,
        "rejected": rejected,
        "match_rate": match_rate,
    }
