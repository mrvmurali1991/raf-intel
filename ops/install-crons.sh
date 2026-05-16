#!/usr/bin/env bash
# =============================================================================
# install-crons.sh — Install the RAF Intelligence cron jobs into /etc/cron.d
#
# Usage:
#   sudo bash ops/install-crons.sh
#
# Idempotent: re-running just overwrites the existing /etc/cron.d/* files with
# the repo copy and reloads cron.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_SRC="${SCRIPT_DIR}/cron"
CRON_DST="/etc/cron.d"

# Must run as root so we can write to /etc/cron.d
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: install-crons.sh must be run as root (use sudo)." >&2
    exit 1
fi

# Source files we ship in the repo
files=(raf-backup raf-tls-check)

for f in "${files[@]}"; do
    src="${CRON_SRC}/${f}"
    dst="${CRON_DST}/${f}"
    [ -f "$src" ] || { echo "ERROR: missing source ${src}" >&2; exit 1; }

    # cron.d files MUST be owned by root and not world-writable; chmod 644 is
    # the conventional permission for entries in /etc/cron.d.
    install -o root -g root -m 0644 "$src" "$dst"
    echo "Installed ${dst}"

    # Validate syntax when crontab supports -T (Debian/Ubuntu vixie-cron does)
    if crontab -T "$dst" >/dev/null 2>&1; then
        echo "  syntax OK"
    elif crontab -T --help >/dev/null 2>&1; then
        # -T exists but rejected — re-run to surface the error
        crontab -T "$dst" || { echo "ERROR: ${dst} failed crontab -T validation" >&2; exit 1; }
    else
        echo "  (crontab -T not available — skipping syntax check)"
    fi
done

# Reload cron — try systemd first, fall back to service(8) for older boxes.
if command -v systemctl >/dev/null 2>&1; then
    systemctl reload cron 2>/dev/null || systemctl restart cron
elif command -v service >/dev/null 2>&1; then
    service cron reload 2>/dev/null || service cron restart
else
    echo "WARNING: could not reload cron — restart it manually." >&2
fi

echo "All cron jobs installed and cron reloaded."
