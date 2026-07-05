"""
Provider Attestation Service.

Handles the full lifecycle of provider sign-off on suspect HCC conditions:

  - Creating attestation requests from suspect conditions or manual entries
  - Provider decisions: attest (confirm_active / confirm_resolved),
    reject (reject_inaccurate), defer (defer_need_info)
  - Batch attestation sessions for efficient multi-condition review
  - Digital signature: SHA-256 HMAC over (provider_user_id + attested_at + decision)
  - Reminder generation for pending attestations (email / in_app)
  - Dashboard statistics: rates, turnaround, rejection breakdown
  - Auto-update raf_patient_hcc when a condition is attested as active

All timestamps are stored as UTC.  All DB writes go to raf_intelligence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    import MySQLdb  # type: ignore[import]
except ImportError:  # mysqlclient is optional at runtime
    MySQLdb = None  # type: ignore[assignment]

from app.config import settings
from app.db import raf_cursor
from app.services.emr_manager import active_patients_subquery
from app.services.immutable_audit import append_audit_entry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Migration guard — RADV negation gate requires diagnoses.context_classification
# ---------------------------------------------------------------------------

_MIGRATION_022_PRESENT: bool | None = None


def _check_migration_022() -> bool:
    """Return True if migration 022 (diagnoses.context_classification) has run.

    Cached after the first call.  In production, a missing column is fatal:
    raises RuntimeError so the service refuses to start with a broken RADV
    negation gate.  In dev, a missing column emits a loud WARN and returns
    False — callers (``attest``) can then skip the negation gate, but the
    skip is visible in logs rather than silent.
    """
    global _MIGRATION_022_PRESENT
    if _MIGRATION_022_PRESENT is not None:
        return _MIGRATION_022_PRESENT

    # Probe outcomes:
    #   present=True  → column exists; gate is active
    #   present=False → column definitively absent (query succeeded, 0 rows)
    #   probe_failed=True → DB unreachable during the probe; do NOT cache,
    #     and do NOT crash the app on import. Retry on next call.
    present = False
    probe_failed = False
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM   information_schema.COLUMNS
                WHERE  TABLE_NAME  = 'raf_meat_evidence'
                  AND  COLUMN_NAME = 'context_classification'
                LIMIT  1
                """
            )
            present = cur.fetchone() is not None
    except Exception as exc:
        probe_failed = True
        logger.warning(
            "_check_migration_022: information_schema probe failed (%s); "
            "will retry on next call. Skipping fail-fast in import-time check.",
            exc,
        )

    if probe_failed:
        # Connection wasn't ready yet (common during container startup race).
        # Don't crash — return False without caching so the next call retries.
        return False

    if not present:
        env = (os.getenv("APP_ENV") or "").lower()
        msg = (
            "migration 022 required for attestation negation gate "
            "(raf_meat_evidence.context_classification column missing)"
        )
        if env == "production":
            raise RuntimeError(msg)
        logger.warning(
            "ATTESTATION NEGATION GATE DISABLED: %s. "
            "APP_ENV=%r — gate will be skipped at runtime with a visible WARN. "
            "Run migration 022 before going to production.",
            msg, env or "<unset>",
        )

    _MIGRATION_022_PRESENT = present
    return present


# Probe at import time so a real misconfiguration fails fast — but the probe
# is now fail-soft on connection errors (will retry on first runtime call).
try:
    _check_migration_022()
except Exception as _exc:  # noqa: BLE001
    logger.warning(
        "_check_migration_022 import-time probe deferred (%s); "
        "will retry on first attestation call.",
        _exc,
    )

# ---------------------------------------------------------------------------
# Signature helpers
# ---------------------------------------------------------------------------

# The HMAC key is derived from the JWT secret so it shares the same secret
# rotation surface.  An explicit ATTESTATION_HMAC_KEY env var can override it.
_HMAC_KEY: bytes = (
    getattr(settings, "attestation_hmac_key", None)
    or getattr(settings, "jwt_secret", "raf-attestation-dev-key")
).encode()


def _compute_signature(provider_user_id: int, attested_at: str, decision: str) -> str:
    """Return a hex HMAC-SHA256 over the canonical attestation payload.

    The payload is: ``{provider_user_id}|{attested_at}|{decision}``

    This produces a tamper-evident token stored alongside the attestation row.
    It is *not* a legal electronic signature — consult legal counsel for
    regulatory-grade e-signature requirements.
    """
    message = f"{provider_user_id}|{attested_at}|{decision}".encode()
    return hmac.new(_HMAC_KEY, message, hashlib.sha256).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for MySQL


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """Convert non-JSON-serialisable types in a DB row to plain Python types."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, bytes):
            out[k] = v.decode("utf-8", errors="replace")
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public API — Create
# ---------------------------------------------------------------------------

def create_attestation(
    *,
    patient_id: int,
    provider_npi: str,
    provider_user_id: int,
    hcc_code: str,
    hcc_description: str,
    icd10_code: str,
    icd10_description: str,
    source: str = "suspect",
    encounter_id: int | None = None,
    evidence_references: list[dict[str, Any]] | None = None,
    tenant_id: str = "",  # Required — empty string will raise below
) -> dict[str, Any]:
    """Insert a new pending attestation request and return the created row."""
    if not tenant_id:
        raise ValueError(
            "create_attestation: tenant_id is required — "
            "refusing to create attestation without tenant scope (HIPAA multi-tenant isolation)"
        )
    evidence_json = json.dumps(evidence_references) if evidence_references else None
    now = _utcnow()

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO provider_attestations
                (patient_id, encounter_id, hcc_code, hcc_description,
                 icd10_code, icd10_description, source,
                 provider_npi, provider_user_id,
                 status, evidence_references, tenant_id,
                 created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                 'pending', %s, %s, %s, %s)
            """,
            (
                patient_id, encounter_id, hcc_code, hcc_description,
                icd10_code, icd10_description, source,
                provider_npi, provider_user_id,
                evidence_json, tenant_id, now, now,
            ),
        )
        new_id = cur.lastrowid

    return get_attestation(new_id)


