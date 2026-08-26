#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MYSQL_HOME="/opt/homebrew/opt/mysql@8.4"
CONFIG="$ROOT/config/mysql-dev.cnf"
DATA_DIR="$ROOT/.runtime/mysql"
MYSQL="$MYSQL_HOME/bin/mysql"
MYSQLADMIN="$MYSQL_HOME/bin/mysqladmin"
MYSQLD="$MYSQL_HOME/bin/mysqld"

initialize() {
  if [[ ! -d "$DATA_DIR/mysql" ]]; then
    mkdir -p "$DATA_DIR"
    "$MYSQLD" --defaults-file="$CONFIG" --initialize-insecure
  fi
}

is_running() {
  "$MYSQLADMIN" --defaults-file="$CONFIG" ping --silent >/dev/null 2>&1
}

start() {
  initialize
  if is_running; then
    echo "Zhiju MySQL is already running on 127.0.0.1:33306"
    return
  fi
  "$MYSQLD" --defaults-file="$CONFIG" --daemonize
  for _ in {1..30}; do
    if is_running; then
      echo "Zhiju MySQL started on 127.0.0.1:33306"
      return
    fi
    sleep 1
  done
  echo "Zhiju MySQL failed to start; see $DATA_DIR/mysql.err" >&2
  exit 1
}

stop() {
  if is_running; then
    "$MYSQLADMIN" --defaults-file="$CONFIG" shutdown
    echo "Zhiju MySQL stopped"
  else
    echo "Zhiju MySQL is not running"
  fi
}

status() {
  if is_running; then
    echo "running 127.0.0.1:33306"
  else
    echo "stopped"
    exit 1
  fi
}

case "${1:-status}" in
  init) initialize ;;
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  mysql) shift; exec "$MYSQL" --defaults-file="$CONFIG" "$@" ;;
  *) echo "Usage: $0 {init|start|stop|restart|status|mysql}" >&2; exit 2 ;;
esac

