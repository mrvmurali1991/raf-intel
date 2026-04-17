#!/usr/bin/env python3
"""Coefficient-manifest change-log gate.

Every commit that alters ``coefficients_manifest.json`` must also add
a matching entry in ``coefficient_change_log.md``. This script
computes the current manifest hash, scans the change log for a
YAML-block entry with a matching ``hash:`` line, and exits non-zero
if one isn't found.

Runs locally in <100 ms and in CI as a fast-fail gate before the
longer drift-watcher job.

Exit codes:
  0 — current manifest hash is represented in the change log.
  1 — hash not found (missing log entry).
  2 — environment error (manifest or log file missing / unreadable).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_MANIFEST = _BACKEND / "app" / "services" / "raf" / "coefficients_manifest.json"
_CHANGELOG = _BACKEND / "app" / "services" / "raf" / "coefficient_change_log.md"


def _fail(msg: str, code: int = 1) -> None:
    print(f"[changelog-gate] FAIL: {msg}", file=sys.stderr)
    sys.exit(code)


def _current_hash() -> str:
    if not _MANIFEST.exists():
        _fail(f"manifest missing at {_MANIFEST}", code=2)
    return hashlib.sha256(_MANIFEST.read_bytes()).hexdigest()


_HASH_LINE = re.compile(r"^\s*hash:\s*([0-9a-f]{64})\s*$", re.MULTILINE)


def _logged_hashes() -> set[str]:
    if not _CHANGELOG.exists():
        _fail(f"change log missing at {_CHANGELOG}", code=2)
    text = _CHANGELOG.read_text()
    return {m.group(1) for m in _HASH_LINE.finditer(text)}


def main() -> None:
    live = _current_hash()
    logged = _logged_hashes()
    if live in logged:
        print(
            f"[changelog-gate] OK — manifest hash {live[:12]}… is in the log "
            f"({len(logged)} total entries)."
        )
        return

    _fail(
        "current coefficients_manifest.json SHA-256 is NOT represented in "
        f"coefficient_change_log.md.\n"
        f"  current hash: {live}\n"
        f"  logged hashes: {sorted(logged)}\n\n"
        "Append a new entry to coefficient_change_log.md with the matching "
        "hash, CMS source citation, payment year, and summary before merging.",
    )


if __name__ == "__main__":
    main()