def create_attestations_from_suspects(
    suspect_ids: list[int],
    provider_npi: str,
    provider_user_id: int,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Bulk-create pending attestations from raf_suspect_conditions rows."""
    if not suspect_ids:
        return []

    if tenant_id is None:
        raise ValueError(
            "attestation_service.create_attestations_from_suspects: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"attestation_service.create_attestations_from_suspects: "
            f"tenant_id must be numeric, got {tenant_id!r}"
        )

    placeholders = ",".join(["%s"] * len(suspect_ids))
    _sf, _sp = active_patients_subquery(tid)
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, patient_id, suspect_hcc, suspect_icd10, evidence_type, evidence_detail
            FROM   raf_suspect_conditions
            WHERE  id IN ({placeholders})
              AND  status = 'open'
              AND  {_sf}
              AND  tenant_id = %s
            """,
            list(suspect_ids) + [*_sp, tid],
        )
        suspects = cur.fetchall()

    created: list[dict[str, Any]] = []
    for s in suspects:
        try:
            rec = create_attestation(
                patient_id=s["patient_id"],
                provider_npi=provider_npi,
                provider_user_id=provider_user_id,
                hcc_code=str(s["suspect_hcc"]),
                hcc_description="",
                icd10_code=s["suspect_icd10"],
                icd10_description="",
                source="suspect",
                evidence_references=(
                    [s["evidence_detail"]]
                    if s.get("evidence_detail")
                    else None
                ),
                tenant_id=tenant_id,
            )
            created.append(rec)
        except Exception as exc:
            logger.warning(
                "create_attestations_from_suspects: suspect_id=%s failed: %s",
                s["id"],
                exc,
            )
    return created


# ---------------------------------------------------------------------------
# Public API — Read
# ---------------------------------------------------------------------------

