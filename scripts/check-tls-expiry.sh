#!/usr/bin/env bash
# =============================================================================
# check-tls-expiry.sh — TLS-certificate expiry watchdog
#
# Usage:
#   ./scripts/check-tls-expiry.sh <hostname> [port]
#
# Behaviour:
#   - Logs days-until-expiry to stdout (cron will mail/log it).
#   - If <14 days remain: prints a WARNING to stderr and optionally POSTs
#     to $TLS_ALERT_WEBHOOK (Slack-compatible JSON: { "text": "..." }).
#   - If <7 days remain: exits non-zero so cron picks up the failure.
#
# Companion to ops/cron/raf-tls-check.
# =============================================================================
set -euo pipefail

HOST="${1:-}"
PORT="${2:-443}"
WARN_DAYS=14
CRIT_DAYS=7

[ -n "$HOST" ] || { echo "Usage: $0 <hostname> [port]" >&2; exit 2; }

# ---------------------------------------------------------------------------
# Fetch certificate expiry date via openssl s_client
# ---------------------------------------------------------------------------
end_date=$(
    openssl s_client -connect "${HOST}:${PORT}" -servername "${HOST}" </dev/null 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null \
        | cut -d= -f2
)

if [ -z "$end_date" ]; then
    echo "ERROR: could not retrieve TLS cert for ${HOST}:${PORT}" >&2
    exit 3
fi

# Convert to epoch — GNU date on Linux, BSD `date -j` fallback on macOS
if expiry_epoch=$(date -d "${end_date}" +%s 2>/dev/null); then
    :
else
    expiry_epoch=$(date -j -f "%b %d %T %Y %Z" "${end_date}" +%s)
fi

now_epoch=$(date +%s)
days_left=$(( (expiry_epoch - now_epoch) / 86400 ))

echo "TLS cert ${HOST}:${PORT} expires in ${days_left} day(s) (${end_date})"

# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------
post_webhook() {
    local msg="$1"
    if [ -n "${TLS_ALERT_WEBHOOK:-}" ]; then
        curl -sS -X POST -H 'Content-Type: application/json' \
             --data "$(printf '{"text":"%s"}' "$msg")" \
             "${TLS_ALERT_WEBHOOK}" >/dev/null || true
    fi
}

if [ "$days_left" -lt "$CRIT_DAYS" ]; then
    msg="CRITICAL: TLS cert for ${HOST} expires in ${days_left} day(s) — RENEW NOW"
    echo "$msg" >&2
    post_webhook "$msg"
    exit 1
fi

if [ "$days_left" -lt "$WARN_DAYS" ]; then
    msg="WARNING: TLS cert for ${HOST} expires in ${days_left} day(s)"
    echo "$msg" >&2
    post_webhook "$msg"
fi

exit 0
