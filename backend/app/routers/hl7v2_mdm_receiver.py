"""
HL7 v2 MDM Receiver — HTTP ingest endpoint
===========================================

Endpoint
--------
  POST /api/hl7v2/mdm
    Content-Type: application/hl7-v2  (or text/plain)
    X-RAF-HL7-Source-Key: <hmac-api-key>

    Body: raw HL7 v2 pipe-delimited text

    Returns: HL7 ACK string (MSA^AA on success, MSA^AE on error)

Authentication
--------------
  Per-source HMAC API key in the ``X-RAF-HL7-Source-Key`` header.
  Keys are stored in the ``hl7v2_sources`` table (per-tenant).
  NO JWT required — interface engines (Mirth, Rhapsody, Cloverleaf) do
  not carry user tokens.

Idempotency
-----------
  MSH-10 (message_control_id) is unique per tenant.  A duplicate
  msg_control_id returns HTTP 200 with the same ACK but inserts no
  new row.

Pipeline routing
----------------
  - OBX base64 PDF  → ``gemini_document_extractor.extract_from_document``
  - OBX text TX/FT  → ``nlp_suspect_extractor.extract_hcc_suspects_from_note``
  Patient is resolved via ``patients.emr_pid`` within tenant.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.db import raf_cursor
from app.services.hl7v2_mdm_listener import HL7MDMParseError, parse_mdm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hl7v2", tags=["hl7v2_mdm"])

# ---------------------------------------------------------------------------
# HL7 ACK builder
# ---------------------------------------------------------------------------

_ACK_TEMPLATE = (
    "MSH|^~\\&|RAF-INTELLIGENCE|RAF|{sending_app}|{sending_facility}"
    "|{now}||ACK^{event}|{ack_ctrl_id}|P|2.5\r"
    "MSA|{ack_code}|{msg_ctrl_id}|{msg_text}\r"
)


def _build_ack(
    *,
    msg_ctrl_id: str,
    ack_code: str,  # "AA" | "AE"
    msg_text: str,
    sending_app: str = "",
    sending_facility: str = "",
    event: str = "T02",
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ack_ctrl = secrets.token_hex(8).upper()
    return _ACK_TEMPLATE.format(
        sending_app=sending_app or "UNKNOWN",
        sending_facility=sending_facility or "UNKNOWN",
        now=now,
        event=event,
        ack_ctrl_id=ack_ctrl,
        ack_code=ack_code,
        msg_ctrl_id=msg_ctrl_id,
        msg_text=msg_text[:80],
    )


# ---------------------------------------------------------------------------
# HMAC key authentication helpers
# ---------------------------------------------------------------------------


def _lookup_source(source_key: str) -> dict[str, Any] | None:
    """Return the hl7v2_sources row matching *source_key*, or None."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, name, hmac_secret, is_active
            FROM   hl7v2_sources
            WHERE  hmac_secret = %s AND is_active = 1
            LIMIT 1
            """,
            (source_key,),
        )
        return cur.fetchone()


def _verify_source_key(source_key: str) -> dict[str, Any]:
    """
    Authenticate the inbound request via per-source HMAC key.

    The key passed in ``X-RAF-HL7-Source-Key`` is compared against the
    ``hmac_secret`` column using a constant-time comparison to prevent
    timing attacks.  Raises HTTPException 401/403 as appropriate.
    """
    if not source_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-RAF-HL7-Source-Key header",
        )
    source = _lookup_source(source_key)
    if source is None:
        # Use constant-time compare against a dummy secret so the lookup
        # timing doesn't leak whether the key exists at all.
        secrets.compare_digest(source_key, "0" * len(source_key))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or inactive HL7 source key",
        )
    # Update last_seen_at (best-effort, ignore failures)
    try:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE hl7v2_sources SET last_seen_at = %s WHERE id = %s",
                (datetime.now(timezone.utc), source["id"]),
            )
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
    return source


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------


def _is_duplicate(tenant_id: str, msg_control_id: str) -> bool:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM hl7v2_messages_received
            WHERE  tenant_id = %s AND msg_control_id = %s
            LIMIT 1
            """,
            (tenant_id, msg_control_id),
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_message(
    *,
    tenant_id: str,
    source_id: int,
    msg_control_id: str,
    msg_type: str,
    raw_message: str,
    patient_external_id: str,
    status: str = "received",
    error_text: str | None = None,
) -> int:
    """Insert a row into hl7v2_messages_received; returns the new id."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO hl7v2_messages_received
              (tenant_id, source_id, msg_control_id, msg_type,
               raw_message, patient_external_id, received_at,
               status, suspects_extracted, error_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                source_id,
                msg_control_id,
                msg_type,
                raw_message,
                patient_external_id,
                datetime.now(timezone.utc),
                status,
                0,
                error_text,
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


def _update_message_status(
    row_id: int,
    *,
    status_val: str,
    suspects_extracted: int = 0,
    error_text: str | None = None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE hl7v2_messages_received
            SET    status = %s, suspects_extracted = %s, error_text = %s
            WHERE  id = %s
            """,
            (status_val, suspects_extracted, error_text, row_id),
        )


# ---------------------------------------------------------------------------
# Patient resolution
# ---------------------------------------------------------------------------