def get_attestation(attestation_id: int) -> dict[str, Any]:
    """Return a single attestation row or raise ValueError if not found."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM provider_attestations WHERE id = %s",
            (attestation_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Attestation {attestation_id} not found")
    return _serialize(row)


def list_attestations(
    *,
    provider_user_id: int | None = None,
    provider_npi: str | None = None,
    patient_id: int | None = None,
    status: str | None = None,
    tenant_id: str,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return attestations filtered by the supplied criteria."""
    if tenant_id is None:
        raise ValueError(
            "attestation_service.list_attestations: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    try:
        _tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"attestation_service.list_attestations: tenant_id must be numeric, got {tenant_id!r}"
        )

    _sf, _sp = active_patients_subquery(_tid)
    conditions: list[str] = [_sf, "tenant_id = %s"]
    params: list[Any] = [*_sp, _tid]

    if provider_user_id is not None:
        conditions.append("provider_user_id = %s")
        params.append(provider_user_id)
    if provider_npi:
        conditions.append("provider_npi = %s")
        params.append(provider_npi)
    if patient_id is not None:
        conditions.append("patient_id = %s")
        params.append(patient_id)
    if status and status != "all":
        conditions.append("status = %s")
        params.append(status)

    where = "WHERE " + " AND ".join(conditions)
    params += [limit, offset]

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM provider_attestations
            {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Internal — immutable audit helper
# ---------------------------------------------------------------------------

def _emit_audit(
    *,
    event_type: str,
    user_id: int | str | None,
    tenant_id: str | None,
    patient_id: int | None,
    hcc_code: str | None,
    model_version: str | None,
    payment_year: int | None,
    reason: str | None,
) -> None:
    """Emit a tamper-evident audit entry via append_audit_entry.

    Wraps the call in try/except so that an audit-write failure never prevents
    the upstream decision from being persisted.  Logging is non-optional so
    that operations can reconstruct the event from structured logs if the JSONL
    write fails.

    Event types used by attestation_service:
        ATTEST_ACCEPTED
        ATTEST_REJECTED_DOS
        ATTEST_REJECTED_CONTRADICTION
        ATTEST_WITHDRAWN
    """
    try:
        append_audit_entry(
            event_type=event_type,
            user_id=user_id,
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            resource_type="hcc_attestation",
            resource_id=str(patient_id) if patient_id is not None else None,
            action=event_type.lower(),
            details={
                "patient_id": patient_id,
                "hcc_code": hcc_code,
                "model_version": model_version,
                "payment_year": payment_year,
                "reason": reason,
            },
        )
    except Exception as exc:
        logger.error(
            "_emit_audit: failed to write immutable audit event %s "
            "(patient=%s hcc=%s year=%s): %s",
            event_type, patient_id, hcc_code, payment_year, exc,
        )


# ---------------------------------------------------------------------------
# Public API — Provider decisions
# ---------------------------------------------------------------------------

def _check_dos_year_gate(
    *,
    tenant_id: str,
    patient_id: int,
    hcc_code: str,
    payment_year: int,
) -> None:
    """SEV-1 RADV gate (A): reject if the most-recent MEAT evidence DOS is after payment_year-12-31.

    Queries raf_meat_evidence joined to raf_patient_hcc for the (tenant, patient, hcc) triple
    and checks that MAX(encounter_date) <= date(payment_year, 12, 31).

    Raises ValueError("DOS outside payment year") if the gate fails.

    TODO(migration-022): When context_classification column is added to raf_meat_evidence,
    tighten this to filter only active-context rows before computing MAX(encounter_date).
    """
    cutoff = date(payment_year, 12, 31)
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(me.encounter_date) AS max_dos
                FROM   raf_meat_evidence me
                JOIN   raf_patient_hcc ph ON ph.id = me.patient_hcc_id
                WHERE  ph.patient_id       = %s
                  AND  ph.hcc_code         = %s
                  AND  ph.measurement_year = %s
                  AND  ph.tenant_id        = %s
                """,
                (patient_id, hcc_code, payment_year, tenant_id),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error(
            "_check_dos_year_gate: DB error querying raf_meat_evidence "
            "(patient=%s hcc=%s year=%s) — gate check failed. err=%s",
            patient_id, hcc_code, payment_year, exc,
        )
        raise ValueError(
            f"RADV gate check failed due to database error for patient {patient_id}, "
            f"HCC {hcc_code}, year {payment_year}. Cannot verify DOS compliance."
        ) from exc

    max_dos = row["max_dos"] if row else None

    if max_dos is None:
        raise ValueError("DOS outside payment year")

    # max_dos may be a date or datetime depending on the DB driver
    if isinstance(max_dos, datetime):
        max_dos = max_dos.date()

    if max_dos > cutoff:
        raise ValueError("DOS outside payment year")


def _check_negation_contradiction(
    *,
    tenant_id: str,
    patient_id: int,
    hcc_code: str,
    payment_year: int,
    active_max_dos: date | None,
) -> None:
    """SEV-1 RADV gate (B): reject if a negation/resolution context is more recent than active evidence.

    Queries raf_meat_evidence for rows where context_classification (stored in the JSON
    ``metadata`` column as metadata->>'$.context_classification') is one of:
        ('negated', 'historical', 'resolved', 'family', 'hypothetical')
    AND that row's encounter_date > active_max_dos.

    TODO(migration-022): Add a real context_classification VARCHAR column to
    raf_meat_evidence so this can be a plain column filter instead of JSON extraction.
    If neither the column nor the metadata key exists the gate is skipped with a WARNING.

    Raises ValueError("Contradictory evidence: <classification> on <date>") if found.
    """
    NEGATION_LABELS = ("negated", "historical", "resolved", "family", "hypothetical")

    # Attempt 1: dedicated context_classification column (post-migration-022)
    row = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT me.context_classification AS ctx, me.encounter_date AS dos
                FROM   raf_meat_evidence me
                JOIN   raf_patient_hcc ph ON ph.id = me.patient_hcc_id
                WHERE  ph.patient_id       = %s
                  AND  ph.hcc_code         = %s
                  AND  ph.measurement_year = %s
                  AND  ph.tenant_id        = %s
                  AND  me.context_classification IN (%s, %s, %s, %s, %s)
                  AND  me.encounter_date   > %s
                ORDER  BY me.encounter_date DESC
                LIMIT  1
                """,
                (
                    patient_id, hcc_code, payment_year, tenant_id,
                    *NEGATION_LABELS,
                    active_max_dos or date(payment_year, 1, 1),
                ),
            )
            row = cur.fetchone()
    except MySQLdb.OperationalError as exc:
        if exc.args[0] == 1054:
            # Unknown column — fall through to JSON metadata path
            logger.warning(
                "_check_negation_contradiction: context_classification column missing on "
                "raf_meat_evidence — falling back to metadata JSON. "
                "TODO: run migration 022 to add the column. "
                "(patient=%s hcc=%s year=%s)",
                patient_id, hcc_code, payment_year,
            )
        else:
            logger.warning(
                "_check_negation_contradiction: DB error on column path "
                "(patient=%s hcc=%s year=%s) — skipping gate. err=%s",
                patient_id, hcc_code, payment_year, exc,
            )
            return

    if row is None:
        # Attempt 2: context stored inside JSON ``metadata`` column
        try:
            with raf_cursor() as cur:
                # Build IN-list placeholders for the JSON path comparison
                label_placeholders = ", ".join(["%s"] * len(NEGATION_LABELS))
                cur.execute(
                    f"""
                    SELECT me.metadata->>'$.context_classification' AS ctx,
                           me.encounter_date                          AS dos
                    FROM   raf_meat_evidence me
                    JOIN   raf_patient_hcc ph ON ph.id = me.patient_hcc_id
                    WHERE  ph.patient_id       = %s
                      AND  ph.hcc_code         = %s
                      AND  ph.measurement_year = %s
                      AND  ph.tenant_id        = %s
                      AND  me.metadata->>'$.context_classification' IN ({label_placeholders})
                      AND  me.encounter_date   > %s
                    ORDER  BY me.encounter_date DESC
                    LIMIT  1
                    """,
                    (
                        patient_id, hcc_code, payment_year, tenant_id,
                        *NEGATION_LABELS,
                        active_max_dos or date(payment_year, 1, 1),
                    ),
                )
                row = cur.fetchone()
        except MySQLdb.OperationalError as exc2:
            if exc2.args[0] in (1054, 3143):
                # 3143 = Invalid JSON path expression; column may not exist either
                logger.warning(
                    "_check_negation_contradiction: metadata JSON path unavailable "
                    "(patient=%s hcc=%s year=%s) — skipping contradiction gate. "
                    "TODO: run migration 022 to add context_classification column. err=%s",
                    patient_id, hcc_code, payment_year, exc2,
                )
                return
            logger.warning(
                "_check_negation_contradiction: DB error on metadata JSON path "
                "(patient=%s hcc=%s year=%s) — skipping gate. err=%s",
                patient_id, hcc_code, payment_year, exc2,
            )
            return
        except Exception as exc2:
            logger.warning(
                "_check_negation_contradiction: unexpected error "
                "(patient=%s hcc=%s year=%s) — skipping gate. err=%s",
                patient_id, hcc_code, payment_year, exc2,
            )
            return

    if row:
        ctx = row.get("ctx") or "unknown"
        dos = row.get("dos")
        dos_str = dos.isoformat() if isinstance(dos, (date, datetime)) else str(dos)
        raise ValueError(f"Contradictory evidence: {ctx} on {dos_str}")


