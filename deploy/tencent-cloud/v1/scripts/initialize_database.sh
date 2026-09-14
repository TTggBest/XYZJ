#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${ZHJ_APP_ROOT:-/opt/zhiju/current}"
APP_ENV_FILE="${ZHJ_APP_ENV_FILE:-/etc/zhiju/zhiju-app.env}"
ADMIN_ENV_FILE="${ZHJ_ADMIN_ENV_FILE:-/etc/zhiju/zhiju-admin.env}"

[[ -r "$APP_ENV_FILE" ]] || { echo "Cloud app environment file is not readable: $APP_ENV_FILE" >&2; exit 1; }
[[ -r "$ADMIN_ENV_FILE" ]] || { echo "Cloud admin environment file is not readable: $ADMIN_ENV_FILE" >&2; exit 1; }
set -a
source "$APP_ENV_FILE"
source "$ADMIN_ENV_FILE"
set +a

# This validator rejects zhiju_prod and Studio hosts before Alembic can connect or migrate.
PYTHONPATH="$APP_ROOT/backend" "$APP_ROOT/.venv/bin/python" \
  "$APP_ROOT/deploy/tencent-cloud/v1/scripts/validate_environment.py" --require-migration
PYTHONPATH="$APP_ROOT/backend" "$APP_ROOT/.venv/bin/alembic" \
  -c "$APP_ROOT/alembic.ini" upgrade head
