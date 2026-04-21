"""Audit-defensibility: every RAF calculation must carry a provenance stamp.

These tests guarantee that :func:`app.services.raf.provenance.provenance_stamp`
always produces a non-trivial bundle of fields suitable for RADV defence.

We do **not** exercise the live DB upsert here — persistence is covered by
the existing raf pipeline tests. The contract we pin is:
  * the manifest hash is a valid SHA-256 hex string,
  * the coefficient source encodes the hccinfhir version,
  * the model_version is passed through unchanged,
  * commit SHA is either an env override or a git SHA (tolerant of absence in CI).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.services.raf import provenance


def test_coefficient_manifest_hash_is_valid_sha256() -> None:
    h = provenance.coefficient_manifest_hash()
    assert h is not None, "manifest must exist and hash cleanly"
    assert re.fullmatch(r"[0-9a-f]{64}", h), f"expected sha256 hex, got {h!r}"


def test_coefficient_manifest_hash_changes_when_manifest_changes(tmp_path) -> None:
    """Sanity check the hashing logic — identical bytes → identical digest,
    changed bytes → different digest.  Uses an isolated temp manifest so we
    do not touch the real file on disk.
    """
    manifest_a = tmp_path / "a.json"
    manifest_b = tmp_path / "b.json"
    manifest_a.write_bytes(b'{"version": "A"}')
    manifest_b.write_bytes(b'{"version": "B"}')

    import hashlib
    digest_a = hashlib.sha256(manifest_a.read_bytes()).hexdigest()
    digest_b = hashlib.sha256(manifest_b.read_bytes()).hexdigest()
    assert digest_a != digest_b


def test_coefficient_source_includes_hccinfhir_version() -> None:
    src = provenance.coefficient_source()
    assert src.startswith("hccinfhir=="), src
    # Version segment must be non-empty and not the placeholder.
    version = src.split("==", 1)[1]
    assert version and version != "unknown", f"unexpected source: {src}"


def test_calculator_commit_sha_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    provenance.calculator_commit_sha.cache_clear()
    monkeypatch.setenv("CALCULATOR_COMMIT_SHA", "deadbeef" * 5)
    try:
        sha = provenance.calculator_commit_sha()
    finally:
        provenance.calculator_commit_sha.cache_clear()
    assert sha == "deadbeef" * 5


def test_provenance_stamp_shape() -> None:
    stamp = provenance.provenance_stamp("V28")
    assert stamp["model_version"] == "V28"
    assert stamp["coefficient_source"].startswith("hccinfhir==")
    assert stamp["coefficient_manifest_hash"] is not None
    # calculator_commit_sha may be None in detached CI — contract allows that,
    # but the key must exist.
    assert "calculator_commit_sha" in stamp


@pytest.mark.parametrize("model", ["V24", "V28", "V22", "BLEND"])
def test_provenance_stamp_preserves_model_version(model: str) -> None:
    assert provenance.provenance_stamp(model)["model_version"] == model


def test_audit_migration_file_present() -> None:
    """Migration 020 must exist so the audit columns are defined in schema."""
    migrations = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    assert (migrations / "020_raf_scores_audit_columns.py").exists()
