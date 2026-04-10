"""
PHI Encryption Service.

Encrypts/decrypts Protected Health Information stored in raf_intelligence database.
Uses AES-256-GCM for HIPAA-compliant encryption at rest.

Fernet is built on AES-128-CBC + HMAC-SHA256. For true AES-256-GCM we use the
lower-level hazmat primitives from the cryptography library alongside Fernet for
simple field-level helpers.
"""

import base64
import logging
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".phi_key")
KEY_FILE = os.path.normpath(KEY_FILE)

# AES-256-GCM requires a 32-byte (256-bit) key.
_AES256_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".phi_aes256_key")
_AES256_KEY_FILE = os.path.normpath(_AES256_KEY_FILE)


def _get_or_create_fernet_key() -> bytes:
    """Load or generate a Fernet key persisted on disk."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    logger.info("Generated new Fernet PHI key at %s", KEY_FILE)
    return key


def _get_or_create_aes256_key() -> bytes:
    """Load or generate a 256-bit AES key persisted on disk (raw bytes, not base64)."""
    if os.path.exists(_AES256_KEY_FILE):
        with open(_AES256_KEY_FILE, "rb") as f:
            raw = f.read()
        if len(raw) == 32:
            return raw
        # Legacy: stored as base64
        return base64.urlsafe_b64decode(raw)
    key = secrets.token_bytes(32)  # 256 bits
    with open(_AES256_KEY_FILE, "wb") as f:
        f.write(key)
    logger.info("Generated new AES-256 PHI key at %s", _AES256_KEY_FILE)
    return key


# Module-level singletons initialised once at import time.
_fernet = Fernet(_get_or_create_fernet_key())
_aesgcm = AESGCM(_get_or_create_aes256_key())

# Nonce size for AES-GCM (96 bits is the standard recommendation).
_GCM_NONCE_BYTES = 12


# ---------------------------------------------------------------------------
# Public API — Fernet helpers (simple, authenticated)
# ---------------------------------------------------------------------------


def encrypt_phi(plaintext: str) -> str:
    """Encrypt a PHI string using Fernet (AES-128-CBC + HMAC-SHA256).

    Args:
        plaintext: The raw PHI string to protect.

    Returns:
        A URL-safe base64-encoded ciphertext string safe for database storage.

    Raises:
        ValueError: If *plaintext* is not a string.
    """
    if not isinstance(plaintext, str):
        raise ValueError("encrypt_phi expects a str, got %s" % type(plaintext).__name__)
    token: bytes = _fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_phi(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted PHI string.

    Args:
        ciphertext: The base64-encoded token returned by :func:`encrypt_phi`.

    Returns:
        The original plaintext string.

    Raises:
        ValueError: If *ciphertext* is invalid or has been tampered with.
    """
    if not isinstance(ciphertext, str):
        raise ValueError("decrypt_phi expects a str, got %s" % type(ciphertext).__name__)
    try:
        plaintext_bytes: bytes = _fernet.decrypt(ciphertext.encode("ascii"))
        return plaintext_bytes.decode("utf-8")
    except InvalidToken as exc:
        logger.error("PHI decryption failed — token invalid or key mismatch")
        raise ValueError("Decryption failed: invalid token or wrong key") from exc


# ---------------------------------------------------------------------------
# Public API — AES-256-GCM helpers (clinical notes, higher security tier)
# ---------------------------------------------------------------------------


def encrypt_note_excerpt(note: str) -> str:
    """Encrypt a clinical note excerpt before storing in DB using AES-256-GCM.

    A fresh 96-bit nonce is generated per call. The nonce is prepended to the
    ciphertext (first 12 bytes) so that :func:`decrypt_note_excerpt` can
    recover it without any separate storage column.

    Args:
        note: The plaintext clinical note excerpt.

    Returns:
        A URL-safe base64-encoded string: ``<12-byte nonce><ciphertext>``.

    Raises:
        ValueError: If *note* is not a string.
    """
    if not isinstance(note, str):
        raise ValueError("encrypt_note_excerpt expects a str, got %s" % type(note).__name__)
    nonce = secrets.token_bytes(_GCM_NONCE_BYTES)
    ciphertext: bytes = _aesgcm.encrypt(nonce, note.encode("utf-8"), None)
    blob = nonce + ciphertext
    return base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt_note_excerpt(encrypted: str) -> str:
    """Decrypt a stored AES-256-GCM clinical note excerpt for display.

    Args:
        encrypted: The base64-encoded blob returned by :func:`encrypt_note_excerpt`.

    Returns:
        The original plaintext note excerpt.

    Raises:
        ValueError: If *encrypted* is malformed, tampered with, or uses wrong key.
    """
    if not isinstance(encrypted, str):
        raise ValueError(
            "decrypt_note_excerpt expects a str, got %s" % type(encrypted).__name__
        )
    try:
        blob = base64.urlsafe_b64decode(encrypted.encode("ascii"))
    except Exception as exc:
        raise ValueError("decrypt_note_excerpt: base64 decode failed") from exc

    if len(blob) < _GCM_NONCE_BYTES + 1:
        raise ValueError("decrypt_note_excerpt: ciphertext blob too short")

    nonce = blob[:_GCM_NONCE_BYTES]
    ciphertext = blob[_GCM_NONCE_BYTES:]
    try:
        plaintext_bytes: bytes = _aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("AES-256-GCM note decryption failed — possible tampering")
        raise ValueError("Decryption failed: authentication tag mismatch or wrong key") from exc


# ---------------------------------------------------------------------------
# Convenience: batch helpers
# ---------------------------------------------------------------------------


def encrypt_phi_fields(record: dict, fields: list[str]) -> dict:
    """Return a copy of *record* with specified *fields* encrypted.

    Non-string field values are left unchanged (e.g. None, int).

    Args:
        record: Mapping of column name -> value.
        fields: Column names to encrypt.

    Returns:
        New dict with the named fields replaced by their encrypted equivalents.
    """
    result = dict(record)
    for field in fields:
        value = result.get(field)
        if isinstance(value, str) and value:
            result[field] = encrypt_phi(value)
    return result


def decrypt_phi_fields(record: dict, fields: list[str]) -> dict:
    """Return a copy of *record* with specified *fields* decrypted.

    Args:
        record: Mapping of column name -> encrypted value.
        fields: Column names to decrypt.

    Returns:
        New dict with the named fields replaced by their decrypted equivalents.
    """
    result = dict(record)
    for field in fields:
        value = result.get(field)
        if isinstance(value, str) and value:
            try:
                result[field] = decrypt_phi(value)
            except ValueError:
                logger.warning("Could not decrypt field '%s' — storing as-is", field)
    return result
