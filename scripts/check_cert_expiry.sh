#!/usr/bin/env bash
# check_cert_expiry.sh — Print days-until-expiry for RAF TLS certs.
# Exits 0 when all certs are >= WARN_DAYS away; exits 1 if any are below.
#
# Usage:
#   bash /home/ubuntu/raf-intelligence/scripts/check_cert_expiry.sh
#
# Recommended crontab (run as ubuntu on 10.1.0.204):
#   0 8 * * 1 /home/ubuntu/raf-intelligence/scripts/check_cert_expiry.sh \
#               >> /var/log/raf-cert-check.log 2>&1
#
# The script logs a timestamped line to stdout every run, and exits 1 on expiry
# warning so the cron mailer (MAILTO=...) will fire automatically.

set -euo pipefail

WARN_DAYS=30
DOMAINS=(
  "raf.comercioit.com"
  "raf-api.comercioit.com"
)

overall_ok=0
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

for domain in "${DOMAINS[@]}"; do
  # Pull the leaf certificate's notAfter field
  expiry_raw=$(
    openssl s_client -connect "${domain}:443" -servername "${domain}" \
      </dev/null 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null \
    | cut -d= -f2
  )

  if [[ -z "$expiry_raw" ]]; then
    echo "${timestamp} ERROR: could not retrieve cert for ${domain}" >&2
    overall_ok=1
    continue
  fi

  # Convert expiry date to epoch seconds (GNU date on Linux)
  expiry_epoch=$(date -d "${expiry_raw}" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "${expiry_raw}" +%s)
  now_epoch=$(date +%s)
  days_left=$(( (expiry_epoch - now_epoch) / 86400 ))

  if (( days_left < WARN_DAYS )); then
    echo "${timestamp} WARNING: ${domain} cert expires in ${days_left} day(s) (${expiry_raw}) — RENEW NOW"
    overall_ok=1
  else
    echo "${timestamp} OK: ${domain} cert expires in ${days_left} day(s) (${expiry_raw})"
  fi
done

exit "${overall_ok}"
