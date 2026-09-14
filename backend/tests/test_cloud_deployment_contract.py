from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from zhiju.cloud_deployment import bootstrap_super_admin, validate_deployment_artifacts
from zhiju.auth_context import Principal
from zhiju.config import Settings, validate_cloud_database_url
from zhiju.models import (
    AppIconSetting,
    AppUser,
    Base,
    Permission,
    RuntimePackageBuild,
    SchemaComment,
    Tenant,
)
from zhiju.security import verify_password
import zhiju.api.settings as settings_api
import zhiju.api.youtube_oauth as youtube_oauth_api
import zhiju.cloud_deployment as cloud_deployment_module
import zhiju.database as database_module
import zhiju.permissions as permissions_module
from zhiju.permissions import require_super_code_machine


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = ROOT / "deploy" / "tencent-cloud" / "v1"


@pytest.fixture
def sqlite_bootstrap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        cloud_deployment_module,
        "_bootstrap_database_lock",
        lambda _session: nullcontext(),
    )
    return bootstrap_super_admin


def cloud_settings(**overrides: str) -> Settings:
    values = {
        "env": "production",
        "deployment": "cloud",
        "database_url": "mysql+pymysql://zhiju_app:secret@127.0.0.1:3306/zhiju_cloud",
        "migration_database_url": (
            "mysql+pymysql://zhiju_migrator:secret@127.0.0.1:3306/zhiju_cloud"
        ),
        "host": "127.0.0.1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_cloud_web_settings_do_not_require_migration_credentials() -> None:
    settings = cloud_settings(migration_database_url=None)

    assert settings.database_url.endswith("/zhiju_cloud")
    assert settings.migration_database_url is None


def test_cloud_platform_control_accepts_bootstrap_admin_without_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(permissions_module, "get_settings", cloud_settings)
    principal = Principal(
        user_id="cloud-admin",
        tenant_id=None,
        membership_role=None,
        platform_role="super_admin",
        device_id=None,
        device_trust_level="normal",
        permissions=frozenset({"platform.tenant.manage"}),
    )

    assert require_super_code_machine(principal) is principal
    assert principal.device_id is None


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"deployment": "cluod"}, "local.*cloud"),
        ({"env": "development"}, "ZHJ_ENV=production"),
        (
            {"database_url": "mysql+pymysql://u:p@127.0.0.1/zhiju_prod"},
            "zhiju_cloud",
        ),
        (
            {"migration_database_url": "mysql+pymysql://u:p@127.0.0.1/zhiju_prod"},
            "zhiju_cloud",
        ),
        (
            {"database_url": "mysql+pymysql://u:p@192.168.8.251/zhiju_cloud"},
            "本机 TCP",
        ),
        ({"host": "0.0.0.0"}, "127.0.0.1"),
    ],
)
def test_cloud_settings_reject_unsafe_targets_before_engine_creation(
    overrides: dict[str, str], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_calls: list[str] = []
    monkeypatch.setattr(
        database_module,
        "_create_database_engine",
        lambda url: engine_calls.append(url),
    )

    with pytest.raises(ValidationError, match=message):
        cloud_settings(**overrides)

    assert engine_calls == []


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "LOCALHOST.", "[::1]"],
)
def test_cloud_database_accepts_only_normalized_local_tcp_hosts(host: str) -> None:
    validate_cloud_database_url(
        f"mysql+pymysql://user:secret@{host}:3306/zhiju_cloud",
        label="test",
    )


@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://user:secret@127.0.0.2:3306/zhiju_cloud",
        "mysql+pymysql://user:secret@192.168.8.251:3306/zhiju_cloud",
        "mysql+pymysql://user:secret@192.168.8.99:3306/zhiju_cloud",
        "mysql+pymysql://user:secret@studio-alias.internal:3306/zhiju_cloud",
        "mysql+pymysql://user:secret@db.internal:3306/zhiju_cloud",
        "mysql+pymysql://user:secret@localhost/zhiju_cloud?unix_socket=/tmp/mysql.sock",
    ],
)
def test_cloud_database_rejects_nonlocal_aliases_and_socket_bypasses(url: str) -> None:
    with pytest.raises(ValueError, match="本机 TCP"):
        validate_cloud_database_url(url, label="test")


