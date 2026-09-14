#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from zhiju.cloud_deployment import bootstrap_super_admin
from zhiju.config import Settings


APP_ENV_FILE = Path(os.environ.get("ZHJ_APP_ENV_FILE", "/etc/zhiju/zhiju-app.env"))
ADMIN_ENV_FILE = Path(
    os.environ.get("ZHJ_ADMIN_ENV_FILE", "/etc/zhiju/zhiju-admin.env")
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the first Zhiju cloud super-admin")
    parser.add_argument("--login-name", required=True)
    parser.add_argument("--display-name", required=True)
    return parser


def _read_password() -> str:
    password = os.environ.get("ZHJ_BOOTSTRAP_PASSWORD")
    if password is not None:
        return password
    first = getpass.getpass("Initial super-admin password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Password confirmation does not match")
    return first


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings(
        _env_file=(APP_ENV_FILE, ADMIN_ENV_FILE)
    )  # Validates both targets before create_engine.
    if settings.deployment != "cloud":
        raise SystemExit("Cloud bootstrap requires ZHJ_DEPLOYMENT=cloud")
    if not settings.migration_database_url:
        raise SystemExit("Cloud bootstrap requires ZHJ_MIGRATION_DATABASE_URL")
    password = _read_password()
    engine = create_engine(settings.migration_database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            bootstrap_super_admin(
                session,
                login_name=args.login_name,
                display_name=args.display_name,
                password=password,
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
