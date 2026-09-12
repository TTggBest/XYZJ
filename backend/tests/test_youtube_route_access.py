from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju import auth_context, database
from zhiju.api import history as history_api
from zhiju.api import youtube_oauth as youtube_oauth_api
from zhiju.auth_context import Principal
from zhiju.models import Base, Channel, YoutubeVideo, YoutubeVideoStatusHistory


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
TENANT_PRINCIPAL = Principal(
    user_id="user-a",
    tenant_id="tenant-a",
    membership_role="owner",
    platform_role=None,
    device_id="builder-device",
    device_trust_level="normal",
    permissions=frozenset(),
)
PLATFORM_PRINCIPAL = Principal(
    user_id="platform-admin",
    tenant_id=None,
    membership_role=None,
    platform_role="super_admin",
    device_id="builder-device",
    device_trust_level="normal",
    permissions=frozenset({"platform.tenant.manage"}),
)


@pytest.fixture
def youtube_route_app(monkeypatch):
    engine = sa.create_engine(
        "sqlite://",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for key in ("a", "b"):
            session.add(Channel(
                id=f"channel-{key}",
                tenant_id=f"tenant-{key}",
                youtube_channel_id=f"UC-{key}",
                original_name=f"Channel {key}",
                status="active",
            ))
            session.add(YoutubeVideo(
                id=f"video-{key}",
                tenant_id=f"tenant-{key}",
                youtube_video_id=f"remote-video-{key}",
                channel_id=f"channel-{key}",
                title=f"Video {key}",
                url=f"https://youtu.be/remote-video-{key}",
                privacy_status="public",
                publish_status="published",
                source="youtube_sync",
            ))
            session.add(YoutubeVideoStatusHistory(
                id=f"history-{key}",
                tenant_id=f"tenant-{key}",
                video_id=f"video-{key}",
                old_publish_status="scheduled",
                new_publish_status="published",
                old_privacy_status="private",
                new_privacy_status="public",
                reason=f"tenant-{key}-reason",
                source="youtube_sync",
                changed_at=NOW,
            ))
        session.commit()

    def unscoped_db():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(history_api.router, prefix="/api")
    app.dependency_overrides[database.get_db] = unscoped_db
    monkeypatch.setattr(database.database_router, "get_active_engine", lambda: engine)
    yield app
    engine.dispose()


def test_video_status_history_requires_authentication(youtube_route_app):
    with TestClient(youtube_route_app) as client:
        response = client.get("/api/v3/youtube/videos/video-a/status-history")

    assert response.status_code == 401


def test_video_status_history_hides_foreign_video(youtube_route_app):
    youtube_route_app.dependency_overrides[auth_context.get_current_principal] = (
        lambda: TENANT_PRINCIPAL
    )
    with TestClient(youtube_route_app) as client:
        response = client.get("/api/v3/youtube/videos/video-b/status-history")

    assert response.status_code == 404


def test_video_status_history_returns_owned_history(youtube_route_app):
    youtube_route_app.dependency_overrides[auth_context.get_current_principal] = (
        lambda: TENANT_PRINCIPAL
    )
    with TestClient(youtube_route_app) as client:
        response = client.get("/api/v3/youtube/videos/video-a/status-history")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["history-a"]


@pytest.fixture
def oauth_settings_app(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(youtube_oauth_api.router, prefix="/api")
    monkeypatch.setattr(
        youtube_oauth_api,
        "get_settings",
        lambda: SimpleNamespace(device_role="builder"),
    )
    legacy_path = tmp_path / "client_secret.json"
    legacy_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(youtube_oauth_api, "_legacy_client_path", lambda: legacy_path)
    monkeypatch.setattr(youtube_oauth_api, "import_oauth_client_file", lambda path, store: None)
    monkeypatch.setattr(
        youtube_oauth_api,
        "oauth_client_status",
        lambda path, store, *, can_manage: {
            "configured": True,
            "can_manage": can_manage,
            "client_type": "web",
            "project_id": "fixture-project",
            "redirect_uri": "http://127.0.0.1/callback",
            "credential_ref": "keychain://fixture/oauth-client",
            "scopes": [],
            "legacy_file_available": Path(path).is_file(),
        },
    )
    return app


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v3/settings/youtube-oauth"),
    ("POST", "/api/v3/settings/youtube-oauth/import-legacy"),
])
def test_oauth_platform_settings_reject_ordinary_tenant_user(
    oauth_settings_app, method, path,
):
    oauth_settings_app.dependency_overrides[auth_context.get_current_principal] = (
        lambda: TENANT_PRINCIPAL
    )
    with TestClient(oauth_settings_app) as client:
        response = client.request(method, path)

    assert response.status_code == 403


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v3/settings/youtube-oauth"),
    ("POST", "/api/v3/settings/youtube-oauth/import-legacy"),
])
def test_oauth_platform_settings_allow_platform_admin(
    oauth_settings_app, method, path,
):
    oauth_settings_app.dependency_overrides[auth_context.get_current_principal] = (
        lambda: PLATFORM_PRINCIPAL
    )
    with TestClient(oauth_settings_app) as client:
        response = client.request(method, path)

    assert response.status_code == 200, response.text
    assert response.json()["can_manage"] is True
