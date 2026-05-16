#!/usr/bin/env bash
# =============================================================================
# 02-rotate-jwt-secret.sh — Rotate JWT_SECRET in production (BLOCKER)
#
# Why:
#   `.env.example` currently ships the literal placeholder `<rotate-before-prod>`
#   for JWT_SECRET. If prod inherited that placeholder (or any short/guessable
#   value) every signed token is trivially forgeable. Rotating it is the single
#   highest-leverage action on the readiness checklist.
#
# What this script DOES:
#   1. Generates a cryptographically strong 64-byte (512-bit) secret.
#   2. Prints the exact commands you need to run on the prod host to update
#      /opt/raf-intelligence/.env and restart the backend.
#   3. Optionally — if you pass --apply — runs those commands for you via SSH.
#
# What this script DOES NOT do by default:
#   - Touch prod (safe by default — prints plan, no side effects).
#   - Commit the secret anywhere (the secret is printed to stdout only — pipe
#     it straight to your password manager, do not paste into git/Slack).
#
# Usage:
#   bash ops/runbooks/02-rotate-jwt-secret.sh          # dry-run: print plan
#   bash ops/runbooks/02-rotate-jwt-secret.sh --apply  # apply via SSH
#
# Idempotent:
#   Re-running with --apply rotates the secret AGAIN (issuing fresh secret each
#   time). That logs out everyone again but is otherwise safe.
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# Configurable knobs — override via env if your topology differs.
# -----------------------------------------------------------------------------
PROD_USER="${PROD_USER:-ubuntu}"
PROD_HOST="${PROD_HOST:-10.1.0.204}"
JUMP_HOST="${JUMP_HOST:-15.204.73.232}"
JUMP_PORT="${JUMP_PORT:-2222}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/openvpn-key-v2.pem}"
PROD_ENV_PATH="${PROD_ENV_PATH:-/opt/raf-intelligence/.env}"
PROD_COMPOSE_DIR="${PROD_COMPOSE_DIR:-/opt/raf-intelligence}"

APPLY=0
if [ "${1:-}" = "--apply" ]; then
    APPLY=1
fi

# -----------------------------------------------------------------------------
# 1. Sanity checks
# -----------------------------------------------------------------------------
echo "==> Pre-flight checks"

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl is required to generate the secret." >&2
    exit 1
fi

if [ "$APPLY" -eq 1 ]; then
    if [ ! -f "$SSH_KEY" ]; then
        echo "ERROR: SSH key not found at $SSH_KEY" >&2
        echo "       Set SSH_KEY=... or run without --apply to see the plan." >&2
        exit 1
    fi
    if ! command -v ssh >/dev/null 2>&1; then
        echo "ERROR: ssh client not found." >&2
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# 2. Generate the new secret
# -----------------------------------------------------------------------------
echo "==> Generating new JWT_SECRET (64 bytes, base64url)"

# 64 random bytes -> base64url, stripped of padding. Yields ~86 chars of entropy.
NEW_SECRET="$(openssl rand -base64 64 | tr '+/' '-_' | tr -d '=\n')"

if [ "${#NEW_SECRET}" -lt 64 ]; then
    echo "ERROR: generated secret unexpectedly short (${#NEW_SECRET} chars)." >&2
    exit 1
fi

echo "    Generated $(printf '%s' "$NEW_SECRET" | wc -c | tr -d ' ') chars of entropy."

# -----------------------------------------------------------------------------
# 3. Build the remote update plan
# -----------------------------------------------------------------------------
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_PATH="${PROD_ENV_PATH}.bak.${TIMESTAMP}"

