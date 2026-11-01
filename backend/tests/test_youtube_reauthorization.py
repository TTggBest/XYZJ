import io
import json
from urllib.error import HTTPError

import pytest
from dataclasses import replace
from types import SimpleNamespace
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from test_oauth_tenant_state import state_store, PRINCIPAL
from zhiju.app import app
from zhiju.auth_context import get_current_principal, get_tenant_db
from zhiju.database import TenantSession, get_db
from zhiju.models import Channel, OAuthGrant, AccountChannelAuthorization
from zhiju.services.oauth_secret_store import EncryptedDatabaseSecretStore

from test_youtube_oauth_service import client_document
from zhiju.services.youtube_oauth import parse_oauth_client_document, refresh_oauth_access_token
from zhiju.services.youtube_channel_sync import fetch_channel_upload_videos


@pytest.mark.parametrize("code,reauthorize", [("invalid_grant", True), ("invalid_client", False)])
def test_refresh_failure_only_requests_reauthorization_for_invalid_grant(monkeypatch, code, reauthorize):
    from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired

    def reject(*args, **kwargs):
        raise HTTPError("https://oauth2.googleapis.com/token", 400, "Bad Request", {},
                        io.BytesIO(json.dumps({"error": code}).encode()))

    monkeypatch.setattr("zhiju.services.youtube_oauth.open_google_url", reject)
    expected = YouTubeAuthorizationRequired if reauthorize else ValueError
    with pytest.raises(expected):
        refresh_oauth_access_token(parse_oauth_client_document(client_document()), "test-refresh")


@pytest.mark.parametrize("status,reason,reauthorize", [
    (401, "authError", True), (403, "insufficientPermissions", True),
    (403, "quotaExceeded", False), (503, "backendError", False),
])
def test_channel_operation_distinguishes_authorization_from_quota_and_network(monkeypatch, status, reason, reauthorize):
    from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired

    def reject(*args, **kwargs):
        raise HTTPError("https://www.googleapis.com/youtube/v3/channels", status, "Error", {},
                        io.BytesIO(json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()))

    monkeypatch.setattr("zhiju.services.youtube_channel_sync.open_google_url", reject)
    with pytest.raises(YouTubeAuthorizationRequired if reauthorize else ValueError):
        fetch_channel_upload_videos("test-access", "UC-A")


def test_cloud_channel_reauthorization_reuses_channel_and_updates_token(state_store, monkeypatch):
    import zhiju.api.youtube_oauth as api
    settings = SimpleNamespace(deployment="cloud", device_role="worker", oauth_encryption_key=Fernet.generate_key().decode())
    config = parse_oauth_client_document(client_document())
    principal = replace(PRINCIPAL, permissions=frozenset({"channel.manage"}))
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(api, "cloud_oauth_client_config", lambda _: config)
    monkeypatch.setattr(api, "exchange_authorization_code", lambda *_: {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})
    monkeypatch.setattr(api, "fetch_google_identity", lambda _: {"sub": "owner", "email": "owner@example.com"})
    monkeypatch.setattr(api, "fetch_youtube_channels", lambda _: {"items": [{"id": "UC-A", "snippet": {"title": "A"}}]})

    def tenant_db():
        with TenantSession(state_store, info={"tenant_id": "tenant-a"}) as session:
            yield session

    def callback_db():
        with Session(state_store) as session:
            yield session

    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_tenant_db] = tenant_db
    app.dependency_overrides[get_db] = callback_db
    try:
        client = TestClient(app)
        for index in range(2):
            if index:
                with TenantSession(state_store, info={"tenant_id":"tenant-a"}) as session:
                    session.scalar(select(OAuthGrant)).status = "expired"
                    session.commit()
            monkeypatch.setattr(api, "exchange_authorization_code", lambda *_: {
                "access_token": "new-access", "refresh_token": f"refresh-{index}", "expires_in": 3600})
            started = client.post("/api/v3/channels/channel-a/youtube-authorization/start")
            assert started.status_code == 200, started.text
            from urllib.parse import parse_qs, urlparse
            state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
            result = client.get("/api/v3/youtube/oauth/callback", params={"state": state, "code": "test-code"})
            assert result.status_code == 200, result.text
            assert '"type": "youtube-auth-complete"' in result.text
            assert '"channel_id": "channel-a"' in result.text
        with TenantSession(state_store, info={"tenant_id": "tenant-a"}) as session:
            assert session.scalar(select(func.count()).select_from(Channel)) == 1
            assert session.get(Channel, "channel-a").youtube_channel_id == "UC-A"
            assert session.scalar(select(func.count()).select_from(AccountChannelAuthorization)) == 1
            grant = session.scalar(select(OAuthGrant))
            assert EncryptedDatabaseSecretStore(session, settings.oauth_encryption_key).get(grant.id)["refresh_token"] == "refresh-1"
            assert grant.status == "active"
            from zhiju.services.identity import list_channel_overview
            assert list_channel_overview(session)[0]['youtube_authorization_status'] == 'authorized'
        # A different company cannot start authorization for this channel.
        assert client.post("/api/v3/channels/channel-b/youtube-authorization/start").status_code == 404
        # Picking an account that does not own the target channel must not replace its grant.
        monkeypatch.setattr(api, "fetch_youtube_channels", lambda _: {"items": [{"id": "UC-WRONG", "snippet": {"title": "Wrong"}}]})
        started = client.post("/api/v3/channels/channel-a/youtube-authorization/start")
        state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
        result = client.get("/api/v3/youtube/oauth/callback", params={"state": state, "code": "wrong-account"})
        assert result.status_code == 400
        with TenantSession(state_store, info={"tenant_id": "tenant-a"}) as session:
            assert session.scalar(select(func.count()).select_from(AccountChannelAuthorization)) == 1
            assert session.scalar(select(func.count()).select_from(OAuthGrant)) == 1
            assert session.get(Channel, "channel-a").youtube_channel_id == "UC-A"
        app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
        assert client.post("/api/v3/channels/channel-a/youtube-authorization/start").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_sync_authorization_error_identifies_channel_without_logging_out(monkeypatch):
    import zhiju.api.youtube_oauth as api
    from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(
        deployment="cloud", oauth_encryption_key=Fernet.generate_key().decode()))

    def expired(*args, **kwargs):
        raise YouTubeAuthorizationRequired("YouTube授权已失效，请重新授权该频道")

    monkeypatch.setattr(api, "sync_authorized_channel_videos", expired)
    app.dependency_overrides[get_tenant_db] = lambda: object()
    try:
        result = TestClient(app, raise_server_exceptions=False).post("/api/v3/channels/channel-a/youtube-videos/sync")
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "youtube_reauthorization_required"
        assert result.json()["detail"]["channel_id"] == "channel-a"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('authorization_failure',[True,False])
