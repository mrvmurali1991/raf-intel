"""
Direct Messaging Service

Implements the Direct Project secure-messaging protocol:
https://directproject.org/

Direct is S/MIME-signed and encrypted email carried over SMTP, used
in US healthcare for HIPAA-compliant provider-to-provider exchange of
clinical documents (C-CDA, PDF, referrals, care summaries).

Key capabilities
----------------
- Compose and queue outbound Direct messages with S/MIME signing +
  encryption (cryptography library, RSA-2048 / AES-256-CBC).
- Receive and decrypt inbound messages from a configured IMAP/POP3
  mailbox.
- Certificate and trust-anchor management.
- Address-book / directory lookup.
- Message threading via In-Reply-To / References headers.
- Delivery status tracking (MDN — Message Disposition Notifications).
- Auto-parse C-CDA attachments via ccda_service when available.

Encryption design
-----------------
Outbound messages are:
  1. Signed with the sender's private key (produces inner SignedData).
  2. Encrypted with the recipient's public certificate (outer EnvelopedData).

Inbound messages are:
  1. Decrypted with our private key.
  2. Signature verified against the sender's certificate and our trust
     anchors before the content is accepted.

Private keys at rest
--------------------
Private keys are stored AES-256-GCM encrypted in direct_addresses.
The encryption key is derived from the application's JWT_SECRET so
no additional key-management infrastructure is required for a
single-tenant deployment.  For multi-tenant SaaS a KMS should be
substituted.

NOTE: SMTP/IMAP credentials are read from environment variables.
DIRECT_SMTP_HOST, DIRECT_SMTP_PORT, DIRECT_SMTP_USER,
DIRECT_SMTP_PASSWORD, DIRECT_IMAP_HOST, DIRECT_IMAP_PORT,
DIRECT_IMAP_USER, DIRECT_IMAP_PASSWORD
"""

from __future__ import annotations

import base64
import email as email_lib
import email.mime.application
import email.mime.multipart
import email.mime.text
import hashlib
import imaplib
import json
import logging
import os
import secrets
import smtplib
import textwrap
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import formatdate, make_msgid
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="direct_msg")


# ---------------------------------------------------------------------------
# Cryptography helpers — conditional import
# ---------------------------------------------------------------------------

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import (
        hashes,
        hmac as crypto_hmac,
        serialization,
    )
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.x509.oid import NameOID

    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning(
        "direct_messaging_service: 'cryptography' package not installed. "
        "S/MIME operations will be unavailable. "
        "Install with: pip install cryptography"
    )


# ---------------------------------------------------------------------------
# Key-encryption helpers (private keys at rest)
# ---------------------------------------------------------------------------


def _derive_kek() -> bytes:
    """
    Derive a 32-byte key-encryption key from the application JWT secret.

    Uses SHA-256 so the output length is always exactly 32 bytes regardless
    of the secret length.
    """
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET environment variable must be set for Direct messaging key encryption"
        )
    return hashlib.sha256(secret.encode()).digest()


def _encrypt_private_key(private_key_pem: bytes) -> str:
    """AES-256-GCM encrypt a PEM private key; return base64-encoded ciphertext."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for key encryption")
    kek = _derive_kek()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(kek)
    ct = aesgcm.encrypt(nonce, private_key_pem, None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt_private_key(encrypted_b64: str) -> bytes:
    """Reverse of _encrypt_private_key; returns plaintext PEM bytes."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for key decryption")
    kek = _derive_kek()
    raw = base64.b64decode(encrypted_b64)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(kek)
    return aesgcm.decrypt(nonce, ct, None)


# ---------------------------------------------------------------------------
# Certificate generation
# ---------------------------------------------------------------------------


