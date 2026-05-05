"""
Dispute & Appeal Service — workflow management for denied HCC codes.

When CMS, a payer, or an internal audit denies an HCC submission, this service
tracks the denial, gathers MEAT evidence, helps draft an appeal letter, records
the outcome, and supports win-rate / dollars-recovered reporting.

Tables (see database/migrations/add_disputes_appeals.sql):
  * hcc_disputes         — one row per denial event
  * hcc_appeals          — one row per appeal round per dispute
  * dispute_evidence     — evidence cited in the appeal (auto-pulled from MEAT)

Public API
----------
    create_dispute(payload)                   -> dict     new dispute
    list_disputes(filters)                    -> list     filtered disputes
    get_dispute(dispute_id)                   -> dict     full dispute (with evidence + appeals)
    assign_dispute(dispute_id, user_id)       -> dict     update assignment
    gather_evidence(dispute_id)               -> list     MEAT-derived evidence rows
    compose_appeal_draft(dispute_id, round)   -> dict     LLM-generated letter draft
    submit_appeal(dispute_id, appeal_data)    -> dict     persist a submitted appeal
    record_outcome(appeal_id, outcome, $$$)   -> dict     close out an appeal
    get_metrics(tenant_id=None)               -> dict     win-rate / $ / cycle-time

NOTE on LLM safety:
    compose_appeal_draft() instructs Gemini to ONLY cite the evidence we provide
    and to insert "[NO EVIDENCE]" placeholders rather than fabricate facts.
    The pre-formatted evidence block is included verbatim in the prompt so the
    model's claims can be cross-checked against it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.meat_evidence_service import get_meat_for_hcc

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()


def _utcnow_year() -> int:
    return datetime.now(timezone.utc).year


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_DISPUTED_BY = {"cms", "payer", "internal_audit"}
VALID_STATUSES = {"open", "in_review", "appealing", "won", "lost", "abandoned"}
VALID_APPEAL_OUTCOMES = {"pending", "overturned", "upheld", "partial", "withdrawn"}

# Map appeal outcome → dispute status transition
OUTCOME_TO_DISPUTE_STATUS = {
    "overturned": "won",
    "partial":    "won",      # business decision: partial overturn = win
    "upheld":     "lost",
    "withdrawn":  "abandoned",
    "pending":    "appealing",
}


# ---------------------------------------------------------------------------
# 1. create_dispute
# ---------------------------------------------------------------------------

def create_dispute(payload: dict[str, Any]) -> dict[str, Any]:
    """Record a new denial / dispute event.

    Required keys in payload:
      patient_id (int), hcc_code (int), icd10 (str), disputed_by (enum),
      denial_received_at (ISO datetime str), financial_impact (float).
    Optional keys:
      tenant_id, measurement_year, original_submission_id, payer_name,
      denial_reason_code, denial_reason_text, assigned_to, notes, created_by.
    """
    required = ("patient_id", "hcc_code", "icd10", "disputed_by", "denial_received_at")
    missing = [k for k in required if payload.get(k) in (None, "")]
    if missing:
        raise ValueError(f"create_dispute: missing required fields: {missing}")

    if payload["disputed_by"] not in VALID_DISPUTED_BY:
        raise ValueError(
            f"create_dispute: disputed_by must be one of {VALID_DISPUTED_BY}, got {payload['disputed_by']!r}"
        )

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO hcc_disputes (
                tenant_id, patient_id, measurement_year, hcc_code, icd10,
                original_submission_id, disputed_by, payer_name,
                denial_reason_code, denial_reason_text, denial_received_at,
                financial_impact, status, assigned_to, notes, created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                payload.get("tenant_id"),
                int(payload["patient_id"]),
                int(payload.get("measurement_year") or _utcnow_year()),
                int(payload["hcc_code"]),
                str(payload["icd10"]).strip(),
                payload.get("original_submission_id"),
                payload["disputed_by"],
                payload.get("payer_name"),
                payload.get("denial_reason_code"),
                payload.get("denial_reason_text"),
                payload["denial_received_at"],
                float(payload.get("financial_impact") or 0.0),
                payload.get("status", "open"),
                payload.get("assigned_to"),
                payload.get("notes"),
                payload.get("created_by"),
            ),
        )
        dispute_id = int(cur.lastrowid)  # type: ignore[arg-type]

    logger.info(
        "create_dispute: id=%d patient_id=%s hcc=%s disputed_by=%s impact=$%.2f",
        dispute_id, payload["patient_id"], payload["hcc_code"],
        payload["disputed_by"], float(payload.get("financial_impact") or 0.0),
    )
    return get_dispute(dispute_id)


# ---------------------------------------------------------------------------
# 2. list_disputes
# ---------------------------------------------------------------------------

def list_disputes(
    status: str | None = None,
    assigned_to: str | None = None,
    tenant_id: int | None = None,
    patient_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return disputes filtered by status / assignee / tenant / patient."""
    where: list[str] = []
    args: list[Any] = []

    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"list_disputes: invalid status {status!r}")
        where.append("status = %s")
        args.append(status)
    if assigned_to:
        where.append("assigned_to = %s")
        args.append(assigned_to)
    if tenant_id is not None:
        where.append("tenant_id = %s")
        args.append(int(tenant_id))
    if patient_id is not None:
        where.append("patient_id = %s")
        args.append(int(patient_id))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT *
        FROM hcc_disputes
        {where_sql}
        ORDER BY denial_received_at DESC, id DESC
        LIMIT %s
    """
    args.append(int(limit))

    with raf_cursor() as cur:
        cur.execute(sql, args)
        rows = [_row_to_dict(r) for r in cur.fetchall()]

    return rows


# ---------------------------------------------------------------------------
# 3. get_dispute
# ---------------------------------------------------------------------------

def get_dispute(dispute_id: int) -> dict[str, Any]:
    """Return a single dispute joined with its evidence + appeals."""
    with raf_cursor() as cur:
        cur.execute("SELECT * FROM hcc_disputes WHERE id = %s", (int(dispute_id),))
        row = cur.fetchone()
        if not row:
            raise LookupError(f"dispute {dispute_id} not found")
        dispute = _row_to_dict(row)

        cur.execute(
            "SELECT * FROM dispute_evidence WHERE dispute_id = %s ORDER BY uploaded_at",
            (dispute_id,),
        )
        dispute["evidence"] = [_row_to_dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT * FROM hcc_appeals WHERE dispute_id = %s ORDER BY appeal_round",
            (dispute_id,),
        )
        appeals = []
        for r in cur.fetchall():
            a = _row_to_dict(r)
            if a.get("evidence_attached_json") and isinstance(a["evidence_attached_json"], str):
                try:
                    a["evidence_attached_json"] = json.loads(a["evidence_attached_json"])
                except (TypeError, json.JSONDecodeError):
                    pass
            appeals.append(a)
        dispute["appeals"] = appeals

    return dispute


# ---------------------------------------------------------------------------
# 4. assign_dispute
# ---------------------------------------------------------------------------

def assign_dispute(dispute_id: int, user_id: str) -> dict[str, Any]:
    """Assign (or reassign) a dispute to a coder/auditor."""
    if not user_id:
        raise ValueError("assign_dispute: user_id is required")

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE hcc_disputes
            SET assigned_to = %s,
                status = CASE WHEN status = 'open' THEN 'in_review' ELSE status END
            WHERE id = %s
            """,
            (user_id, int(dispute_id)),
        )
        if cur.rowcount == 0:
            # Either dispute doesn't exist or no change – verify which
            cur.execute("SELECT id FROM hcc_disputes WHERE id = %s", (int(dispute_id),))
            if cur.fetchone() is None:
                raise LookupError(f"dispute {dispute_id} not found")

    logger.info("assign_dispute: id=%d → %s", dispute_id, user_id)
    return get_dispute(dispute_id)


