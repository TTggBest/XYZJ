from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from zhiju.cloud_deployment import bootstrap_super_admin, validate_deployment_artifacts
from zhiju.config import Settings
from zhiju.models import AppUser, Base, Tenant
from zhiju.security import verify_password
import zhiju.api.settings as settings_api
import zhiju.api.youtube_oauth as youtube_oauth_api
import zhiju.database as database_module


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = ROOT / "deploy" / "tencent-cloud" / "v1"


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
            "Studio",
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


def test_cloud_macos_only_endpoints_fail_clearly_without_invoking_macos_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        youtube_oauth_api,
        "get_settings",
        lambda: SimpleNamespace(deployment="cloud", device_role="builder"),
    )
    monkeypatch.setattr(
        youtube_oauth_api,
        "MacOSKeychainSecretStore",
        lambda: pytest.fail("cloud request invoked macOS Keychain"),
    )

    with pytest.raises(HTTPException) as error:
        youtube_oauth_api.get_youtube_oauth_status()

    assert error.value.status_code == 501
    assert "macOS" in error.value.detail
    assert "云端" in error.value.detail


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


def test_deployment_validator_catches_public_uvicorn_and_missing_sse_settings(
    tmp_path: Path,
) -> None:
    systemd = tmp_path / "zhiju.service"
    nginx = tmp_path / "nginx.conf"
    env = tmp_path / "zhiju-cloud.env.example"
    systemd.write_text(
        "ExecStart=/opt/zhiju/current/.venv/bin/uvicorn zhiju.app:app --host 0.0.0.0 --port 19732\n",
        encoding="utf-8",
    )
    nginx.write_text(
        "server { client_max_body_size 10m; location /api/v3/realtime/events { proxy_pass http://127.0.0.1:19732; } }\n",
        encoding="utf-8",
    )
    env.write_text(
        "ZHJ_ENV=production\nZHJ_DEPLOYMENT=cloud\n"
        "ZHJ_DATABASE_URL=mysql+pymysql://user:CHANGE_ME@127.0.0.1/zhiju_cloud\n"
        "ZHJ_MIGRATION_DATABASE_URL=mysql+pymysql://user:CHANGE_ME@127.0.0.1/zhiju_cloud\n"
        "ZHJ_HOST=127.0.0.1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="loopback"):
        validate_deployment_artifacts(tmp_path)


def test_bootstrap_creates_one_super_admin_without_exposing_password() -> None:
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

        created = bootstrap_super_admin(
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
            bootstrap_super_admin(
                session,
                login_name="another-admin",
                display_name="Another Admin",
                password="another-password",
                output=messages.append,
            )
    engine.dispose()


def test_bootstrap_refuses_a_nonempty_cloud_tenant_database() -> None:
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
            bootstrap_super_admin(
                session,
                login_name="cloud-admin",
                display_name="Cloud Admin",
                password="not-logged",
            )
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
