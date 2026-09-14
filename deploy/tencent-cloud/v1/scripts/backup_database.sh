#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ZHJ_ENV_FILE:-/etc/zhiju/zhiju-cloud.env}"
BACKUP_DIR="${ZHJ_BACKUP_DIR:-/var/lib/zhiju/backups}"
set -a
source "$ENV_FILE"
set +a
APP_ROOT="${ZHJ_APP_ROOT:-/opt/zhiju/current}"
PYTHONPATH="$APP_ROOT/backend" "$APP_ROOT/.venv/bin/python" \
  "$APP_ROOT/deploy/tencent-cloud/v1/scripts/validate_environment.py"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP_DIR"
# Credentials are read by mysql_config_editor/login-path; never placed in argv or output.
mysqldump --login-path=zhiju-backup --single-transaction --routines --triggers zhiju_cloud \
  | gzip -9 >"$BACKUP_DIR/zhiju_cloud-$timestamp.sql.gz"
echo "Backup written: $BACKUP_DIR/zhiju_cloud-$timestamp.sql.gz"
