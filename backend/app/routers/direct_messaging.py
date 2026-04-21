"""
Direct Messaging router — secure provider-to-provider messaging via the
Direct Project protocol (S/MIME over SMTP).

Endpoints
---------
GET    /api/direct/dashboard              – Aggregate stats
GET    /api/direct/messages               – Inbox / sent with filters
POST   /api/direct/messages               – Compose and send
GET    /api/direct/messages/{id}          – Message detail with attachments
PUT    /api/direct/messages/{id}/read     – Mark as read
DELETE /api/direct/messages/{id}          – Delete message
GET    /api/direct/addresses              – Managed Direct addresses
POST   /api/direct/addresses              – Register new Direct address
PUT    /api/direct/addresses/{id}         – Update address record
GET    /api/direct/addresses/search       – Address book / directory search
GET    /api/direct/trust-anchors          – Trust bundles
POST   /api/direct/trust-anchors          – Add trust anchor

Authentication: all endpoints require a valid Bearer JWT.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id
from app.services.direct_messaging_service import (
    count_messages,
    create_direct_address,
    create_trust_anchor,
    delete_message,
    fetch_inbound_messages,
    get_dashboard_stats,
    get_direct_address,
    get_message,
    get_message_attachments,
    get_trust_anchor,
    list_direct_addresses,
    list_messages,
    list_trust_anchors,
    mark_message_read,
    search_address_book,
    send_direct_message,
    update_direct_address,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/direct", tags=["direct_messaging"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class AttachmentIn(BaseModel):
    """A single attachment included with an outbound message."""
    filename: str = Field(..., max_length=255, description="Attachment filename")
    content_type: str = Field(
        default="application/octet-stream",
        max_length=255,
        description="MIME content-type",
    )
    content_base64: str = Field(
        ...,
        description="Base64-encoded attachment content",
    )
    file_path: str | None = Field(
        default=None,
        description="Server-side staging path (optional, for large files pre-uploaded via /documents)",
    )


class SendMessageRequest(BaseModel):
    """Payload for composing and sending a Direct message."""
    from_address: str = Field(
        ...,
        max_length=255,
        description="Sender Direct address — must be registered in this tenant",
    )
    to_address: str = Field(
        ...,
        max_length=255,
        description="Recipient Direct address",
    )
    subject: str = Field(
        ...,
        max_length=500,
        description="Message subject line",
    )
    body: str = Field(
        ...,
        description="Plain-text message body",
    )
    patient_id: int | None = Field(
        default=None,
        description="OpenEMR patient ID to link this message to a patient record",
    )
    in_reply_to: str | None = Field(
        default=None,
        max_length=255,
        description="RFC 2822 Message-ID of the parent message when replying",
    )
    attachments: list[AttachmentIn] | None = Field(
        default=None,
        description="Optional list of attachments (C-CDA, PDF, etc.)",
    )

    @field_validator("from_address", "to_address")
    @classmethod
    def must_be_direct_address(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Must be a valid email-format Direct address")
        return v.lower().strip()


class RegisterAddressRequest(BaseModel):
    """Register a new Direct address for this tenant."""
    direct_address: str = Field(
        ...,
        max_length=255,
        description="Direct address to register, e.g. drsmith@direct.clinic.org",
    )
    display_name: str | None = Field(
        default=None,
        max_length=255,
        description="Friendly name shown in the address book",
    )
    provider_npi: str | None = Field(
        default=None,
        max_length=10,
        description="NPI of the associated provider",
    )
    trust_anchor_id: int | None = Field(
        default=None,
        description="ID of the trust anchor (CA) that will issue the certificate",
    )
    auto_generate_cert: bool = Field(
        default=True,
        description=(
            "When True (default) a self-signed certificate is generated automatically. "
            "Set to False when you will supply an externally-issued certificate."
        ),
    )

    @field_validator("direct_address")
    @classmethod
    def validate_direct_address(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Must be a valid email-format Direct address")
        return v.lower().strip()

    @field_validator("provider_npi")
    @classmethod
    def validate_npi(cls, v: str | None) -> str | None:
        if v is not None and (not v.isdigit() or len(v) != 10):
            raise ValueError("NPI must be exactly 10 digits")
        return v


class UpdateAddressRequest(BaseModel):
    """Fields that may be updated on an existing Direct address."""
    display_name: str | None = Field(default=None, max_length=255)
    provider_npi: str | None = Field(default=None, max_length=10)
    status: Literal["active", "inactive", "pending_verification"] | None = Field(default=None)
    trust_anchor_id: int | None = Field(default=None)
    certificate_pem: str | None = Field(
        default=None,
        description="Replace the end-entity certificate (PEM format)",
    )


class AddTrustAnchorRequest(BaseModel):
    """Register a trusted CA certificate."""
    name: str = Field(
        ...,
        max_length=255,
        description='Human-readable label, e.g. "DirectTrust Production Bundle"',
    )
    certificate_pem: str = Field(
        ...,
        description="PEM-encoded CA certificate",
    )
    organization: str | None = Field(default=None, max_length=255)
    trust_bundle_url: str | None = Field(
        default=None,
        max_length=512,
        description="URL to periodically fetch an updated PKCS#7 trust bundle",
    )

    @field_validator("certificate_pem")
    @classmethod
    def validate_pem(cls, v: str) -> str:
        if "BEGIN CERTIFICATE" not in v:
            raise ValueError("certificate_pem must be a PEM-encoded certificate")
        return v.strip()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _message_or_404(message_id: int, tenant_id: str) -> dict[str, Any]:
    """Load a message and enforce tenant ownership; raise 404 if not found."""
    msg = get_message(message_id)
    if not msg or str(msg.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )
    return msg


def _address_or_404(address_id: int, tenant_id: str) -> dict[str, Any]:
    """Load a Direct address and enforce tenant ownership; raise 404 if not found."""
    addr = get_direct_address(address_id)
    if not addr or str(addr.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Direct address not found.",
        )
    return addr


def _anchor_or_404(anchor_id: int, tenant_id: str) -> dict[str, Any]:
    """Load a trust anchor and enforce tenant ownership; raise 404 if not found."""
    anchor = get_trust_anchor(anchor_id)
    if not anchor or str(anchor.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trust anchor not found.",
        )
    return anchor


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    summary="Direct Messaging dashboard statistics",
)
def dashboard(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return aggregate counts for the Direct Messaging module:
    total messages, unread, failed, active addresses, trusted anchors,
    and SMTP/IMAP configuration status.
    """
    try:
        return get_dashboard_stats(tenant_id)
    except Exception as exc:
        logger.error("direct/dashboard error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard statistics.",
        )


