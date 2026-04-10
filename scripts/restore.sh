#!/usr/bin/env bash
# RAF Intelligence Database Restore Script
#
# Usage:
#   ./scripts/restore.sh <backup_file.sql.gz> [--raf|--openemr]
#
# The database target flag controls which connection credentials are used
# (RAF_DB_* or OPENEMR_DB_*).  The dump itself selects which schema is
# restored — the flag simply points the mysql client at the right server.
#
# Environment variables:
#   RAF_DB_HOST         (default: 127.0.0.1)
#   RAF_DB_PORT         (default: 3309)
#   RAF_DB_USER         (required for --raf)
#   RAF_DB_PASSWORD     (required for --raf)
#   OPENEMR_DB_HOST     (default: 127.0.0.1)
#   OPENEMR_DB_PORT     (default: 3309)
#   OPENEMR_DB_USER     (required for --openemr)
#   OPENEMR_DB_PASSWORD (required for --openemr)
#
# Exit codes:
#   0 — restore completed successfully
#   1 — validation error, user aborted, or restore failed

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

RAF_DB_HOST="${RAF_DB_HOST:-127.0.0.1}"
RAF_DB_PORT="${RAF_DB_PORT:-3309}"

OPENEMR_DB_HOST="${OPENEMR_DB_HOST:-127.0.0.1}"
OPENEMR_DB_PORT="${OPENEMR_DB_PORT:-3309}"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO  $*"; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN  $*" >&2; }
err()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR $*" >&2; }

# ---------------------------------------------------------------------------
# Usage / argument parsing
# ---------------------------------------------------------------------------

usage() {
    echo "Usage: $0 <backup_file.sql.gz> [--raf|--openemr]"
    echo ""
    echo "  <backup_file.sql.gz>   Path to the gzip-compressed SQL dump to restore."
    echo "  --raf                  Restore using RAF Intelligence DB credentials."
    echo "  --openemr              Restore using OpenEMR DB credentials."
    echo ""
    echo "If the target flag is omitted the script infers the target from the"
    echo "backup filename (looks for 'openemr' or 'raf_intelligence')."
}

if [[ $# -lt 1 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 1
fi

BACKUP_FILE="$1"
TARGET_FLAG="${2:-}"

# ---------------------------------------------------------------------------
# Validate backup file
# ---------------------------------------------------------------------------

if [[ ! -e "$BACKUP_FILE" ]]; then
    err "Backup file not found: $BACKUP_FILE"
    exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
    err "Path exists but is not a regular file: $BACKUP_FILE"
    exit 1
fi

if [[ ! -r "$BACKUP_FILE" ]]; then
    err "Backup file is not readable: $BACKUP_FILE"
    exit 1
fi

# Detect encrypted backups
IS_ENCRYPTED=0
if [[ "$BACKUP_FILE" == *.enc ]]; then
    IS_ENCRYPTED=1
    if [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
        err "Backup file is encrypted but BACKUP_ENCRYPTION_KEY is not set."
        exit 1
    fi
    if ! command -v openssl &>/dev/null; then
        err "openssl is required to decrypt .enc backups."
        exit 1
    fi
else
    # Verify it looks like a valid gzip file
    if ! gzip -t "$BACKUP_FILE" 2>/dev/null; then
        err "File does not appear to be a valid gzip archive: $BACKUP_FILE"
        exit 1
    fi
fi

BACKUP_BASENAME="$(basename "$BACKUP_FILE")"
BACKUP_SIZE="$(du -sh "$BACKUP_FILE" 2>/dev/null | cut -f1)"

# ---------------------------------------------------------------------------
# Infer or validate target
# ---------------------------------------------------------------------------

if [[ -z "$TARGET_FLAG" ]]; then
    if [[ "$BACKUP_BASENAME" == openemr* ]]; then
        TARGET_FLAG="--openemr"
        warn "Target flag not provided; inferred --openemr from filename."
    elif [[ "$BACKUP_BASENAME" == raf_intelligence* ]]; then
        TARGET_FLAG="--raf"
        warn "Target flag not provided; inferred --raf from filename."
    else
        err "Cannot infer target database from filename '${BACKUP_BASENAME}'."
        err "Specify --raf or --openemr explicitly."
        exit 1
    fi
fi

case "$TARGET_FLAG" in
    --raf)
        DB_LABEL="RAF Intelligence"
        DB_HOST="$RAF_DB_HOST"
        DB_PORT="$RAF_DB_PORT"
        if [[ -z "${RAF_DB_USER:-}" ]]; then
            err "RAF_DB_USER is not set."
            exit 1
        fi
        if [[ -z "${RAF_DB_PASSWORD:-}" ]]; then
            err "RAF_DB_PASSWORD is not set."
            exit 1
        fi
        DB_USER="$RAF_DB_USER"
        DB_PASSWORD="$RAF_DB_PASSWORD"
        ;;
    --openemr)
        DB_LABEL="OpenEMR"
        DB_HOST="$OPENEMR_DB_HOST"
        DB_PORT="$OPENEMR_DB_PORT"
        if [[ -z "${OPENEMR_DB_USER:-}" ]]; then
            err "OPENEMR_DB_USER is not set."
            exit 1
        fi
        if [[ -z "${OPENEMR_DB_PASSWORD:-}" ]]; then
            err "OPENEMR_DB_PASSWORD is not set."
            exit 1
        fi
        DB_USER="$OPENEMR_DB_USER"
        DB_PASSWORD="$OPENEMR_DB_PASSWORD"
        ;;
    *)
        err "Unknown target flag: $TARGET_FLAG. Expected --raf or --openemr."
        usage
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