def test_cloud_marker_keeps_production_runtime_and_disables_environment_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = cloud_settings()
    monkeypatch.setattr(database_module, "settings", settings)
    monkeypatch.setattr(settings_api, "get_settings", lambda: settings)
    events: list[str] = []
    monkeypatch.setattr(
        settings_api, "can_switch_database_environment", lambda: False
    )
    monkeypatch.setattr(
        settings_api,
        "upgrade_production_database",
        lambda: events.append("migrate"),
    )

    with pytest.raises(HTTPException) as error:
        settings_api.put_runtime_environment(
            SimpleNamespace(environment="production"), _session=SimpleNamespace()
        )

    assert settings.env == "production"
    assert settings.deployment == "cloud"
    assert database_module.can_switch_database_environment() is False
    assert error.value.status_code == 403
    assert "云端" in error.value.detail
    assert events == []


def test_cloud_oauth_status_uses_server_configuration_without_macos_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        youtube_oauth_api,
        "get_settings",
        lambda: SimpleNamespace(
            deployment="cloud",
            device_role="builder",
            youtube_oauth_configured=False,
            youtube_oauth_client_id="",
            youtube_oauth_redirect_uri="https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback",
        ),
    )
    monkeypatch.setattr(
        youtube_oauth_api,
        "MacOSKeychainSecretStore",
        lambda: pytest.fail("cloud request invoked macOS Keychain"),
    )

    result = youtube_oauth_api.get_youtube_oauth_status()

    assert result.configured is False
    assert result.channel_import_enabled is True
    assert result.redirect_uri == "https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback"


def test_cloud_app_icon_write_fails_before_invoking_macos_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_api,
        "get_settings",
        lambda: SimpleNamespace(deployment="cloud"),
    )
    monkeypatch.setattr(
        settings_api,
        "upload_app_icon",
        lambda *args: pytest.fail("cloud request invoked macOS icon renderer"),
    )

    with pytest.raises(HTTPException) as error:
        settings_api.put_app_icon(
            SimpleNamespace(filename="icon.png", data_url="data:image/png;base64,eA=="),
            session=SimpleNamespace(),
        )

    assert error.value.status_code == 501
    assert "macOS" in error.value.detail


def test_versioned_templates_pass_the_executable_deployment_validator() -> None:
    result = validate_deployment_artifacts(DEPLOYMENT_ROOT)

    assert result == {
        "deployment": "cloud",
        "database": "zhiju_cloud",
        "uvicorn_host": "127.0.0.1",
        "sse_buffering": "off",
        "upload_limit_megabytes": 1024,
    }


def test_web_service_environment_has_no_migration_credentials() -> None:
    app_env = (DEPLOYMENT_ROOT / "zhiju-app.env.example").read_text(encoding="utf-8")
    admin_env = (DEPLOYMENT_ROOT / "zhiju-admin.env.example").read_text(
        encoding="utf-8"
    )
    service = (DEPLOYMENT_ROOT / "zhiju.service").read_text(encoding="utf-8")
    initializer = (DEPLOYMENT_ROOT / "scripts" / "initialize_database.sh").read_text(
        encoding="utf-8"
    )
    bootstrap = (
        DEPLOYMENT_ROOT / "scripts" / "bootstrap_super_admin.py"
    ).read_text(encoding="utf-8")

    assert "ZHJ_DATABASE_URL=" in app_env
    assert "ZHJ_MIGRATION_DATABASE_URL" not in app_env
    assert "ZHJ_MIGRATION_DATABASE_URL=" in admin_env
    assert "ZHJ_DATABASE_URL=" not in admin_env.replace(
        "ZHJ_MIGRATION_DATABASE_URL=", ""
    )
    assert "EnvironmentFile=/etc/zhiju/zhiju-app.env" in service
    assert "zhiju-admin.env" not in service
    assert "ZHJ_MIGRATION_DATABASE_URL" not in service
    assert "zhiju-app.env" in initializer and "zhiju-admin.env" in initializer
    assert "zhiju-app.env" in bootstrap and "zhiju-admin.env" in bootstrap


