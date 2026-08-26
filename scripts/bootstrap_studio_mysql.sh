#!/usr/bin/env bash
set -euo pipefail

PORT=33306
ROOT="$HOME/Documents/XYData/XYZJ"
MYSQL_ROOT="$ROOT/mysql/zhiju"
DATADIR="$MYSQL_ROOT/data"
SOCKET="$MYSQL_ROOT/mysql.sock"
PID_FILE="$MYSQL_ROOT/mysql.pid"
LOG_FILE="$MYSQL_ROOT/mysql.log"
CNF_FILE="$MYSQL_ROOT/my.cnf"
SHARED_CONFIG="$ROOT/config/zhiju-runtime.env"
MYSQL_PREFIX="$(/opt/homebrew/bin/brew --prefix mysql)"
MYSQLD="$MYSQL_PREFIX/bin/mysqld"
MYSQL="$MYSQL_PREFIX/bin/mysql"

[[ -d "$ROOT" ]] || { echo "[初始化失败] Studio 数据目录不存在：$ROOT"; exit 1; }
mkdir -p "$MYSQL_ROOT" "$ROOT/config"

cat >"$CNF_FILE" <<CNF
[mysqld]
port=$PORT
bind-address=0.0.0.0
datadir=$DATADIR
socket=$SOCKET
pid-file=$PID_FILE
log-error=$LOG_FILE
mysqlx=0
skip-name-resolve

[client]
port=$PORT
socket=$SOCKET
CNF

if [[ ! -d "$DATADIR/mysql" ]]; then
  mkdir -p "$DATADIR"
  "$MYSQLD" --defaults-file="$CNF_FILE" --initialize-insecure
fi

if ! lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; then
  nohup "$MYSQLD" --defaults-file="$CNF_FILE" >"$MYSQL_ROOT/start.log" 2>&1 &
  for _ in $(seq 1 80); do
    [[ -S "$SOCKET" ]] && "$MYSQL" --protocol=socket --socket="$SOCKET" -uroot -e "SELECT 1" >/dev/null 2>&1 && break
    sleep 0.25
  done
fi
"$MYSQL" --protocol=socket --socket="$SOCKET" -uroot -e "SELECT 1" >/dev/null 2>&1 || {
  echo "[初始化失败] 智矩 MySQL 未能在端口 $PORT 启动。"
  exit 1
}

if [[ ! -f "$SHARED_CONFIG" ]]; then
  APP_PASSWORD="$(openssl rand -hex 24)"
  MIGRATOR_PASSWORD="$(openssl rand -hex 24)"
  "$MYSQL" --protocol=socket --socket="$SOCKET" -uroot <<SQL
CREATE DATABASE IF NOT EXISTS zhiju_prod CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'zhiju_app'@'%' IDENTIFIED BY '$APP_PASSWORD';
ALTER USER 'zhiju_app'@'%' IDENTIFIED BY '$APP_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON zhiju_prod.* TO 'zhiju_app'@'%';
CREATE USER IF NOT EXISTS 'zhiju_migrator'@'%' IDENTIFIED BY '$MIGRATOR_PASSWORD';
ALTER USER 'zhiju_migrator'@'%' IDENTIFIED BY '$MIGRATOR_PASSWORD';
GRANT ALL PRIVILEGES ON zhiju_prod.* TO 'zhiju_migrator'@'%';
FLUSH PRIVILEGES;
SQL
  umask 077
  cat >"$SHARED_CONFIG" <<ENV
ZHJ_ENV=production
ZHJ_DATABASE_URL=mysql+pymysql://zhiju_app:${APP_PASSWORD}@192.168.8.8:${PORT}/zhiju_prod?charset=utf8mb4
ZHJ_MIGRATION_DATABASE_URL=mysql+pymysql://zhiju_migrator:${MIGRATOR_PASSWORD}@192.168.8.8:${PORT}/zhiju_prod?charset=utf8mb4
ENV
  chmod 600 "$SHARED_CONFIG"
fi

echo "[筱宇智矩] Studio 独立 MySQL 已就绪：0.0.0.0:${PORT}/zhiju_prod"
echo "[筱宇智矩] 共享生产配置已就绪：$SHARED_CONFIG"
