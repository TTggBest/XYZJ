from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path
from threading import RLock

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from zhiju.config import get_settings


PRODUCTION_CONFIG_CANDIDATES = (
    Path.home() / "Documents" / "XYData" / "XYZJ" / "config" / "zhiju-runtime.env",
    Path("/Volumes/XYData/XYZJ/config/zhiju-runtime.env"),
    Path.home() / "Library" / "Application Support" / "筱宇智矩" / "runtime.env",
)


def read_database_url(path: Path) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("ZHJ_DATABASE_URL="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    raise ValueError(f"生产配置未提供 ZHJ_DATABASE_URL：{path}")


def load_production_database_url() -> str:
    for path in PRODUCTION_CONFIG_CANDIDATES:
        if path.is_file():
            return read_database_url(path)
    raise FileNotFoundError("未找到智矩生产配置，请确认 XYData/XYZJ 已挂载")


def _create_database_engine(database_url: str) -> Engine:
    options: dict[str, object] = {"pool_pre_ping": True}
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        options.update(pool_recycle=1800, pool_size=10, max_overflow=20)
    if url.drivername == "mysql+pymysql":
        options["connect_args"] = {"connect_timeout": 3}
    return create_engine(database_url, **options)


class DatabaseRouter:
    def __init__(
        self,
        database_url: str,
        *,
        initial_environment: str,
        production_url_loader: Callable[[], str] = load_production_database_url,
    ) -> None:
        environment = "production" if initial_environment == "production" else "development"
        engine = _create_database_engine(database_url)
        self._lock = RLock()
        self._active_environment = environment
        self._production_url_loader = production_url_loader
        self._engines = {environment: engine}
        self._session_factories = {
            environment: sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        }

    @property
    def active_environment(self) -> str:
        with self._lock:
            return self._active_environment

    @property
    def active_database_url(self) -> str:
        with self._lock:
            return self._engines[self._active_environment].url.render_as_string(hide_password=False)

    def get_active_engine(self) -> Engine:
        with self._lock:
            return self._engines[self._active_environment]

    def open_session(self) -> Session:
        with self._lock:
            factory = self._session_factories[self._active_environment]
        return factory()

    def switch_environment(self, environment: str, *, allow_switch: bool) -> None:
        if not allow_switch:
            raise PermissionError("仅代码机开发模式允许切换数据库环境")
        if environment not in {"development", "production"}:
            raise ValueError("数据库环境只能是 development 或 production")

        with self._lock:
            if environment == self._active_environment:
                return
            engine = self._engines.get(environment)

        created_engine = False
        if engine is None:
            if environment != "production":
                raise RuntimeError("当前进程没有开发数据库配置")
            try:
                database_url = self._production_url_loader()
                engine = _create_database_engine(database_url)
                created_engine = True
            except Exception as exc:
                raise RuntimeError(f"生产数据库配置读取失败：{exc}") from exc

        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            if created_engine:
                engine.dispose()
            label = "生产" if environment == "production" else "开发"
            raise RuntimeError(f"{label}数据库连接失败：{exc.__class__.__name__}") from exc

        with self._lock:
            if created_engine:
                self._engines[environment] = engine
                self._session_factories[environment] = sessionmaker(
                    bind=engine,
                    autoflush=False,
                    expire_on_commit=False,
                )
            self._active_environment = environment

    def dispose(self) -> None:
        with self._lock:
            engines = list(self._engines.values())
        for engine in engines:
            engine.dispose()


settings = get_settings()
database_router = DatabaseRouter(
    settings.database_url,
    initial_environment=settings.env,
)


def can_switch_database_environment() -> bool:
    return settings.env == "development" and settings.device_role == "builder"


def get_db() -> Generator[Session, None, None]:
    with database_router.open_session() as session:
        yield session
