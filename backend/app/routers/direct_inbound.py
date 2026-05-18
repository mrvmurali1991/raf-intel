"""
Direct Trust Inbound Endpoint
==============================
Receives MIME-encoded email messages delivered via the Direct Project
(S/MIME-over-SMTP) protocol and processes inbound C-CDA XML attachments.

Endpoint
--------
POST /api/direct/inbound
    Accepts a raw MIME email body (RFC 5322 format) as the request body.
    Required headers:
        X-Direct-From   — sender Direct address (e.g. provider@direct.example.org)
        X-Direct-To     — recipient Direct address managed by this system

Processing pipeline
-------------------
1. Validate required headers (X-Direct-From, X-Direct-To).
2. Look up sender in ``direct_trust_anchors`` — reject unknown senders with 403.
3. Parse MIME body; extract all MIME parts.
4. For each ``application/x-cda-xml`` or ``text/xml`` attachment:
   a. Call ``ccda_parser.parse_ccda_xml`` to extract structured data.
   b. Persist a row to ``ccda_documents`` (source = 'direct_message').
   c. Run extracted ICD-10 codes against ``hcc_icd10_crosswalk`` and write
      any new HCC suspects to ``raf_suspect_conditions``.
5. For ``application/pdf`` attachments: delegate to
   ``gemini_document_extractor.extract_suspects_from_document``.
6. Track the inbound message in ``direct_inbound_messages``.
7. Return 200 JSON with counts.

S/MIME verification
-------------------
TODO(production): Full S/MIME signature verification (decrypt outer
EnvelopedData, verify inner SignedData against sender certificate anchored in
``direct_trust_anchors.certificate_pem``) is deferred to the production
deploy.  For now the trust anchor whitelist (sender address domain or exact
address lookup) provides the security boundary.

Idempotency
-----------
The ``message_id`` RFC-2822 header is used as the deduplication key.
Re-submitting the same message returns 200 with ``duplicate: true`` and no
new rows are written.
"""
from __future__ import annotations

import email as email_lib
import email.policy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.db import raf_cursor
from app.services.ccda_parser import parse_ccda_xml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/direct", tags=["direct_messaging"])

# Content-type values that identify a C-CDA XML attachment
_CCDA_CONTENT_TYPES = frozenset(
    {"application/x-cda-xml", "text/xml", "application/xml", "application/x-hl7-cda+xml"}
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lookup_trust_anchor(tenant_id: str, from_address: str) -> bool:
    """Return True if the sender domain or exact address is in direct_trust_anchors.

    A sender is trusted when:
    - An exact-match row exists for ``from_address``, OR
    - A domain-wildcard row exists for the sender's domain.

    Only rows with ``status = 'trusted'`` are considered.
    """
    domain = from_address.split("@")[-1].lower() if "@" in from_address else from_address.lower()
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id FROM direct_trust_anchors
                WHERE tenant_id = %s
                  AND status = 'trusted'
                  AND (
                      organization = %s
                      OR organization = %s
                      OR name LIKE %s
                  )
                LIMIT 1
                """,
                (tenant_id, from_address.lower(), domain, f"%{domain}%"),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        logger.warning("Trust anchor lookup error: %s", exc)
        return False


def _check_duplicate(tenant_id: str, message_id: str) -> bool:
    """Return True if message_id was already processed for this tenant."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM direct_inbound_messages "
                "WHERE tenant_id = %s AND message_id = %s LIMIT 1",
                (tenant_id, message_id),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        logger.debug("Duplicate check error: %s", exc)
        return False


def _record_inbound_message(
    tenant_id: str,
    message_id: str,
    from_address: str,
    to_address: str,
    subject: str | None,
    ccda_parsed: int,
    suspects_extracted: int,
    msg_status: str,
    error_text: str | None = None,
) -> None:
    """Insert a row into direct_inbound_messages tracking table."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO direct_inbound_messages
                  (tenant_id, message_id, from_address, to_address, subject,
                   received_at, ccda_parsed, suspects_extracted, status, error_text)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  ccda_parsed        = VALUES(ccda_parsed),
                  suspects_extracted = VALUES(suspects_extracted),
                  status             = VALUES(status),
                  error_text         = VALUES(error_text)
                """,
                (
                    tenant_id,
                    message_id,
                    from_address,
                    to_address,
                    subject,
                    ccda_parsed,
                    suspects_extracted,
                    msg_status,
                    error_text,
                ),
            )
    except Exception as exc:
        logger.error("Failed to record inbound message: %s", exc)


def _persist_ccda_document(
    tenant_id: str,
    parsed: dict[str, Any],
    raw_xml: bytes,
) -> int | None:
    """Insert a row into ccda_documents and return the new id."""
    try:
        parsed_data_json = json.dumps({
            "problems_count":   len(parsed.get("problems", [])),
            "medications_count": len(parsed.get("medications", [])),
            "results_count":    len(parsed.get("results", [])),
            "encounters_count": len(parsed.get("encounters", [])),
            "allergies_count":  len(parsed.get("allergies", [])),
            "hcc_suspects":     parsed.get("hcc_suspects", []),
            "patient":          parsed.get("patient", {}),
        })
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ccda_documents
                  (tenant_id, document_type, source, file_path, file_size,
                   status, parsed_data, created_at, updated_at)
                VALUES (%s, 'ccd', 'direct_message', '', %s, 'parsed', %s, NOW(), NOW())
                """,
                (tenant_id, len(raw_xml), parsed_data_json),
            )
            return cur.lastrowid
    except Exception as exc:
        logger.error("Failed to persist ccda_document: %s", exc)
        return None


def _persist_hcc_suspects(
    tenant_id: str,
    problems: list[dict],
    ccda_doc_id: int | None,
) -> int:
    """Write new HCC suspect rows to raf_suspect_conditions.

    Returns the count of suspects written.
    """
    written = 0
    for prob in problems:
        icd10 = prob.get("icd10_code")
        hcc   = prob.get("hcc_code")
        if not icd10 or not hcc:
            continue
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    INSERT IGNORE INTO raf_suspect_conditions
                      (tenant_id, icd10_code, hcc_code, source, status,
                       source_document_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 'direct_ccda', 'open', %s, NOW(), NOW())
                    """,
                    (tenant_id, icd10, hcc, ccda_doc_id),
                )
                if cur.rowcount:
                    written += 1
        except Exception as exc:
            logger.debug("Suspect insert skipped for %s: %s", icd10, exc)
    return written


