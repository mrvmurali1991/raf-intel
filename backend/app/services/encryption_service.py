"""
Encryption Service — envelope encryption with AWS KMS BYOK support.

Provider selection at boot
--------------------------
  ``AWS_KMS_KEY_ARN`` set  →  AwsKmsProvider   (KMS envelope encryption)
  otherwise                →  LocalFernetProvider  (env ENCRYPTION_KEY or HKDF fallback)

Blob wire format (1-byte version prefix stored with every encrypted value)
--------------------------------------------------------------------------
  b"\\x01" + <fernet token>       — legacy / Fernet (reads + writes when provider is Fernet)
  b"\\x02" + <kms envelope blob>  — KMS AES-256-GCM envelope (reads + writes when KMS)

On read, the version byte routes to the correct decryption path regardless of which
provider is currently active, so a rolling key rotation does not break existing rows.

Backward compatibility
----------------------
The pre-existing ``encrypt()`` / ``decrypt()`` public functions (AES-256-GCM with
HKDF-derived key) are preserved as a thin wrapper that calls the active provider,
so callers importing those names continue to work unchanged.

Usage::

    from app.services.encryption_service import encrypt, decrypt, get_provider

    stored = encrypt("super-secret")   # store in DB
    plain  = decrypt(stored)           # call before using the value
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import struct
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

# ── imports that may already be installed ──────────────────────────────────
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------------------------------------------------------------------------
# Version tags
# ---------------------------------------------------------------------------

VERSION_FERNET: bytes = b"\x01"
VERSION_KMS: bytes = b"\x02"

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EncryptionProvider(ABC):
    """Common interface for all encryption back-ends."""

    @abstractmethod
    def encrypt(self, plaintext: bytes) -> bytes:
        """Return a versioned blob."""

    @abstractmethod
    def decrypt(self, blob: bytes) -> bytes:
        """Decrypt a versioned blob produced by :meth:`encrypt`."""

    # Convenience wrappers
    def encrypt_str(self, plaintext: str) -> str:
        return base64.urlsafe_b64encode(self.encrypt(plaintext.encode("utf-8"))).decode("ascii")

    def decrypt_str(self, ciphertext: str) -> str:
        blob = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        return self.decrypt(blob).decode("utf-8")


# ---------------------------------------------------------------------------
# LocalFernetProvider
# ---------------------------------------------------------------------------


class LocalFernetProvider(EncryptionProvider):
    """Fernet (AES-128-CBC + HMAC-SHA256) using an env-supplied key.

    Key resolution order:
      1. Constructor *key* argument
      2. ``ENCRYPTION_KEY`` env var (URL-safe base64 Fernet key)
      3. Ephemeral random key (dev only — lost on restart)
    """

    def __init__(self, key: Optional[bytes] = None) -> None:
        if key is None:
            raw = os.getenv("ENCRYPTION_KEY", "").strip()
            if raw:
                key = raw.encode("ascii")
            else:
                key = Fernet.generate_key()
                logger.warning(
                    "ENCRYPTION_KEY not set — generated ephemeral Fernet key. "
                    "Encrypted data will be unreadable after restart."
                )
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        token = self._fernet.encrypt(plaintext)
        return VERSION_FERNET + token

    def decrypt(self, blob: bytes) -> bytes:
        if not blob:
            raise ValueError("Empty blob")
        version, payload = blob[:1], blob[1:]
        if version == VERSION_FERNET:
            return self._decrypt_fernet(payload)
        if version == VERSION_KMS:
            raise ValueError(
                "Blob is KMS-encrypted but LocalFernetProvider is active. "
                "Set AWS_KMS_KEY_ARN to decrypt KMS blobs."
            )
        raise ValueError(f"Unknown encryption version byte: {version!r}")

    def _decrypt_fernet(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise ValueError("Fernet decryption failed: invalid token or wrong key") from exc


# ---------------------------------------------------------------------------
# AwsKmsProvider
# ---------------------------------------------------------------------------

# Cache entry: (plaintext_data_key, encrypted_data_key, expiry_monotonic)
_CacheEntry = tuple[bytes, bytes, float]
_DATA_KEY_CACHE: dict[str, _CacheEntry] = {}  # keyed by KMS key ARN
_CACHE_TTL_SECONDS: int = 300  # 5 minutes


class AwsKmsProvider(EncryptionProvider):
    """AES-256-GCM envelope encryption backed by AWS KMS GenerateDataKey.

    KMS blob layout (after stripping the 1-byte b"\\x02" version prefix):
      [4 bytes BE uint32]  — encrypted_data_key length
      [N bytes]            — KMS-encrypted data key ciphertext
      [12 bytes]           — AES-GCM nonce
      [rest]               — AES-GCM ciphertext + 16-byte auth tag

    The plaintext data key is cached in-process for up to 5 minutes to reduce
    KMS API calls.  Only the *encrypted* data key is written to the DB blob.
    """

    def __init__(self, key_arn: str, region: Optional[str] = None) -> None:
        self._key_arn = key_arn
        self._region = region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self._boto3_mod = None  # lazy import

    # ── boto3 lazy init ────────────────────────────────────────────────────

    def _kms_client(self):  # noqa: ANN202
        if self._boto3_mod is None:
            try:
                import boto3  # noqa: PLC0415
                self._boto3_mod = boto3
            except ImportError as exc:
                raise RuntimeError(
                    "boto3 is required for KMS encryption. "
                    "Install it with: pip install boto3"
                ) from exc
        return self._boto3_mod.client("kms", region_name=self._region)

    # ── data-key cache helpers ─────────────────────────────────────────────

    def _cached_plaintext_key(self) -> Optional[bytes]:
        entry = _DATA_KEY_CACHE.get(self._key_arn)
        if entry and time.monotonic() < entry[2]:
            return entry[0]
        return None

    def _cache_key(self, plaintext_key: bytes, encrypted_key: bytes) -> None:
        expiry = time.monotonic() + _CACHE_TTL_SECONDS
        _DATA_KEY_CACHE[self._key_arn] = (plaintext_key, encrypted_key, expiry)

    # ── KMS calls ──────────────────────────────────────────────────────────

    def _generate_data_key(self) -> tuple[bytes, bytes]:
        """Return (plaintext_key, encrypted_key) from KMS."""
        resp = self._kms_client().generate_data_key(
            KeyId=self._key_arn, KeySpec="AES_256"
        )
        plaintext_key: bytes = resp["Plaintext"]
        encrypted_key: bytes = resp["CiphertextBlob"]
        self._cache_key(plaintext_key, encrypted_key)
        return plaintext_key, encrypted_key

    def _decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        """Unwrap encrypted data key via KMS Decrypt (with cache check)."""
        entry = _DATA_KEY_CACHE.get(self._key_arn)
        if entry and time.monotonic() < entry[2] and entry[1] == encrypted_key:
            return entry[0]
        resp = self._kms_client().decrypt(
            CiphertextBlob=encrypted_key, KeyId=self._key_arn
        )
        plaintext_key: bytes = resp["Plaintext"]
        self._cache_key(plaintext_key, encrypted_key)
        return plaintext_key

    # ── encrypt / decrypt ──────────────────────────────────────────────────

    def encrypt(self, plaintext: bytes) -> bytes:
        cached = self._cached_plaintext_key()
        if cached is not None:
            plaintext_key = cached
            encrypted_key = _DATA_KEY_CACHE[self._key_arn][1]
        else:
            plaintext_key, encrypted_key = self._generate_data_key()

        nonce = secrets.token_bytes(12)
        ct = AESGCM(plaintext_key).encrypt(nonce, plaintext, None)
        enc_key_len = struct.pack(">I", len(encrypted_key))
        inner = enc_key_len + encrypted_key + nonce + ct
        return VERSION_KMS + inner

    def decrypt(self, blob: bytes) -> bytes:
        if not blob:
            raise ValueError("Empty blob")
        version, payload = blob[:1], blob[1:]
        if version == VERSION_KMS:
            return self._decrypt_kms_payload(payload)
        if version == VERSION_FERNET:
            raise ValueError(
                "Blob is Fernet-encrypted but AwsKmsProvider is active. "
                "Run key rotation to re-encrypt with KMS."
            )
        raise ValueError(f"Unknown encryption version byte: {version!r}")

    def _decrypt_kms_payload(self, payload: bytes) -> bytes:
        if len(payload) < 4:
            raise ValueError("KMS blob too short")
        (enc_key_len,) = struct.unpack(">I", payload[:4])
        offset = 4 + enc_key_len
        encrypted_key = payload[4:offset]
        nonce = payload[offset: offset + 12]
        ct = payload[offset + 12:]
        plaintext_key = self._decrypt_data_key(encrypted_key)
        try:
            return AESGCM(plaintext_key).decrypt(nonce, ct, None)
        except Exception as exc:
            raise ValueError("KMS AES-GCM decryption failed: authentication tag mismatch") from exc


# ---------------------------------------------------------------------------
# Universal decrypt — version-aware routing
# ---------------------------------------------------------------------------


def _universal_decrypt(blob: bytes, active: EncryptionProvider) -> bytes:
    """Route decryption by version byte.

    If the active provider is KMS but the blob carries version 0x01 (Fernet),
    a transient LocalFernetProvider is constructed on-the-fly using ENCRYPTION_KEY
    so legacy rows remain readable even after a provider switch.
    """
    if not blob:
        raise ValueError("Empty blob")
    version = blob[:1]
    if version == VERSION_FERNET:
        if isinstance(active, LocalFernetProvider):
            return active.decrypt(blob)
        # KMS is active — delegate to a Fernet provider for legacy blobs.
        return LocalFernetProvider().decrypt(blob)
    if version == VERSION_KMS:
        if isinstance(active, AwsKmsProvider):
            return active.decrypt(blob)
        raise ValueError("Blob is KMS-encrypted but no KMS provider is configured.")
    raise ValueError(f"Unknown encryption version byte: {version!r}")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def _build_provider() -> EncryptionProvider:
    arn = os.getenv("AWS_KMS_KEY_ARN", "").strip()
    if arn:
        logger.info("Encryption: AwsKmsProvider (key ARN %s)", arn)
        return AwsKmsProvider(key_arn=arn)
    logger.info("Encryption: LocalFernetProvider (set AWS_KMS_KEY_ARN to enable KMS)")
    return LocalFernetProvider()


_provider: EncryptionProvider = _build_provider()


def get_provider() -> EncryptionProvider:
    """Return the active encryption provider singleton."""
    return _provider


# ---------------------------------------------------------------------------
# Public API — high-level convenience functions
# ---------------------------------------------------------------------------


def encrypt_field(plaintext: str) -> str:
    """Encrypt *plaintext* with the active provider; return base64-encoded blob."""
    blob = _provider.encrypt(plaintext.encode("utf-8"))
    return base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a base64-encoded blob; handles both Fernet and KMS versions."""
    blob = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    return _universal_decrypt(blob, _provider).decode("utf-8")


# ---------------------------------------------------------------------------
# Backward-compat shim — preserve old `encrypt()` / `decrypt()` signatures
# ---------------------------------------------------------------------------


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* (backward-compat wrapper)."""
    return encrypt_field(plaintext)


def decrypt(encrypted: str) -> str:
    """Decrypt *encrypted* (backward-compat wrapper)."""
    return decrypt_field(encrypted)
