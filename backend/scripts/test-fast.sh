#!/usr/bin/env bash
# test-fast.sh — Run the unit test suite only (excludes @pytest.mark.integration).
#
# Runs in under 60 seconds on a modern laptop.  Suitable for pre-commit hooks
# and CI fast-feedback gates.
#
# Usage:
#   ./scripts/test-fast.sh           # from backend/
#   bash backend/scripts/test-fast.sh  # from repo root
#
# Exit code mirrors pytest exit code (0 = all passed, 1 = failures exist).

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
echo "Started: $(date)"
echo ""

START_TS=$(date +%s)

# Run pytest and capture exit code without letting set -e abort early
"$VENV_PYTEST" tests/ \
    -m "not integration" \
    --no-cov \
    --no-header \
    --tb=line \
    --timeout=20 \
    --timeout-method=thread \
    -p no:cacheprovider \
    --ignore=tests/load \
    --ignore=tests/integration \
    --ignore-glob="tests/accuracy/*" \
    --ignore=tests/test_response_model_contract.py \
    --ignore=tests/test_suspect_kg_orchestrator.py \
    --continue-on-collection-errors \
    -q \
    "$@"
PYTEST_EXIT=$?

END_TS=$(date +%s)
ELAPSED=$(( END_TS - START_TS ))

echo ""
echo "=== test-fast.sh complete in ${ELAPSED}s ==="
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "Result: PASSED"
else
    echo "Result: FAILED (exit code $PYTEST_EXIT)"
fi

exit $PYTEST_EXIT