# ---------------------------------------------------------------------------
# 5. gather_evidence
# ---------------------------------------------------------------------------

def gather_evidence(dispute_id: int) -> list[dict[str, Any]]:
    """Auto-pull MEAT evidence from raf_meat_evidence for the disputed HCC.

    Reuses meat_evidence_service.get_meat_for_hcc() so we never duplicate the
    extraction logic.  Evidence rows that are already attached to the dispute
    (matched via source_table + source_row_id) are skipped to keep the call
    idempotent.
    """
    dispute = get_dispute(dispute_id)
    patient_id = int(dispute["patient_id"])
    hcc_code = int(dispute["hcc_code"])
    year = int(dispute.get("measurement_year") or _utcnow_year())

    # Find raf_patient_hcc.id for this (patient, hcc, year)
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM raf_patient_hcc
            WHERE patient_id = %s AND hcc_code = %s AND measurement_year = %s
            LIMIT 1
            """,
            (patient_id, hcc_code, year),
        )
        phcc = cur.fetchone()

    if not phcc:
        logger.warning(
            "gather_evidence: no raf_patient_hcc row for patient_id=%d hcc=%d year=%d",
            patient_id, hcc_code, year,
        )
        return dispute.get("evidence", [])

    patient_hcc_id = int(phcc["id"])
    meat_rows = get_meat_for_hcc(patient_hcc_id)

    # Existing source_row_ids already attached → skip dupes
    existing_keys = {
        (e.get("source_table"), e.get("source_row_id"))
        for e in dispute.get("evidence", [])
    }

    inserted = 0
    with raf_cursor() as cur:
        for ev in meat_rows:
            key = ("raf_meat_evidence", int(ev["id"]))
            if key in existing_keys:
                continue

            components = "".join([
                "M" if ev.get("meat_m_present") else "",
                "E" if ev.get("meat_e_present") else "",
                "A" if ev.get("meat_a_present") else "",
                "T" if ev.get("meat_t_present") else "",
            ]) or "—"

            snippet_parts: list[str] = []
            for label, key_ in [("M", "meat_m"), ("E", "meat_e"),
                                ("A", "meat_a"), ("T", "meat_t")]:
                val = ev.get(key_)
                if val:
                    snippet_parts.append(f"[{label}] {val.strip()}")
            if not snippet_parts and ev.get("raw_note_excerpt"):
                snippet_parts.append(ev["raw_note_excerpt"].strip())
            snippet = "\n".join(snippet_parts)[:5000]  # cap size

            cur.execute(
                """
                INSERT INTO dispute_evidence (
                    dispute_id, evidence_type, source_doc_id, source_table,
                    source_row_id, encounter_date, snippet_text, meat_components,
                    uploaded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(dispute_id),
                    "chart_excerpt",
                    str(ev.get("encounter_id") or ""),
                    "raf_meat_evidence",
                    int(ev["id"]),
                    ev.get("encounter_date"),
                    snippet,
                    components,
                    "system:gather_evidence",
                ),
            )
            inserted += 1

    logger.info(
        "gather_evidence: dispute_id=%d patient_hcc_id=%d — added %d/%d MEAT rows",
        dispute_id, patient_hcc_id, inserted, len(meat_rows),
    )

    # Return refreshed evidence list
    return get_dispute(dispute_id)["evidence"]