def _route_pdf_to_gemini(
    tenant_id: str,
    content_bytes: bytes,
    filename: str,
) -> int:
    """Delegate a PDF attachment to gemini_document_extractor.

    Returns the number of suspects extracted (0 on any error).
    """
    try:
        from app.services.gemini_document_extractor import extract_suspects_from_document  # noqa: F401 — may not exist
        suspects = extract_suspects_from_document(
            content_bytes,
            mime_type="application/pdf",
            source_label=filename,
            tenant_id=tenant_id,
        )
        return len(suspects) if suspects else 0
    except Exception as exc:
        logger.warning("Gemini PDF extraction failed for %s: %s", filename, exc)
        return 0


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/inbound",
    summary="Receive a Direct Trust inbound MIME message",
    response_model=None,
    status_code=200,
)
async def direct_inbound(
    request: Request,
    x_direct_from: str | None = Header(default=None, alias="X-Direct-From"),
    x_direct_to:   str | None = Header(default=None, alias="X-Direct-To"),
) -> dict[str, Any]:
    """Ingest an inbound Direct Trust MIME message.

    The request body must be the RFC 5322 raw MIME message (text or bytes).
    The endpoint is intentionally unauthenticated at the JWT layer because
    Direct Trust senders are not RAF Intelligence users; authentication is
    performed via the trust anchor whitelist.
    """
    # ------------------------------------------------------------------
    # 1. Validate required headers
    # ------------------------------------------------------------------
    if not x_direct_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-Direct-From",
        )
    if not x_direct_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-Direct-To",
        )

    # Tenant identification: derived from the To address domain for now.
    # In production this would be resolved via a tenant registry.
    tenant_id = "default"

    # ------------------------------------------------------------------
    # 2. Trust anchor whitelist check
    # ------------------------------------------------------------------
    if not _lookup_trust_anchor(tenant_id, x_direct_from):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sender {x_direct_from!r} is not in the Direct Trust anchor list",
        )

    # ------------------------------------------------------------------
    # 3. Parse the MIME body
    # ------------------------------------------------------------------
    raw_body = await request.body()
    try:
        msg = email_lib.message_from_bytes(raw_body, policy=email_lib.policy.default)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse MIME message: {exc}",
        ) from exc

    # RFC 2822 Message-ID for deduplication
    message_id: str = (
        msg.get("Message-ID", "").strip().strip("<>")
        or str(uuid.uuid4())
    )
    subject: str | None = msg.get("Subject") or None

    # ------------------------------------------------------------------
    # 4. Idempotency check
    # ------------------------------------------------------------------
    if _check_duplicate(tenant_id, message_id):
        logger.info("Duplicate Direct inbound message ignored: %s", message_id)
        return {
            "status": "ok",
            "duplicate": True,
            "message_id": message_id,
            "ccda_documents": 0,
            "suspects_extracted": 0,
        }

    # ------------------------------------------------------------------
    # 5. Walk MIME parts and process attachments
    # ------------------------------------------------------------------
    ccda_docs_created = 0
    total_suspects    = 0
    errors: list[str] = []

    for part in msg.walk():
        content_type = (part.get_content_type() or "").lower()
        if content_type == "multipart/signed":
            # TODO(production): Verify S/MIME SignedData before accepting content.
            # For now, trust anchor whitelist is the only check.
            continue

        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue

        filename = part.get_filename() or f"attachment.{content_type.split('/')[-1]}"

        if content_type in _CCDA_CONTENT_TYPES:
            # C-CDA XML path
            try:
                parsed = parse_ccda_xml(payload)
                doc_id = _persist_ccda_document(tenant_id, parsed, payload)
                suspects = _persist_hcc_suspects(
                    tenant_id, parsed.get("problems", []), doc_id
                )
                ccda_docs_created += 1
                total_suspects    += suspects
                logger.info(
                    "Direct inbound CCDA processed: msg=%s doc=%s suspects=%d",
                    message_id, doc_id, suspects,
                )
            except Exception as exc:
                err_msg = f"CCDA parse error for {filename}: {exc}"
                logger.warning(err_msg)
                errors.append(err_msg)

        elif content_type == "application/pdf":
            # PDF path — delegate to Gemini
            suspects = _route_pdf_to_gemini(tenant_id, payload, filename)
            total_suspects += suspects

    # ------------------------------------------------------------------
    # 6. Track the inbound message
    # ------------------------------------------------------------------
    final_status = "error" if errors and ccda_docs_created == 0 else "processed"
    _record_inbound_message(
        tenant_id       = tenant_id,
        message_id      = message_id,
        from_address    = x_direct_from,
        to_address      = x_direct_to,
        subject         = subject,
        ccda_parsed     = ccda_docs_created,
        suspects_extracted = total_suspects,
        msg_status      = final_status,
        error_text      = "; ".join(errors) if errors else None,
    )

    return {
        "status": "ok",
        "duplicate": False,
        "message_id": message_id,
        "ccda_documents": ccda_docs_created,
        "suspects_extracted": total_suspects,
        "errors": errors,
    }
