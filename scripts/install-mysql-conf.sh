#!/usr/bin/env bash
# Install the RAF Intelligence MySQL persistent configuration.
#
# This script is REQUIRED on every host running MySQL for RAF Intelligence.
# The project memory note `feedback_mysql_binlog_growth` documents that
# binlog retention is currently set via `SET GLOBAL` at runtime, which
# reverts to MySQL's 30-day default on restart and grows ~100 MB/min on
# 10.1.0.204, filling disk within days.
#
# This script copies mysql/my.cnf into MySQL's drop-in conf.d directory
# (/etc/mysql/conf.d/raf-intelligence.cnf) and restarts the mysql service
# so the values in my.cnf take effect persistently across reboots.
#
# Usage (as root or via sudo):
#   sudo ./scripts/install-mysql-conf.sh
#
# Verify afterwards:
#   mysql -e "SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/../mysql/my.cnf"
DEST="/etc/mysql/conf.d/raf-intelligence.cnf"

if [[ ! -f "$SRC" ]]; then
    echo "ERROR: source config not found at $SRC" >&2
    exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: must be run as root (try: sudo $0)" >&2
    exit 1
fi

echo "Installing $SRC -> $DEST"
install -m 0644 -o root -g root "$SRC" "$DEST"

echo "Restarting MySQL ..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl restart mysql || systemctl restart mysqld
else
    service mysql restart || service mysqld restart
fi

echo "Done. Verify with: mysql -e \"SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';\""
