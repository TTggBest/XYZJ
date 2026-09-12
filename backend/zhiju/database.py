from __future__ import annotations

from collections.abc import Callable, Generator
import os
from pathlib import Path
import subprocess
import sys
from threading import RLock
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria

from zhiju.config import APP_ROOT, get_settings
from zhiju.models.base import TenantOwnedMixin
from zhiju.tenant_repository import require_tenant_entities

if TYPE_CHECKING:
    from zhiju.auth_context import Principal


class TenantSession(Session):
    """Business unit of work bound to one resolved principal's tenant."""


@event.listens_for(TenantSession, "do_orm_execute")
def _scope_tenant_statement(state: ORMExecuteState) -> None:
    if state.is_update and state.bind_mapper is not None and issubclass(
        state.bind_mapper.class_, TenantOwnedMixin,
    ):
        # Bulk UPDATE bypasses before_flush; ownership is immutable here too.
        assignments = list(state.statement._values or {})
        assignments.extend(key for key, _ in state.statement._ordered_values or ())
        parameters = state.parameters or {}
        parameter_sets = parameters if isinstance(parameters, list) else [parameters]
        if any(getattr(key, "key", key) == "tenant_id" for key in assignments) or any(
            "tenant_id" in values for values in parameter_sets
        ):
            raise HTTPException(status_code=403, detail="不能更改数据所属主账号")
        if state.is_executemany:
            # SQLAlchemy's bulk-by-PK path does not apply loader criteria.
            require_tenant_entities(
                state.session, state.bind_mapper.class_,
                [values["id"] for values in parameter_sets], lock=True,
            )
    if state.is_select or state.is_update or state.is_delete:
        tenant_id = state.session.info["tenant_id"]
        state.statement = state.statement.options(with_loader_criteria(
            TenantOwnedMixin, lambda model: model.tenant_id == tenant_id, include_aliases=True,
        ))


@event.listens_for(TenantSession, "before_flush")
def _validate_tenant_objects(session: TenantSession, flush_context, instances) -> None:
    tenant_id = session.info["tenant_id"]
    for obj in session.new | session.dirty | session.deleted:
        if not isinstance(obj, TenantOwnedMixin):
            continue
        if obj in session.new and obj.tenant_id is None:
            obj.tenant_id = tenant_id
        history = inspect(obj).attrs.tenant_id.history
        if obj.tenant_id != tenant_id or any(old != tenant_id for old in history.deleted):
            raise HTTPException(status_code=403, detail="不能写入其他主账号的数据")


PRODUCTION_CONFIG_CANDIDATES = (
    Path.home() / "Documents" / "XYData" / "XYZJ" / "config" / "zhiju-runtime.env",
    Path("/Volumes/XYData/XYZJ/config/zhiju-runtime.env"),
    Path.home() / "Library" / "Application Support" / "筱宇智矩" / "runtime.env",
)


def _read_runtime_value(path: Path, key: str) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    raise ValueError(f"生产配置未提供 {key}：{path}")


def read_database_url(path: Path) -> str:
    return _read_runtime_value(path, "ZHJ_DATABASE_URL")


def _load_production_runtime_value(key: str) -> str:
    for path in PRODUCTION_CONFIG_CANDIDATES:
        if path.is_file():
            return _read_runtime_value(path, key)
    raise FileNotFoundError("未找到智矩生产配置，请确认 XYData/XYZJ 已挂载")


def load_production_database_url() -> str:
    return _load_production_runtime_value("ZHJ_DATABASE_URL")


def upgrade_production_database() -> None:
    database_url = load_production_database_url()
    migration_url = _load_production_runtime_value("ZHJ_MIGRATION_DATABASE_URL")
    if make_url(database_url).database != "zhiju_prod" or make_url(migration_url).database != "zhiju_prod":
        raise RuntimeError("生产数据库迁移失败：生产配置未指向 zhiju_prod")

    environment = os.environ.copy()
    environment.update(
        ZHJ_ENV="production",
        ZHJ_DATABASE_URL=database_url,
        ZHJ_MIGRATION_DATABASE_URL=migration_url,
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(APP_ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=APP_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(f"生产数据库迁移失败：{detail[-1] if detail else 'Alembic 执行失败'}")


def load_development_database_url() -> str:
    path = APP_ROOT / ".env"
    if not path.is_file():
        raise FileNotFoundError(f"未找到代码机开发配置：{path}")
    database_url = read_database_url(path)
    if make_url(database_url).database != "zhiju_dev":
        raise ValueError(f"代码机开发配置未指向 zhiju_dev：{path}")
    return database_url


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
        development_url_loader: Callable[[], str] = load_development_database_url,
        production_url_loader: Callable[[], str] = load_production_database_url,
    ) -> None:
        environment = "production" if initial_environment == "production" else "development"
        engine = _create_database_engine(database_url)
        self._lock = RLock()
        self._active_environment = environment
        self._development_url_loader = development_url_loader
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
            raise PermissionError("仅代码机允许切换数据库环境")
        if environment not in {"development", "production"}:
            raise ValueError("数据库环境只能是 development 或 production")

        with self._lock:
            if environment == self._active_environment:
                return
            engine = self._engines.get(environment)

        created_engine = False
        if engine is None:
            try:
                loader = (
                    self._production_url_loader
                    if environment == "production"
                    else self._development_url_loader
                )
                database_url = loader()
                engine = _create_database_engine(database_url)
                created_engine = True
            except Exception as exc:
                label = "生产" if environment == "production" else "开发"
                raise RuntimeError(f"{label}数据库配置读取失败：{exc}") from exc

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
    return settings.device_role == "builder"


def get_db() -> Generator[Session, None, None]:
    """Unscoped sessions for authentication, platform management and bootstrap."""
    with database_router.open_session() as session:
        yield session


def open_tenant_session(principal: Principal) -> TenantSession:
    if not principal.tenant_id:
        raise HTTPException(status_code=403, detail="请选择当前主账号")
    return TenantSession(
        bind=database_router.get_active_engine(), autoflush=False, expire_on_commit=False,
        info={
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "permissions": principal.permissions,
        },
    )
