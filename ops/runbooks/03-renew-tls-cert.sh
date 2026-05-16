#!/usr/bin/env bash
# =============================================================================
# 03-renew-tls-cert.sh — Renew the production TLS certificate (BLOCKER)
#
# Why:
#   Per the readiness audit, the prod cert for raf.comercioit.com expires in
#   ≤ 9 days. Run this NOW to roll a fresh Let's Encrypt certificate via
#   certbot, then reload nginx so the new cert is served.
#
# What this script DOES:
#   1. Reads the current cert expiry from the live endpoint.
#   2. SSHes to prod, runs `certbot renew` (Let's Encrypt's idempotent renewal).
#   3. Reloads nginx (zero-downtime — no socket drop).
#   4. Verifies the new expiry from the laptop side.
#
# What this script DOES NOT do:
#   - Force-renew if the existing cert is healthy (>30 days remaining).
#     Pass --force to override (only for emergencies).
#   - Touch DNS, change cert authority, or rotate keys for non-LE certs.
#
# Usage:
#   bash ops/runbooks/03-renew-tls-cert.sh           # standard renewal
#   bash ops/runbooks/03-renew-tls-cert.sh --force   # force even if healthy
#
# Idempotent:
#   Yes — certbot's own `renew` subcommand is idempotent. Re-running on a
#   freshly-renewed cert is a no-op and exits 0.
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# Configurable knobs
# -----------------------------------------------------------------------------
PROD_USER="${PROD_USER:-ubuntu}"
PROD_HOST="${PROD_HOST:-10.1.0.204}"
JUMP_HOST="${JUMP_HOST:-15.204.73.232}"
JUMP_PORT="${JUMP_PORT:-2222}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/openvpn-key-v2.pem}"
DOMAIN="${DOMAIN:-raf.comercioit.com}"

FORCE=0
if [ "${1:-}" = "--force" ]; then
    FORCE=1
fi

# -----------------------------------------------------------------------------
# 1. Pre-flight checks
# -----------------------------------------------------------------------------
echo "==> Pre-flight checks"

for cmd in openssl ssh date; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    fi
done

if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found at $SSH_KEY" >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# 2. Inspect the live certificate
# -----------------------------------------------------------------------------
echo "==> Inspecting current cert for ${DOMAIN}"

# Pull the live cert and parse notAfter. `set +e` because openssl s_client may
# exit non-zero if the cert is already expired — we still want the date.
set +e
LIVE_CERT="$(echo | openssl s_client -servername "$DOMAIN" -connect "${DOMAIN}:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null)"
set -e

if [ -z "$LIVE_CERT" ]; then
    echo "WARNING: could not fetch live cert (network? firewall?). Continuing anyway."
    DAYS_REMAINING=-1
else
    # `notAfter=May 20 12:34:56 2026 GMT` -> epoch
    NOT_AFTER="${LIVE_CERT#notAfter=}"
    # GNU date and BSD date both accept this format
    EXPIRY_EPOCH="$(date -j -f "%b %e %T %Y %Z" "$NOT_AFTER" +%s 2>/dev/null || date -d "$NOT_AFTER" +%s 2>/dev/null || echo 0)"
    NOW_EPOCH="$(date +%s)"
    DAYS_REMAINING=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    echo "    Current expiry: ${NOT_AFTER}"
    echo "    Days remaining: ${DAYS_REMAINING}"
fi

# -----------------------------------------------------------------------------
# 3. Decide whether to renew
# -----------------------------------------------------------------------------
if [ "$FORCE" -eq 0 ] && [ "$DAYS_REMAINING" -gt 30 ]; then
    echo
    echo "==> Cert has ${DAYS_REMAINING} days left — no renewal needed."
    echo "    (Let's Encrypt only renews certs with <30 days left by default.)"
    echo "    Re-run with --force to renew anyway."
    exit 0
fi

# -----------------------------------------------------------------------------
# 4. Remote renewal plan
# -----------------------------------------------------------------------------
if [ "$FORCE" -eq 1 ]; then
    CERTBOT_CMD="sudo certbot renew --force-renewal --non-interactive"