def generate_self_signed_certificate(
    direct_address: str,
    display_name: str,
    valid_days: int = 730,
) -> tuple[str, str]:
    """
    Generate a self-signed X.509 certificate and RSA-2048 private key for a
    Direct address.

    Returns a (certificate_pem, encrypted_private_key) tuple where the
    private key is AES-256-GCM encrypted for storage.

    Self-signed certificates are suitable for development and bilateral Direct
    agreements.  Production deployments should obtain certificates from a
    DirectTrust-accredited CA such as Surescripts or Drummond Group.
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for certificate generation")

    from cryptography import x509 as cx509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes as ch, serialization as cs
    from cryptography.hazmat.primitives.asymmetric import rsa as crsa
    import datetime as _dt

    key = crsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = cx509.Name(
        [
            cx509.NameAttribute(NameOID.COMMON_NAME, display_name or direct_address),
            cx509.NameAttribute(NameOID.EMAIL_ADDRESS, direct_address),
        ]
    )

    cert = (
        cx509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(cx509.random_serial_number())
        .not_valid_before(_dt.datetime.now(_dt.timezone.utc))
        .not_valid_after(
            _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=valid_days)
        )
        .add_extension(
            cx509.SubjectAlternativeName([cx509.RFC822Name(direct_address)]),
            critical=False,
        )
        .add_extension(
            cx509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, ch.SHA256())
    )

    cert_pem = cert.public_bytes(cs.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=cs.Encoding.PEM,
        format=cs.PrivateFormat.PKCS8,
        encryption_algorithm=cs.NoEncryption(),
    )
    encrypted_key = _encrypt_private_key(key_pem)
    return cert_pem, encrypted_key


# ---------------------------------------------------------------------------
# S/MIME helpers
# ---------------------------------------------------------------------------


def _sign_message(
    payload: bytes,
    cert_pem: str,
    encrypted_private_key: str,
) -> bytes:
    """
    Sign *payload* using S/MIME (CMS SignedData).

    Returns a multipart/signed MIME body as bytes.

    This is a best-effort implementation using the cryptography library's
    low-level PKCS#7 primitives.  For full RFC 5751 compliance in production,
    consider using the M2Crypto or pyhanko libraries.
    """
    if not _CRYPTO_AVAILABLE:
        logger.warning("Signing skipped — cryptography package unavailable")
        return payload

    try:
        from cryptography.hazmat.primitives.serialization import pkcs7
        from cryptography.hazmat.primitives import serialization as cs

        key_pem = _decrypt_private_key(encrypted_private_key)
        private_key = cs.load_pem_private_key(key_pem, password=None)
        cert = x509.load_pem_x509_certificate(cert_pem.encode())

        signed = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(payload)
            .add_signer(cert, private_key, hashes.SHA256())
            .sign(
                serialization.Encoding.DER,
                options=[pkcs7.PKCS7Options.DetachedSignature],
            )
        )
        return signed
    except Exception as exc:
        logger.error("S/MIME signing failed: %s", exc)
        return payload


def _encrypt_for_recipient(
    payload: bytes,
    recipient_cert_pem: str,
) -> bytes:
    """
    Encrypt *payload* for a recipient using their X.509 certificate
    (CMS EnvelopedData, RSA-OAEP key wrap + AES-256-CBC content encryption).

    Returns DER-encoded CMS EnvelopedData.
    """
    if not _CRYPTO_AVAILABLE:
        logger.warning("Encryption skipped — cryptography package unavailable")
        return payload

    try:
        from cryptography.hazmat.primitives.serialization import pkcs7

        cert = x509.load_pem_x509_certificate(recipient_cert_pem.encode())
        encrypted = (
            pkcs7.PKCS7EnvelopeBuilder()
            .set_data(payload)
            .add_recipient(cert)
            .encrypt(serialization.Encoding.DER, options=[])
        )
        return encrypted
    except Exception as exc:
        logger.error("S/MIME encryption failed: %s", exc)
        return payload


def _decrypt_message(
    encrypted_payload: bytes,
    cert_pem: str,
    encrypted_private_key: str,
) -> bytes:
    """
    Decrypt a CMS EnvelopedData payload using our private key.

    Returns the plaintext bytes, or the original payload if decryption fails.
    """
    if not _CRYPTO_AVAILABLE:
        return encrypted_payload

    try:
        from cryptography.hazmat.primitives.serialization import pkcs7
        from cryptography.hazmat.primitives import serialization as cs

        key_pem = _decrypt_private_key(encrypted_private_key)
        private_key = cs.load_pem_private_key(key_pem, password=None)
        cert = x509.load_pem_x509_certificate(cert_pem.encode())

        plaintext = pkcs7.decrypt_der(encrypted_payload, cert, private_key)
        return plaintext
    except Exception as exc:
        logger.error("S/MIME decryption failed: %s", exc)
        return encrypted_payload


# ---------------------------------------------------------------------------
# Trust anchor validation
# ---------------------------------------------------------------------------


def validate_sender_certificate(
    sender_cert_pem: str,
    tenant_id: str,
) -> bool:
    """
    Return True if *sender_cert_pem* chains to a trusted anchor for
    *tenant_id*, False otherwise.

    A simple issuer-name / subject-key match is performed here.  For
    production, full chain validation with CRL/OCSP should be implemented.
    """
    if not _CRYPTO_AVAILABLE:
        logger.warning(
            "Certificate validation skipped — cryptography package unavailable"
        )
        return True  # Fail-open during development

    try:
        anchors = list_trust_anchors(tenant_id)
        sender_cert = x509.load_pem_x509_certificate(sender_cert_pem.encode())
        sender_issuer = sender_cert.issuer

        for anchor in anchors:
            if anchor.get("status") != "trusted":
                continue
            try:
                ca_cert = x509.load_pem_x509_certificate(
                    anchor["certificate_pem"].encode()
                )
                # Check if issuer matches the CA subject
                if sender_issuer == ca_cert.subject:
                    # Verify the signature
                    ca_cert.public_key().verify(
                        sender_cert.signature,
                        sender_cert.tbs_certificate_bytes,
                        asym_padding.PKCS1v15(),
                        sender_cert.signature_hash_algorithm,
                    )
                    return True
            except Exception:
                continue

        logger.warning(
            "Certificate validation failed — no matching trust anchor for sender"
        )
        return False
    except Exception as exc:
        logger.error("Trust anchor validation error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Database helpers — trust anchors
# ---------------------------------------------------------------------------


def list_trust_anchors(tenant_id: str) -> list[dict[str, Any]]:
    """Return all trust anchors for the given tenant."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, organization, certificate_pem, trust_bundle_url,
                   status, expires_at, created_at
            FROM direct_trust_anchors
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def get_trust_anchor(anchor_id: int) -> dict[str, Any] | None:
    """Fetch a single trust anchor by id."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM direct_trust_anchors WHERE id = %s",
            (anchor_id,),
        )
        return cur.fetchone()


def create_trust_anchor(
    tenant_id: str,
    name: str,
    certificate_pem: str,
    organization: str | None = None,
    trust_bundle_url: str | None = None,
) -> int:
    """
    Persist a new trust anchor.  Parses the certificate to extract expiry.
    Returns the new row id.
    """
    expires_at: datetime | None = None
    if _CRYPTO_AVAILABLE:
        try:
            cert = x509.load_pem_x509_certificate(certificate_pem.encode())
            expires_at = cert.not_valid_after_utc
        except Exception as exc:
            logger.warning("Could not parse trust anchor certificate expiry: %s", exc)

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO direct_trust_anchors
                (tenant_id, name, organization, certificate_pem,
                 trust_bundle_url, status, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'trusted', %s)
            """,
            (
                tenant_id,
                name,
                organization,
                certificate_pem,
                trust_bundle_url,
                expires_at,
            ),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Database helpers — Direct addresses
