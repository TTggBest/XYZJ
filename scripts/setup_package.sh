#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
CONFIG_DIR="$HOME/Library/Application Support/筱宇智矩"
CONFIG_FILE="$CONFIG_DIR/runtime.env"
SHARED_CONFIG=""
PYTHON_BIN=""

mkdir -p "$CONFIG_DIR"
for candidate in \
  "$HOME/Documents/XYData/XYZJ/config/zhiju-runtime.env" \
  "/Volumes/XYData/XYZJ/config/zhiju-runtime.env"; do
  if [[ -f "$candidate" ]]; then
    SHARED_CONFIG="$candidate"
    break
  fi
done
[[ -n "$SHARED_CONFIG" ]] || { echo "[安装失败] 未找到智矩生产配置，请确认 XYData/XYZJ 已就绪。"; exit 1; }

cp "$SHARED_CONFIG" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"
set -a
source "$CONFIG_FILE"
set +a
[[ "${ZHJ_ENV:-}" == "production" ]] || { echo "[安装失败] 智矩共享配置不是 production。"; exit 1; }
echo "[筱宇智矩] 已加载生产配置：$SHARED_CONFIG"

ln -sfn "$CONFIG_FILE" "$ROOT/.env"
for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
  if [[ -x "$candidate" ]]; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  BREW_BIN="$(command -v brew || true)"
  [[ -n "$BREW_BIN" ]] || { echo "[安装失败] 未找到 Homebrew，无法自动安装 Python 3.12。"; exit 1; }
  echo "[筱宇智矩] 正在安装 Python 3.12..."
  if ! "$BREW_BIN" install python@3.12; then
    echo "[筱宇智矩] Homebrew 依赖链接冲突，使用已有依赖继续安装 Python 3.12..."
    "$BREW_BIN" install --ignore-dependencies python@3.12
  fi
  PYTHON_BIN="$("$BREW_BIN" --prefix python@3.12)/bin/python3.12"
fi
[[ -x "$PYTHON_BIN" ]] || { echo "[安装失败] Python 3.12 安装后不可用：$PYTHON_BIN"; exit 1; }
echo "[筱宇智矩] 使用运行环境：$($PYTHON_BIN --version 2>&1)"
rm -rf "$ROOT/.venv"
"$PYTHON_BIN" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$ROOT/requirements-runtime.txt"
bash "$ROOT/scripts/ensure_local_production_mysql.sh"
PYTHONPATH="$ROOT/backend" "$ROOT/.venv/bin/python" "$ROOT/scripts/configure_package_device.py"
set -a
source "$CONFIG_FILE"
set +a
if [[ "${ZHJ_DEVICE_ROLE:-}" == "studio" ]]; then
  [[ -n "${ZHJ_MIGRATION_DATABASE_URL:-}" ]] || { echo "[安装失败] Studio 未配置智矩生产库迁移账号。"; exit 1; }
  echo "[筱宇智矩] 正在升级生产数据库结构..."
  PYTHONPATH="$ROOT/backend" "$ROOT/.venv/bin/alembic" -c "$ROOT/alembic.ini" upgrade head
fi
if [[ "${ZHJ_SKIP_DESKTOP_APP:-0}" != "1" ]]; then
  bash "$ROOT/scripts/create_package_app.sh"
fi
PYTHONPATH="$ROOT/backend" "$ROOT/.venv/bin/python" "$ROOT/scripts/preflight_package.py"
echo "[筱宇智矩] 生产运行包安装完成：$(cat "$ROOT/VERSION")"
