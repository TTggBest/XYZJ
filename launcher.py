#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / ".server.pid"
PORT_FILE = ROOT / ".server.port"
LOG_FILE = ROOT / "server.log"
OPEN_HOST = "127.0.0.1"
SERVER_HOST = "0.0.0.0"
PREFERRED_PORT = 19732
TITLE_MARK = "筱宇智矩"
HEALTH_MARK = "筱宇智矩"
PYTHON_CANDIDATES = (
    str(ROOT / ".venv" / "bin" / "python"),
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    sys.executable,
    "/usr/bin/python3",
)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def port_accepts(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((OPEN_HOST, port)) == 0


def is_management_server(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{OPEN_HOST}:{port}/", timeout=0.8) as response:
            body = response.read(4096).decode("utf-8", errors="ignore")
        return TITLE_MARK in body
    except Exception:
        return False


def is_app_server(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{OPEN_HOST}:{port}/api/health", timeout=0.8) as response:
            body = response.read(4096).decode("utf-8", errors="ignore")
        return HEALTH_MARK in body
    except Exception:
        return False


def python_executable() -> str:
    for candidate in PYTHON_CANDIDATES:
        if candidate and shutil.which(candidate):
            return candidate
    raise RuntimeError("没有找到可用的 python3。")


def existing_port() -> int | None:
    pid = read_int(PID_FILE)
    port = read_int(PORT_FILE)
    if pid and port and pid_alive(pid) and is_app_server(port):
        return port
    if is_app_server(PREFERRED_PORT):
        return PREFERRED_PORT
    return None


def start_server(port: int) -> None:
    if port_accepts(port) and not is_app_server(port):
        raise RuntimeError(f"端口 {port} 已被其他服务占用。请先关闭占用端口的服务，或修改启动端口。")
    python = python_executable()
    subprocess.run(
        [str(ROOT / "scripts" / "mysql_dev.sh"), "start"],
        cwd=str(ROOT),
        check=True,
    )
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] desktop launch port {port}, python {python}\n")
        process = subprocess.Popen(
            [python, str(ROOT / "run_v3.py")],
            cwd=str(ROOT),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    PORT_FILE.write_text(str(port), encoding="utf-8")
    for _ in range(30):
        if is_app_server(port):
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError(f"管理系统服务启动失败，请查看日志：{LOG_FILE}")


def main() -> None:
    port = existing_port()
    if port is None:
        port = PREFERRED_PORT
        start_server(port)
    webbrowser.open(f"http://{OPEN_HOST}:{port}/")


if __name__ == "__main__":
    main()
