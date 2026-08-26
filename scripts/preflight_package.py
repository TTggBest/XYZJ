#!/usr/bin/env python3
from pathlib import Path

from sqlalchemy import create_engine, text

from zhiju.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.env != "production":
        raise SystemExit("运行包只允许 production 环境")
    if settings.device_role not in {"builder", "studio", "worker"}:
        raise SystemExit(f"未知设备角色：{settings.device_role}")
    if settings.shared_root is None or not Path(settings.shared_root).is_dir():
        raise SystemExit(f"共享目录未就绪：{settings.shared_root}")

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise SystemExit(f"无法连接智矩生产 MySQL：{exc}") from exc
    finally:
        engine.dispose()

    print(f"[智矩] 生产预检通过：{settings.device_role} / {settings.shared_root}")


if __name__ == "__main__":
    main()
