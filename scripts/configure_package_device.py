#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from zhiju.models import Device  # noqa: E402
from zhiju.runtime_device import match_device, runtime_values_for_device  # noqa: E402


CONFIG_FILE = Path.home() / "Library" / "Application Support" / "筱宇智矩" / "runtime.env"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def hostname_candidates() -> list[str]:
    values = [socket.gethostname(), platform.node()]
    for key in ("ComputerName", "LocalHostName", "HostName"):
        result = subprocess.run(["scutil", "--get", key], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            values.append(result.stdout.strip())
    return values


def main() -> None:
    if not CONFIG_FILE.is_file():
        raise SystemExit(f"[设备识别失败] 未找到生产配置：{CONFIG_FILE}")
    current = read_env(CONFIG_FILE)
    database_url = current.get("ZHJ_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("[设备识别失败] 生产 MySQL 连接未配置")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            devices = list(session.scalars(select(Device)))
    except Exception as exc:
        raise SystemExit(f"[设备识别失败] 无法读取智矩生产设备表：{exc}") from exc
    finally:
        engine.dispose()

    try:
        device = match_device(devices, hostname_candidates())
        runtime = runtime_values_for_device(device, home=str(Path.home()))
    except ValueError as exc:
        raise SystemExit(f"[设备识别失败] {exc}") from exc

    runtime["ZHJ_DATABASE_URL"] = database_url
    if current.get("ZHJ_MIGRATION_DATABASE_URL"):
        runtime["ZHJ_MIGRATION_DATABASE_URL"] = current["ZHJ_MIGRATION_DATABASE_URL"]
    for key in (
        "ZHJ_FEISHU_APP_ID",
        "ZHJ_FEISHU_APP_SECRET",
        "ZHJ_FEISHU_WIKI_TOKEN",
        "ZHJ_FEISHU_WORK_ORDER_SHEET_ID",
        "ZHJ_FEISHU_OPERATION_PACKAGE_SHEET_ID",
        "ZHJ_ZHIHE_API_BASE_URL",
        "ZHJ_ZHIHE_API_TOKEN",
    ):
        if current.get(key):
            runtime[key] = current[key]
    CONFIG_FILE.write_text("".join(f"{key}={value}\n" for key, value in runtime.items()), encoding="utf-8")
    os.chmod(CONFIG_FILE, 0o600)
    print(f"[筱宇智矩] 已识别设备：{device.hostname} / {device.device_role}")


if __name__ == "__main__":
    main()
