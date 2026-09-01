from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from zhiju.app import app
import zhiju.api.settings as settings_api
import zhiju.database as database_module
from zhiju.database import DatabaseRouter, read_database_url


def test_database_router_switches_only_new_sessions(tmp_path: Path) -> None:
    development_url = f"sqlite:///{tmp_path / 'development.db'}"
    production_url = f"sqlite:///{tmp_path / 'production.db'}"
    router = DatabaseRouter(
        development_url,
        initial_environment="development",
        production_url_loader=lambda: production_url,
    )

    existing_session = router.open_session()
    try:
        router.switch_environment("production", allow_switch=True)
        with router.open_session() as new_session:
            assert new_session.get_bind().url.database == str(tmp_path / "production.db")
        assert existing_session.get_bind().url.database == str(tmp_path / "development.db")
        assert router.active_environment == "production"
    finally:
        existing_session.close()
        router.dispose()


def test_failed_connection_keeps_current_environment(tmp_path: Path) -> None:
    development_url = f"sqlite:///{tmp_path / 'development.db'}"
    missing_parent_url = f"sqlite:///{tmp_path / 'missing' / 'production.db'}"
    router = DatabaseRouter(
        development_url,
        initial_environment="development",
        production_url_loader=lambda: missing_parent_url,
    )

    with pytest.raises(RuntimeError, match="生产数据库连接失败"):
        router.switch_environment("production", allow_switch=True)

    assert router.active_environment == "development"
    with router.open_session() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    router.dispose()


def test_database_switch_requires_builder_device(tmp_path: Path) -> None:
    router = DatabaseRouter(
        f"sqlite:///{tmp_path / 'development.db'}",
        initial_environment="development",
        production_url_loader=lambda: f"sqlite:///{tmp_path / 'production.db'}",
    )

    with pytest.raises(PermissionError, match="仅代码机"):
        router.switch_environment("production", allow_switch=False)

    assert router.active_environment == "development"
    router.dispose()


def test_builder_started_in_production_can_switch_to_development(tmp_path: Path) -> None:
    development_url = f"sqlite:///{tmp_path / 'development.db'}"
    production_url = f"sqlite:///{tmp_path / 'production.db'}"
    router = DatabaseRouter(
        production_url,
        initial_environment="production",
        development_url_loader=lambda: development_url,
    )

    router.switch_environment("development", allow_switch=True)

    assert router.active_environment == "development"
    with router.open_session() as session:
        assert session.get_bind().url.database == str(tmp_path / "development.db")
    router.dispose()


def test_switch_permission_depends_on_builder_role_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        database_module,
        "settings",
        SimpleNamespace(env="production", device_role="builder"),
    )

    assert database_module.can_switch_database_environment() is True


def test_read_database_url_uses_existing_runtime_config(tmp_path: Path) -> None:
    config = tmp_path / "zhiju-runtime.env"
    config.write_text(
        "# production\nZHJ_ENV=production\n"
        "ZHJ_DATABASE_URL=mysql+pymysql://app:secret@192.168.8.8:33306/zhiju_prod\n",
        encoding="utf-8",
    )

    assert read_database_url(config).endswith("@192.168.8.8:33306/zhiju_prod")


def test_runtime_api_declares_builder_environment_switch() -> None:
    client = TestClient(app)
    openapi = client.get("/openapi.json").json()

    assert "/api/v3/settings/runtime/environment" in openapi["paths"]
    runtime_fields = openapi["components"]["schemas"]["RuntimeOverview"]["properties"]
    assert "can_switch_environment" in runtime_fields
    assert "base_environment" in runtime_fields


def test_frontend_exposes_switch_and_persistent_environment_state() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "assets" / "app.js").read_text(encoding="utf-8")
    html_source = (root / "index.html").read_text(encoding="utf-8")
    backend_source = (root / "backend" / "zhiju" / "app.py").read_text(encoding="utf-8")

    assert 'data-action="switch-database-environment"' in app_source
    assert 'id="environmentState"' in html_source
    assert "生产环境" in app_source
    assert "开发环境" in app_source
    assert '"/api/v3/settings/runtime/environment"' in backend_source


def test_switching_to_production_runs_canonical_migrations_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(settings_api, "can_switch_database_environment", lambda: True)
    monkeypatch.setattr(
        settings_api,
        "upgrade_production_database",
        lambda: events.append("migrate"),
        raising=False,
    )
    monkeypatch.setattr(
        settings_api.database_router,
        "switch_environment",
        lambda environment, *, allow_switch: events.append(f"switch:{environment}"),
    )

    response = TestClient(app).put(
        "/api/v3/settings/runtime/environment",
        json={"environment": "production"},
    )

    assert response.status_code == 200
    assert events == ["migrate", "switch:production"]


def test_failed_production_migration_prevents_environment_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switched: list[str] = []

    monkeypatch.setattr(settings_api, "can_switch_database_environment", lambda: True)

    def fail_migration() -> None:
        raise RuntimeError("生产数据库迁移失败：测试错误")

    monkeypatch.setattr(
        settings_api,
        "upgrade_production_database",
        fail_migration,
        raising=False,
    )
    monkeypatch.setattr(
        settings_api.database_router,
        "switch_environment",
        lambda environment, *, allow_switch: switched.append(environment),
    )

    response = TestClient(app).put(
        "/api/v3/settings/runtime/environment",
        json={"environment": "production"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "生产数据库迁移失败：测试错误"
    assert switched == []


def test_production_upgrade_uses_project_alembic_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_config = tmp_path / "zhiju-runtime.env"
    runtime_config.write_text(
        "ZHJ_ENV=production\n"
        "ZHJ_DATABASE_URL=mysql+pymysql://app:secret@db:33306/zhiju_prod\n"
        "ZHJ_MIGRATION_DATABASE_URL=mysql+pymysql://migrator:secret@db:33306/zhiju_prod\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(database_module, "PRODUCTION_CONFIG_CANDIDATES", (runtime_config,))
    monkeypatch.setattr(subprocess, "run", fake_run)

    database_module.upgrade_production_database()

    assert captured["command"][-2:] == ["upgrade", "head"]
    environment = captured["kwargs"]["env"]
    assert environment["ZHJ_ENV"] == "production"
    assert environment["ZHJ_DATABASE_URL"].endswith("/zhiju_prod")
    assert environment["ZHJ_MIGRATION_DATABASE_URL"].endswith("/zhiju_prod")
