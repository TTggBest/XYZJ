#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from zhiju.cloud_deployment import bootstrap_super_admin
from zhiju.config import get_settings


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
    settings = get_settings()  # Validates cloud target before create_engine.
    if settings.deployment != "cloud":
        raise SystemExit("Cloud bootstrap requires ZHJ_DEPLOYMENT=cloud")
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
