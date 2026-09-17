from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from zhiju import auth_context
from zhiju.api import youtube_oauth as youtube_oauth_api
from zhiju.auth_context import Principal
from zhiju.services.youtube_oauth import OAuthClientConfig


PRINCIPAL = Principal(
    user_id="user-a",
    tenant_id="tenant-a",
    membership_role="owner",
    platform_role="super_admin",
    device_id=None,
    device_trust_level="normal",
    permissions=frozenset({"channel.manage"}),
    session_id="auth-session-a",
)


def _app(monkeypatch):
    app = FastAPI()
    app.include_router(youtube_oauth_api.router, prefix="/api")
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    app.dependency_overrides[auth_context.get_tenant_db] = lambda: SimpleNamespace()
    monkeypatch.setattr(
        youtube_oauth_api,
        "get_settings",
        lambda: SimpleNamespace(device_role="builder", port=19732),
    )
    return app


def test_start_channel_import_uses_configured_google_oauth_without_placeholder_channel(monkeypatch):
    app = _app(monkeypatch)
    config = OAuthClientConfig(
        client_type="installed",
        client_id="client-id",
        client_secret_value="client-secret",
        project_id="fixture",
        auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
        token_uri="https://oauth2.googleapis.com/token",
        redirect_uri="http://127.0.0.1:8080",
    )
    monkeypatch.setattr(youtube_oauth_api, "load_oauth_client_config", lambda store: config)
    monkeypatch.setattr(youtube_oauth_api, "create_channel_import_state", lambda session, principal, **kwargs: "state-a")
    monkeypatch.setattr(youtube_oauth_api.callback_relay, "ensure", lambda registered, callback: None)

    with TestClient(app) as client:
        response = client.post("/api/v3/youtube/channel-imports/start")

    assert response.status_code == 200, response.text
    assert response.json()["authorization_url"].startswith("https://accounts.google.com/")
    assert "state=state-a" in response.json()["authorization_url"]


def test_callback_completes_channel_discovery_and_notifies_opener(monkeypatch):
    import_context = SimpleNamespace(
        tenant_id="tenant-a", user_id="user-a", auth_session_id="auth-session-a",
    )
    outer_session = SimpleNamespace(
        scalar=lambda query: import_context,
        get_bind=lambda: object(),
        rollback=lambda: None,
    )
    tenant_session = SimpleNamespace()
    monkeypatch.setattr(youtube_oauth_api, "get_settings", lambda: SimpleNamespace(device_role="builder", port=19732))
    monkeypatch.setattr(youtube_oauth_api, "TenantSession", lambda **kwargs: nullcontext(tenant_session))
    monkeypatch.setattr(youtube_oauth_api, "load_oauth_client_config", lambda store: SimpleNamespace())
    monkeypatch.setattr(youtube_oauth_api, "exchange_authorization_code", lambda config, code: {"access_token": "token", "refresh_token": "refresh"})
    monkeypatch.setattr(youtube_oauth_api, "fetch_google_identity", lambda token: {"sub": "google-a", "email": "a@example.com"})
    monkeypatch.setattr(youtube_oauth_api, "fetch_youtube_channels", lambda token: {"items": [{"id": "UC-a", "snippet": {"title": "A"}}]})
    monkeypatch.setattr(youtube_oauth_api, "complete_channel_import_oauth", lambda session, store, **kwargs: "import-a")

    response = youtube_oauth_api.get_youtube_oauth_callback(
        state="state-a", code="code-a", session=outer_session,
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert "youtube-channel-import-ready" in body
    assert "import-a" in body