else
    CERTBOT_CMD="sudo certbot renew --non-interactive"
fi

REMOTE_PLAN=$(cat <<EOF
set -euo pipefail

echo "  Verifying certbot is installed..."
if ! command -v certbot >/dev/null 2>&1; then
    echo "  ERROR: certbot is not installed on prod. Install with:"
    echo "    sudo apt-get update && sudo apt-get install -y certbot python3-certbot-nginx"
    exit 1
fi

echo "  Current cert files:"
sudo ls -la /etc/letsencrypt/live/${DOMAIN}/ 2>/dev/null || {
    echo "  ERROR: /etc/letsencrypt/live/${DOMAIN}/ not found." >&2
    echo "  Was this domain ever issued by certbot? Run:" >&2
    echo "    sudo certbot certificates" >&2
    exit 1
}

echo "  Renewing..."
${CERTBOT_CMD}

echo "  New cert expiry per certbot:"
sudo openssl x509 -noout -enddate -in /etc/letsencrypt/live/${DOMAIN}/fullchain.pem

echo "  Reloading nginx (zero-downtime)..."
# nginx -t before reload — abort if config invalid
sudo nginx -t
sudo systemctl reload nginx
echo "  nginx reloaded."
EOF
)

# -----------------------------------------------------------------------------
# 5. Execute on prod
# -----------------------------------------------------------------------------
echo
echo "==> Running renewal on ${PROD_USER}@${PROD_HOST}"

ssh -T \
    -i "$SSH_KEY" \
    -o StrictHostKeyChecking=accept-new \
    -J "${PROD_USER}@${JUMP_HOST}:${JUMP_PORT}" \
    "${PROD_USER}@${PROD_HOST}" \
    bash <<< "$REMOTE_PLAN"

# -----------------------------------------------------------------------------
# 6. Verify from the laptop
# -----------------------------------------------------------------------------
echo
echo "==> Verifying new cert from laptop (this confirms nginx is serving it)"
sleep 2

NEW_CERT="$(echo | openssl s_client -servername "$DOMAIN" -connect "${DOMAIN}:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null || true)"

if [ -z "$NEW_CERT" ]; then
    echo "WARNING: could not fetch new cert — verify manually with:"
    echo "    echo | openssl s_client -servername ${DOMAIN} -connect ${DOMAIN}:443 2>/dev/null | openssl x509 -noout -enddate"
    exit 1
fi

NEW_NOT_AFTER="${NEW_CERT#notAfter=}"
NEW_EXPIRY_EPOCH="$(date -j -f "%b %e %T %Y %Z" "$NEW_NOT_AFTER" +%s 2>/dev/null || date -d "$NEW_NOT_AFTER" +%s 2>/dev/null || echo 0)"
NOW_EPOCH="$(date +%s)"
NEW_DAYS=$(( (NEW_EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

echo "    New expiry: ${NEW_NOT_AFTER}"
echo "    Days remaining: ${NEW_DAYS}"

if [ "$NEW_DAYS" -lt 60 ]; then
    echo
    echo "WARNING: new cert has only ${NEW_DAYS} days — Let's Encrypt issues 90-day"
    echo "certs, so something is off. Did certbot actually renew, or did nginx"
    echo "fail to reload? Check:"
    echo "    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST} 'sudo certbot certificates'"
    exit 1
fi

echo
echo "==> SUCCESS — cert renewed. ${NEW_DAYS} days remaining."
echo
echo "==> Rollback (Let's Encrypt keeps previous certs in /etc/letsencrypt/archive/):"
echo "    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST}"
echo "    sudo ls /etc/letsencrypt/archive/${DOMAIN}/"
echo "    # Identify the previous cert<N>.pem / privkey<N>.pem pair, then update"
echo "    # /etc/letsencrypt/live/${DOMAIN}/ symlinks to point at the older pair,"
echo "    # and sudo systemctl reload nginx."
echo
echo "==> NEXT: install the weekly TLS-expiry cron via runbook 04 so this never"
echo "          gets within 30 days again without alerting you."