# ---------------------------------------------------------------------------
# Messages — list and compose
# ---------------------------------------------------------------------------

@router.get(
    "/messages",
    summary="List Direct messages (inbox / sent)",
)
def list_direct_messages(
    direction: str | None = Query(
        default=None,
        description="Filter by direction: inbound or outbound",
    ),
    msg_status: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status: draft, queued, sent, delivered, failed, received, read",
    ),
    patient_id: int | None = Query(default=None, description="Filter by linked patient"),
    from_address: str | None = Query(default=None, description="Filter by sender address"),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return a paginated list of Direct messages for the current tenant.

    Use ``direction=inbound`` for the inbox and ``direction=outbound`` for
    the sent folder.  All filters are combinable.
    """
    _valid_directions = {"inbound", "outbound", None}
    _valid_statuses = {"draft", "queued", "sent", "delivered", "failed", "received", "read", None}

    if direction not in _valid_directions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="direction must be 'inbound' or 'outbound'",
        )
    if msg_status not in _valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be one of: draft, queued, sent, delivered, failed, received, read",
        )

    try:
        messages = list_messages(
            tenant_id=tenant_id,
            direction=direction,
            status=msg_status,
            patient_id=patient_id,
            from_address=from_address,
            limit=limit,
            offset=offset,
        )
        total = count_messages(
            tenant_id=tenant_id,
            direction=direction,
            status=msg_status,
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "messages": messages,
        }
    except Exception as exc:
        logger.error("direct/messages list error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve messages.",
        )


@router.post(
    "/messages",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Compose and send a Direct message",
)
def compose_message(
    body: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Compose, sign, encrypt, and queue a Direct message for delivery.

    The ``from_address`` must be a registered, active Direct address owned
    by this tenant.  The message is persisted immediately with
    ``status=queued`` and delivered asynchronously via the SMTP thread pool.

    If attachments are included they are base64-decoded and stored as
    ``direct_attachments`` rows.  C-CDA attachments are automatically routed
    to the C-CDA parsing pipeline.
    """
    import base64

    # Decode attachment content from base64
    decoded_attachments: list[dict[str, Any]] | None = None
    if body.attachments:
        decoded_attachments = []
        for att in body.attachments:
            try:
                content = base64.b64decode(att.content_base64)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid base64 content for attachment '{att.filename}'",
                )
            decoded_attachments.append({
                "filename": att.filename,
                "content_type": att.content_type,
                "content": content,
                "file_path": att.file_path,
            })

    try:
        result = send_direct_message(
            tenant_id=tenant_id,
            from_address=body.from_address,
            to_address=body.to_address,
            subject=body.subject,
            body=body.body,
            patient_id=body.patient_id,
            in_reply_to=body.in_reply_to,
            attachments=decoded_attachments,
        )
        logger.info(
            "direct/messages: queued message %d from %s to %s (user=%s)",
            result["id"], body.from_address, body.to_address, current_user.get("id"),
        )
        return result
    except PermissionError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request"
        )
    except Exception as exc:
        logger.error("direct/messages compose error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send message.",
        )


