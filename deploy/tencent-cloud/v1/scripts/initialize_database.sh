#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${ZHJ_APP_ROOT:-/opt/zhiju/current}"
ENV_FILE="${ZHJ_ENV_FILE:-/etc/zhiju/zhiju-cloud.env}"

[[ -r "$ENV_FILE" ]] || { echo "Cloud environment file is not readable: $ENV_FILE" >&2; exit 1; }
set -a
source "$ENV_FILE"
set +a

# This validator rejects zhiju_prod and Studio hosts before Alembic can connect or migrate.
PYTHONPATH="$APP_ROOT/backend" "$APP_ROOT/.venv/bin/python" \
  "$APP_ROOT/deploy/tencent-cloud/v1/scripts/validate_environment.py"
PYTHONPATH="$APP_ROOT/backend" "$APP_ROOT/.venv/bin/alembic" \
  -c "$APP_ROOT/alembic.ini" upgrade head