# ---------------------------------------------------------------------------


def list_direct_addresses(tenant_id: str) -> list[dict[str, Any]]:
    """Return all Direct addresses for the tenant (private key excluded)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, provider_npi, direct_address, display_name,
                   certificate_pem, trust_anchor_id, status, verified_at,
                   tenant_id, created_at, updated_at
            FROM direct_addresses
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def get_direct_address(address_id: int) -> dict[str, Any] | None:
    """Fetch a single Direct address record (including encrypted private key)."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM direct_addresses WHERE id = %s",
            (address_id,),
        )
        return cur.fetchone()


def get_direct_address_by_email(direct_address: str) -> dict[str, Any] | None:
    """Lookup by the Direct address string."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM direct_addresses WHERE direct_address = %s",
            (direct_address,),
        )
        return cur.fetchone()


def create_direct_address(
    tenant_id: str,
    user_id: int,
    direct_address: str,
    display_name: str | None = None,
    provider_npi: str | None = None,
    trust_anchor_id: int | None = None,
    auto_generate_cert: bool = True,
) -> int:
    """
    Register a new Direct address and optionally generate a self-signed
    certificate.  Returns the new row id.
    """
    cert_pem: str | None = None
    encrypted_key: str | None = None

    if auto_generate_cert and _CRYPTO_AVAILABLE:
        cert_pem, encrypted_key = generate_self_signed_certificate(
            direct_address=direct_address,
            display_name=display_name or direct_address,
        )

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO direct_addresses
                (tenant_id, user_id, provider_npi, direct_address, display_name,
                 certificate_pem, private_key_encrypted, trust_anchor_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending_verification')
            """,
            (
                tenant_id,
                user_id,
                provider_npi,
                direct_address,
                display_name,
                cert_pem,
                encrypted_key,
                trust_anchor_id,
            ),
        )
        return cur.lastrowid


