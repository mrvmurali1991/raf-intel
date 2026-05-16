#!/usr/bin/env bash
# RAF Intelligence Database Backup Script
#
# Usage:
#   ./scripts/backup.sh [--full|--raf-only|--openemr-only]

# Source .env from the repo root so cron invocations get DB credentials
# without requiring them to be baked into the crontab line.
if [ -f "$(dirname "$0")/../.env" ]; then
  set -a
  . "$(dirname "$0")/../.env"
  set +a
fi
#
# Environment variables:
#   RAF_DB_HOST            (default: 127.0.0.1)
#   RAF_DB_PORT            (default: 3309)
#   RAF_DB_USER            (required)
#   RAF_DB_PASSWORD        (required)
#   RAF_DB_NAME            (default: raf_intelligence)
#   OPENEMR_DB_HOST        (default: 127.0.0.1)
#   OPENEMR_DB_PORT        (default: 3309)
#   OPENEMR_DB_USER        (required)
#   OPENEMR_DB_PASSWORD    (required)
#   OPENEMR_DB_NAME        (default: openemr)
#   BACKUP_DIR             (default: ./data/backups)
#   BACKUP_RETENTION_DAYS  (default: 30)
#   BACKUP_ENCRYPTION_KEY  (optional — if set, backups are AES-256-CBC encrypted)
#   BACKUP_S3_BUCKET       (optional — if set, completed dump is uploaded to s3://$BACKUP_S3_BUCKET/)
#                          Requires AWS credentials available to `aws` CLI
#                          (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
#                           or an attached IAM role / ~/.aws/credentials profile).
#
# Exit codes:
#   0  — all requested backups completed successfully
#   1  — one or more backups failed or a required variable is missing

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

RAF_DB_HOST="${RAF_DB_HOST:-127.0.0.1}"
RAF_DB_PORT="${RAF_DB_PORT:-3309}"
RAF_DB_NAME="${RAF_DB_NAME:-raf_intelligence}"

OPENEMR_DB_HOST="${OPENEMR_DB_HOST:-127.0.0.1}"
OPENEMR_DB_PORT="${OPENEMR_DB_PORT:-3309}"
OPENEMR_DB_NAME="${OPENEMR_DB_NAME:-openemr}"

BACKUP_DIR="${BACKUP_DIR:-./data/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
BACKUP_MODE="full"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO  $*"; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN  $*" >&2; }
err()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR $*" >&2; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

if [[ $# -gt 1 ]]; then
    err "Too many arguments. Usage: $0 [--full|--raf-only|--openemr-only]"
    exit 1
fi

case "${1:-}" in
    --full)         BACKUP_MODE="full"        ;;
    --raf-only)     BACKUP_MODE="raf"         ;;
    --openemr-only) BACKUP_MODE="openemr"     ;;
    "")             BACKUP_MODE="full"        ;;
    *)
        err "Unknown option: $1. Expected --full, --raf-only, or --openemr-only."
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

if ! command -v mysqldump &>/dev/null; then
    err "mysqldump is not installed or not on PATH. Cannot proceed."
    exit 1
fi

if ! command -v gzip &>/dev/null; then
    err "gzip is not installed or not on PATH. Cannot proceed."
    exit 1
fi

# ---------------------------------------------------------------------------
# Validate required credentials based on mode
# ---------------------------------------------------------------------------

_check_raf_creds() {
    if [[ -z "${RAF_DB_USER:-}" ]]; then
        err "RAF_DB_USER is not set."
        exit 1
    fi
    if [[ -z "${RAF_DB_PASSWORD:-}" ]]; then
        err "RAF_DB_PASSWORD is not set."
        exit 1
    fi
}

_check_openemr_creds() {
    if [[ -z "${OPENEMR_DB_USER:-}" ]]; then
        err "OPENEMR_DB_USER is not set."
        exit 1
    fi
    if [[ -z "${OPENEMR_DB_PASSWORD:-}" ]]; then
        err "OPENEMR_DB_PASSWORD is not set."
        exit 1
    fi
}

case "$BACKUP_MODE" in
    full)    _check_raf_creds; _check_openemr_creds ;;
    raf)     _check_raf_creds    ;;
    openemr) _check_openemr_creds ;;
esac

# ---------------------------------------------------------------------------
# Prepare backup directory
# ---------------------------------------------------------------------------

