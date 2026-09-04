#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
CONFIG_FILE="$HOME/Library/Application Support/筱宇智矩/runtime.env"
PYTHON="$ROOT/.venv/bin/python"

[[ -f "$CONFIG_FILE" ]] || { echo "[启动失败] 未找到生产配置：$CONFIG_FILE"; exit 1; }
[[ -x "$PYTHON" ]] || { echo "[启动失败] 运行环境未安装：$PYTHON"; exit 1; }

set -a
source "$CONFIG_FILE"
set +a

read -r DATABASE_HOST DATABASE_PORT < <(
  "$PYTHON" - <<'PY'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["ZHJ_DATABASE_URL"])
print(url.host or "", url.port or 3306)
PY
)

if ! ifconfig | awk '$1 == "inet" {print $2}' | grep -Fxq "$DATABASE_HOST"; then
  exit 0
fi

MYSQL_ROOT="$HOME/Documents/XYData/XYZJ/mysql/zhiju"
DATADIR="$MYSQL_ROOT/data"
CNF_FILE="$MYSQL_ROOT/my.cnf"
SOCKET="$MYSQL_ROOT/mysql.sock"
LOG_FILE="$MYSQL_ROOT/mysql.log"

[[ -d "$DATADIR/mysql" ]] || {
  echo "[启动失败] Studio 原生产数据库目录不存在，已停止，不会初始化空库：$DATADIR" >&2
  exit 1
}
[[ -f "$CNF_FILE" ]] || {
  echo "[启动失败] Studio 生产 MySQL 配置不存在：$CNF_FILE" >&2
  exit 1
}

MYSQL_PREFIX="$(/opt/homebrew/bin/brew --prefix mysql)"
MYSQLD="$MYSQL_PREFIX/bin/mysqld"
MYSQL="$MYSQL_PREFIX/bin/mysql"

if [[ -S "$SOCKET" ]] && "$MYSQL" --protocol=socket --socket="$SOCKET" -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "[筱宇智矩] Studio 生产 MySQL 已运行：127.0.0.1:${DATABASE_PORT}"
  exit 0
fi

echo "[筱宇智矩] 正在启动 Studio 已有生产 MySQL..."
nohup "$MYSQLD" --defaults-file="$CNF_FILE" >"$MYSQL_ROOT/start.log" 2>&1 &
for _ in $(seq 1 80); do
  if [[ -S "$SOCKET" ]] && "$MYSQL" --protocol=socket --socket="$SOCKET" -uroot -e "SELECT 1" >/dev/null 2>&1; then
    echo "[筱宇智矩] Studio 生产 MySQL 已就绪：0.0.0.0:${DATABASE_PORT}/zhiju_prod"
    exit 0
  fi
  sleep 0.25
done

echo "[启动失败] Studio 生产 MySQL 未能启动，请查看：$LOG_FILE" >&2
exit 1