def attest(
    attestation_id: int,
    *,
    provider_user_id: int,
    attestation_type: str,
    clinical_justification: str | None = None,
    evidence_references: list[dict[str, Any]] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """Record a provider attestation decision (confirm_active or confirm_resolved).

    Computes a tamper-evident HMAC signature and, when attestation_type is
    'confirm_active', propagates the confirmed HCC into raf_patient_hcc.

    RADV gates (fail-closed):
      (A) DOS-year gate  — supporting MEAT evidence must have MAX(encounter_date)
          within the payment year.  Raises ValueError("DOS outside payment year").
      (B) Negation gate  — rejects if a negated/historical/resolved/family/
          hypothetical evidence row is more recent than the active evidence.
          Raises ValueError("Contradictory evidence: <ctx> on <date>").

    Both gates emit an immutable audit entry before raising.
    ``measurement_year`` defaults to the current calendar year if not supplied;
    pass it explicitly so the gate uses the correct payment-year window.
    """
    valid_types = {"confirm_active", "confirm_resolved"}
    if attestation_type not in valid_types:
        raise ValueError(
            f"attestation_type must be one of {valid_types}, got {attestation_type!r}"
        )

    rec = get_attestation(attestation_id)
    if rec["status"] != "pending":
        raise ValueError(
            f"Attestation {attestation_id} is already {rec['status']} and cannot be re-attested"
        )

    tenant_id: str = str(rec.get("tenant_id", ""))
    patient_id: int = rec.get("patient_id")
    hcc_code: str = str(rec.get("hcc_code", ""))
    model_version: str = str(rec.get("model_version", "V28"))

    now = _utcnow()

    # Resolve payment year — fall back to current year with a warning if not passed.
    # TODO(migration-022): Router should pass measurement_year from the attestation
    # request body once AttestRequest adds that field.
    if measurement_year is None:
        logger.warning(
            "attest: measurement_year not provided for attestation_id=%s — "
            "defaulting to current year %s. Pass measurement_year explicitly for "
            "correct RADV DOS-year gate behaviour.",
            attestation_id, now.year,
        )
        payment_year = now.year
    else:
        payment_year = measurement_year

    # ------------------------------------------------------------------
    # RADV gate (A): DOS-year check
    # ------------------------------------------------------------------
    try:
        _check_dos_year_gate(
            tenant_id=tenant_id,
            patient_id=patient_id,
            hcc_code=hcc_code,
            payment_year=payment_year,
        )
    except ValueError as dos_exc:
        _emit_audit(
            event_type="ATTEST_REJECTED_DOS",
            user_id=provider_user_id,
            tenant_id=tenant_id,
            patient_id=patient_id,
            hcc_code=hcc_code,
            model_version=model_version,
            payment_year=payment_year,
            reason=str(dos_exc),
        )
        raise

    # ------------------------------------------------------------------
    # Compute active MAX(encounter_date) for the negation comparison
    # ------------------------------------------------------------------
    active_max_dos: date | None = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(me.encounter_date) AS max_dos
                FROM   raf_meat_evidence me
                JOIN   raf_patient_hcc ph ON ph.id = me.patient_hcc_id
                WHERE  ph.patient_id       = %s
                  AND  ph.hcc_code         = %s
                  AND  ph.measurement_year = %s
                  AND  ph.tenant_id        = %s
                """,
                (patient_id, hcc_code, payment_year, tenant_id),
            )
            _row = cur.fetchone()
            if _row and _row["max_dos"]:
                _dos = _row["max_dos"]
                active_max_dos = _dos.date() if isinstance(_dos, datetime) else _dos
    except Exception as exc:
        logger.warning(
            "attest: could not resolve active_max_dos for negation gate "
            "(attestation_id=%s): %s",
            attestation_id, exc,
        )

    # ------------------------------------------------------------------
    # RADV gate (B): negation contradiction check
    #
    # Guarded by migration 022 — without the diagnoses.context_classification
    # column the clinical contradiction check cannot run.  In production the
    # import-time check raises RuntimeError; in dev we skip the gate but emit
    # a visible WARN every time it would have run, so the skip is never silent.
    # ------------------------------------------------------------------
    if not _check_migration_022():
        logger.warning(
            "attest: SKIPPING RADV negation gate for attestation_id=%s "
            "(patient=%s hcc=%s year=%s) — migration 022 has not run; "
            "diagnoses.context_classification column is missing. "
            "This is acceptable in dev only — run migration 022 before prod.",
            attestation_id, patient_id, hcc_code, payment_year,
        )
    else:
        try:
            _check_negation_contradiction(
                tenant_id=tenant_id,
                patient_id=patient_id,
                hcc_code=hcc_code,
                payment_year=payment_year,
                active_max_dos=active_max_dos,
            )
        except ValueError as neg_exc:
            _emit_audit(
                event_type="ATTEST_REJECTED_CONTRADICTION",
                user_id=provider_user_id,
                tenant_id=tenant_id,
                patient_id=patient_id,
                hcc_code=hcc_code,
                model_version=model_version,
                payment_year=payment_year,
                reason=str(neg_exc),
            )
            raise

    # ------------------------------------------------------------------
    # Persist the attestation decision
    # ------------------------------------------------------------------
    attested_at_iso = now.isoformat()
    sig = _compute_signature(provider_user_id, attested_at_iso, attestation_type)
    evidence_json = json.dumps(evidence_references) if evidence_references else None

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO attestation_history
                (attestation_id, previous_status, new_status, changed_by, change_reason, snapshot)
            VALUES (%s, %s, 'attested', %s, %s, %s)
            """,
            (
                attestation_id,
                rec["status"],
                provider_user_id,
                clinical_justification,
                json.dumps(rec),
            ),
        )
        cur.execute(
            """
            UPDATE provider_attestations
            SET    status               = 'attested',
                   attestation_type     = %s,
                   clinical_justification = %s,
                   evidence_references  = COALESCE(%s, evidence_references),
                   signature_hash       = %s,
                   attested_at          = %s,
                   ip_address           = %s,
                   user_agent           = %s,
                   updated_at           = %s
            WHERE  id = %s
            """,
            (
                attestation_type,
                clinical_justification,
                evidence_json,
                sig,
                now,
                ip_address,
                user_agent,
                now,
                attestation_id,
            ),
        )

    updated = get_attestation(attestation_id)

    # Propagate to raf_patient_hcc when provider confirms the condition is active
    if attestation_type == "confirm_active":
        _propagate_to_patient_hcc(updated)

    # Emit success audit event
    _emit_audit(
        event_type="ATTEST_ACCEPTED",
        user_id=provider_user_id,
        tenant_id=tenant_id,
        patient_id=patient_id,
        hcc_code=hcc_code,
        model_version=model_version,
        payment_year=payment_year,
        reason=attestation_type,
    )

    return updated


