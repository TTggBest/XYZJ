#!/bin/bash

set -e

ROOT="/Volumes/TTggg_mini01_2T/ai/筱宇短剧运营-youtube/管理系统"
URL="http://127.0.0.1:19732/"
HEALTH_URL="http://127.0.0.1:19732/api/health"

cd "$ROOT"
printf '\033]0;筱宇智矩 - 19732\007'

CURRENT_BRANCH="$(git branch --show-current)"
DEV_COMMIT="$(git rev-parse --short=12 HEAD)"
BROWSER_URL="${URL}?dev_commit=${DEV_COMMIT}"

echo "[筱宇智矩] 项目目录：$ROOT"
echo "[筱宇智矩] Web 地址：$URL"
echo "[筱宇智矩] 代码分支：${CURRENT_BRANCH:-未知}"
echo "[筱宇智矩] 代码提交：$DEV_COMMIT"

if curl -fsS --max-time 2 "$HEALTH_URL" 2>/dev/null | grep -q '筱宇智矩'; then
  OLD_PID="$(lsof -tiTCP:19732 -sTCP:LISTEN | head -n 1)"
  if [ -z "$OLD_PID" ]; then
    echo "[启动失败] 已检测到智矩服务，但无法取得服务进程。"
    read -r -n 1 -s -p "按任意键关闭窗口..."
    exit 1
  fi

  echo "[筱宇智矩] 检测到正在运行的服务（PID ${OLD_PID}），正在重启..."
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

if lsof -nP -iTCP:19732 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[启动失败] 端口 19732 已被其他程序占用。"
  echo "请关闭占用程序后重新启动。"
  read -r -n 1 -s -p "按任意键关闭窗口..."
  exit 1
fi

echo "[筱宇智矩] 启动 MySQL..."
./scripts/mysql_dev.sh start

echo "[筱宇智矩] 更新数据库结构..."
.venv/bin/alembic upgrade head

(
  for _ in $(seq 1 50); do
    if curl -fsS --max-time 1 "$HEALTH_URL" 2>/dev/null | grep -q '筱宇智矩'; then
      bash "$ROOT/scripts/open_app_url.sh" "$BROWSER_URL" "$URL"
      exit 0
    fi
    sleep 0.2
  done
) &

echo "[筱宇智矩] 正在启动 Web 服务；关闭本窗口或按 Control-C 可停止服务。"
exec .venv/bin/python run_v3.py
