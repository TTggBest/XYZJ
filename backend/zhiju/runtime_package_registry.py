from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from zhiju.config import get_settings
from zhiju.models import RuntimePackageBuild


def get_runtime_package_db() -> Generator[Session, None, None]:
    path = get_settings().runtime_package_registry_path
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    RuntimePackageBuild.__table__.create(engine, checkfirst=True)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