def test_cloud_runbook_configures_web_youtube_oauth_without_studio_secrets() -> None:
    app_env = (DEPLOYMENT_ROOT / "zhiju-app.env.example").read_text(encoding="utf-8")
    runbook = (DEPLOYMENT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "ZHJ_YOUTUBE_OAUTH_CLIENT_ID=" in app_env
    assert "ZHJ_YOUTUBE_OAUTH_CLIENT_SECRET=" in app_env
    assert "ZHJ_YOUTUBE_OAUTH_REDIRECT_URI=https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback" in app_env
    assert "ZHJ_OAUTH_ENCRYPTION_KEY=" in app_env
    assert "Web 应用" in runbook
    assert "Studio" in runbook
    assert "不要复用" in runbook


def test_cloud_runtime_installs_oauth_encryption_dependency() -> None:
    requirements = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")

    assert "cryptography>=45,<47" in requirements


def test_deployment_validator_catches_public_uvicorn_and_missing_sse_settings(
    tmp_path: Path,
) -> None:
    systemd = tmp_path / "zhiju.service"
    nginx = tmp_path / "nginx.conf"
    app_env = tmp_path / "zhiju-app.env.example"
    admin_env = tmp_path / "zhiju-admin.env.example"
    systemd.write_text(
        "EnvironmentFile=/etc/zhiju/zhiju-app.env\n"
        "Environment=TMPDIR=/run/zhiju\n"
        "RuntimeDirectory=zhiju\n"
        "RuntimeDirectoryMode=0750\n"
        "ReadWritePaths=/var/lib/zhiju/shared /run/zhiju\n"
        "ExecStartPre=/opt/zhiju/current/.venv/bin/python -c "
        '"import tempfile; tempfile.TemporaryFile().close()"\n'
        "ExecStart=/opt/zhiju/current/.venv/bin/uvicorn zhiju.app:app --host 0.0.0.0 --port 19732\n",
        encoding="utf-8",
    )
    nginx.write_text(
        "server { client_max_body_size 10m; location /api/v3/realtime/events { proxy_pass http://127.0.0.1:19732; } }\n",
        encoding="utf-8",
    )
    app_env.write_text(
        "ZHJ_ENV=production\nZHJ_DEPLOYMENT=cloud\n"
        "ZHJ_DATABASE_URL=mysql+pymysql://user:CHANGE_ME@127.0.0.1/zhiju_cloud\n"
        "ZHJ_HOST=127.0.0.1\n",
        encoding="utf-8",
    )
    admin_env.write_text(
        "ZHJ_MIGRATION_DATABASE_URL="
        "mysql+pymysql://user:CHANGE_ME@127.0.0.1/zhiju_cloud\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="loopback"):
        validate_deployment_artifacts(tmp_path)


def test_bootstrap_creates_one_super_admin_without_exposing_password(
    sqlite_bootstrap,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    messages: list[str] = []
    with Session(engine) as session:
        session.add(
            Tenant(
                id="00000000-0000-4000-8000-000000000001",
                company_name="智矩现有业务",
                short_name="智矩现有业务",
                status="active",
                lease_expires_at=datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            )
        )
        session.commit()

        created = sqlite_bootstrap(
            session,
            login_name="cloud-admin",
            display_name="Cloud Admin",
            password="never-print-this-password",
            output=messages.append,
        )

        stored = session.scalar(select(AppUser))
        assert created is True
        assert stored is not None
        assert stored.login_name == "cloud-admin"
        assert stored.platform_role == "super_admin"
        assert verify_password("never-print-this-password", stored.password_hash)
        assert session.get(Tenant, "00000000-0000-4000-8000-000000000001") is None
        assert "never-print-this-password" not in "\n".join(messages)

        with pytest.raises(ValueError, match="已存在"):
            sqlite_bootstrap(
                session,
                login_name="another-admin",
                display_name="Another Admin",
                password="another-password",
                output=messages.append,
            )
    engine.dispose()


def test_bootstrap_refuses_a_nonempty_cloud_tenant_database(sqlite_bootstrap) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Tenant(
                id="tenant-existing",
                company_name="Existing Company",
                short_name="existing",
                status="active",
                lease_expires_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
            )
        )
        session.commit()

        with pytest.raises(ValueError, match="非空"):
            sqlite_bootstrap(
                session,
                login_name="cloud-admin",
                display_name="Cloud Admin",
                password="not-logged",
            )
    engine.dispose()


def test_bootstrap_allows_only_migration_seed_tables(sqlite_bootstrap) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add_all(
            [
                Permission(id="permission", code="tenant.read", name_zh="查看主账号"),
                SchemaComment(
                    table_name="channels",
                    column_name="id",
                    chinese_comment="系统主键",
                    updated_at=now,
                ),
                AppIconSetting(
                    id="current-app-icon",
                    source_type="default",
                    source_path="assets/app-icon-default.png",
                    original_filename="app-icon-default.png",
                    applied_at=now,
                ),
            ]
        )
        session.commit()

        assert sqlite_bootstrap(
            session,
            login_name="cloud-admin",
            display_name="Cloud Admin",
            password="not-logged",
            output=lambda _message: None,
        )
    engine.dispose()


def test_bootstrap_refuses_non_tenant_runtime_records_without_writing_user(
    sqlite_bootstrap,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            RuntimePackageBuild(
                build_number=1,
                version="3.0.0-build.1",
                target_environment="production",
                status="succeeded",
                artifact_path=None,
                file_count=1,
                size_bytes=1,
                started_at=now,
                completed_at=now,
            )
        )
        session.commit()

        with pytest.raises(ValueError, match="runtime_package_builds"):
            sqlite_bootstrap(
                session,
                login_name="cloud-admin",
                display_name="Cloud Admin",
                password="not-logged",
                output=lambda _message: None,
            )

        assert session.scalar(select(AppUser)) is None
    engine.dispose()


def test_two_independent_mysql_sessions_serialize_bootstrap_competition() -> None:
    database_url = os.environ.get("ZHJ_DATABASE_URL", "")
    if not database_url or make_url(database_url).database != "zhiju_dev":
        pytest.skip("requires the code-machine zhiju_dev test database")
    engine = create_engine(database_url, pool_pre_ping=True)
    start = Barrier(2)
    bootstrap_state: list[int] = []

    def attempt(index: int) -> str:
        with Session(engine) as session:
            start.wait()
            with cloud_deployment_module._bootstrap_database_lock(session):
                if bootstrap_state:
                    return "refused"
                time.sleep(0.15)
                bootstrap_state.append(index)
                session.commit()
                return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))

    assert sorted(results) == ["created", "refused"]
    assert len(bootstrap_state) == 1
    engine.dispose()