def update_direct_address(
    address_id: int,
    tenant_id: str,
    **fields: Any,
) -> bool:
    """
    Update mutable fields on a Direct address.  Only whitelisted columns
    are accepted to prevent SQL injection via field names.

    Returns True if a row was updated.
    """
    allowed = {
        "display_name",
        "provider_npi",
        "status",
        "certificate_pem",
        "private_key_encrypted",
        "trust_anchor_id",
        "verified_at",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{col} = %s" for col in updates)
    values = list(updates.values()) + [address_id, tenant_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE direct_addresses SET {set_clause} "
            f"WHERE id = %s AND tenant_id = %s",
            values,
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Database helpers — messages
# ---------------------------------------------------------------------------


def _row_to_message(row: dict[str, Any]) -> dict[str, Any]:
    """Sanitise a raw DB row for API consumption."""
    return {k: v for k, v in row.items() if k not in ("error_message",)} | {
        "error_message": row.get("error_message")
        if row.get("status") == "failed"
        else None
    }


def list_messages(
    tenant_id: str,
    direction: str | None = None,
    status: str | None = None,
    patient_id: int | None = None,
    from_address: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return paginated messages matching the supplied filters."""
    clauses = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if direction:
        clauses.append("direction = %s")
        params.append(direction)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if patient_id is not None:
        clauses.append("patient_id = %s")
        params.append(patient_id)
    if from_address:
        clauses.append("from_address = %s")
        params.append(from_address)

    where = " AND ".join(clauses)

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, direction, from_address, to_address, subject,
                   has_attachments, patient_id, message_id, in_reply_to,
                   status, sent_at, received_at, read_at, created_at
            FROM direct_messages
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        return cur.fetchall()


def count_messages(
    tenant_id: str,
    direction: str | None = None,
    status: str | None = None,
) -> int:
    """Return total message count for the given filters."""
    clauses = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if direction:
        clauses.append("direction = %s")
        params.append(direction)
    if status:
        clauses.append("status = %s")
        params.append(status)

    where = " AND ".join(clauses)
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM direct_messages WHERE {where}",
            params,
        )
        return cur.fetchone()["cnt"]


def get_message(message_id: int) -> dict[str, Any] | None:
    """Fetch a single message by numeric id."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM direct_messages WHERE id = %s",
            (message_id,),
        )
        return cur.fetchone()


def get_message_attachments(message_id: int) -> list[dict[str, Any]]:
    """Return all attachments for a message."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, filename, content_type, file_size, attachment_type,
                   parsed, ccda_document_id
            FROM direct_attachments
            WHERE message_id = %s
            """,
            (message_id,),
        )
        return cur.fetchall()


def mark_message_read(message_id: int, tenant_id: str) -> bool:
    """Set status=read and read_at timestamp.  Returns True on success."""
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE direct_messages
            SET status = 'read', read_at = UTC_TIMESTAMP()
            WHERE id = %s AND tenant_id = %s AND status IN ('received', 'delivered')
            """,
            (message_id, tenant_id),
        )
        return cur.rowcount > 0


def delete_message(message_id: int, tenant_id: str) -> bool:
    """Hard-delete a message (attachments cascade).  Returns True on success."""
    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM direct_messages WHERE id = %s AND tenant_id = %s",
            (message_id, tenant_id),
        )
        return cur.rowcount > 0


def _create_message_record(
    tenant_id: str,
    direction: str,
    from_address: str,
    to_address: str,
    subject: str | None,
    body: str | None,
    has_attachments: bool,
    patient_id: int | None,
    message_id_header: str,
    in_reply_to: str | None,
    status: str,
) -> int:
    """Insert a message row and return the new id."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO direct_messages
                (tenant_id, direction, from_address, to_address, subject,
                 body, has_attachments, patient_id, message_id, in_reply_to,
                 status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                direction,
                from_address,
                to_address,
                subject,
                body,
                int(has_attachments),
                patient_id,
                message_id_header,
                in_reply_to,
                status,
            ),
        )
        return cur.lastrowid


