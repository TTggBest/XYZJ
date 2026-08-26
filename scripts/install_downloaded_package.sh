#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-}"
NEW_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
CURRENT_ROOT="$HOME/Downloads/zhiju-runtime-current"
OLD_ROOT="$HOME/Downloads/.zhiju-runtime-old-$$"
PORT=19732

[[ -f "$NEW_ROOT/VERSION" ]] || { echo "[安装失败] 运行包缺少 VERSION。"; exit 1; }
[[ -x "$NEW_ROOT/scripts/setup_package.sh" ]] || { echo "[安装失败] 运行包缺少安装脚本。"; exit 1; }

echo "[筱宇智矩] 正在安装生产版：$(cat "$NEW_ROOT/VERSION")"
ZHJ_SKIP_DESKTOP_APP=1 bash "$NEW_ROOT/scripts/setup_package.sh"

if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" 2>/dev/null | grep -q '筱宇智矩'; then
  OLD_PID="$(lsof -tiTCP:${PORT} -sTCP:LISTEN | head -n 1)"
  echo "[筱宇智矩] 正在停止旧版服务（PID ${OLD_PID}）..."
  kill -TERM "$OLD_PID"
  for _ in $(seq 1 50); do
    lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.2
  done
fi
if lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[安装失败] 端口 ${PORT} 被非智矩进程占用。"
  exit 1
fi

if [[ -e "$CURRENT_ROOT" ]]; then
  mv "$CURRENT_ROOT" "$OLD_ROOT"
fi
if ! mv "$NEW_ROOT" "$CURRENT_ROOT"; then
  [[ ! -e "$OLD_ROOT" ]] || mv "$OLD_ROOT" "$CURRENT_ROOT"
  exit 1
fi

if ! bash "$CURRENT_ROOT/scripts/create_package_app.sh"; then
  rm -rf "$CURRENT_ROOT"
  [[ ! -e "$OLD_ROOT" ]] || mv "$OLD_ROOT" "$CURRENT_ROOT"
  [[ ! -x "$CURRENT_ROOT/scripts/create_package_app.sh" ]] || bash "$CURRENT_ROOT/scripts/create_package_app.sh"
  exit 1
fi

rm -rf "$OLD_ROOT"
find "$HOME/Downloads" -maxdepth 1 -type f -name 'zhiju-runtime-*.tar.gz' -exec rm -f {} +
find "$HOME/Downloads" -maxdepth 1 -type d -name '.zhiju-runtime-new.*' -exec rm -rf {} +
echo "[筱宇智矩] 安装完成。"
echo "[筱宇智矩] 代码目录：$CURRENT_ROOT"
echo "[筱宇智矩] 桌面应用：$HOME/Desktop/筱宇智矩-$(cat "$CURRENT_ROOT/VERSION").app"
