#!/usr/bin/env python3
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from zhiju.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "zhiju.app:app",
        app_dir=str(ROOT / "backend"),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
