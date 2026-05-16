#!/usr/bin/env bash
# =============================================================================
# 04-install-prod-crons.sh — Install raf-backup + raf-tls-check crons on prod
#
# Why:
#   Per docs/READINESS_MATRIX.md § Operational Checklist item 3, ops/install-crons.sh
#   is in the repo but has never been executed on the prod host. Without these
#   crons:
#     - raf-backup: NO nightly DB backups (data-loss exposure window = forever)
#     - raf-tls-check: NO weekly TLS-expiry alert (we relearn TLS pain every 90d)
#
# What this script DOES:
#   1. Ensures /opt/raf-intelligence on prod has the latest copy of ops/cron/*
#      and ops/install-crons.sh (via `git pull` on prod or a scp fallback).
#   2. Runs `sudo bash /opt/raf-intelligence/ops/install-crons.sh` on prod.
#   3. Verifies the two files now exist in /etc/cron.d/ and cron is running.
#
# What this script DOES NOT do:
#   - Modify /etc/cron.d files outside of those owned by RAF.
#   - Touch the underlying backup.sh or check-tls-expiry.sh scripts (those are
#     already committed in scripts/).
#
# Usage:
#   bash ops/runbooks/04-install-prod-crons.sh
#
# Idempotent:
#   Yes — install-crons.sh uses `install -m 0644` which overwrites in place.
#   Re-running just refreshes the cron files from repo.
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
PROD_REPO_DIR="${PROD_REPO_DIR:-/opt/raf-intelligence}"
PROD_BRANCH="${PROD_BRANCH:-fix/post-review-batch-10}"

# -----------------------------------------------------------------------------
# 1. Pre-flight
# -----------------------------------------------------------------------------
echo "==> Pre-flight checks"

if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found at $SSH_KEY" >&2
    exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
    echo "ERROR: ssh client not found." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# 2. Remote plan: refresh repo, install crons, verify
# -----------------------------------------------------------------------------
REMOTE_PLAN=$(cat <<EOF
set -euo pipefail

cd "${PROD_REPO_DIR}"

echo "  Current repo state on prod:"
git status --short || true
git log --oneline -1

# Per memory: prod often has WIP drift. Stash anything dirty before pulling so
# we never lose local edits — but ONLY stash, never discard.
if ! git diff --quiet || ! git diff --cached --quiet; then
    STASH_MSG="auto-stash-before-cron-install-\$(date +%Y%m%d-%H%M%S)"
    echo "  Stashing local edits as: \$STASH_MSG"
    git stash push -u -m "\$STASH_MSG"
fi

echo "  Fetching latest..."
git fetch origin "${PROD_BRANCH}"

echo "  Checking out / refreshing ${PROD_BRANCH}..."
git checkout "${PROD_BRANCH}"
git pull --ff-only origin "${PROD_BRANCH}" || {
    echo "  WARNING: fast-forward pull failed (prod has unpushed commits per memory)."
    echo "  Continuing with the version of ops/install-crons.sh currently on disk."
}

if [ ! -f "${PROD_REPO_DIR}/ops/install-crons.sh" ]; then
    echo "  ERROR: ops/install-crons.sh not found at ${PROD_REPO_DIR}/ops/install-crons.sh" >&2
    exit 1
fi

echo "  Verifying source cron files exist..."
for f in raf-backup raf-tls-check; do
    test -f "${PROD_REPO_DIR}/ops/cron/\$f" || {
        echo "  ERROR: ${PROD_REPO_DIR}/ops/cron/\$f missing" >&2
        exit 1
    }
done

echo "  Installing crons (requires sudo)..."
sudo bash "${PROD_REPO_DIR}/ops/install-crons.sh"

echo "  Verifying /etc/cron.d/ entries..."
for f in raf-backup raf-tls-check; do
    if [ -f "/etc/cron.d/\$f" ]; then
        echo "    /etc/cron.d/\$f present (\$(sudo stat -c '%a %U:%G' /etc/cron.d/\$f))"
    else
        echo "  ERROR: /etc/cron.d/\$f not installed" >&2
        exit 1
    fi
done

echo "  Verifying cron daemon is running..."
if systemctl is-active --quiet cron; then
    echo "    cron service is active"
else
    echo "  ERROR: cron service is not active — start it with: sudo systemctl start cron" >&2
    exit 1
fi

echo "  Verifying backup script + TLS check script are executable..."
for s in scripts/backup.sh scripts/check-tls-expiry.sh; do
    if [ -x "${PROD_REPO_DIR}/\$s" ]; then
        echo "    \$s is executable"
    else
        echo "  WARNING: \$s is not executable — fixing..."
        sudo chmod +x "${PROD_REPO_DIR}/\$s"
    fi
done

echo "  Log files (created on first cron run):"
sudo ls -la /var/log/raf-backup.log /var/log/raf-tls.log 2>/dev/null || \
    echo "    (no log files yet — that's expected before first cron fire)"

echo "  Next backup run (per /etc/cron.d/raf-backup):"
sudo cat /etc/cron.d/raf-backup | grep -v '^#'
echo "  Next TLS-check run (per /etc/cron.d/raf-tls-check):"
sudo cat /etc/cron.d/raf-tls-check | grep -v '^#'
EOF
)

# -----------------------------------------------------------------------------
# 3. Execute on prod
# -----------------------------------------------------------------------------
echo
echo "==> Running cron installer on ${PROD_USER}@${PROD_HOST}"

ssh -T \
    -i "$SSH_KEY" \
    -o StrictHostKeyChecking=accept-new \
    -J "${PROD_USER}@${JUMP_HOST}:${JUMP_PORT}" \
    "${PROD_USER}@${PROD_HOST}" \
    bash <<< "$REMOTE_PLAN"

# -----------------------------------------------------------------------------
# 4. Smoke-test the backup script (manual one-shot fire)
# -----------------------------------------------------------------------------
echo
echo "==> Smoke test — fire the backup once manually to confirm it works"
echo "    (this writes a real backup; harmless and recommended)"
read -r -p "Run smoke test now? [y/N]: " RUN_SMOKE
if [ "${RUN_SMOKE:-N}" = "y" ] || [ "${RUN_SMOKE:-N}" = "Y" ]; then
    ssh -T \
        -i "$SSH_KEY" \
        -J "${PROD_USER}@${JUMP_HOST}:${JUMP_PORT}" \
        "${PROD_USER}@${PROD_HOST}" \
        bash <<EOF
set -euo pipefail
echo "  Running ${PROD_REPO_DIR}/scripts/backup.sh manually..."
sudo bash "${PROD_REPO_DIR}/scripts/backup.sh" 2>&1 | tail -20
echo
echo "  Recent backups:"
sudo ls -lat /var/backups/raf-intelligence/ 2>/dev/null | head -5 || \
    sudo ls -lat /var/backups/ 2>/dev/null | head -5
EOF
else
    echo "    Skipped. Wait until 02:00 UTC for the first scheduled run."
fi

echo
echo "==> Verification (run these from your laptop tomorrow):"
echo
echo "    # After 02:00 UTC tonight — verify nightly backup ran"
echo "    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST} \\"
echo "      'sudo tail -50 /var/log/raf-backup.log'"
echo
echo "    # After next Monday 09:00 — verify weekly TLS check ran"
echo "    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST} \\"
echo "      'sudo tail -50 /var/log/raf-tls.log'"
echo
echo "==> Rollback (remove the crons):"
echo
echo "    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST} \\"
echo "      'sudo rm -f /etc/cron.d/raf-backup /etc/cron.d/raf-tls-check && sudo systemctl reload cron'"
echo
echo "==> Done."