if ! command -v mysql &>/dev/null; then
    err "mysql client is not installed or not on PATH. Cannot proceed."
    exit 1
fi

if ! command -v gzip &>/dev/null; then
    err "gzip is not installed or not on PATH. Cannot proceed."
    exit 1
fi

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

echo ""
echo "  ┌─────────────────────────────────────────────────────────────┐"
echo "  │                  !! DESTRUCTIVE OPERATION !!                │"
echo "  │                                                             │"
echo "  │  This will overwrite the target database with the contents  │"
echo "  │  of the backup file. All existing data will be replaced.    │"
echo "  └─────────────────────────────────────────────────────────────┘"
echo ""
echo "  Backup file : $BACKUP_FILE ($BACKUP_SIZE)"
echo "  Target DB   : $DB_LABEL ($DB_HOST:$DB_PORT)"
echo "  User        : $DB_USER"
echo ""

read -rp "  Type 'yes' to confirm restore: " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    log "Restore aborted by user."
    exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# Perform restore
# ---------------------------------------------------------------------------

log "Starting restore: ${BACKUP_BASENAME} -> ${DB_LABEL} (${DB_HOST}:${DB_PORT})"

if [[ $IS_ENCRYPTED -eq 1 ]]; then
    log "Decrypting (AES-256-CBC) and decompressing..."
    DECOMPRESS_CMD="openssl enc -aes-256-cbc -d -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY -in '$BACKUP_FILE' | gzip -dc"
else
    log "Decompressing and piping to mysql..."
    DECOMPRESS_CMD="gzip -dc '$BACKUP_FILE'"
fi

if eval "$DECOMPRESS_CMD" \
    | MYSQL_PWD="$DB_PASSWORD" mysql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --user="$DB_USER" \
        2>/tmp/raf_restore_mysql_stderr; then

    log "Restore completed successfully: ${BACKUP_BASENAME} -> ${DB_LABEL}"
    exit 0
else
    exit_code=$?
    stderr_content="$(cat /tmp/raf_restore_mysql_stderr 2>/dev/null || true)"
    err "Restore FAILED: mysql exited with code ${exit_code}"
    [[ -n "$stderr_content" ]] && err "mysql stderr: ${stderr_content}"
    exit 1
fi