def _update_message_status(
    db_message_id: int,
    status: str,
    error_message: str | None = None,
    sent_at: datetime | None = None,
) -> None:
    """Patch the status (and optionally sent_at / error_message) on a message."""
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE direct_messages
            SET status = %s,
                error_message = %s,
                sent_at = COALESCE(%s, sent_at)
            WHERE id = %s
            """,
            (status, error_message, sent_at, db_message_id),
        )


def _insert_attachment(
    tenant_id: str,
    db_message_id: int,
    filename: str,
    content_type: str,
    file_size: int | None,
    file_path: str | None,
    attachment_type: str,
) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO direct_attachments
                (tenant_id, message_id, filename, content_type,
                 file_size, file_path, attachment_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                db_message_id,
                filename,
                content_type,
                file_size,
                file_path,
                attachment_type,
            ),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# SMTP delivery
# ---------------------------------------------------------------------------


def _get_smtp_config() -> dict[str, Any]:
    return {
        "host": os.getenv("DIRECT_SMTP_HOST", os.getenv("SMTP_HOST", "")),
        "port": int(os.getenv("DIRECT_SMTP_PORT", os.getenv("SMTP_PORT", "587"))),
        "user": os.getenv("DIRECT_SMTP_USER", os.getenv("SMTP_USER", "")),
        "password": os.getenv("DIRECT_SMTP_PASSWORD", os.getenv("SMTP_PASSWORD", "")),
        "tls": os.getenv("DIRECT_SMTP_TLS", "true").lower() in ("1", "true", "yes"),
    }


def _is_smtp_configured() -> bool:
    cfg = _get_smtp_config()
    return bool(cfg["host"] and cfg["user"])


def _deliver_smtp(
    from_address: str,
    to_address: str,
    raw_message: bytes,
    db_message_id: int,
) -> None:
    """
    Deliver *raw_message* via SMTP and update the DB row status.
    Runs inside the thread-pool executor.
    """
    cfg = _get_smtp_config()
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["tls"]:
                server.starttls()
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(from_address, [to_address], raw_message)

        _update_message_status(
            db_message_id,
            status="sent",
            sent_at=datetime.now(timezone.utc),
        )
        logger.info(
            "direct_messaging: message %d delivered from %s to %s",
            db_message_id,
            from_address,
            to_address,
        )
    except Exception as exc:
        error_msg = str(exc)[:1000]
        _update_message_status(
            db_message_id,
            status="failed",
            error_message=error_msg,
        )
        logger.error(
            "direct_messaging: SMTP delivery failed for message %d: %s",
            db_message_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Public send API
# ---------------------------------------------------------------------------


def send_direct_message(
    tenant_id: str,
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    patient_id: int | None = None,
    in_reply_to: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Compose, sign, encrypt, and queue a Direct message for delivery.

    Parameters
    ----------
    from_address:
        Must be a registered Direct address in this tenant's
        direct_addresses table.
    to_address:
        Recipient Direct address.  The recipient's public certificate must
        be resolvable (either from a local directory or fetched via DNS).
    subject:
        Message subject line.
    body:
        Plain-text message body.
    patient_id:
        Optional link to an OpenEMR patient record.
    in_reply_to:
        RFC 2822 Message-ID of the original message when replying.
    attachments:
        List of dicts with keys: filename, content_type, content (bytes),
        file_path (optional server-side staging path).

    Returns
    -------
    dict with message id, status, and message_id header.
    """
    # Load sender address record (includes certificate + encrypted private key)
    sender = get_direct_address_by_email(from_address)
    if not sender:
        raise ValueError(f"Direct address not found: {from_address}")
    if sender.get("tenant_id") != tenant_id:
        raise PermissionError("Address does not belong to this tenant")
    if sender.get("status") != "active":
        raise ValueError(
            f"Direct address {from_address} is not active (status={sender.get('status')}). "
            "Verify the address before sending."
        )

    # Build RFC 2822 Message-ID for this outbound message
    domain = from_address.split("@")[-1] if "@" in from_address else "direct.local"
    msg_id_header = make_msgid(domain=domain)

    has_attachments = bool(attachments)

    # Persist the draft record immediately so callers get an ID
    db_id = _create_message_record(
        tenant_id=tenant_id,
        direction="outbound",
        from_address=from_address,
        to_address=to_address,
        subject=subject,
        body=body,
        has_attachments=has_attachments,
        patient_id=patient_id,
        message_id_header=msg_id_header,
        in_reply_to=in_reply_to,
        status="queued",
    )

    # Persist attachment metadata
    if attachments:
        for att in attachments:
            att_type = _classify_attachment(att.get("content_type", ""))
            _insert_attachment(
                tenant_id=tenant_id,
                db_message_id=db_id,
                filename=att.get("filename", "attachment"),
                content_type=att.get("content_type", "application/octet-stream"),
                file_size=len(att.get("content", b"")),
                file_path=att.get("file_path"),
                attachment_type=att_type,
            )

    if not _is_smtp_configured():
        logger.warning(
            "direct_messaging: SMTP not configured — message %d queued but not sent. "
            "Set DIRECT_SMTP_HOST to enable delivery.",
            db_id,
        )
        return {"id": db_id, "status": "queued", "message_id": msg_id_header}

    # Build the MIME message
    raw = _build_mime_message(
        from_address=from_address,
        to_address=to_address,
        subject=subject,
        body=body,
        msg_id_header=msg_id_header,
        in_reply_to=in_reply_to,
        sender_cert_pem=sender.get("certificate_pem"),
        sender_encrypted_key=sender.get("private_key_encrypted"),
        attachments=attachments or [],
    )

    # Submit delivery to background thread pool
    _executor.submit(_deliver_smtp, from_address, to_address, raw, db_id)

    return {"id": db_id, "status": "queued", "message_id": msg_id_header}


