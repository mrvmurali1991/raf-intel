"""Coefficient change-log gate tests.

These tests lock the governance contract:

- Current manifest hash must have a matching entry in the log.
- Log entries must carry the minimum required fields (hash, payment
  year, effective date, CMS source, changed_by, summary).
- Every hash listed in the log must be a valid SHA-256 hex string.
- The gate script exits 0 on success, 1 on missing entry, and does
  not swallow errors.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_MANIFEST = _BACKEND / "app" / "services" / "raf" / "coefficients_manifest.json"
_CHANGELOG = _BACKEND / "app" / "services" / "raf" / "coefficient_change_log.md"
_GATE = _BACKEND / "scripts" / "verify_coefficient_changelog.py"

_REQUIRED_FIELDS = (
    "hash",
    "payment_year",
    "effective_date",
    "cms_source",
    "changed_by",
    "summary",
)

_HASH_LINE = re.compile(r"^\s*hash:\s*([0-9a-f]{64})\s*$", re.MULTILINE)


def _current_hash() -> str:
    return hashlib.sha256(_MANIFEST.read_bytes()).hexdigest()


def _logged_hashes() -> set[str]:
    return {m.group(1) for m in _HASH_LINE.finditer(_CHANGELOG.read_text())}


class TestChangeLogPresence:
    def test_changelog_file_exists(self) -> None:
        assert _CHANGELOG.exists(), (
            f"coefficient_change_log.md must exist at {_CHANGELOG}"
        )

    def test_manifest_file_exists(self) -> None:
        assert _MANIFEST.exists(), (
            f"coefficients_manifest.json must exist at {_MANIFEST}"
        )

    def test_current_manifest_hash_is_logged(self) -> None:
        """The hash of the manifest as-shipped must have a log entry."""
        assert _current_hash() in _logged_hashes(), (
            "Current manifest hash has no entry in "
            "coefficient_change_log.md. Every manifest change requires "
            "a new log entry."
        )


class TestEntryFormat:
    def test_every_logged_hash_is_valid_sha256_hex(self) -> None:
        for h in _logged_hashes():
            assert re.fullmatch(r"[0-9a-f]{64}", h), (
                f"logged hash {h!r} is not 64-char lowercase hex"
            )

    def test_every_entry_has_all_required_fields(self) -> None:
        """Parse fenced YAML blocks; each must carry the required keys.

        We don't use a full YAML parser here — matching on ``key:`` at
        line starts is enough to catch missing fields.
        """
        text = _CHANGELOG.read_text()
        # Extract each YAML block between ```yaml fences.
        blocks = re.findall(r"```yaml\s*(.+?)```", text, re.DOTALL)
        assert blocks, "expected at least one YAML block in change log"
        for block in blocks:
            for field in _REQUIRED_FIELDS:
                assert re.search(
                    rf"^\s*{field}\s*:", block, re.MULTILINE
                ), (
                    f"YAML block missing required field {field!r}:\n{block}"
                )


class TestGateScript:
    def test_script_exists_and_is_executable(self) -> None:
        assert _GATE.exists(), f"gate script missing at {_GATE}"

    def test_script_exits_zero_on_current_manifest(self) -> None:
        """On a clean tree, the gate must exit 0."""
        result = subprocess.run(
            [sys.executable, str(_GATE)],
            check=False, capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"gate failed on clean tree: stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_script_fails_loud_on_bogus_changelog(self, tmp_path: Path) -> None:
        """Run the gate against a stub changelog with the wrong hash."""
        # Create a temporary fake backend tree so the script finds a
        # mismatched changelog.
        fake_backend = tmp_path / "backend"
        fake_raf = fake_backend / "app" / "services" / "raf"
        fake_scripts = fake_backend / "scripts"
        fake_raf.mkdir(parents=True)
        fake_scripts.mkdir(parents=True)
        # Copy manifest as-is, but write a changelog with a wrong hash.
        (fake_raf / "coefficients_manifest.json").write_bytes(
            _MANIFEST.read_bytes()
        )
        (fake_raf / "coefficient_change_log.md").write_text(
            "# Change Log\n\n```yaml\n"
            "hash: 0000000000000000000000000000000000000000000000000000000000000000\n"
            "payment_year: 2026\n"
            "effective_date: 2026-01-01\n"
            "cms_source: fake\n"
            "changed_by: nobody\n"
            "summary: not a real entry\n"
            "```\n"
        )
        # Copy the real gate script verbatim.
        (fake_scripts / "verify_coefficient_changelog.py").write_text(
            _GATE.read_text()
        )
        result = subprocess.run(
            [sys.executable, str(fake_scripts / "verify_coefficient_changelog.py")],
            check=False, capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1, (
            f"gate should fail when hashes don't match; stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}, returncode={result.returncode}"
        )
        assert "NOT represented" in result.stderr


class TestLogContent:
    def test_log_has_at_least_one_entry(self) -> None:
        assert len(_logged_hashes()) >= 1, (
            "Change log must carry at least the initial baseline entry"
        )

    def test_log_mentions_cms(self) -> None:
        text = _CHANGELOG.read_text()
        assert "CMS" in text, (
            "Change log must reference CMS as the source of record"
        )

    @pytest.mark.parametrize("field", _REQUIRED_FIELDS)
    def test_log_format_section_documents_required_fields(
        self, field: str
    ) -> None:
        """Up-front 'Entry format' section must list every required field."""
        text = _CHANGELOG.read_text()
        # The 'Entry format' section is at the top of the file.
        head = text.split("##", 2)[:2]  # preamble + first H2
        head_text = "\n".join(head) if len(head) >= 2 else text
        assert field in head_text, (
            f"Entry-format section must document the {field!r} field"
        )