# ---------------------------------------------------------------------------
# 6. compose_appeal_draft
# ---------------------------------------------------------------------------

# Importing the LLM client at call-time keeps unit tests fast and avoids
# requiring GOOGLE_API_KEY for module import.

def _build_appeal_prompt(dispute: dict[str, Any], evidence_block: str) -> str:
    """Construct the LLM prompt; isolated for easier unit testing."""
    return f"""You are an expert clinical documentation specialist drafting a
formal appeal letter to overturn an HCC denial.

CRITICAL INSTRUCTIONS — follow exactly:
  1. ONLY cite facts that appear verbatim in the EVIDENCE BLOCK below.
  2. Where the evidence does NOT support a clinical fact, write
     "[NO EVIDENCE]" instead of inventing one.
  3. Reference each evidence item by its bracketed [E#] tag in the body of
     the letter.
  4. Do NOT fabricate dates, providers, lab values, or test results.
  5. Output a complete business letter — header, body, signature block.

DISPUTE FACTS
  Patient ID:        {dispute["patient_id"]}
  HCC code:          {dispute["hcc_code"]}
  ICD-10:            {dispute["icd10"]}
  Disputed by:       {dispute["disputed_by"]}{f' ({dispute["payer_name"]})' if dispute.get("payer_name") else ''}
  Denial reason:     {dispute.get("denial_reason_text") or dispute.get("denial_reason_code") or "[NO EVIDENCE]"}
  Denial received:   {dispute["denial_received_at"]}
  Financial impact:  ${float(dispute.get("financial_impact") or 0):,.2f}

EVIDENCE BLOCK (cite ONLY from this block):
{evidence_block}

Draft the appeal letter now.
"""


