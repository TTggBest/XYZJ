#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from zhiju.cloud_deployment import validate_deployment_artifacts
from zhiju.config import get_settings


def main() -> None:
    settings = get_settings()
    # Settings validation is deliberately first: no DB engine, migration, or file write precedes it.
    if settings.deployment != "cloud":
        raise SystemExit("Cloud deployment requires ZHJ_DEPLOYMENT=cloud")
    result = validate_deployment_artifacts(Path(__file__).resolve().parents[1])
    print(
        "Cloud contract valid: "
        f"{settings.deployment}/{result['database']}/uvicorn={result['uvicorn_host']}"
    )


if __name__ == "__main__":
    main()
