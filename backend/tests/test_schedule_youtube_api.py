from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from test_schedule_video_edit import _schedule_fixture
from zhiju.app import app
from zhiju.auth_context import get_tenant_db, get_current_principal, Principal
from zhiju.database import TenantSession
from zhiju.models import Base, Channel, Drama, GoogleAccount, OAuthGrant, AccountChannelAuthorization
from zhiju.services.oauth_secret_store import EncryptedDatabaseSecretStore


@pytest.fixture
def api_context(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as session:
        schedule = _schedule_fixture(session)
        schedule.source_video_id = schedule.source_video_url = None
        channel = session.get(Channel, schedule.channel_id)
        channel.default_language = "ar"
        title = session.get(Drama, schedule.drama_id).chinese_title
        account = GoogleAccount(nickname="Owner", google_email="owner@example.com", status="active", authorization_status="authorized")
        session.add(account)
        session.flush()
        grant = OAuthGrant(account_id=account.id, provider_subject="owner", credential_ref="encrypted-test", status="active", token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        session.add(grant)
        session.flush()
        session.add(AccountChannelAuthorization(account_id=account.id, channel_id=channel.id, oauth_grant_id=grant.id,
            status="active", verified_youtube_channel_id=channel.youtube_channel_id, verified_at=datetime.now(timezone.utc)))
        key = Fernet.generate_key().decode()
        EncryptedDatabaseSecretStore(session, key).put(grant.id, {"access_token": "test-access", "refresh_token": "test-refresh"})
        session.commit()
        principal = Principal(user_id="user-a", tenant_id="tenant-a", membership_role="owner", platform_role=None,
            device_id=None, device_trust_level="normal", permissions=frozenset({"channel.read", "channel.manage"}))
        monkeypatch.setitem(app.dependency_overrides, get_tenant_db, lambda: session)
        monkeypatch.setitem(app.dependency_overrides, get_current_principal, lambda: principal)
        monkeypatch.setattr("zhiju.api.youtube_oauth.get_settings", lambda: SimpleNamespace(deployment="cloud", device_role="worker", oauth_encryption_key=key))
        yield TestClient(app), session, schedule, title
    engine.dispose()


def test_cloud_sync_reads_owner_filename_and_exposes_matching_status_to_schedule_api(api_context, monkeypatch):
    client, session, schedule, title = api_context
    calls = []
    def google_get(url, token):
        assert token == "test-access"
        calls.append(url)
        path, query = urlparse(url).path, parse_qs(urlparse(url).query)
        if path.endswith("/channels"):
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU-owner"}}}]}
        if path.endswith("/playlistItems"):
            return {"items": [{"snippet": {"publishedAt": "2026-10-15T12:00:00Z"}, "contentDetails": {"videoId": "arabic-one1"}}]}
        assert "fileDetails" in query["part"][0]
        return {"items": [{"id": "arabic-one1", "snippet": {"title": "阿拉伯语运营标题", "publishedAt": "2026-10-15T12:00:00Z"},
            "status": {"privacyStatus": "unlisted", "uploadStatus": "processed"}, "fileDetails": {"fileName": f"{title}_阿拉伯语.mp4"}, "contentDetails": {"duration": "PT1H"}}]}
    monkeypatch.setattr("zhiju.services.youtube_channel_sync._youtube_request_json", google_get)
    response = client.post(f"/api/v3/channels/{schedule.channel_id}/youtube-videos/sync")
    assert response.status_code == 200, response.text
    assert response.json()["fetched"] == 1
    page = client.get("/api/v3/schedules/channel-view", params={"channel_id": schedule.channel_id}).json()
    row = page["items"][0]
    assert row["source_video_id"] == "arabic-one1"
    assert row["is_uploaded"] is True and row["is_published"] is False
    assert row["video_sync"]["selected"]["state"] == "unlisted"
    assert row["video_sync"]["selected"]["file_name"] == f"{title}_阿拉伯语.mp4"
    assert len(calls) == 3
    response = client.post(f"/api/v3/schedules/{schedule.id}/youtube-selection", json={"video_id": "arabic-one1"})
    assert response.status_code == 200
    assert session.get(type(schedule), schedule.id).source_video_overridden is True


def test_foreign_channel_and_schedule_are_rejected_before_any_google_request(api_context, monkeypatch):
    client, _, _, _ = api_context
    def unexpected(*args):
        raise AssertionError("Foreign tenant must not cause external requests")
    monkeypatch.setattr("zhiju.services.youtube_channel_sync._youtube_request_json", unexpected)
    assert client.post("/api/v3/channels/foreign/youtube-videos/sync").status_code == 404
    assert client.get("/api/v3/schedules/foreign/youtube-review").status_code == 404
    assert client.post("/api/v3/schedules/foreign/youtube-selection", json={"video_id": "arabic-one1"}).status_code == 404


def test_sync_api_recomputes_red_yellow_and_cleared_warnings(api_context, monkeypatch):
    client, session, schedule, title = api_context
    schedule.planned_utc_time = datetime.now(timezone.utc) + timedelta(days=10)
    session.commit()
    restriction = {"blocked": ["US", "SA"]}
    ids = ["firstvideo1", "duplicate01"]
    failed = False

    def google_get(url, token):
        if failed:
            raise ValueError("无法连接YouTube API")
        path = urlparse(url).path
        if path.endswith("/channels"):
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU-owner"}}}]}
        if path.endswith("/playlistItems"):
            return {"items": [{"snippet": {"publishedAt": f"2026-10-15T0{i}:00:00Z"}, "contentDetails": {"videoId": v}} for i, v in enumerate(ids)]}
        return {"items": [{"id": v, "snippet": {"title": title},
            "status": {"privacyStatus": "private", "uploadStatus": "processed"},
            "fileDetails": {"fileName": f"{title}_阿拉伯语.mp4"},
            "contentDetails": {"duration": "PT1H", **({"regionRestriction": restriction} if v == "duplicate01" and restriction else {})}}
            for v in ids]}

    monkeypatch.setattr("zhiju.services.youtube_channel_sync._youtube_request_json", google_get)

    def sync():
        response = client.post(f"/api/v3/channels/{schedule.channel_id}/youtube-videos/sync")
        assert response.status_code == 200, response.text
        return client.get(f"/api/v3/schedules/{schedule.id}/youtube-review").json()

    blocked = sync()
    assert blocked["warning_level"] == "error"
    assert next(v for v in blocked["videos"] if v["video_id"] == "duplicate01")["selectable"] is False
    failed = True
    assert client.post(f"/api/v3/channels/{schedule.channel_id}/youtube-videos/sync").status_code == 409
    uncertain = client.get(f"/api/v3/schedules/{schedule.id}/youtube-review").json()
    assert uncertain["sync_complete"] is False
    assert "youtube_blocked" in [w["code"] for w in uncertain["warnings"]]
    failed = False
    restriction = None
    assert sync()["warning_level"] == "warning"
    ids = ["firstvideo1"]
    cleared = sync()
    assert cleared["warnings"] == []
    assert cleared["warning_level"] is None
    assert [v["video_id"] for v in cleared["videos"]] == ["firstvideo1"]


def test_incomplete_channel_read_keeps_existing_id_and_returns_failed_sync(api_context, monkeypatch):
    client, session, schedule, _ = api_context
    schedule.source_video_id = "keep-this01"
    session.commit()
    def google_get(url, token):
        path = urlparse(url).path
        if path.endswith("/channels"):
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU-owner"}}}]}
        if path.endswith("/playlistItems"):
            return {"items": [{"contentDetails": {"videoId": "unreadable1"}}]}
        return {"items": []}
    monkeypatch.setattr("zhiju.services.youtube_channel_sync._youtube_request_json", google_get)
    response = client.post(f"/api/v3/channels/{schedule.channel_id}/youtube-videos/sync")
    assert response.status_code == 409
    assert "不完整" in response.json()["detail"]
    review = client.get(f"/api/v3/schedules/{schedule.id}/youtube-review").json()
    assert review["sync_complete"] is False
    assert schedule.source_video_id == "keep-this01"


def test_cloud_expired_token_refresh_uses_cloud_config_and_preserves_refresh_token(api_context, monkeypatch):
    _, session, _, _ = api_context
    from sqlalchemy import select
    from zhiju.models import OAuthTokenSecret
    from zhiju.services.youtube_channel_sync import ensure_grant_access_token
    grant = session.scalar(select(OAuthGrant))
    grant.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    settings = __import__("zhiju.api.youtube_oauth", fromlist=["get_settings"]).get_settings()
    store = EncryptedDatabaseSecretStore(session, settings.oauth_encryption_key)
    sentinel = object()
    monkeypatch.setattr("zhiju.services.youtube_channel_sync.cloud_oauth_client_config", lambda _: sentinel)
    calls = []
    def refresh(config, token):
        assert config is sentinel
        calls.append(token)
        return {"access_token": "new-access", "expires_in": 3600}
    monkeypatch.setattr("zhiju.services.youtube_channel_sync.refresh_oauth_access_token", refresh)
    assert ensure_grant_access_token(session, store, grant) == "new-access"
    assert calls == ["test-refresh"]
    assert store.get(grant.id)["refresh_token"] == "test-refresh"
    assert "new-access" not in session.scalar(select(OAuthTokenSecret)).encrypted_payload