def _resolve_patient_id(
    tenant_id: str, patient_external_id: str
) -> int | None:
    """Map emr_pid → internal patients.id within tenant."""
    if not patient_external_id:
        return None
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM patients
            WHERE  tenant_id = %s AND emr_pid = %s
            LIMIT 1
            """,
            (tenant_id, patient_external_id),
        )
        row = cur.fetchone()
        return row["id"] if row else None


# ---------------------------------------------------------------------------
# Pipeline routing
# ---------------------------------------------------------------------------


def _run_pipeline(
    *,
    row_id: int,
    tenant_id: str,
    patient_id: int | None,
    parsed: dict[str, Any],
    measurement_year: int,
) -> int:
    """Route to Gemini vision (PDF) or NLP text extractor; return suspect count."""
    suspects_count = 0

    if parsed["encoded_payload"] is not None:
        # ---- PDF path: Gemini vision ----------------------------------------
        from app.services.gemini_document_extractor import extract_from_document

        result = extract_from_document(
            doc_bytes=parsed["encoded_payload"],
            mime_type=parsed["payload_mime"],
            year=measurement_year,
            document_filename=parsed.get("document_filename") or None,
            tenant_id=tenant_id,
        )
        suspects_count = len(result.get("suspects") or [])
        if result.get("skipped") or result.get("error"):
            logger.warning(
                "hl7v2_mdm: gemini skipped/error for row %d: %s",
                row_id,
                result.get("skipped") or result.get("error"),
            )

    elif parsed.get("text_payload"):
        # ---- Text path: NLP extractor ---------------------------------------
        from app.services.nlp_suspect_extractor import (
            extract_hcc_suspects_from_note,
        )

        suspects = extract_hcc_suspects_from_note(
            note_text=parsed["text_payload"],
            existing_codes=[],
            measurement_year=measurement_year,
        )
        suspects_count = len(suspects)

    return suspects_count


# ---------------------------------------------------------------------------
# POST /api/hl7v2/mdm
# ---------------------------------------------------------------------------


@router.post("/mdm", response_class=PlainTextResponse)
async def receive_mdm(
    request: Request,
    x_raf_hl7_source_key: str = Header(
        default="",
        alias="X-RAF-HL7-Source-Key",
        description="Per-source HMAC API key issued by RAF Intelligence admin",
    ),
) -> str:
    """Accept a raw HL7 v2 MDM message via HTTP POST.

    Returns an HL7 ACK string (``MSA|AA|...`` on success,
    ``MSA|AE|...`` on parse or auth failure).
    """
    # 1. Auth
    source = _verify_source_key(x_raf_hl7_source_key)
    tenant_id: str = source["tenant_id"]
    source_id: int = source["id"]

    # 2. Read raw body
    body_bytes = await request.body()
    raw = body_bytes.decode("utf-8", errors="replace").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty request body",
        )

    # 3. Parse
    try:
        parsed = parse_mdm(raw)
    except HL7MDMParseError as exc:
        logger.warning("hl7v2_mdm: parse error from source %s: %s", source_id, exc)
        return _build_ack(
            msg_ctrl_id="UNKNOWN",
            ack_code="AE",
            msg_text=str(exc)[:80],
        )

    msg_ctrl_id: str = parsed["msg_control_id"]
    msg_type: str = parsed["msg_type"]
    event = msg_type.split("^")[1] if "^" in msg_type else "T02"

    # 4. Idempotency
    if _is_duplicate(tenant_id, msg_ctrl_id):
        logger.info(
            "hl7v2_mdm: duplicate msg_control_id=%s tenant=%s — skipping",
            msg_ctrl_id,
            tenant_id,
        )
        return _build_ack(
            msg_ctrl_id=msg_ctrl_id,
            ack_code="AA",
            msg_text="Duplicate — already processed",
            sending_app=parsed.get("sending_app", ""),
            sending_facility=parsed.get("sending_facility", ""),
            event=event,
        )

    # 5. Persist (initial row)
    row_id = _persist_message(
        tenant_id=tenant_id,
        source_id=source_id,
        msg_control_id=msg_ctrl_id,
        msg_type=msg_type,
        raw_message=raw,
        patient_external_id=parsed.get("patient_external_id", ""),
        status="received",
    )

    # 6. Resolve patient + run pipeline (best-effort; errors captured)
    error_text: str | None = None
    suspects_extracted = 0
    final_status = "parsed"

    try:
        patient_id = _resolve_patient_id(
            tenant_id, parsed.get("patient_external_id", "")
        )
        measurement_year = datetime.now(timezone.utc).year
        suspects_extracted = _run_pipeline(
            row_id=row_id,
            tenant_id=tenant_id,
            patient_id=patient_id,
            parsed=parsed,
            measurement_year=measurement_year,
        )
        final_status = "extracted"
    except Exception as exc:
        logger.exception("hl7v2_mdm: pipeline error for row %d: %s", row_id, exc)
        error_text = str(exc)[:500]
        final_status = "failed"

    _update_message_status(
        row_id,
        status_val=final_status,
        suspects_extracted=suspects_extracted,
        error_text=error_text,
    )

    return _build_ack(
        msg_ctrl_id=msg_ctrl_id,
        ack_code="AA",
        msg_text=f"Accepted — {suspects_extracted} suspects queued",
        sending_app=parsed.get("sending_app", ""),
        sending_facility=parsed.get("sending_facility", ""),
        event=event,
    )
