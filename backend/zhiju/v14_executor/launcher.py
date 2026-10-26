"""Loopback-only wake-up service. Model workers are short-lived child processes."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Lock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .client import CloudClient


class WorkerManager:
    def __init__(self, settings):
        self.settings = settings
        self.lock = Lock()
        self.process = None
        self.pending = None
        self.closed = False
        self.last_error = None

    def validate(self, config):
        for remote, local in (("base_url", "origin"), ("host_id", "host_id"),
                              ("tenant_id", "tenant_id"), ("account_profile", "account_profile")):
            if config.get(remote) != self.settings[local]:
                raise ValueError("本机组件与当前公司、主机或账号配置不匹配")
        if not isinstance(config.get("session_token"), str) or not config["session_token"]:
            raise ValueError("缺少当前网页登录授权，请重新登录")
        return {key: config[key] for key in ("base_url", "host_id", "tenant_id", "account_profile", "session_token")}

    def prepare(self, config):
        config = self.validate(config)
        principal = CloudClient(config["base_url"], config["session_token"], config["host_id"],
                                config["tenant_id"]).request("GET", "/auth/me")
        if principal.get("tenant_id") != config["tenant_id"] or (principal.get("device") or {}).get("id") != config["host_id"]:
            raise ValueError("当前授权不属于本机绑定的公司和设备")
        env = os.environ.copy()
        if self.settings.get("codex_home"):
            env["CODEX_HOME"] = self.settings["codex_home"]
        probe = subprocess.run([self.settings["codex_binary"], "login", "status"],
            capture_output=True, timeout=15, env=env)
        if probe.returncode:
            raise ValueError("本机 Codex 尚未登录，请先完成一次 CLI 登录")
        return {"ready": True, **self.status()}

    def status(self):
        with self.lock:
            return self._status()

    def _status(self):
        running = self.process is not None and self.process.poll() is None
        return {"host_id": self.settings["host_id"], "tenant_id": self.settings["tenant_id"],
                "running": running, "pid": self.process.pid if running else None,
                "last_error": self.last_error, "worker_limit": 10}

    def _spawn(self, config):
        worker = {**config, "codex_binary": self.settings["codex_binary"]}
        for key in ("codex_home", "cache_root"):
            if self.settings.get(key):
                worker[key] = self.settings[key]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(self.settings["runtime_root"]) / "backend")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        path = Path(self.settings["log_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "ab") as log:
            process = subprocess.Popen([self.settings["python"], "-m", "zhiju.v14_executor",
                "--config-stdin", "--drain"], stdin=subprocess.PIPE, stdout=log, stderr=log,
                cwd=self.settings["runtime_root"], env=env, start_new_session=True)
        try:
            process.stdin.write(json.dumps(worker).encode())
            process.stdin.close()
        except Exception:
            process.terminate()
            process.wait()
            raise
        self.process = process
        self.last_error = None

    def start(self, config):
        config = self.validate(config)
        with self.lock:
            if self.closed:
                raise ValueError("本机唤起组件正在关闭")
            if self.process is not None:
                # A request arriving as the worker drains must not lose its wake-up.
                self.pending = config
            else:
                self._spawn(config)
                Thread(target=self._monitor, daemon=True).start()
            return self._status()

    def _monitor(self):
        while True:
            code = self.process.wait()
            with self.lock:
                if self.pending and not self.closed and code == 0:
                    config, self.pending = self.pending, None
                    try:
                        self._spawn(config)
                        continue
                    except OSError:
                        self.last_error = "V14 执行器重新启动失败，请重试唤起"
                elif code:
                    self.last_error = f"V14 执行器已退出（退出码 {code}），请查看本机日志并重试唤起"
                self.process = self.pending = None
                return

    def close(self):
        with self.lock:
            self.closed = True
            self.pending = None
            process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def make_server(manager, port=19733):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log browser authorization bodies or session tokens.

        def allowed(self):
            return self.headers.get("Origin") == manager.settings["origin"]

        def reply(self, code, payload=None):
            body = json.dumps(payload or {}).encode()
            self.send_response(code)
            if self.allowed():
                self.send_header("Access-Control-Allow-Origin", manager.settings["origin"])
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.reply(200 if self.allowed() else 403)

        def do_GET(self):
            if self.path != "/health":
                return self.reply(404)
            if self.headers.get("Origin") and not self.allowed():
                return self.reply(403)
            self.reply(200, manager.status())

        def do_POST(self):
            if not self.allowed():
                return self.reply(403, {"detail": "当前网页未获本机唤起授权"})
            if self.path not in {"/prepare", "/start"}:
                return self.reply(404)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("本机启动请求格式不正确")
                config = json.loads(self.rfile.read(length))
                ready = manager.prepare(config)
                self.reply(200, ready if self.path == "/prepare" else manager.start(config))
            except (ValueError, PermissionError, ConnectionError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                self.reply(409, {"detail": str(exc) if not isinstance(exc, OSError) else "本机执行程序不可用，请检查安装"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="智矩 V14 本机自动唤起组件")
    parser.add_argument("--settings", type=Path, required=True)
    args = parser.parse_args()
    manager = WorkerManager(json.loads(args.settings.read_text()))
    server = make_server(manager)
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()


if __name__ == "__main__":
    main()
