import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from zhiju import auth_context
from zhiju.api import youtube_oauth as youtube_oauth_api
from zhiju.auth_context import Principal


PRINCIPAL = Principal(
    user_id="user-a",
    tenant_id="tenant-a",
    membership_role="owner",
    platform_role=None,
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
        lambda: SimpleNamespace(
            deployment="cloud",
            device_role="worker",
            youtube_oauth_configured=True,
            youtube_oauth_client_id="client-id",
            youtube_oauth_client_secret="client-secret",
            youtube_oauth_redirect_uri="https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback",
            oauth_encryption_key="unused-in-route-test",
        ),
    )
    return app


def test_cloud_start_returns_web_authorization_url(monkeypatch) -> None:
    app = _app(monkeypatch)
    monkeypatch.setattr(youtube_oauth_api, "create_channel_import_state", lambda session, principal, **kwargs: "state-a")

    with TestClient(app) as client:
        response = client.post("/api/v3/youtube/channel-imports/start")

    assert response.status_code == 200, response.text
    assert response.json()["authorization_url"].startswith("https://accounts.google.com/")
    assert "state=state-a" in response.json()["authorization_url"]


def test_import_detail_returns_candidates_without_tokens(monkeypatch) -> None:
    app = _app(monkeypatch)
    monkeypatch.setattr(
        youtube_oauth_api,
        "get_channel_import",
        lambda session, principal, import_session_id: {
            "session": SimpleNamespace(
                id=import_session_id,
                status="ready",
                expires_at=datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
            ),
            "candidates": [SimpleNamespace(
                id="candidate-a",
                youtube_channel_id="UC-a",
                title="Channel A",
                description="Description",
                avatar_url="https://img.example/a.jpg",
                custom_url="@a",
                youtube_country_code="US",
                youtube_default_language="en",
                uploads_playlist_id="UU-a",
            )],
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/v3/youtube/channel-imports/import-a")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"][0]["youtube_channel_id"] == "UC-a"
    assert "access_token" not in json.dumps(body)
    assert "refresh_token" not in json.dumps(body)


def test_cloud_callback_completes_import_and_notifies_opener(monkeypatch) -> None:
    settings = SimpleNamespace(
        deployment="cloud",
        youtube_oauth_configured=True,
        youtube_oauth_client_id="client-id",
        youtube_oauth_client_secret="client-secret",
        youtube_oauth_redirect_uri="https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback",
        oauth_encryption_key="encryption-key",
    )
    context = SimpleNamespace(
        tenant_id="tenant-a",
        user_id="user-a",
        auth_session_id="auth-session-a",
    )
    outer_session = SimpleNamespace(
        scalar=lambda query: context,
        get_bind=lambda: object(),
        rollback=lambda: None,
    )
    tenant_session = SimpleNamespace()
    monkeypatch.setattr(youtube_oauth_api, "get_settings", lambda: settings)
    monkeypatch.setattr(
        youtube_oauth_api,
        "TenantSession",
        lambda **kwargs: nullcontext(tenant_session),
    )
    monkeypatch.setattr(youtube_oauth_api, "EncryptedDatabaseSecretStore", lambda session, key: object())
    monkeypatch.setattr(youtube_oauth_api, "exchange_authorization_code", lambda config, code: {"access_token": "token", "refresh_token": "refresh"})
    monkeypatch.setattr(youtube_oauth_api, "fetch_google_identity", lambda token: {"sub": "google-a", "email": "a@example.com"})
    monkeypatch.setattr(youtube_oauth_api, "fetch_youtube_channels", lambda token: {"items": [{"id": "UC-a"}]})
    monkeypatch.setattr(
        youtube_oauth_api,
        "complete_channel_import_oauth",
        lambda session, store, **kwargs: "import-a",
    )

    response = youtube_oauth_api.get_youtube_oauth_callback(
        state="state-a", code="code-a", session=outer_session,
    )

    assert response.status_code == 200
    assert "youtube-channel-import-ready" in response.body.decode()
    assert "import-a" in response.body.decode()
