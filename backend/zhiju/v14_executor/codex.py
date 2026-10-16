import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class CodexClient:
    def __init__(self, binary="codex", timeout=900, account_profile="current", codex_home=None):
        self.binary, self.timeout = binary, timeout
        self.account_profile, self.codex_home = account_profile, codex_home
        self.cancelled = lambda: False

    def generate(self, stage, model):
        if not model or self.cancelled():
            raise RuntimeError("模型未指定或执行已取消")
        env = os.environ.copy()
        if self.codex_home:
            env["CODEX_HOME"] = str(Path(self.codex_home).expanduser().resolve())
        with tempfile.TemporaryDirectory(prefix="zhiju-v14-") as temp:
            root = Path(temp)
            schema, output = root / "schema.json", root / "result.json"
            schema.write_text(json.dumps(stage.schema, ensure_ascii=False), encoding="utf-8")
            args = [self.binary, "--ask-for-approval", "never", "exec", "--ignore-user-config", "--ignore-rules",
                "--sandbox", "read-only", "--cd", temp, "--ephemeral", "--skip-git-repo-check",
                "--model", model, "--output-schema", str(schema), "--output-last-message", str(output)]
            if stage.node_type == "search":
                args += ["--enable", "standalone_web_search"]
            args += ["-"]
            with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as logs:
                stdin.write(stage.prompt.encode("utf-8"))
                stdin.seek(0)
                process = subprocess.Popen(args, stdin=stdin, stdout=logs, stderr=logs, env=env, start_new_session=True)
                deadline = time.monotonic() + self.timeout
                try:
                    while process.poll() is None:
                        if self.cancelled():
                            raise RuntimeError("执行取消或云端会话已失效")
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Codex 调用超时，子进程已停止")
                        time.sleep(min(0.1, self.timeout))
                    if process.returncode:
                        raise RuntimeError(f"Codex 调用失败，退出码 {process.returncode}；请检查账号和所选模型（不自动切换模型）")
                    if not output.exists():
                        raise RuntimeError("Codex 未返回结构化结果")
                    return json.loads(output.read_text(encoding="utf-8"))
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
