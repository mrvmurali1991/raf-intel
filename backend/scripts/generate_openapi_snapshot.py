#!/usr/bin/env python3
"""
generate_openapi_snapshot.py — Generate openapi.json from the FastAPI app.

Usage:
    python backend/scripts/generate_openapi_snapshot.py \
        [--output backend/openapi.snapshot.json]

CI usage (check for drift):
    python backend/scripts/generate_openapi_snapshot.py --output /tmp/openapi.live.json
    diff -u backend/openapi.snapshot.json /tmp/openapi.live.json

To refresh the snapshot after intentional API changes:
    python backend/scripts/generate_openapi_snapshot.py
    git add backend/openapi.snapshot.json
    git commit -m "chore: refresh OpenAPI snapshot"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal environment stubs so the FastAPI app can be imported without a
# live database connection.
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "APP_ENV": "development",
    "JWT_SECRET": "snapshot-jwt-secret-not-for-production-use-64chars-pad",
    "JWT_REFRESH_SECRET": "snapshot-refresh-not-for-production-64chars-padded",
    "RAF_DB_HOST": "127.0.0.1",
    "RAF_DB_PORT": "3306",
    "RAF_DB_USER": "raf_app",
    "RAF_DB_PASSWORD": "test",
    "RAF_DB_NAME": "raf_intelligence",
    "OPENEMR_DB_HOST": "127.0.0.1",
    "OPENEMR_DB_PORT": "3306",
    "OPENEMR_DB_USER": "raf_app",
    "OPENEMR_DB_PASSWORD": "test",
    "OPENEMR_DB_NAME": "openemr",
    "REDIS_URL": "redis://localhost:6379/0",
    "GOOGLE_API_KEY": "",
    "SENTRY_DSN": "",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)

# Add backend/ to sys.path so `from app.main import app` resolves.
_repo_root = Path(__file__).resolve().parents[2]
_backend = _repo_root / "backend"
sys.path.insert(0, str(_backend))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OpenAPI snapshot from FastAPI app")
    parser.add_argument(
        "--output",
        default=str(_backend / "openapi.snapshot.json"),
        help="Output path for the snapshot JSON file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Diff against committed snapshot; exit 1 on drift",
    )
    args = parser.parse_args()

    try:
        from app.main import app  # type: ignore[import]
    except Exception as exc:
        print(f"ERROR: Could not import FastAPI app: {exc}", file=sys.stderr)
        return 1

    schema = app.openapi()
    live_json = json.dumps(schema, indent=2, sort_keys=True)

    if args.check:
        snapshot_path = Path(_backend / "openapi.snapshot.json")
        if not snapshot_path.exists():
            print(
                "ERROR: openapi.snapshot.json not found. Run without --check first.",
                file=sys.stderr,
            )
            return 1
        committed = snapshot_path.read_text()
        if committed.strip() == live_json.strip():
            print("PASS: OpenAPI schema matches committed snapshot.")
            return 0

        # Show a summary diff (first 50 lines).
        import difflib

        diff = list(
            difflib.unified_diff(
                committed.splitlines(),
                live_json.splitlines(),
                fromfile="openapi.snapshot.json",
                tofile="live schema",
                lineterm="",
            )
        )
        print("\n".join(diff[:50]))
        if len(diff) > 50:
            print(f"... and {len(diff) - 50} more lines")
        print(
            "\nFAIL: OpenAPI schema has drifted from the committed snapshot.",
            file=sys.stderr,
        )
        print(
            "Run `python backend/scripts/generate_openapi_snapshot.py` "
            "and commit the updated snapshot.",
            file=sys.stderr,
        )
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(live_json + "\n")
    print(f"Written: {output_path}")
    endpoints = len(schema.get("paths", {}))
    print(f"Endpoints: {endpoints}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
