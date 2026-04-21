#!/usr/bin/env bash
# check_mypy_baseline.sh — Fail if mypy error count exceeds the locked baseline.
#
# Usage (from repo root):
#   bash backend/scripts/check_mypy_baseline.sh
#
# The baseline is stored in .github/mypy-baseline.txt.
# To update the baseline after intentional type improvements:
#   1. Run this script to verify the count dropped.
#   2. Update .github/mypy-baseline.txt with the new (lower) number.
#   3. Commit both files together.

set -euo pipefail

BASELINE_FILE="$(git rev-parse --show-toplevel)/.github/mypy-baseline.txt"
CONFIG_FILE="$(git rev-parse --show-toplevel)/backend/mypy.ini"
APP_DIR="$(git rev-parse --show-toplevel)/backend/app"

if [[ ! -f "$BASELINE_FILE" ]]; then
  echo "ERROR: baseline file not found at $BASELINE_FILE" >&2
  exit 1
fi

BASELINE=$(cat "$BASELINE_FILE" | tr -d '[:space:]')
echo "Locked baseline: $BASELINE errors"

# Run mypy, capture output, count error lines.
MYPY_OUTPUT=$(mypy "$APP_DIR" --config-file "$CONFIG_FILE" 2>&1 || true)
CURRENT=$(echo "$MYPY_OUTPUT" | grep -c " error:" || true)

echo "Current count:  $CURRENT errors"

if [[ "$CURRENT" -gt "$BASELINE" ]]; then
  echo ""
  echo "FAIL: mypy error count increased from $BASELINE to $CURRENT."
  echo "Fix the new type errors or update the baseline if they are intentional."
  exit 1
fi

echo "PASS: mypy error count ($CURRENT) is within baseline ($BASELINE)."