def test_bootstrap_cli_has_no_password_argument() -> None:
    script = DEPLOYMENT_ROOT / "scripts" / "bootstrap_super_admin.py"
    spec = importlib.util.spec_from_file_location("cloud_bootstrap_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    option_strings = {
        option
        for action in module.build_parser()._actions
        for option in action.option_strings
    }
    assert "--password" not in option_strings
    assert "--password-file" not in option_strings


def test_cloud_runbook_covers_operational_and_macos_boundaries() -> None:
    runbook = (DEPLOYMENT_ROOT / "README.md").read_text(encoding="utf-8")

    for topic in ("部署", "更新", "回滚", "备份", "Certbot", "macOS"):
        assert topic in runbook


def test_environment_file_permissions_match_service_and_bootstrap_user() -> None:
    app_env_instructions = (DEPLOYMENT_ROOT / "zhiju-app.env.example").read_text(
        encoding="utf-8"
    )
    admin_env_instructions = (DEPLOYMENT_ROOT / "zhiju-admin.env.example").read_text(
        encoding="utf-8"
    )
    runbook = (DEPLOYMENT_ROOT / "README.md").read_text(encoding="utf-8")
    service = (DEPLOYMENT_ROOT / "zhiju.service").read_text(encoding="utf-8")

    assert "root:zhiju 0640" in app_env_instructions
    assert "root:root 0600" in admin_env_instructions
    assert "install -o root -g zhiju -m 0640" in runbook
    assert "install -o root -g root -m 0600" in runbook
    assert "sudo -u zhiju -g zhiju" not in runbook
    assert "User=zhiju" in service and "Group=zhiju" in service


def test_release_tree_is_root_owned_read_only_before_current_switch() -> None:
    provision = (DEPLOYMENT_ROOT / "scripts" / "provision_ubuntu.sh").read_text(
        encoding="utf-8"
    )
    service = (DEPLOYMENT_ROOT / "zhiju.service").read_text(encoding="utf-8")

    assert "install -d -o root -g zhiju -m 0755 /opt/zhiju/releases" in provision
    assert 'chown -R root:zhiju "$release"' in provision
    assert 'chmod -R a=rX,u+w "$release"' in provision
    assert "chown -R zhiju:zhiju" not in provision
    pip_install = provision.index('"$release/.venv/bin/pip" install')
    ownership = provision.index('chown -R root:zhiju "$release"')
    permission_probe = provision.index('sudo -u zhiju -- "$release/.venv/bin/python"')
    uvicorn_probe = provision.index('sudo -u zhiju -- "$release/.venv/bin/uvicorn"')
    current_switch = provision.index('ln -sfn "$release" /opt/zhiju/current')
    assert pip_install < ownership < permission_probe < uvicorn_probe < current_switch
    assert "ProtectSystem=strict" in service
    assert "ReadOnlyPaths=/opt/zhiju" in service
    assert "ReadWritePaths=/var/lib/zhiju/shared" in service


def test_systemd_runtime_directory_supports_package_build_and_download_tempfiles() -> None:
    validate_deployment_artifacts(DEPLOYMENT_ROOT)
    service = (DEPLOYMENT_ROOT / "zhiju.service").read_text(encoding="utf-8")

    assert "RuntimeDirectory=zhiju" in service
    assert "RuntimeDirectoryMode=0750" in service
    assert "Environment=TMPDIR=/run/zhiju" in service
    assert "ReadWritePaths=/var/lib/zhiju/shared /run/zhiju" in service
    assert "ExecStartPre=" in service and "TemporaryFile" in service
