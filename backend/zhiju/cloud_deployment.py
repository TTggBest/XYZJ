from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from zhiju.config import validate_cloud_database_url
from zhiju.models import AppUser, Tenant
from zhiju.security import hash_password


DEFAULT_EXISTING_TENANT_ID = "00000000-0000-4000-8000-000000000001"
BOOTSTRAP_LOCK_NAME = "zhiju_cloud.bootstrap_super_admin.v1"
ALLOWED_MIGRATION_SEED_TABLES = frozenset(
    {
        "alembic_version",
        "app_icon_settings",
        "permissions",
        "publish_cadence_template_slots",
        "role_permissions",
        "schema_comments",
    }
)


def _read_env_template(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _upload_limit_megabytes(nginx: str) -> int:
    match = re.search(r"client_max_body_size\s+(\d+)([mMgG])\s*;", nginx)
    if not match:
        raise ValueError("Nginx 缺少 client_max_body_size")
    amount = int(match.group(1))
    return amount * 1024 if match.group(2).lower() == "g" else amount


def validate_deployment_artifacts(root: Path) -> dict[str, object]:
    app_env = _read_env_template(root / "zhiju-app.env.example")
    admin_env = _read_env_template(root / "zhiju-admin.env.example")
    systemd = (root / "zhiju.service").read_text(encoding="utf-8")
    nginx = (root / "nginx.conf").read_text(encoding="utf-8")

    if (
        app_env.get("ZHJ_ENV") != "production"
        or app_env.get("ZHJ_DEPLOYMENT") != "cloud"
    ):
        raise ValueError("云端模板必须使用 production 运行姿态和 cloud marker")
    if "ZHJ_MIGRATION_DATABASE_URL" in app_env:
        raise ValueError("Web 运行配置禁止包含 DDL 凭据")
    if "ZHJ_DATABASE_URL" in admin_env:
        raise ValueError("一次性管理配置不应重复 Web 凭据")
    for values, key in (
        (app_env, "ZHJ_DATABASE_URL"),
        (admin_env, "ZHJ_MIGRATION_DATABASE_URL"),
    ):
        value = values.get(key, "")
        validate_cloud_database_url(value, label=key)
        password = make_url(value).password or ""
        if password not in {"CHANGE_ME", "${ZHJ_DB_PASSWORD}"}:
            raise ValueError(f"{key} 模板中禁止嵌入真实密码")
    if app_env.get("ZHJ_HOST") != "127.0.0.1":
        raise ValueError("cloud environment must keep Uvicorn on loopback")
    if "EnvironmentFile=/etc/zhiju/zhiju-app.env" not in systemd:
        raise ValueError("systemd must load only the cloud app environment")
    if "zhiju-admin.env" in systemd or "ZHJ_MIGRATION_DATABASE_URL" in systemd:
        raise ValueError("systemd Web process must not receive migration credentials")

    exec_start = next(
        (line for line in systemd.splitlines() if line.strip().startswith("ExecStart=")),
        "",
    )
    if not re.search(r"--host\s+127\.0\.0\.1(?:\s|$)", exec_start):
        raise ValueError("systemd must bind Uvicorn to loopback")

    upload_limit = _upload_limit_megabytes(nginx)
    if upload_limit < 512:
        raise ValueError("Nginx upload limit is too small for 100-200 image batches")
    sse_location = re.search(
        r"location\s+[^\{]*(?:realtime|events)[^\{]*\{(?P<body>.*?)\}",
        nginx,
        flags=re.DOTALL,
    )
    if not sse_location or not re.search(
        r"proxy_buffering\s+off\s*;", sse_location.group("body")
    ):
        raise ValueError("Nginx SSE proxy must disable buffering")

    return {
        "deployment": "cloud",
        "database": "zhiju_cloud",
        "uvicorn_host": "127.0.0.1",
        "sse_buffering": "off",
        "upload_limit_megabytes": upload_limit,
    }


def _remove_empty_legacy_tenant(session: Session) -> None:
    tenant = session.get(Tenant, DEFAULT_EXISTING_TENANT_ID)
    if tenant is None:
        return
    bind = session.get_bind()
    inspector = inspect(bind)
    references: list[str] = []
    for table_name in inspector.get_table_names():
        if table_name == "tenants":
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "tenant_id" not in columns:
            continue
        quoted = inspector.dialect.identifier_preparer.quote(table_name)
        count = session.scalar(
            text(f"SELECT COUNT(*) FROM {quoted} WHERE tenant_id = :tenant_id"),
            {"tenant_id": DEFAULT_EXISTING_TENANT_ID},
        )
        if count:
            references.append(table_name)
    if references:
        raise ValueError(
            "云端初始化拒绝删除存在业务引用的旧默认主账号："
            + "、".join(sorted(references))
        )
    session.delete(tenant)
    session.flush()


def _require_empty_cloud_database(session: Session) -> None:
    if session.scalar(
        select(func.count()).select_from(Tenant).where(
            Tenant.id != DEFAULT_EXISTING_TENANT_ID
        )
    ):
        raise ValueError("云端 bootstrap 要求非空业务主账号为零")
    inspector = inspect(session.get_bind())
    occupied: list[str] = []
    for table_name in inspector.get_table_names():
        if table_name == "tenants" or table_name in ALLOWED_MIGRATION_SEED_TABLES:
            continue
        quoted = inspector.dialect.identifier_preparer.quote(table_name)
        if session.scalar(text(f"SELECT COUNT(*) FROM {quoted}")):
            occupied.append(table_name)
    if occupied:
        raise ValueError("云端 bootstrap 要求业务表为空：" + "、".join(sorted(occupied)))


@contextmanager
def _bootstrap_database_lock(session: Session):
    bind = session.get_bind()
    dialect = bind.dialect.name
    if dialect != "mysql":
        raise RuntimeError(f"云端 bootstrap 只支持 MySQL，当前为：{dialect}")
    with bind.connect() as lock_connection:
        acquired_mysql_lock = lock_connection.scalar(
            text("SELECT GET_LOCK(:lock_name, 30)"),
            {"lock_name": BOOTSTRAP_LOCK_NAME},
        ) == 1
        if not acquired_mysql_lock:
            raise RuntimeError("无法获取云端 bootstrap 数据库锁")
        try:
            yield
        except Exception:
            session.rollback()
            raise
        finally:
            lock_connection.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": BOOTSTRAP_LOCK_NAME},
            )


def bootstrap_super_admin(
    session: Session,
    *,
    login_name: str,
    display_name: str,
    password: str,
    output: Callable[[str], None] = print,
) -> bool:
    login_name = login_name.strip()
    display_name = display_name.strip()
    if not login_name or not display_name or not password:
        raise ValueError("超级管理员登录名、显示名和密码均不能为空")
    with _bootstrap_database_lock(session):
        if session.scalar(select(func.count()).select_from(AppUser)):
            raise ValueError("用户已存在，云库非空，拒绝重复 bootstrap")
        _require_empty_cloud_database(session)

        _remove_empty_legacy_tenant(session)
        now = datetime.now(timezone.utc)
        session.add(
            AppUser(
                display_name=display_name,
                login_name=login_name,
                password_hash=hash_password(password),
                platform_role="super_admin",
                status="active",
                password_changed_at=now,
            )
        )
        session.commit()
    output(f"云端超级管理员已创建：{login_name}")
    return True
