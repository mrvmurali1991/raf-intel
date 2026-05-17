"""
Tests for KMS BYOK encryption service.

Covers:
  1. LocalFernetProvider encrypt + decrypt round-trip.
  2. AwsKmsProvider encrypt + decrypt round-trip (mocked boto3).
  3. Legacy Fernet blob is readable when KMS provider is active.
  4. Data-key cache hit: 2 decrypts within 5 min → only 1 KMS Decrypt call.
  5. Cache expiry: second decrypt after >5 min → fresh KMS Decrypt call.
  6. Key rotation: 5 Fernet-encrypted rows → all become KMS-versioned after rotate.

No live AWS credentials or database required — all external calls are mocked.
"""
from __future__ import annotations

import base64
import os
import struct
import time
import unittest
from unittest.mock import MagicMock, patch

import pytest

# ── ensure env is clean before importing the service ──────────────────────
os.environ.pop("AWS_KMS_KEY_ARN", None)
os.environ.pop("ENCRYPTION_KEY", None)

from app.services.encryption_service import (  # noqa: E402
    VERSION_FERNET,
    VERSION_KMS,
    AwsKmsProvider,
    LocalFernetProvider,
    _DATA_KEY_CACHE,
    _universal_decrypt,
    decrypt_field,
    encrypt_field,
)

# ── test helpers ──────────────────────────────────────────────────────────

PLAINTEXT = "super-secret-value-123"
PLAINTEXT_BYTES = PLAINTEXT.encode("utf-8")

# A valid 32-byte Fernet key (URL-safe base64 of 32 random bytes)
from cryptography.fernet import Fernet

_FERNET_KEY = Fernet.generate_key()

# Synthetic KMS responses
_PLAINTEXT_DATA_KEY = os.urandom(32)  # 256-bit data key
_ENCRYPTED_DATA_KEY = b"FAKE_ENCRYPTED_DATA_KEY_CIPHERTEXT_BLOB_32B"  # arbitrary bytes


def _make_boto3_mock(plaintext_key: bytes = _PLAINTEXT_DATA_KEY,
                     encrypted_key: bytes = _ENCRYPTED_DATA_KEY) -> MagicMock:
    """Return a mock boto3 module whose kms client returns predictable responses."""
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    mock_client.generate_data_key.return_value = {
        "Plaintext": plaintext_key,
        "CiphertextBlob": encrypted_key,
    }
    mock_client.decrypt.return_value = {
        "Plaintext": plaintext_key,
        "KeyId": "arn:aws:kms:us-east-1:123456789012:key/test-key-id",
    }
    return mock_boto3


# ── Test 1: LocalFernetProvider round-trip ─────────────────────────────────


class TestLocalFernetProvider(unittest.TestCase):

    def setUp(self):
        self.provider = LocalFernetProvider(key=_FERNET_KEY)

    def test_encrypt_returns_version_prefix(self):
        blob = self.provider.encrypt(PLAINTEXT_BYTES)
        self.assertEqual(blob[:1], VERSION_FERNET)

    def test_round_trip(self):
        blob = self.provider.encrypt(PLAINTEXT_BYTES)
        recovered = self.provider.decrypt(blob)
        self.assertEqual(recovered, PLAINTEXT_BYTES)

    def test_encrypt_str_round_trip(self):
        ct = self.provider.encrypt_str(PLAINTEXT)
        pt = self.provider.decrypt_str(ct)
        self.assertEqual(pt, PLAINTEXT)

    def test_wrong_version_raises(self):
        kms_blob = VERSION_KMS + b"\x00" * 40
        with self.assertRaises(ValueError):
            self.provider.decrypt(kms_blob)

    def test_empty_blob_raises(self):
        with self.assertRaises(ValueError):
            self.provider.decrypt(b"")


# ── Test 2: AwsKmsProvider round-trip (mocked boto3) ──────────────────────


