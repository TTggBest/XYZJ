from fastapi import APIRouter
from sqlalchemy import text

from zhiju import __version__
from zhiju.config import get_settings
from zhiju.database import engine


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    database_ok = False
    database_error = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # Keep health available while the database recovers.
        database_error = exc.__class__.__name__
    return {
        "ok": database_ok,
        "system": "筱宇智矩",
        "version": __version__,
        "environment": settings.env,
        "database": {"ok": database_ok, "error": database_error},
    }