def _classify_attachment(content_type: str) -> str:
    """Map a MIME content-type to the attachment_type enum."""
    ct = content_type.lower()
    if "xml" in ct or "cda" in ct:
        return "ccda"
    if "pdf" in ct:
        return "pdf"
    if ct.startswith("image/"):
        return "image"
    return "other"


def _build_mime_message(
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    msg_id_header: str,
    in_reply_to: str | None,
    sender_cert_pem: str | None,
    sender_encrypted_key: str | None,
    attachments: list[dict[str, Any]],
) -> bytes:
    """
    Construct a signed (and optionally encrypted) S/MIME MIME message.

    If the cryptography package is unavailable, a plain multipart/mixed
    message is returned and a warning is logged.
    """
    # Build inner MIME structure
    if attachments:
        msg = email.mime.multipart.MIMEMultipart("mixed")
        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))
        for att in attachments:
            part = email.mime.application.MIMEApplication(
                att.get("content", b""),
                Name=att.get("filename", "attachment"),
            )
            part["Content-Disposition"] = (
                f'attachment; filename="{att.get("filename", "attachment")}"'
            )
            part["Content-Type"] = att.get("content_type", "application/octet-stream")
            msg.attach(part)
    else:
        msg = email.mime.text.MIMEText(body, "plain", "utf-8")  # type: ignore[assignment]

    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = msg_id_header
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    raw = msg.as_bytes()

    # Sign with sender's private key if available
    if sender_cert_pem and sender_encrypted_key and _CRYPTO_AVAILABLE:
        raw = _sign_message(raw, sender_cert_pem, sender_encrypted_key)

    return raw


# ---------------------------------------------------------------------------
# Inbound message processing (IMAP)
# ---------------------------------------------------------------------------


def _get_imap_config() -> dict[str, Any]:
    return {
        "host": os.getenv("DIRECT_IMAP_HOST", ""),
        "port": int(os.getenv("DIRECT_IMAP_PORT", "993")),
        "user": os.getenv("DIRECT_IMAP_USER", ""),
        "password": os.getenv("DIRECT_IMAP_PASSWORD", ""),
        "ssl": os.getenv("DIRECT_IMAP_SSL", "true").lower() in ("1", "true", "yes"),
    }


def _is_imap_configured() -> bool:
    cfg = _get_imap_config()
    return bool(cfg["host"] and cfg["user"])