# ---------------------------------------------------------------------------
# Messages — detail, read, delete
# ---------------------------------------------------------------------------

@router.get(
    "/messages/{message_id}",
    summary="Get Direct message detail",
)
def get_message_detail(
    message_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return full message details including body, status history timestamps,
    and attachment metadata.  The raw attachment content is not included in
    this response; it must be retrieved separately if needed.
    """
    msg = _message_or_404(message_id, tenant_id)
    attachments = get_message_attachments(message_id)
    return {**msg, "attachments": attachments}


@router.put(
    "/messages/{message_id}/read",
    summary="Mark a Direct message as read",
)
def mark_read(
    message_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Mark an inbound message as read.  Sets ``status=read`` and records
    the ``read_at`` timestamp.  Returns the updated message.

    Only ``received`` or ``delivered`` messages can be marked as read.
    """
    _message_or_404(message_id, tenant_id)
    updated = mark_message_read(message_id, tenant_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Message could not be marked as read. It may already be read or not in a receivable state.",
        )
    msg = get_message(message_id)
    return msg


@router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a Direct message",
)
def delete_direct_message(
    message_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> None:
    """
    Permanently delete a Direct message and all associated attachments.
    This action is irreversible.
    """
    _message_or_404(message_id, tenant_id)
    success = delete_message(message_id, tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete message.",
        )
    logger.info(
        "direct/messages: deleted message %d (user=%s, tenant=%s)",
        message_id, current_user.get("id"), tenant_id,
    )


# ---------------------------------------------------------------------------
# Direct addresses
# ---------------------------------------------------------------------------

@router.get(
    "/addresses",
    summary="List managed Direct addresses",
)
def list_addresses(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return all Direct addresses registered for the current tenant.

    Private keys are never included in the response.
    """
    try:
        addresses = list_direct_addresses(tenant_id)
        return {"total": len(addresses), "addresses": addresses}
    except Exception as exc:
        logger.error("direct/addresses list error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve addresses.",
        )


@router.get(
    "/addresses/search",
    summary="Search the Direct address book",
)
def address_book_search(
    q: str = Query(..., min_length=2, description="Search term (address or display name)"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Search the local Direct address book for addresses matching *q*.

    Returns active addresses only.  In production this endpoint should also
    query the DirectTrust Certificate Discovery Service for cross-HISP lookups.
    """
    try:
        results = search_address_book(q, tenant_id, limit=limit)
        return {"query": q, "total": len(results), "results": results}
    except Exception as exc:
        logger.error("direct/addresses search error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Address search failed.",
        )


@router.post(
    "/addresses",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new Direct address",
)
def register_address(
    body: RegisterAddressRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Register a new Direct address for this tenant.

    By default (``auto_generate_cert=true``) a self-signed X.509 certificate
    and RSA-2048 private key are generated automatically.  The address is
    created with ``status=pending_verification`` until domain ownership can
    be confirmed (manually or via DNS challenge).

    For production deployments, obtain a certificate from a DirectTrust-
    accredited CA such as Surescripts or Drummond Group and upload it via
    ``PUT /api/direct/addresses/{id}``.
    """
    user_id: int = current_user["id"]

    try:
        new_id = create_direct_address(
            tenant_id=tenant_id,
            user_id=user_id,
            direct_address=body.direct_address,
            display_name=body.display_name,
            provider_npi=body.provider_npi,
            trust_anchor_id=body.trust_anchor_id,
            auto_generate_cert=body.auto_generate_cert,
        )
    except Exception as exc:
        # Duplicate key → 409
        if "Duplicate" in str(exc) or "1062" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Direct address '{body.direct_address}' is already registered.",
            )
        logger.error("direct/addresses register error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register Direct address.",
        )

    logger.info(
        "direct/addresses: registered %s (id=%d, user=%s, tenant=%s)",
        body.direct_address, new_id, user_id, tenant_id,
    )

    addr = get_direct_address(new_id)
    # Strip private key from response
    if addr:
        addr.pop("private_key_encrypted", None)
    return addr or {"id": new_id}


@router.put(
    "/addresses/{address_id}",
    summary="Update a Direct address",
)
def update_address(
    address_id: int,
    body: UpdateAddressRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Update mutable fields on a registered Direct address.

    Use this endpoint to:
    - Activate or deactivate an address (``status`` field).
    - Upload an externally-issued certificate (``certificate_pem`` field).
    - Update the display name or linked NPI.
    """
    _address_or_404(address_id, tenant_id)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update.",
        )

    try:
        success = update_direct_address(address_id, tenant_id, **updates)
    except Exception as exc:
        logger.error("direct/addresses update error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update address.",
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update had no effect.",
        )

    addr = get_direct_address(address_id)
    if addr:
        addr.pop("private_key_encrypted", None)
    return addr or {"id": address_id}


# ---------------------------------------------------------------------------
# Trust anchors
# ---------------------------------------------------------------------------

@router.get(
    "/trust-anchors",
    summary="List Direct trust anchors",
)
def list_anchors(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return all trust anchors (CA certificates) registered for this tenant.

    Trust anchors are used to validate the certificates of inbound message
    senders.  The DirectTrust national trust bundle covers the majority of
    US healthcare organisations; individual bilateral trust agreements may
    require additional anchors.
    """
    try:
        anchors = list_trust_anchors(tenant_id)
        return {"total": len(anchors), "trust_anchors": anchors}
    except Exception as exc:
        logger.error("direct/trust-anchors list error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve trust anchors.",
        )


@router.post(
    "/trust-anchors",
    status_code=status.HTTP_201_CREATED,
    summary="Add a Direct trust anchor",
)
def add_trust_anchor(
    body: AddTrustAnchorRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Register a new trust anchor (CA certificate) for this tenant.

    The certificate must be PEM-encoded.  If a ``trust_bundle_url`` is
    provided the system can periodically refresh the anchor from that URL
    (refresh scheduling is outside this endpoint's scope).

    Certificate validity (expiry) is automatically extracted from the
    PEM data and stored in ``expires_at``.
    """
    try:
        new_id = create_trust_anchor(
            tenant_id=tenant_id,
            name=body.name,
            certificate_pem=body.certificate_pem,
            organization=body.organization,
            trust_bundle_url=body.trust_bundle_url,
        )
    except Exception as exc:
        logger.error("direct/trust-anchors add error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add trust anchor.",
        )

    logger.info(
        "direct/trust-anchors: added '%s' (id=%d, user=%s, tenant=%s)",
        body.name, new_id, current_user.get("id"), tenant_id,
    )

    anchor = get_trust_anchor(new_id)
    return anchor or {"id": new_id}


# ---------------------------------------------------------------------------
# Inbound fetch (manual trigger — useful for testing / on-demand pull)
# ---------------------------------------------------------------------------

@router.post(
    "/messages/fetch-inbound",
    status_code=status.HTTP_200_OK,
    summary="Manually trigger inbound message fetch from IMAP",
)
def trigger_inbound_fetch(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Poll the configured IMAP mailbox for unread Direct messages and import
    them into the platform.

    In production this should run on a scheduled interval (every 5 minutes
    is typical for Direct).  This endpoint allows on-demand triggering for
    testing and operational troubleshooting.

    Returns the list of newly imported message summaries.
    """
    try:
        new_messages = fetch_inbound_messages(tenant_id)
        return {
            "fetched": len(new_messages),
            "messages": new_messages,
        }
    except Exception as exc:
        logger.error("direct/fetch-inbound error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Inbound fetch failed.",
        )
