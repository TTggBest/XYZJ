#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from zhiju.cloud_deployment import validate_deployment_artifacts
from zhiju.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the Zhiju cloud environment")
    parser.add_argument("--require-migration", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    # Settings validation is deliberately first: no DB engine, migration, or file write precedes it.
    if settings.deployment != "cloud":
        raise SystemExit("Cloud deployment requires ZHJ_DEPLOYMENT=cloud")
    if args.require_migration and not settings.migration_database_url:
        raise SystemExit("Database initialization requires ZHJ_MIGRATION_DATABASE_URL")
    result = validate_deployment_artifacts(Path(__file__).resolve().parents[1])
    print(
        "Cloud contract valid: "
        f"{settings.deployment}/{result['database']}/uvicorn={result['uvicorn_host']}"
    )


if __name__ == "__main__":
    main()