def reject(
    attestation_id: int,
    *,
    provider_user_id: int,
    reject_reason: str,
    clinical_justification: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Record a provider rejection decision (reject_inaccurate).

    After marking the attestation as rejected the linked raf_patient_hcc row is
    withdrawn inside the same transaction so it is excluded from future RAPS/EDPS
    submissions.  Graceful fallbacks are applied when the schema predates the
    is_withdrawn column.

    Emits an ATTEST_WITHDRAWN immutable audit event after the transaction commits.
    """
    rec = get_attestation(attestation_id)
    if rec["status"] != "pending":
        raise ValueError(
            f"Attestation {attestation_id} is already {rec['status']} and cannot be rejected"
        )

    now = _utcnow()
    sig = _compute_signature(provider_user_id, now.isoformat(), "reject_inaccurate")

    patient_id = rec.get("patient_id")
    hcc_code = rec.get("hcc_code")
    tenant_id: str = str(rec.get("tenant_id", ""))
    model_version: str = str(rec.get("model_version", "V28"))
    payment_year = now.year

    with raf_cursor() as cur:
        # --- 1. Audit history -------------------------------------------------
        cur.execute(
            """
            INSERT INTO attestation_history
                (attestation_id, previous_status, new_status, changed_by, change_reason, snapshot)
            VALUES (%s, %s, 'rejected', %s, %s, %s)
            """,
            (
                attestation_id,
                rec["status"],
                provider_user_id,
                reject_reason,
                json.dumps(rec),
            ),
        )

        # --- 2. Mark attestation rejected -------------------------------------
        cur.execute(
            """
            UPDATE provider_attestations
            SET    status               = 'rejected',
                   attestation_type     = 'reject_inaccurate',
                   reject_reason        = %s,
                   clinical_justification = %s,
                   signature_hash       = %s,
                   attested_at          = %s,
                   ip_address           = %s,
                   user_agent           = %s,
                   updated_at           = %s
            WHERE  id = %s
            """,
            (
                reject_reason,
                clinical_justification,
                sig,
                now,
                ip_address,
                user_agent,
                now,
                attestation_id,
            ),
        )

        # --- 3. Withdraw linked raf_patient_hcc row ---------------------------
        _withdraw_patient_hcc(
            cur=cur,
            attestation_id=attestation_id,
            patient_id=patient_id,
            hcc_code=hcc_code,
            payment_year=payment_year,
            reject_reason=reject_reason,
            withdrawn_by_user_id=provider_user_id,
            now=now,
        )

    # Emit immutable audit event for the withdrawal
    _emit_audit(
        event_type="ATTEST_WITHDRAWN",
        user_id=provider_user_id,
        tenant_id=tenant_id,
        patient_id=patient_id,
        hcc_code=hcc_code,
        model_version=model_version,
        payment_year=payment_year,
        reason=reject_reason,
    )

    return get_attestation(attestation_id)


# ---------------------------------------------------------------------------
# Internal — withdraw raf_patient_hcc on rejection
# ---------------------------------------------------------------------------

_WITHDRAWAL_AUDIT_TABLE_WARNED: bool = False


def _withdraw_patient_hcc(
    *,
    cur: Any,
    attestation_id: int,
    patient_id: int | None,
    hcc_code: str | None,
    payment_year: int,
    reject_reason: str,
    withdrawn_by_user_id: int,
    now: datetime,
) -> None:
    """Withdraw the raf_patient_hcc row matching this rejection.

    Strategy (in order):
      1. Try UPDATE … SET is_withdrawn = 1 (preferred — excludes row from RAPS/EDPS).
      2. On unknown-column MySQLError fall back to SET status = 'withdrawn'
         (or meat_status = 'withdrawn' if status column is absent).
      3. Attempt an INSERT into raf_hcc_withdrawals for a durable audit trail;
         silently skip if the table does not yet exist.

    All operations execute within the caller's already-open cursor so they
    participate in the same transaction as the attestation update.
    """
    if patient_id is None or hcc_code is None:
        logger.warning(
            "_withdraw_patient_hcc: attestation_id=%s missing patient_id or hcc_code — "
            "skipping HCC withdrawal",
            attestation_id,
        )
        return

    # -- Primary path: is_withdrawn column ------------------------------------
    try:
        cur.execute(
            """
            UPDATE raf_patient_hcc
            SET    is_withdrawn         = 1,
                   withdrawn_at         = %s,
                   withdrawn_reason     = %s,
                   withdrawn_by_user_id = %s
            WHERE  patient_id = %s
              AND  hcc_code   = %s
              AND  measurement_year = %s
            """,
            (now, reject_reason, withdrawn_by_user_id, patient_id, hcc_code, payment_year),
        )
        logger.info(
            "_withdraw_patient_hcc: patient=%s hcc=%s year=%s rows_affected=%s",
            patient_id,
            hcc_code,
            payment_year,
            cur.rowcount,
        )
    except MySQLdb.OperationalError as exc:
        # Error 1054 = Unknown column
        if exc.args[0] != 1054:
            raise
        logger.warning(
            "raf_patient_hcc.is_withdrawn column missing — add column to enable "
            "automatic withdrawal. Falling back to status flag. "
            "(attestation_id=%s patient=%s hcc=%s)",
            attestation_id,
            patient_id,
            hcc_code,
        )
        # -- Fallback: try status = 'withdrawn' --------------------------------
        try:
            cur.execute(
                """
                UPDATE raf_patient_hcc
                SET    status     = 'withdrawn',
                       updated_at = %s
                WHERE  patient_id = %s
                  AND  hcc_code   = %s
                  AND  measurement_year = %s
                """,
                (now, patient_id, hcc_code, payment_year),
            )
        except MySQLdb.OperationalError as exc2:
            if exc2.args[0] != 1054:
                raise
            # -- Last resort: meat_status = 'withdrawn' ------------------------
            try:
                cur.execute(
                    """
                    UPDATE raf_patient_hcc
                    SET    meat_status = 'withdrawn',
                           updated_at  = %s
                    WHERE  patient_id = %s
                      AND  hcc_code   = %s
                      AND  measurement_year = %s
                    """,
                    (now, patient_id, hcc_code, payment_year),
                )
            except Exception as exc3:
                logger.error(
                    "_withdraw_patient_hcc: all fallback UPDATE strategies failed "
                    "for patient=%s hcc=%s: %s",
                    patient_id,
                    hcc_code,
                    exc3,
                )

    # -- Audit trail: raf_hcc_withdrawals (best-effort) ------------------------
    global _WITHDRAWAL_AUDIT_TABLE_WARNED
    try:
        cur.execute(
            """
            INSERT INTO raf_hcc_withdrawals
                (patient_hcc_id, rejected_attestation_id, reason, withdrawn_by, withdrawn_at)
            SELECT id, %s, %s, %s, %s
            FROM   raf_patient_hcc
            WHERE  patient_id        = %s
              AND  hcc_code          = %s
              AND  measurement_year  = %s
            LIMIT  1
            """,
            (
                attestation_id,
                reject_reason,
                withdrawn_by_user_id,
                now,
                patient_id,
                hcc_code,
                payment_year,
            ),
        )
    except MySQLdb.OperationalError as exc:
        # Error 1146 = Table doesn't exist
        if exc.args[0] == 1146 and not _WITHDRAWAL_AUDIT_TABLE_WARNED:
            logger.warning(
                "raf_hcc_withdrawals table does not exist — withdrawal audit row skipped. "
                "Run the schema migration to create it."
            )
            _WITHDRAWAL_AUDIT_TABLE_WARNED = True
        elif exc.args[0] != 1146:
            logger.warning(
                "_withdraw_patient_hcc: audit insert failed for patient=%s hcc=%s: %s",
                patient_id,
                hcc_code,
                exc,
            )
    except Exception as exc:
        logger.warning(
            "_withdraw_patient_hcc: audit insert failed for patient=%s hcc=%s: %s",
            patient_id,
            hcc_code,
            exc,
        )


def defer(
    attestation_id: int,
    *,
    provider_user_id: int,
    deferred_until: date | None = None,
    clinical_justification: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Record a provider deferral decision (defer_need_info)."""
    rec = get_attestation(attestation_id)
    if rec["status"] != "pending":
        raise ValueError(
            f"Attestation {attestation_id} is already {rec['status']} and cannot be deferred"
        )

    now = _utcnow()
    sig = _compute_signature(provider_user_id, now.isoformat(), "defer_need_info")

    # Default defer window: 30 days
    if deferred_until is None:
        deferred_until = (now + timedelta(days=30)).date()

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO attestation_history
                (attestation_id, previous_status, new_status, changed_by, change_reason, snapshot)
            VALUES (%s, %s, 'deferred', %s, %s, %s)
            """,
            (
                attestation_id,
                rec["status"],
                provider_user_id,
                clinical_justification,
                json.dumps(rec),
            ),
        )
        cur.execute(
            """
            UPDATE provider_attestations
            SET    status               = 'deferred',
                   attestation_type     = 'defer_need_info',
                   deferred_until       = %s,
                   clinical_justification = %s,
                   signature_hash       = %s,
                   attested_at          = %s,
                   ip_address           = %s,
                   user_agent           = %s,
                   updated_at           = %s
            WHERE  id = %s
            """,
            (
                deferred_until,
                clinical_justification,
                sig,
                now,
                ip_address,
                user_agent,
                now,
                attestation_id,
            ),
        )
    return get_attestation(attestation_id)


# ---------------------------------------------------------------------------
# Public API — Batch operations
# ---------------------------------------------------------------------------

def create_batch(
    *,
    provider_npi: str,
    provider_user_id: int,
    attestation_ids: list[int],
    tenant_id: str,
) -> dict[str, Any]:
    """Create a new batch and associate existing attestation IDs with it."""
    if not attestation_ids:
        raise ValueError("attestation_ids must not be empty")
    if not tenant_id:
        raise ValueError(
            "create_batch: tenant_id is required — "
            "refusing to create batch without tenant scope (HIPAA multi-tenant isolation)"
        )

    now = _utcnow()
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO attestation_batches
                (provider_npi, provider_user_id, total_conditions,
                 status, tenant_id, started_at, created_at, updated_at)
            VALUES (%s, %s, %s, 'in_progress', %s, %s, %s, %s)
            """,
            (
                provider_npi, provider_user_id, len(attestation_ids),
                tenant_id, now, now, now,
            ),
        )
        batch_id = cur.lastrowid

        # Link attestations to this batch
        if attestation_ids:
            placeholders = ",".join(["%s"] * len(attestation_ids))
            params = [batch_id] + attestation_ids
            cur.execute(
                f"""
                UPDATE provider_attestations
                SET    batch_id = %s
                WHERE  id IN ({placeholders})
                  AND  provider_user_id = %s
                """,
                params + [provider_user_id],
            )

    return get_batch(batch_id)


