import argparse
import json
from pathlib import Path
import time

from .client import CloudClient
from .codex import CodexClient
from .runner import run_once
from zhiju.v14_runtime.contract import bundled_rules


def main():
    parser = argparse.ArgumentParser(description="智矩 V14 本机执行器（不会回写飞书）")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--export-rules", action="store_true", help="仅向标准输出导出固定规则，不启动执行")
    args = parser.parse_args()
    if args.export_rules:
        print(json.dumps(bundled_rules(), ensure_ascii=False, indent=2))
        return
    if not args.config:
        parser.error("需要 --config，或使用 --export-rules")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    cloud = CloudClient(config["base_url"], config["session_token"], config["host_id"], config["tenant_id"])
    model = CodexClient(binary=config.get("codex_binary", "codex"), timeout=config.get("timeout", 900),
        account_profile=config.get("account_profile", "current"), codex_home=config.get("codex_home"))
    cache = Path(config.get("cache_root", str(Path.home() / "Library/Caches/zhiju-v14"))) / config["tenant_id"] / config["host_id"]
    while True:
        run_once(cloud, model, cache_root=cache)
        if args.once:
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
