#!/usr/bin/env bash
# test-fast.sh — Run the unit test suite only (excludes integration tests).
#
# Runs in under 60 seconds on a modern laptop.  Suitable for pre-commit hooks
# and CI fast-feedback gates.
#
# Usage:
#   ./scripts/test-fast.sh           # from backend/
#   bash backend/scripts/test-fast.sh  # from repo root
#
# Exit code mirrors pytest exit code (0 = all passed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$BACKEND_DIR"

VENV_PYTEST="${BACKEND_DIR}/.venv/bin/pytest"
if [ ! -x "$VENV_PYTEST" ]; then
    echo "ERROR: pytest not found at $VENV_PYTEST" >&2
    echo "       Run: python -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi

echo "=== RAF Intelligence — fast unit test run (not integration) ==="
echo "Backend: $BACKEND_DIR"
echo ""

exec "$VENV_PYTEST" tests/ \
    -m "not integration" \
    --no-cov \
    -q \
    --timeout=30 \
    --timeout-method=thread \
    -p no:cacheprovider \
    --ignore=tests/load \
    "$@"