def get_batch(batch_id: int) -> dict[str, Any]:
    """Return a batch row with its current aggregate counts."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM attestation_batches WHERE id = %s",
            (batch_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Batch {batch_id} not found")
    return _serialize(row)


def submit_batch(
    batch_id: int,
    *,
    provider_user_id: int,
    decisions: list[dict[str, Any]],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Process all decisions in a batch and mark the batch completed.

    ``decisions`` is a list of dicts, each containing:
        attestation_id  (int, required)
        action          ("attest" | "reject" | "defer", required)
        attestation_type (str, required for attest)
        reject_reason   (str, required for reject)
        deferred_until  (ISO date string, optional for defer)
        clinical_justification (str, optional)
    """
    batch = get_batch(batch_id)
    if batch["status"] == "completed":
        raise ValueError(f"Batch {batch_id} is already completed")

    results: list[dict[str, Any]] = []
    attested = rejected = deferred = errors = 0

    for d in decisions:
        aid = d.get("attestation_id")
        action = d.get("action")
        try:
            if action == "attest":
                rec = attest(
                    aid,
                    provider_user_id=provider_user_id,
                    attestation_type=d.get("attestation_type", "confirm_active"),
                    clinical_justification=d.get("clinical_justification"),
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                attested += 1
            elif action == "reject":
                rec = reject(
                    aid,
                    provider_user_id=provider_user_id,
                    reject_reason=d.get("reject_reason", ""),
                    clinical_justification=d.get("clinical_justification"),
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                rejected += 1
            elif action == "defer":
                deferred_until_raw = d.get("deferred_until")
                deferred_until_val: date | None = None
                if deferred_until_raw:
                    deferred_until_val = date.fromisoformat(deferred_until_raw)
                rec = defer(
                    aid,
                    provider_user_id=provider_user_id,
                    deferred_until=deferred_until_val,
                    clinical_justification=d.get("clinical_justification"),
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                deferred += 1
            else:
                raise ValueError(f"Unknown action {action!r}")
            results.append({"attestation_id": aid, "status": "ok", "record": rec})
        except Exception as exc:
            errors += 1
            results.append({"attestation_id": aid, "status": "error", "error": str(exc)})
            logger.warning("submit_batch: batch=%s aid=%s failed: %s", batch_id, aid, exc)

    now = _utcnow()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE attestation_batches
            SET    attested_count  = %s,
                   rejected_count  = %s,
                   deferred_count  = %s,
                   status          = 'completed',
                   completed_at    = %s,
                   updated_at      = %s
            WHERE  id = %s
            """,
            (attested, rejected, deferred, now, now, batch_id),
        )

    return {
        "batch_id": batch_id,
        "attested": attested,
        "rejected": rejected,
        "deferred": deferred,
        "errors": errors,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Public API — Reminders
# ---------------------------------------------------------------------------

def generate_reminders(
    *,
    reminder_type: str = "in_app",
    overdue_days: int = 7,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Create reminder records for attestations pending for more than ``overdue_days``.

    Returns the list of newly created reminder rows.  Attestations that have
    already received a reminder of the same type within the last 24 hours are
    skipped to avoid spam.
    """
    cutoff = (_utcnow() - timedelta(days=overdue_days)).isoformat()
    now = _utcnow()

    if tenant_id is None:
        raise ValueError(
            "attestation_service.generate_reminders: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    try:
        _tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"attestation_service.generate_reminders: tenant_id must be numeric, got {tenant_id!r}"
        )

    _sf, _sp = active_patients_subquery(_tid, patient_id_column="pa.patient_id")
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT pa.id AS attestation_id,
                   pa.provider_user_id,
                   pa.patient_id,
                   pa.hcc_code,
                   pa.created_at
            FROM   provider_attestations pa
            WHERE  pa.status = 'pending'
              AND  pa.created_at <= %s
              AND  {_sf}
              AND  pa.tenant_id = %s
              AND  pa.id NOT IN (
                  SELECT ar.attestation_id
                  FROM   attestation_reminders ar
                  WHERE  ar.reminder_type = %s
                    AND  ar.sent_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
              )
            """,
            [cutoff, *_sp, _tid, reminder_type],
        )
        candidates = cur.fetchall()

    created: list[dict[str, Any]] = []
    # Single cursor for all reminder inserts — avoids N+1 connection overhead.
    # Each row is still inserted individually so that a duplicate-key violation
    # on one row (e.g. a concurrent worker already inserted it) skips only that
    # row rather than aborting the entire batch.
    with raf_cursor() as cur:
        for row in candidates:
            try:
                cur.execute(
                    """
                    INSERT INTO attestation_reminders
                        (attestation_id, reminder_type, sent_at)
                    VALUES (%s, %s, %s)
                    """,
                    (row["attestation_id"], reminder_type, now),
                )
                reminder_id = cur.lastrowid
                created.append(
                    {
                        "reminder_id": reminder_id,
                        "attestation_id": row["attestation_id"],
                        "provider_user_id": row["provider_user_id"],
                        "patient_id": row["patient_id"],
                        "hcc_code": row["hcc_code"],
                        "reminder_type": reminder_type,
                        "sent_at": now.isoformat(),
                    }
                )
            except Exception as exc:
                logger.warning(
                    "generate_reminders: attestation_id=%s failed: %s",
                    row["attestation_id"],
                    exc,
                )

    logger.info(
        "generate_reminders: type=%s created=%d skipped=%d",
        reminder_type,
        len(created),
        len(candidates) - len(created),
    )
    return created


# ---------------------------------------------------------------------------
# Public API — Dashboard statistics
# ---------------------------------------------------------------------------

def get_dashboard_stats(
    *,
    provider_user_id: int | None = None,
    tenant_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """Return attestation KPIs for the dashboard.

    Metrics returned:
      - total / pending / attested / rejected / deferred counts
      - attestation rate (attested / (attested + rejected + deferred))
      - average turnaround hours
      - rejection reason breakdown
      - attestation type breakdown
    """
    since = (_utcnow() - timedelta(days=days)).isoformat()

    if tenant_id is None:
        raise ValueError(
            "attestation_service.get_dashboard_stats: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    try:
        _tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"attestation_service.get_dashboard_stats: tenant_id must be numeric, got {tenant_id!r}"
        )

    _sf2, _sp2 = active_patients_subquery(_tid)
    conditions: list[str] = ["created_at >= %s", _sf2, "tenant_id = %s"]
    params: list[Any] = [since, *_sp2, _tid]
    if provider_user_id is not None:
        conditions.append("provider_user_id = %s")
        params.append(provider_user_id)

    where = "WHERE " + " AND ".join(conditions)

    with raf_cursor() as cur:
        # Status counts
        cur.execute(
            f"""
            SELECT status, COUNT(*) AS cnt
            FROM   provider_attestations
            {where}
            GROUP  BY status
            """,
            params,
        )
        status_rows = cur.fetchall()

        # Average turnaround (hours from created_at to attested_at)
        cur.execute(
            f"""
            SELECT AVG(TIMESTAMPDIFF(HOUR, created_at, attested_at)) AS avg_hours
            FROM   provider_attestations
            {where}
              AND  attested_at IS NOT NULL
            """,
            params,
        )
        turnaround_row = cur.fetchone()

        # Rejection reason breakdown
        cur.execute(
            f"""
            SELECT reject_reason, COUNT(*) AS cnt
            FROM   provider_attestations
            {where}
              AND  status = 'rejected'
              AND  reject_reason IS NOT NULL
            GROUP  BY reject_reason
            ORDER  BY cnt DESC
            LIMIT  10
            """,
            params,
        )
        rejection_breakdown = cur.fetchall()

        # Attestation type breakdown
        cur.execute(
            f"""
            SELECT attestation_type, COUNT(*) AS cnt
            FROM   provider_attestations
            {where}
              AND  attestation_type IS NOT NULL
            GROUP  BY attestation_type
            """,
            params,
        )
        type_breakdown = cur.fetchall()

    counts: dict[str, int] = {
        "pending": 0, "attested": 0, "rejected": 0, "deferred": 0
    }
    for r in status_rows:
        counts[r["status"]] = int(r["cnt"])

    total = sum(counts.values())
    decided = counts["attested"] + counts["rejected"] + counts["deferred"]
    attestation_rate = round(counts["attested"] / decided * 100, 1) if decided else 0.0
    avg_hours = float(turnaround_row["avg_hours"] or 0) if turnaround_row else 0.0

    return {
        "period_days": days,
        "total": total,
        "by_status": counts,
        "attestation_rate_pct": attestation_rate,
        "avg_turnaround_hours": round(avg_hours, 1),
        "rejection_reasons": [
            {"reason": r["reject_reason"], "count": int(r["cnt"])}
            for r in rejection_breakdown
        ],
        "attestation_types": [
            {"type": r["attestation_type"], "count": int(r["cnt"])}
            for r in type_breakdown
        ],
    }


# ---------------------------------------------------------------------------
# Internal — propagate to raf_patient_hcc
# ---------------------------------------------------------------------------

def _propagate_to_patient_hcc(attestation: dict[str, Any]) -> None:
    """Upsert a confirmed-active HCC into raf_patient_hcc.

    Called automatically by ``attest()`` when attestation_type is
    'confirm_active'.  Uses INSERT ... ON DUPLICATE KEY UPDATE so that
    re-attesting an already-confirmed condition is idempotent.
    """
    patient_id = attestation.get("patient_id")
    hcc_code = attestation.get("hcc_code")
    icd10_code = attestation.get("icd10_code")
    icd10_description = attestation.get("icd10_description", "")
    now = _utcnow()
    year = now.year

    try:
        with raf_cursor() as cur:
            # Check if raf_patient_hcc exists (it should from earlier migrations)
            cur.execute(
                """
                INSERT INTO raf_patient_hcc
                    (patient_id, measurement_year, hcc_code, icd10_code,
                     icd10_description, source, model_version, confirmed_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'attestation', 'V28', %s, %s)
                ON DUPLICATE KEY UPDATE
                    source          = 'attestation',
                    model_version   = VALUES(model_version),
                    confirmed_at    = %s,
                    updated_at      = %s
                """,
                (
                    patient_id, year, hcc_code, icd10_code,
                    icd10_description, now, now,
                    now, now,
                ),
            )
    except Exception as exc:
        # Non-fatal: log but do not roll back the attestation decision itself.
        logger.error(
            "_propagate_to_patient_hcc: patient=%s hcc=%s failed: %s",
            patient_id,
            hcc_code,
            exc,
        )
