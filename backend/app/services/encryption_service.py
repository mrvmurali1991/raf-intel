"""
AES-256-GCM encryption for sensitive data at rest.

A 256-bit key is derived via HKDF-SHA256 from either:
  1. ``DATA_ENCRYPTION_KEY`` env var (preferred — independent of JWT_SECRET), or
  2. ``JWT_SECRET`` (fallback, for backwards compatibility).

The salt is read from ``ENCRYPTION_SALT``.  In production both must be set;
missing values raise ``RuntimeError`` so the service refuses to start rather
than silently encrypting with a weak default.

The nonce (12 bytes) is prepended to the ciphertext before base64-encoding,
making each encrypted value self-contained.

Usage::

    from app.services.encryption_service import encrypt, decrypt

    stored  = encrypt("super-secret")   # store this in the DB
    plain   = decrypt(stored)            # call before using the value
"""
from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Import is deferred inside functions so the module can be imported before
# the settings object is fully initialised (e.g. during tests).


def _derive_key() -> bytes:
    """Derive a stable 256-bit AES key using HKDF-SHA256.

    Key material priority:
      1. ``DATA_ENCRYPTION_KEY`` env var — preferred; keeps encryption
         independent of the JWT signing secret.
      2. ``JWT_SECRET`` (via app.config.settings) — backwards-compatible
         fallback used when DATA_ENCRYPTION_KEY is absent.

    Salt is read from ``ENCRYPTION_SALT``.  A missing salt (or key) is a
    hard error in production so misconfigured deployments fail loudly at
    startup rather than silently encrypting data with a weak default.
    """
    is_production = os.getenv("APP_ENV", "development") == "production"

    # --- salt -----------------------------------------------------------
    env_salt = os.getenv("ENCRYPTION_SALT", "").encode()
    if not env_salt:
        if is_production:
            raise RuntimeError(
                "FATAL: ENCRYPTION_SALT environment variable must be set in production"
            )
        logger.warning(
            "Using default encryption salt — set ENCRYPTION_SALT env var in production"
        )
    salt = env_salt or b"raf-intelligence-encryption-salt"

    # --- key material ---------------------------------------------------
    data_key = os.getenv("DATA_ENCRYPTION_KEY", "")
    if data_key:
        secret = data_key.encode()
    else:
        # Late import to avoid circular dependency at module load time.
        from app.config import settings  # noqa: PLC0415

        if is_production:
            raise RuntimeError(
                "FATAL: DATA_ENCRYPTION_KEY environment variable must be set in production"
            )
        logger.warning(
            "DATA_ENCRYPTION_KEY not set — deriving encryption key from JWT_SECRET. "
            "Set DATA_ENCRYPTION_KEY in production to decouple encryption from JWT."
        )
        secret = settings.jwt_secret.encode()

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"data-at-rest-encryption",
    )
    return hkdf.derive(secret)


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns a base64-encoded string of ``nonce (12 B) || ciphertext+tag``.
    Each call produces a unique ciphertext because a fresh random nonce is
    generated per invocation.
    """
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(encrypted: str) -> str:
    """Decrypt a value produced by :func:`encrypt`.

    Raises ``ValueError`` if the ciphertext is corrupt or the key has changed.
    """
    key = _derive_key()
    aesgcm = AESGCM(key)
    try:
        raw = base64.b64decode(encrypted)
    except Exception as exc:
        raise ValueError("encrypted value is not valid base64") from exc

    # Minimum valid size: 12-byte nonce + 16-byte GCM authentication tag + 1 byte plaintext = 29
    if len(raw) < 29:
        raise ValueError(
            f"encrypted value is too short to be valid ({len(raw)} bytes, need at least 29)"
        )

    nonce = raw[:12]
    ciphertext = raw[12:]
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("decryption failed – key mismatch or corrupt data") from exc

    return plaintext.decode()