def test_known_refresh_rejection_persists_state_and_channel_overview(state_store,authorization_failure):
    from datetime import datetime,timedelta,timezone
    from zhiju.models import GoogleAccount
    from zhiju.services.identity import list_channel_overview
    from zhiju.services.youtube_channel_sync import ensure_grant_access_token
    from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired
    now=datetime.now(timezone.utc)
    with TenantSession(state_store,info={'tenant_id':'tenant-a'}) as session:
        session.add(GoogleAccount(id='account-a',nickname='owner',google_email='owner@example.com',status='active',authorization_status='authorized'))
        session.add(OAuthGrant(id='grant-a',account_id='account-a',provider_subject='owner',credential_ref='test',status='active',token_expires_at=now-timedelta(minutes=5)))
        session.add(AccountChannelAuthorization(account_id='account-a',channel_id='channel-a',oauth_grant_id='grant-a',status='active',verified_youtube_channel_id='UC-A',verified_at=now))
        # The consumer uses the most recently verified binding, not an older working grant.
        session.add(GoogleAccount(id='account-old',nickname='old',google_email='old@example.com',status='active',authorization_status='authorized'))
        session.add(OAuthGrant(id='grant-old',account_id='account-old',provider_subject='old',credential_ref='test',status='active'))
        session.add(AccountChannelAuthorization(account_id='account-old',channel_id='channel-a',oauth_grant_id='grant-old',status='active',verified_youtube_channel_id='UC-A',verified_at=now-timedelta(hours=1)))
        session.commit()
        assert list_channel_overview(session)[0]['youtube_authorization_status']=='authorized'
        class Store:
            def get(self,*args):return json.dumps({'access_token':'old','refresh_token':'old-refresh'})
        def reject(_):
            if authorization_failure:raise YouTubeAuthorizationRequired('YouTube授权已失效，请重新授权该频道')
            raise ValueError('无法连接 Google')
        with pytest.raises(YouTubeAuthorizationRequired if authorization_failure else ValueError):
            ensure_grant_access_token(session,Store(),session.get(OAuthGrant,'grant-a'),refresher=reject)
    with TenantSession(state_store,info={'tenant_id':'tenant-a'}) as session:
        assert session.get(OAuthGrant,'grant-a').status==('expired' if authorization_failure else 'active')
        assert list_channel_overview(session)[0]['youtube_authorization_status']==('reauthorization_required' if authorization_failure else 'authorized')