def compose_appeal_draft(
    dispute_id: int,
    appeal_round: int = 1,
    llm_caller: Any = None,  # injectable for tests
) -> dict[str, Any]:
    """Generate an appeal-letter draft using Gemini, citing collected evidence.

    Parameters
    ----------
    dispute_id   : int
    appeal_round : int        Which appeal round this draft is for (1, 2, 3).
    llm_caller   : callable   Optional override; must accept (prompt: str, model: str)
                              and return a string.  Defaults to gemini_service._call_gemini.

    Returns
    -------
    dict with keys: dispute_id, appeal_round, draft_text, evidence_cited,
    model_used, generated_at.
    """
    dispute = get_dispute(dispute_id)
    evidence: list[dict[str, Any]] = dispute.get("evidence") or []

    if not evidence:
        raise ValueError(
            f"compose_appeal_draft: dispute {dispute_id} has no evidence; "
            "call gather_evidence() first."
        )

    # Build a numbered evidence block; the LLM is told to cite by [E#].
    evidence_lines: list[str] = []
    evidence_cited: list[dict[str, Any]] = []
    for idx, ev in enumerate(evidence, start=1):
        tag = f"[E{idx}]"
        snippet = (ev.get("snippet_text") or "").strip().replace("\n", " ")
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "…"
        date_str = ev.get("encounter_date") or "unknown date"
        evidence_lines.append(
            f"{tag} type={ev.get('evidence_type')} date={date_str} "
            f"meat={ev.get('meat_components') or '—'}\n     {snippet}"
        )
        evidence_cited.append({
            "tag": tag,
            "evidence_id": ev["id"],
            "evidence_type": ev.get("evidence_type"),
            "encounter_date": str(ev.get("encounter_date") or ""),
        })

    evidence_block = "\n".join(evidence_lines)
    prompt = _build_appeal_prompt(dispute, evidence_block)

    # Resolve the LLM caller.  Default to the project's existing wrapper.
    model_name = "gemini-2.5-pro"
    if llm_caller is None:
        try:
            from app.services._legacy.gemini_service import _call_gemini  # type: ignore
            llm_caller = _call_gemini
        except Exception as exc:  # pragma: no cover — env without LLM
            logger.warning("compose_appeal_draft: LLM unavailable (%s); returning stub", exc)
            draft_text = (
                "[STUB DRAFT — Gemini unavailable in this environment]\n\n"
                + prompt
            )
            return {
                "dispute_id": dispute_id,
                "appeal_round": appeal_round,
                "draft_text": draft_text,
                "evidence_cited": evidence_cited,
                "model_used": "stub",
                "generated_at": _utcnow_iso(),
            }

    try:
        draft_text = llm_caller(prompt, model_name)  # type: ignore[misc]
    except TypeError:
        # Allow simpler test doubles: llm_caller(prompt)
        draft_text = llm_caller(prompt)  # type: ignore[misc]

    return {
        "dispute_id": dispute_id,
        "appeal_round": int(appeal_round),
        "draft_text": draft_text,
        "evidence_cited": evidence_cited,
        "model_used": model_name,
        "generated_at": _utcnow_iso(),
    }


# ---------------------------------------------------------------------------
# 7. submit_appeal
# ---------------------------------------------------------------------------

