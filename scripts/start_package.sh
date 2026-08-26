#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
CONFIG_FILE="$HOME/Library/Application Support/筱宇智矩/runtime.env"
PORT=19732
URL="http://127.0.0.1:${PORT}/"
HEALTH_URL="${URL}api/health"

printf '\033]0;筱宇智矩生产服务 - %s\007' "$(cat "$ROOT/VERSION")"
echo "[筱宇智矩] 版本：$(cat "$ROOT/VERSION")"
echo "[筱宇智矩] 代码目录：$ROOT"

[[ -f "$CONFIG_FILE" ]] || { echo "[启动失败] 未找到生产配置：$CONFIG_FILE"; exit 1; }
[[ -x "$ROOT/.venv/bin/python" ]] || { echo "[启动失败] 运行环境未安装，请重新执行运行包安装指令。"; exit 1; }

PYTHONPATH="$ROOT/backend" "$ROOT/.venv/bin/python" "$ROOT/scripts/configure_package_device.py"

set -a
source "$CONFIG_FILE"
set +a

if curl -fsS --max-time 2 "$HEALTH_URL" 2>/dev/null | grep -q '筱宇智矩'; then
  OLD_PID="$(lsof -tiTCP:${PORT} -sTCP:LISTEN | head -n 1)"
  echo "[筱宇智矩] 正在重启已运行服务（PID ${OLD_PID}）..."
  kill -TERM "$OLD_PID"
  for _ in $(seq 1 50); do
    kill -0 "$OLD_PID" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[筱宇智矩] 旧服务仍在等待长连接，正在强制终止..."
    kill -KILL "$OLD_PID"
    for _ in $(seq 1 20); do
      kill -0 "$OLD_PID" 2>/dev/null || break
      sleep 0.1
    done
  fi
fi

if lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[启动失败] 端口 ${PORT} 被非智矩进程占用。"
  exit 1
fi

PYTHONPATH="$ROOT/backend" "$ROOT/.venv/bin/python" "$ROOT/scripts/preflight_package.py"

(
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 1 "$HEALTH_URL" 2>/dev/null | grep -q '筱宇智矩'; then
      bash "$ROOT/scripts/open_app_url.sh" "$URL"
      exit 0
    fi
    sleep 0.25
  done
) &

echo "[筱宇智矩] 生产服务正在启动；关闭终端窗口或按 Control-C 可停止。"
exec "$ROOT/.venv/bin/python" "$ROOT/run_v3.py"
