#!/usr/bin/env bash
# test-all.sh — Run the full test suite including integration tests.
#
# Requires a live backend at http://localhost:8500, MySQL, and optionally
# Redis and a Gemini API key.  Set RAF_DB_HOST if using a remote database.
#
# Uses a 120-second per-test timeout to accommodate Gemini API calls.
#
# Usage:
#   ./scripts/test-all.sh              # from backend/
#   bash backend/scripts/test-all.sh   # from repo root
#
# Exit code mirrors pytest exit code (0 = all passed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$BACKEND_DIR"

VENV_PYTEST="${BACKEND_DIR}/.venv/bin/pytest"
if [ ! -x "$VENV_PYTEST" ]; then
    echo "ERROR: pytest not found at $VENV_PYTEST" >&2
    exit 1
fi

echo "=== RAF Intelligence — full test suite (including integration) ==="
echo "Backend: $BACKEND_DIR"
echo ""

exec "$VENV_PYTEST" tests/ \
    --no-cov \
    -q \
    --timeout=120 \
    --timeout-method=thread \
    -p no:cacheprovider \
    --ignore=tests/load \
    "$@"