def submit_appeal(dispute_id: int, appeal_data: dict[str, Any]) -> dict[str, Any]:
    """Persist a submitted appeal and move dispute → 'appealing'.

    Required appeal_data keys:
      appeal_round (int), appeal_letter_text (str)
    Optional:
      appeal_letter_model, evidence_attached_json (list/dict),
      submitted_by, submitted_at (defaults to now)
    """
    if "appeal_letter_text" not in appeal_data:
        raise ValueError("submit_appeal: appeal_letter_text is required")

    appeal_round = int(appeal_data.get("appeal_round", 1))
    submitted_at = appeal_data.get("submitted_at") or _utcnow_iso()
    evidence_json = appeal_data.get("evidence_attached_json")
    if evidence_json is not None and not isinstance(evidence_json, str):
        evidence_json = json.dumps(evidence_json, default=str)

    with raf_cursor() as cur:
        # Verify dispute exists
        cur.execute("SELECT id FROM hcc_disputes WHERE id = %s", (int(dispute_id),))
        if cur.fetchone() is None:
            raise LookupError(f"dispute {dispute_id} not found")

        cur.execute(
            """
            INSERT INTO hcc_appeals (
                dispute_id, appeal_round, appeal_letter_text, appeal_letter_model,
                evidence_attached_json, submitted_by, submitted_at, outcome
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
            ON DUPLICATE KEY UPDATE
                appeal_letter_text = VALUES(appeal_letter_text),
                appeal_letter_model = VALUES(appeal_letter_model),
                evidence_attached_json = VALUES(evidence_attached_json),
                submitted_by = VALUES(submitted_by),
                submitted_at = VALUES(submitted_at),
                outcome = 'pending'
            """,
            (
                int(dispute_id),
                appeal_round,
                appeal_data["appeal_letter_text"],
                appeal_data.get("appeal_letter_model"),
                evidence_json,
                appeal_data.get("submitted_by"),
                submitted_at,
            ),
        )
        appeal_id = int(cur.lastrowid) if cur.lastrowid else 0
        if not appeal_id:
            cur.execute(
                "SELECT id FROM hcc_appeals WHERE dispute_id = %s AND appeal_round = %s",
                (int(dispute_id), appeal_round),
            )
            row = cur.fetchone()
            appeal_id = int(row["id"]) if row else 0

        cur.execute(
            "UPDATE hcc_disputes SET status = 'appealing' WHERE id = %s",
            (int(dispute_id),),
        )

    logger.info(
        "submit_appeal: dispute_id=%d round=%d appeal_id=%d",
        dispute_id, appeal_round, appeal_id,
    )

    with raf_cursor() as cur:
        cur.execute("SELECT * FROM hcc_appeals WHERE id = %s", (appeal_id,))
        return _row_to_dict(cur.fetchone())


# ---------------------------------------------------------------------------
# 8. record_outcome
# ---------------------------------------------------------------------------

def record_outcome(
    appeal_id: int,
    outcome: str,
    recovered_amount: float = 0.0,
    response_received_at: str | None = None,
    outcome_notes: str | None = None,
) -> dict[str, Any]:
    """Record the result of an appeal and propagate status to the dispute."""
    if outcome not in VALID_APPEAL_OUTCOMES:
        raise ValueError(
            f"record_outcome: outcome must be one of {VALID_APPEAL_OUTCOMES}, got {outcome!r}"
        )

    response_received_at = response_received_at or _utcnow_iso()

    with raf_cursor() as cur:
        cur.execute("SELECT * FROM hcc_appeals WHERE id = %s", (int(appeal_id),))
        appeal_row = cur.fetchone()
        if appeal_row is None:
            raise LookupError(f"appeal {appeal_id} not found")
        dispute_id = int(appeal_row["dispute_id"])

        cur.execute(
            """
            UPDATE hcc_appeals
            SET outcome = %s,
                response_received_at = %s,
                monetary_recovered = %s,
                outcome_notes = %s
            WHERE id = %s
            """,
            (outcome, response_received_at, float(recovered_amount or 0.0),
             outcome_notes, int(appeal_id)),
        )

        # Decide dispute status.  Pending → no change.
        new_dispute_status = OUTCOME_TO_DISPUTE_STATUS.get(outcome)
        if new_dispute_status and new_dispute_status != "appealing":
            cur.execute(
                """
                UPDATE hcc_disputes
                SET status = %s, closed_at = COALESCE(closed_at, %s)
                WHERE id = %s
                """,
                (new_dispute_status, response_received_at, dispute_id),
            )

    logger.info(
        "record_outcome: appeal_id=%d outcome=%s recovered=$%.2f → dispute %d",
        appeal_id, outcome, float(recovered_amount or 0.0), dispute_id,
    )

    with raf_cursor() as cur:
        cur.execute("SELECT * FROM hcc_appeals WHERE id = %s", (int(appeal_id),))
        return _row_to_dict(cur.fetchone())