# We use a temp file on the remote side to avoid embedding the secret in `sed`
# (which would leak it via /proc/<pid>/cmdline to anyone shelled in).
REMOTE_PLAN=$(cat <<EOF
set -euo pipefail

# Back up the existing env file (so we can rollback)
sudo cp "${PROD_ENV_PATH}" "${BACKUP_PATH}"
sudo chmod 600 "${BACKUP_PATH}"

# Write the new secret to a root-owned temp file and read via env file expansion
NEW_SECRET_TMP="\$(sudo mktemp)"
sudo chmod 600 "\$NEW_SECRET_TMP"
sudo tee "\$NEW_SECRET_TMP" >/dev/null <<'__SECRET__'
__NEW_SECRET_PLACEHOLDER__
__SECRET__

# Replace the JWT_SECRET line (or append if absent). Use python for safe quoting.
sudo python3 - "${PROD_ENV_PATH}" "\$NEW_SECRET_TMP" <<'__PY__'
import sys, pathlib
env_path = pathlib.Path(sys.argv[1])
secret = pathlib.Path(sys.argv[2]).read_text().strip()
lines = env_path.read_text().splitlines()
out = []
found = False
for line in lines:
    if line.startswith('JWT_SECRET='):
        out.append(f'JWT_SECRET={secret}')
        found = True
    else:
        out.append(line)
if not found:
    out.append(f'JWT_SECRET={secret}')
env_path.write_text('\n'.join(out) + '\n')
print(f'  JWT_SECRET line updated ({"replaced" if found else "appended"})')
__PY__

sudo shred -u "\$NEW_SECRET_TMP" 2>/dev/null || sudo rm -f "\$NEW_SECRET_TMP"

# Confirm the line is present (without printing the secret value)
if sudo grep -q '^JWT_SECRET=' "${PROD_ENV_PATH}"; then
    SECRET_LEN=\$(sudo awk -F= '/^JWT_SECRET=/{print length(\$2)}' "${PROD_ENV_PATH}")
    echo "  JWT_SECRET present in ${PROD_ENV_PATH} (length: \$SECRET_LEN chars)"
else
    echo "  ERROR: JWT_SECRET not found after write" >&2
    exit 1
fi

# Restart backend so the new secret is picked up
cd "${PROD_COMPOSE_DIR}"
sudo docker compose restart backend
sudo docker compose ps backend
EOF
)

# Inject the secret into the heredoc placeholder (kept out of the shell history)
REMOTE_PLAN="${REMOTE_PLAN/__NEW_SECRET_PLACEHOLDER__/$NEW_SECRET}"

# -----------------------------------------------------------------------------
# 4. Either print the plan (dry-run) or execute it via SSH (--apply)
# -----------------------------------------------------------------------------
if [ "$APPLY" -eq 0 ]; then
    cat <<EOF

==> DRY RUN — no changes have been made.

The new secret is (save this to your password manager NOW, you only see it once):

--- BEGIN JWT_SECRET ---
${NEW_SECRET}
--- END JWT_SECRET ---

To apply, re-run with --apply:

    bash ops/runbooks/02-rotate-jwt-secret.sh --apply

Or, if you prefer manual application, SSH to prod yourself and run these commands.
(Note: the heredoc placeholder below is for documentation — re-run with --apply
to get a fresh secret automatically embedded.)

    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST}

Then on the prod host, set JWT_SECRET in ${PROD_ENV_PATH}, back up first:

    sudo cp ${PROD_ENV_PATH} ${BACKUP_PATH}
    sudoedit ${PROD_ENV_PATH}    # paste the secret into the JWT_SECRET= line
    cd ${PROD_COMPOSE_DIR} && sudo docker compose restart backend

EOF
    exit 0
fi

# -----------------------------------------------------------------------------
# 5. APPLY mode — run the plan on prod
# -----------------------------------------------------------------------------
echo
echo "==> Applying new JWT_SECRET to ${PROD_USER}@${PROD_HOST} (via jump host)"
echo "    Backup will be saved at: ${BACKUP_PATH}"
echo
echo "==> Save this secret in your password manager NOW:"
echo
echo "--- BEGIN JWT_SECRET ---"
echo "${NEW_SECRET}"
echo "--- END JWT_SECRET ---"
echo
read -r -p "Have you saved the secret? Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted — no changes made on prod."
    exit 1
fi

# Pipe the plan into the remote bash. Use `-T` to disable PTY (no echo of secret).
ssh -T \
    -i "$SSH_KEY" \
    -o StrictHostKeyChecking=accept-new \
    -J "${PROD_USER}@${JUMP_HOST}:${JUMP_PORT}" \
    "${PROD_USER}@${PROD_HOST}" \
    bash <<< "$REMOTE_PLAN"

echo
echo "==> JWT_SECRET rotated and backend restarted."
echo
echo "==> Verification (run these from your laptop):"
echo
echo "    # 1. Healthcheck should still be 200"
echo "    curl -s -o /dev/null -w '%{http_code}\\n' https://raf.comercioit.com/healthz"
echo
echo "    # 2. All existing JWTs should now 401 — verify by hitting an authed endpoint"
echo "    #    with an OLD token (should be 401 Unauthorized)."
echo
echo "    # 3. New login should succeed (returns fresh token signed with new secret)"
echo "    curl -s -X POST https://raf.comercioit.com/api/auth/login \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"email\":\"admin@raf.health\",\"password\":\"Admin@123\"}' | jq .access_token | head -c 40"
echo
echo "==> Rollback (only if everything is on fire):"
echo
echo "    ssh -i ${SSH_KEY} -J ${PROD_USER}@${JUMP_HOST}:${JUMP_PORT} ${PROD_USER}@${PROD_HOST} \\"
echo "      'sudo cp ${BACKUP_PATH} ${PROD_ENV_PATH} && cd ${PROD_COMPOSE_DIR} && sudo docker compose restart backend'"
echo
