#!/usr/bin/env bash
# Validate that all required environment variables are set.
# Usage: ./scripts/validate-env.sh
# Reads from the current environment (source .env first if needed).

set -euo pipefail

REQUIRED_VARS=(
  RAF_DB_HOST
  RAF_DB_USER
  RAF_DB_PASSWORD
  RAF_DB_NAME
  JWT_SECRET
  JWT_REFRESH_SECRET
  REDIS_PASSWORD
  FRONTEND_URL
  GOOGLE_API_KEY
)

PASS=0
FAIL=0

for var in "${REQUIRED_VARS[@]}"; do
  val="${!var:-}"
  if [[ -z "$val" ]]; then
    echo "FAIL  $var (not set or empty)"
    (( FAIL++ )) || true
  else
    echo "PASS  $var"
    (( PASS++ )) || true
  fi
done

echo ""
echo "Result: ${PASS} passed, ${FAIL} failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