# ---------------------------------------------------------------------------
# 9. get_metrics
# ---------------------------------------------------------------------------

def get_metrics(tenant_id: int | None = None) -> dict[str, Any]:
    """Aggregate dispute / appeal metrics.

    Returned shape:
        {
          "tenant_id": int | None,
          "totals": { open, in_review, appealing, won, lost, abandoned, total },
          "win_rate": float,                # won / (won + lost)
          "money_at_risk": float,           # sum of financial_impact on open/in_review/appealing
          "money_recovered": float,         # sum of monetary_recovered across all appeals
          "avg_cycle_time_days": float,     # avg(closed_at - denial_received_at) on closed disputes
        }
    Win-rate intentionally excludes 'abandoned' per spec.
    """
    where_sql = ""
    args: list[Any] = []
    if tenant_id is not None:
        where_sql = "WHERE tenant_id = %s"
        args.append(int(tenant_id))

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT status, COUNT(*) AS cnt, COALESCE(SUM(financial_impact), 0) AS impact
            FROM hcc_disputes
            {where_sql}
            GROUP BY status
            """,
            args,
        )
        totals = {s: 0 for s in VALID_STATUSES}
        money_at_risk = 0.0
        for r in cur.fetchall():
            totals[r["status"]] = int(r["cnt"])
            if r["status"] in ("open", "in_review", "appealing"):
                money_at_risk += float(r["impact"] or 0.0)
        totals["total"] = sum(totals[s] for s in VALID_STATUSES)

        won = totals.get("won", 0)
        lost = totals.get("lost", 0)
        win_rate = (won / (won + lost)) if (won + lost) > 0 else 0.0

        # $ recovered = sum of monetary_recovered across all appeals (joined for tenant filter)
        cur.execute(
            f"""
            SELECT COALESCE(SUM(a.monetary_recovered), 0) AS recovered
            FROM hcc_appeals a
            JOIN hcc_disputes d ON d.id = a.dispute_id
            {('WHERE d.tenant_id = %s' if tenant_id is not None else '')}
            """,
            ([int(tenant_id)] if tenant_id is not None else []),
        )
        recovered_row = cur.fetchone()
        money_recovered = float(recovered_row["recovered"] or 0.0)

        # Avg cycle time on closed disputes
        cur.execute(
            f"""
            SELECT AVG(TIMESTAMPDIFF(SECOND, denial_received_at, closed_at)) AS avg_seconds
            FROM hcc_disputes
            WHERE closed_at IS NOT NULL
              AND status IN ('won','lost','abandoned')
              {('AND tenant_id = %s' if tenant_id is not None else '')}
            """,
            ([int(tenant_id)] if tenant_id is not None else []),
        )
        cyc = cur.fetchone()
        avg_cycle_seconds = float(cyc["avg_seconds"] or 0.0)
        avg_cycle_days = round(avg_cycle_seconds / 86400.0, 2)

    return {
        "tenant_id": tenant_id,
        "totals": totals,
        "win_rate": round(win_rate, 4),
        "money_at_risk": round(money_at_risk, 2),
        "money_recovered": round(money_recovered, 2),
        "avg_cycle_time_days": avg_cycle_days,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: Any) -> dict[str, Any]:
    """Coerce a DB row (dict-cursor) to a JSON-friendly dict.

    Handles: Decimal → float, date/datetime → ISO string.
    """
    if row is None:
        return {}
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif type(v).__name__ == "Decimal":
            out[k] = float(v)
        else:
            out[k] = v
    return out
