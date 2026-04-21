#!/usr/bin/env bash
# check_ruff_baseline.sh — Fail if ruff error count exceeds the locked baseline.
#
# Usage (from repo root):
#   bash backend/scripts/check_ruff_baseline.sh
#
# To update the baseline after intentional fixes:
#   1. Run and confirm count dropped.
#   2. Update .github/ruff-baseline.txt.
#   3. Commit both together.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
BASELINE_FILE="$ROOT/.github/ruff-baseline.txt"
CONFIG="$ROOT/backend/pyproject.toml"

if [[ ! -f "$BASELINE_FILE" ]]; then
  echo "ERROR: baseline file not found at $BASELINE_FILE" >&2
  exit 1
fi

BASELINE=$(cat "$BASELINE_FILE" | tr -d '[:space:]')
echo "Locked baseline: $BASELINE errors"

CURRENT=$(ruff check "$ROOT/backend/app" "$ROOT/backend/tests" \
  --config "$CONFIG" \
  --output-format=concise 2>&1 \
  | grep -E "^Found [0-9]+ error" | grep -oE "[0-9]+" | head -1 || echo "0")

echo "Current count:  $CURRENT errors"

if [[ "$CURRENT" -gt "$BASELINE" ]]; then
  echo ""
  echo "FAIL: ruff error count increased from $BASELINE to $CURRENT."
  echo "Fix new violations or update the baseline if intentional."
  exit 1
fi

echo "PASS: ruff error count ($CURRENT) is within baseline ($BASELINE)."