mkdir -p "$BACKUP_DIR"
log "Backup directory: $(realpath "$BACKUP_DIR" 2>/dev/null || echo "$BACKUP_DIR")"
log "Mode: $BACKUP_MODE | Retention: ${BACKUP_RETENTION_DAYS} days"
if [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
    warn "BACKUP_ENCRYPTION_KEY is not set — backups will NOT be encrypted."
fi

# ---------------------------------------------------------------------------
# Core backup function
# ---------------------------------------------------------------------------
# dump_db <label> <host> <port> <user> <password> <dbname>
# Returns 0 on success, 1 on failure.  Writes <label>_<timestamp>.sql.gz.

dump_db() {
    local label="$1"
    local host="$2"
    local port="$3"
    local user="$4"
    local password="$5"
    local dbname="$6"

    local encrypt="${BACKUP_ENCRYPTION_KEY:-}"
    local ext="sql.gz"
    [[ -n "$encrypt" ]] && ext="sql.gz.enc"

    local filename="${label}_${TIMESTAMP}.${ext}"
    local filepath="${BACKUP_DIR}/${filename}"
    local tmpfile="${filepath}.tmp"

    [[ -n "$encrypt" ]] && log "Encryption: AES-256-CBC enabled"
    log "Starting backup: ${label} (${host}:${port}/${dbname}) -> ${filename}"

    # Use a temp file so a partial dump is never mistaken for a complete one.
    local pipeline="gzip -9"
    [[ -n "$encrypt" ]] && pipeline="gzip -9 | openssl enc -aes-256-cbc -salt -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY"

    if MYSQL_PWD="$password" mysqldump \
        --host="$host" \
        --port="$port" \
        --user="$user" \
        --single-transaction \
        --routines \
        --triggers \
        --add-drop-database \
        --databases "$dbname" \
        2>/tmp/raf_backup_mysqldump_stderr \
        | eval "$pipeline" > "$tmpfile"; then

        mv "$tmpfile" "$filepath"
        local size
        size="$(du -sh "$filepath" 2>/dev/null | cut -f1)"
        log "Backup complete: ${filename} (${size})"

        # Off-site replication: upload to S3 when BACKUP_S3_BUCKET is set.
        # Uses STANDARD_IA storage class for cost-efficient infrequent access.
        if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
            log "Uploading to s3://${BACKUP_S3_BUCKET}/"
            if ! aws s3 cp "$filepath" "s3://${BACKUP_S3_BUCKET}/$(basename "$filepath")" --storage-class STANDARD_IA; then
                err "S3 upload failed for ${filename}"
                return 1
            fi
            log "S3 upload complete: s3://${BACKUP_S3_BUCKET}/$(basename "$filepath")"
        fi

        return 0
    else
        local exit_code=$?
        local stderr_content
        stderr_content="$(cat /tmp/raf_backup_mysqldump_stderr 2>/dev/null || true)"
        err "Backup FAILED: ${label} — mysqldump exited with code ${exit_code}"
        [[ -n "$stderr_content" ]] && err "mysqldump stderr: ${stderr_content}"
        rm -f "$tmpfile"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Run backups
# ---------------------------------------------------------------------------

FAILED=0

if [[ "$BACKUP_MODE" == "full" || "$BACKUP_MODE" == "raf" ]]; then
    dump_db "raf_intelligence" \
        "$RAF_DB_HOST" "$RAF_DB_PORT" \
        "$RAF_DB_USER" "$RAF_DB_PASSWORD" \
        "$RAF_DB_NAME" || FAILED=1
fi

if [[ "$BACKUP_MODE" == "full" || "$BACKUP_MODE" == "openemr" ]]; then
    dump_db "openemr" \
        "$OPENEMR_DB_HOST" "$OPENEMR_DB_PORT" \
        "$OPENEMR_DB_USER" "$OPENEMR_DB_PASSWORD" \
        "$OPENEMR_DB_NAME" || FAILED=1
fi

# ---------------------------------------------------------------------------
# Rotate old backups
# ---------------------------------------------------------------------------

log "Rotating backups older than ${BACKUP_RETENTION_DAYS} days in ${BACKUP_DIR} ..."

deleted_count=0
while IFS= read -r -d '' old_file; do
    log "Deleting expired backup: $(basename "$old_file")"
    rm -f "$old_file"
    (( deleted_count++ )) || true
done < <(find "$BACKUP_DIR" -maxdepth 1 \( -name "*.sql.gz" -o -name "*.sql.gz.enc" \) \
    -mtime +"$BACKUP_RETENTION_DAYS" -print0 2>/dev/null)

if [[ $deleted_count -gt 0 ]]; then
    log "Rotation complete: removed ${deleted_count} expired backup(s)."
else
    log "Rotation complete: no expired backups found."
fi

# ---------------------------------------------------------------------------
# Final status
# ---------------------------------------------------------------------------

if [[ $FAILED -ne 0 ]]; then
    err "One or more backups failed. See errors above."
    exit 1
fi

log "All backups completed successfully."
exit 0
