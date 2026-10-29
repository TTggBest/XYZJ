#!/usr/bin/env python3
"""Install the current user's loopback V14 wake-up service; never start a model job."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from urllib.parse import urlparse


LABEL = "local.xiaoyu.zhiju.v14-launcher"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--account-profile", default="current")
    parser.add_argument("--codex-binary", default=shutil.which("codex"))
    parser.add_argument("--codex-home")
    parser.add_argument("--analysis-workspace-root", help="频道注册表所在项目根目录；用于分析历史和三文件镜像")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("本机自动安装仅支持 macOS")
    parsed = urlparse(args.origin)
    if parsed.scheme != "https" or parsed.path not in {"", "/"} or not parsed.netloc:
        parser.error("--origin 必须是智矩 HTTPS 来源地址，不带路径")
    if not args.codex_binary or not Path(args.codex_binary).is_file():
        parser.error("没有找到本机 Codex CLI，请指定 --codex-binary")
    root = Path(__file__).resolve().parents[1]
    home = Path.home()
    state = home / "Library/Application Support/zhiju-v14-launcher"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = state / "settings.json"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if config.exists():
        previous = json.loads(config.read_text())
        if any(previous.get(k) != v for k, v in (("origin", origin), ("tenant_id", args.tenant_id), ("host_id", args.host_id))):
            parser.error("已有组件绑定其他公司或主机，不能自动覆盖")
    settings = {"origin": origin, "tenant_id": args.tenant_id, "host_id": args.host_id,
        "account_profile": args.account_profile, "runtime_root": str(root), "python": sys.executable,
        "codex_binary": str(Path(args.codex_binary).absolute()),
        "log_path": str(state / "worker.log"), "cache_root": str(home / "Library/Caches/zhiju-v14")}
    if args.codex_home:
        settings["codex_home"] = str(Path(args.codex_home).expanduser().resolve())
    if args.analysis_workspace_root:
        settings['analysis_workspace_root'] = str(Path(args.analysis_workspace_root).expanduser().resolve())
    elif config.exists() and previous.get('analysis_workspace_root'):
        settings['analysis_workspace_root'] = previous['analysis_workspace_root']
    # No cloud session or Codex credential is stored in this configuration.
    config.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    config.chmod(0o600)
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{LABEL}.plist"
    service = {"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "zhiju.v14_executor.launcher",
        "--settings", str(config)], "WorkingDirectory": str(root), "RunAtLoad": True, "KeepAlive": True,
        "EnvironmentVariables": {"PYTHONPATH": str(root / "backend"), "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "StandardOutPath": str(state / "launcher.log"), "StandardErrorPath": str(state / "launcher.log"),
        "ProcessType": "Background", "Umask": 0o077}
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True)
    if loaded.returncode == 0:
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=True)
    path.write_bytes(plistlib.dumps(service))
    path.chmod(0o600)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print(f"本机唤起组件已安装：{path}；只监听 127.0.0.1:19733，未启动生产")


if __name__ == "__main__":
    main()