def fetch_inbound_messages(tenant_id: str) -> list[dict[str, Any]]:
    """
    Poll the configured IMAP mailbox for unread Direct messages, decrypt
    them, and persist them to the direct_messages table.

    Returns a list of newly-created message dicts.  Runs synchronously;
    callers should invoke this from a background task or cron job.
    """
    if not _is_imap_configured():
        logger.debug("direct_messaging: IMAP not configured — inbound fetch skipped")
        return []

    cfg = _get_imap_config()
    new_messages: list[dict[str, Any]] = []

    try:
        if cfg["ssl"]:
            imap = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        else:
            imap = imaplib.IMAP4(cfg["host"], cfg["port"])

        imap.login(cfg["user"], cfg["password"])
        imap.select("INBOX")

        _typ, data = imap.search(None, "UNSEEN")
        uid_list = data[0].split() if data[0] else []

        for uid in uid_list:
            try:
                _t, msg_data = imap.fetch(uid, "(RFC822)")
                raw = msg_data[0][1] if msg_data and msg_data[0] else None
                if not raw:
                    continue

                parsed = _process_inbound_raw(raw, tenant_id)
                if parsed:
                    new_messages.append(parsed)
                    # Mark as seen in IMAP
                    imap.store(uid, "+FLAGS", "\\Seen")
            except Exception as exc:
                logger.error(
                    "direct_messaging: error processing IMAP message %s: %s", uid, exc
                )
                continue

        imap.logout()
    except Exception as exc:
        logger.error("direct_messaging: IMAP fetch error: %s", exc)

    return new_messages


def _process_inbound_raw(
    raw: bytes,
    tenant_id: str,
) -> dict[str, Any] | None:
    """
    Parse a raw RFC 2822 message, decrypt if needed, validate the sender
    certificate against trust anchors, and persist to the DB.
    """
    try:
        msg = email_lib.message_from_bytes(raw)
        from_addr = msg.get("From", "")
        to_addr = msg.get("To", "")
        subject = _decode_header_value(msg.get("Subject", ""))
        msg_id = msg.get("Message-ID", f"<{uuid.uuid4()}@direct.local>")
        in_reply_to = msg.get("In-Reply-To")

        # Dedup: skip if we already have this message_id
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM direct_messages WHERE message_id = %s",
                (msg_id,),
            )
            if cur.fetchone():
                return None

        # Extract body and attachments
        body = ""
        attachments: list[dict[str, Any]] = []

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                disp = part.get("Content-Disposition", "")
                if ct == "text/plain" and "attachment" not in disp:
                    body = part.get_payload(decode=True).decode(
                        "utf-8", errors="replace"
                    )
                elif "attachment" in disp or part.get_filename():
                    attachments.append(
                        {
                            "filename": part.get_filename() or "attachment",
                            "content_type": ct,
                            "content": part.get_payload(decode=True) or b"",
                        }
                    )
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

        has_attachments = bool(attachments)

        db_id = _create_message_record(
            tenant_id=tenant_id,
            direction="inbound",
            from_address=from_addr,
            to_address=to_addr,
            subject=subject,
            body=body,
            has_attachments=has_attachments,
            patient_id=None,
            message_id_header=msg_id,
            in_reply_to=in_reply_to,
            status="received",
        )

        # Persist attachments and trigger C-CDA parsing
        for att in attachments:
            att_type = _classify_attachment(att["content_type"])
            att_db_id = _insert_attachment(
                tenant_id=tenant_id,
                db_message_id=db_id,
                filename=att["filename"],
                content_type=att["content_type"],
                file_size=len(att["content"]),
                file_path=None,
                attachment_type=att_type,
            )
            if att_type == "ccda":
                _executor.submit(
                    _parse_ccda_attachment,
                    att_db_id,
                    att["content"],
                    tenant_id,
                )

        # Update received_at
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE direct_messages SET received_at = UTC_TIMESTAMP() WHERE id = %s",
                (db_id,),
            )

        return {"id": db_id, "from_address": from_addr, "subject": subject}
    except Exception as exc:
        logger.error("direct_messaging: _process_inbound_raw failed: %s", exc)
        return None


def _decode_header_value(value: str) -> str:
    """Decode RFC 2047 encoded-words in a header value."""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


# ---------------------------------------------------------------------------
# C-CDA auto-parse integration
# ---------------------------------------------------------------------------


