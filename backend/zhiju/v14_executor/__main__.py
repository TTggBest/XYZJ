import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import signal
import sys
import time
from threading import Event

from .client import CloudClient
from .codex import CodexClient
from .runner import run_once, replay_pending
from zhiju.v14_runtime.contract import bundled_rules


def main():
    parser = argparse.ArgumentParser(description="智矩 V14 本机执行器（不会回写飞书）")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--config-stdin", action="store_true", help="从私有 stdin 接收本次授权，不保存令牌")
    parser.add_argument("--drain", action="store_true", help="处理完当前队列后自动退出")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--workers", type=int, default=10, choices=range(1, 11), help="普通 Python Worker 并发数，默认 10；--once 固定为单条")
    parser.add_argument("--export-rules", action="store_true", help="仅向标准输出导出固定规则，不启动执行")
    args = parser.parse_args()
    if args.export_rules:
        print(json.dumps(bundled_rules(), ensure_ascii=False, indent=2))
        return
    if not args.config and not args.config_stdin:
        parser.error("需要 --config，或使用 --export-rules")
    if args.config and args.config_stdin:
        parser.error("--config 与 --config-stdin 不能同时使用")
    config = json.load(sys.stdin) if args.config_stdin else json.loads(args.config.read_text(encoding="utf-8"))
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    cache = Path(config.get("cache_root", str(Path.home() / "Library/Caches/zhiju-v14"))) / config["tenant_id"] / config["host_id"]
    def cloud_client():
        return CloudClient(config["base_url"], config["session_token"], config["host_id"], config["tenant_id"])
    # Replay old outbound results once, before any parallel worker can claim work.
    # Each newly claimed run then exclusively owns its own run-id cache directory.
    if not args.once:
        recovery = cloud_client()
        while replay_pending(recovery, cache):
            pass
    stopped = Event()
    def worker():
        cloud = cloud_client()
        model = CodexClient(binary=config.get("codex_binary", "codex"), timeout=config.get("timeout", 900),
            account_profile=config.get("account_profile", "current"), codex_home=config.get("codex_home"))
        try:
            while not stopped.is_set():
                worked = run_once(cloud, model, cache_root=cache, recover=args.once, stop_event=stopped)
                if args.once or (args.drain and not worked):
                    return
                if not args.drain:
                    stopped.wait(5)
        except Exception:
            stopped.set()  # Expired authorization stops all claims and model children.
            raise
    with ThreadPoolExecutor(max_workers=1 if args.once else args.workers) as pool:
        try:
            futures = [pool.submit(worker) for _ in range(1 if args.once else args.workers)]
            for future in as_completed(futures):
                future.result()
        finally:
            stopped.set()


if __name__ == "__main__":
    main()