class TestAwsKmsProvider(unittest.TestCase):

    def _make_provider(self) -> AwsKmsProvider:
        provider = AwsKmsProvider(key_arn="arn:aws:kms:us-east-1:123456789012:key/test")
        provider._boto3_mod = _make_boto3_mock()
        return provider

    def setUp(self):
        _DATA_KEY_CACHE.clear()
        self.provider = self._make_provider()

    def test_encrypt_returns_kms_version(self):
        blob = self.provider.encrypt(PLAINTEXT_BYTES)
        self.assertEqual(blob[:1], VERSION_KMS)

    def test_round_trip(self):
        blob = self.provider.encrypt(PLAINTEXT_BYTES)
        # Fresh provider (no cache) for decrypt
        dec_provider = self._make_provider()
        recovered = dec_provider.decrypt(blob)
        self.assertEqual(recovered, PLAINTEXT_BYTES)

    def test_encrypt_str_round_trip(self):
        ct = self.provider.encrypt_str(PLAINTEXT)
        dec_provider = self._make_provider()
        pt = dec_provider.decrypt_str(ct)
        self.assertEqual(pt, PLAINTEXT)

    def test_wrong_version_raises(self):
        fernet_blob = VERSION_FERNET + b"\x00" * 40
        with self.assertRaises(ValueError):
            self.provider.decrypt(fernet_blob)

    def test_empty_blob_raises(self):
        with self.assertRaises(ValueError):
            self.provider.decrypt(b"")


# ── Test 3: Legacy Fernet blob readable when KMS provider is active ─────────


class TestLegacyFernetReadableUnderKms(unittest.TestCase):

    def setUp(self):
        _DATA_KEY_CACHE.clear()
        self.fernet_provider = LocalFernetProvider(key=_FERNET_KEY)
        self.kms_provider = AwsKmsProvider(key_arn="arn:aws:kms:us-east-1:123456789012:key/test")
        self.kms_provider._boto3_mod = _make_boto3_mock()

    def test_legacy_fernet_blob_decryptable_via_universal_decrypt(self):
        # Encrypt with Fernet (legacy)
        fernet_blob = self.fernet_provider.encrypt(PLAINTEXT_BYTES)
        self.assertEqual(fernet_blob[:1], VERSION_FERNET)

        # Decrypt using universal_decrypt even when KMS provider is active.
        # universal_decrypt falls back to a transient LocalFernetProvider.
        # We need ENCRYPTION_KEY env var set so the fallback key matches.
        with patch.dict(os.environ, {"ENCRYPTION_KEY": _FERNET_KEY.decode("ascii")}):
            recovered = _universal_decrypt(fernet_blob, self.kms_provider)
        self.assertEqual(recovered, PLAINTEXT_BYTES)


# ── Test 4: Cache hit — only 1 KMS Decrypt call for 2 decrypts within 5 min ─


class TestKmsCacheHit(unittest.TestCase):

    def setUp(self):
        _DATA_KEY_CACHE.clear()

    def test_two_decrypts_one_kms_call(self):
        mock_boto3 = _make_boto3_mock()
        provider = AwsKmsProvider(key_arn="arn:aws:kms:us-east-1:123456789012:key/test")
        provider._boto3_mod = mock_boto3

        # Encrypt — calls generate_data_key once, populates cache.
        blob = provider.encrypt(PLAINTEXT_BYTES)

        # Clear the cache to force a real decrypt path for the first call.
        _DATA_KEY_CACHE.clear()

        # First decrypt — calls kms.decrypt once, repopulates cache.
        provider.decrypt(blob)
        # Second decrypt — should hit cache, no additional kms.decrypt call.
        provider.decrypt(blob)

        kms_client = mock_boto3.client.return_value
        self.assertEqual(kms_client.decrypt.call_count, 1,
                         "Expected exactly 1 KMS Decrypt call when cache is warm")


