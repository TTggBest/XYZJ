from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.auth_context import Principal, get_current_principal
from zhiju.config import get_settings


def test_health_reaches_mysql() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["database"]["ok"] is True


def test_health_reports_runtime_web_port() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["web_port"] == get_settings().port


def test_identity_lists_require_login_and_start_from_tenant_database(monkeypatch) -> None:
    client = TestClient(app)
    assert client.get("/api/v3/accounts").status_code == 401
    assert client.get("/api/v3/channels").status_code == 401
    principal = Principal(
        user_id="test-user", tenant_id="00000000-0000-4000-8000-000000000001",
        membership_role="owner", platform_role=None, device_id=None,
        device_trust_level="normal", permissions=frozenset({"channel.read"}),
    )
    monkeypatch.setitem(app.dependency_overrides, get_current_principal, lambda: principal)
    assert client.get("/api/v3/accounts").status_code == 200
    assert client.get("/api/v3/channels").status_code == 200


def test_root_serves_management_ui() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-cache"
    assert "筱宇智矩" in response.text
    assert "operations-page-data.js?v=3.18.4" in response.text
    assert "app.js?v=3.19.0" in response.text
    app_js = client.get("/assets/app.js")
    assert app_js.status_code == 200
    assert app_js.headers["cache-control"] == "no-cache"


def test_navigation_groups_media_with_production_and_hides_builder_pages_by_default() -> None:
    root = TestClient(app).get("/").text
    production_index = root.index('<div class="nav-label">生产执行</div>')
    media_index = root.index('data-view="media"')
    configuration_index = root.index('<div class="nav-label">数据与配置</div>')

    assert production_index < media_index < configuration_index
    assert 'data-view="skills" data-builder-only hidden' in root
    assert 'data-view="logs" data-builder-only hidden' in root

    source = TestClient(app).get("/assets/app.js").text
    assert 'const BUILDER_ONLY_VIEWS = new Set(["skills", "logs", "settings"])' in source
    assert 'document.querySelectorAll("[data-builder-only]")' in source