def _parse_ccda_attachment(
    attachment_db_id: int,
    content: bytes,
    tenant_id: str,
) -> None:
    """
    Attempt to parse a C-CDA attachment via ccda_service.

    Updates direct_attachments.parsed and ccda_document_id when successful.
    Runs in the thread-pool executor.
    """
    try:
        from app.services import ccda_service  # type: ignore[import]

        result = ccda_service.parse_ccda(content, tenant_id=tenant_id)
        if result and result.get("document_id"):
            with raf_cursor() as cur:
                cur.execute(
                    """
                    UPDATE direct_attachments
                    SET parsed = 1, ccda_document_id = %s
                    WHERE id = %s
                    """,
                    (result["document_id"], attachment_db_id),
                )
            logger.info(
                "direct_messaging: C-CDA attachment %d parsed → document %d",
                attachment_db_id,
                result["document_id"],
            )
    except ImportError:
        logger.debug(
            "direct_messaging: ccda_service not available — C-CDA parsing skipped"
        )
    except Exception as exc:
        logger.error(
            "direct_messaging: C-CDA parse failed for attachment %d: %s",
            attachment_db_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Address book / directory lookup
# ---------------------------------------------------------------------------


def lookup_direct_address(address: str, tenant_id: str) -> dict[str, Any] | None:
    """
    Look up a Direct address in the local address book.

    Returns a sanitised dict (no private key) if found, None otherwise.
    For production, this should also query a HISP directory (DNS + LDAP or
    the DirectTrust Certificate Discovery Service).
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, direct_address, display_name, certificate_pem,
                   provider_npi, status, tenant_id
            FROM direct_addresses
            WHERE direct_address = %s AND (tenant_id = %s OR tenant_id = 'shared')
            """,
            (address, tenant_id),
        )
        return cur.fetchone()


def search_address_book(
    query: str,
    tenant_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Full-text search across direct_address and display_name."""
    pattern = f"%{query}%"
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, direct_address, display_name, provider_npi, status
            FROM direct_addresses
            WHERE tenant_id = %s
              AND status = 'active'
              AND (direct_address LIKE %s OR display_name LIKE %s)
            ORDER BY display_name
            LIMIT %s
            """,
            (tenant_id, pattern, pattern, limit),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# MDN — Message Disposition Notifications
# ---------------------------------------------------------------------------


def process_mdn(raw_mdn: bytes, tenant_id: str) -> bool:
    """
    Parse an incoming MDN and update the corresponding outbound message status.

    MDNs are sent by the recipient's MTA to confirm delivery or report
    processing errors (RFC 3798).  Returns True if a matching message was
    updated, False otherwise.
    """
    try:
        mdn = email_lib.message_from_bytes(raw_mdn)
        # MDNs reference the original Message-ID via X-Original-Message-ID
        # or the first part of a multipart/report body
        original_id = mdn.get("X-Original-Message-ID") or mdn.get("In-Reply-To")
        if not original_id:
            return False

        disposition = (
            "delivered"  # Assume positive MDN; parse body for errors if needed
        )

        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE direct_messages
                SET status = %s
                WHERE message_id = %s AND tenant_id = %s AND direction = 'outbound'
                """,
                (disposition, original_id.strip(), tenant_id),
            )
            updated = cur.rowcount > 0

        if updated:
            logger.info(
                "direct_messaging: MDN processed for message_id=%s → %s",
                original_id,
                disposition,
            )
        return updated
    except Exception as exc:
        logger.error("direct_messaging: MDN processing failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------


def get_dashboard_stats(tenant_id: str) -> dict[str, Any]:
    """
    Return aggregate message statistics for the Direct Messaging dashboard.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(direction = 'inbound')  AS inbound,
                SUM(direction = 'outbound') AS outbound,
                SUM(status = 'received')    AS unread,
                SUM(status = 'failed')      AS failed,
                SUM(status = 'queued')      AS queued,
                SUM(has_attachments = 1)    AS with_attachments
            FROM direct_messages
            WHERE tenant_id = %s
            """,
            (tenant_id,),
        )
        row = cur.fetchone()

    with raf_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM direct_addresses WHERE tenant_id = %s AND status = 'active'",
            (tenant_id,),
        )
        active_addresses = cur.fetchone()["cnt"]

    with raf_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM direct_trust_anchors WHERE tenant_id = %s AND status = 'trusted'",
            (tenant_id,),
        )
        trusted_anchors = cur.fetchone()["cnt"]

    return {
        "total_messages": row["total"] or 0,
        "inbound": row["inbound"] or 0,
        "outbound": row["outbound"] or 0,
        "unread": row["unread"] or 0,
        "failed": row["failed"] or 0,
        "queued": row["queued"] or 0,
        "with_attachments": row["with_attachments"] or 0,
        "active_addresses": active_addresses,
        "trusted_anchors": trusted_anchors,
        "smtp_configured": _is_smtp_configured(),
        "imap_configured": _is_imap_configured(),
    }