# ── Test 5: Cache expiry — 2nd decrypt after >5 min triggers new KMS call ───


class TestKmsCacheExpiry(unittest.TestCase):

    def setUp(self):
        _DATA_KEY_CACHE.clear()

    def test_expired_cache_triggers_second_kms_call(self):
        mock_boto3 = _make_boto3_mock()
        provider = AwsKmsProvider(key_arn="arn:aws:kms:us-east-1:123456789012:key/test")
        provider._boto3_mod = mock_boto3

        blob = provider.encrypt(PLAINTEXT_BYTES)
        _DATA_KEY_CACHE.clear()

        # First decrypt populates cache with expiry = now + 300 s.
        provider.decrypt(blob)
        kms_client = mock_boto3.client.return_value
        self.assertEqual(kms_client.decrypt.call_count, 1)

        # Artificially expire the cache by back-dating the expiry.
        arn = "arn:aws:kms:us-east-1:123456789012:key/test"
        pk, ek, _expiry = _DATA_KEY_CACHE[arn]
        _DATA_KEY_CACHE[arn] = (pk, ek, time.monotonic() - 1.0)  # already expired

        # Second decrypt — cache is expired → KMS Decrypt called again.
        provider.decrypt(blob)
        self.assertEqual(kms_client.decrypt.call_count, 2,
                         "Expected 2nd KMS Decrypt call after cache expiry")


# ── Test 6: Key rotation — Fernet rows become KMS-versioned ──────────────


class TestKeyRotationEndpoint(unittest.TestCase):
    """
    Simulate the rotation logic in isolation, without touching a real database.

    The rotation router iterates over rows, decrypts with _universal_decrypt,
    then re-encrypts with the active provider.  We test this core transformation
    on 5 synthetic Fernet-encrypted values.
    """

    def setUp(self):
        _DATA_KEY_CACHE.clear()
        self.fernet_provider = LocalFernetProvider(key=_FERNET_KEY)
        self.kms_provider = AwsKmsProvider(key_arn="arn:aws:kms:us-east-1:123456789012:key/test")
        self.kms_provider._boto3_mod = _make_boto3_mock()

    def _simulate_rotation(self, stored_values: list[str]) -> list[str]:
        """Apply the same re-encryption logic the router uses."""
        rotated = []
        for val in stored_values:
            raw = base64.urlsafe_b64decode(val.encode("ascii"))
            with patch.dict(os.environ, {"ENCRYPTION_KEY": _FERNET_KEY.decode("ascii")}):
                plaintext = _universal_decrypt(raw, self.kms_provider)
            new_blob = self.kms_provider.encrypt(plaintext)
            rotated.append(base64.urlsafe_b64encode(new_blob).decode("ascii"))
        return rotated

    def test_five_fernet_rows_become_kms(self):
        plaintexts = [f"secret-value-{i}" for i in range(5)]

        # Store as legacy Fernet blobs.
        fernet_rows = [
            base64.urlsafe_b64encode(self.fernet_provider.encrypt(pt.encode("utf-8"))).decode("ascii")
            for pt in plaintexts
        ]
        for val in fernet_rows:
            raw = base64.urlsafe_b64decode(val)
            self.assertEqual(raw[:1], VERSION_FERNET, "Should start as Fernet")

        # Run rotation.
        rotated_rows = self._simulate_rotation(fernet_rows)
        self.assertEqual(len(rotated_rows), 5)

        # All should now be KMS-versioned.
        for val in rotated_rows:
            raw = base64.urlsafe_b64decode(val)
            self.assertEqual(raw[:1], VERSION_KMS, "Should be KMS after rotation")

        # And the KMS provider can decrypt them back to the original plaintexts.
        for i, val in enumerate(rotated_rows):
            raw = base64.urlsafe_b64decode(val)
            recovered = self.kms_provider.decrypt(raw)
            self.assertEqual(recovered.decode("utf-8"), plaintexts[i])


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
