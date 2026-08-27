import json
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from zhiju.models import Base
from zhiju.models.identity import AccountChannelAuthorization, Channel, OAuthGrant
from zhiju.services.youtube_oauth import (
    YOUTUBE_OAUTH_SCOPES,
    MacOSKeychainSecretStore,
    OAuthStateStore,
    build_authorization_url,
    choose_youtube_channel,
    complete_channel_authorization,
    import_oauth_client_file,
    oauth_client_status,
    parse_oauth_client_document,
    save_oauth_token,
    youtube_channel_identity,
)


def client_document() -> str:
    return json.dumps(
        {
            "web": {
                "client_id": "client-id.apps.googleusercontent.com",
                "project_id": "xiaoyu-youtube",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "secret-value",
                "redirect_uris": [
                    "http://127.0.0.1:8679/youtube/oauth/callback"
                ],
            }
        }
    )


def test_parse_legacy_web_oauth_client() -> None:
    config = parse_oauth_client_document(client_document())

    assert config.client_type == "web"
    assert config.project_id == "xiaoyu-youtube"
    assert config.redirect_uri == "http://127.0.0.1:8679/youtube/oauth/callback"
    assert config.client_secret_value == "secret-value"


def test_authorization_url_requests_offline_full_channel_access() -> None:
    config = parse_oauth_client_document(client_document())
    query = parse_qs(urlparse(build_authorization_url(config, "state-value")).query)

    assert query["state"] == ["state-value"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent select_account"]
    assert query["include_granted_scopes"] == ["true"]
    assert set(query["scope"][0].split(" ")) == set(YOUTUBE_OAUTH_SCOPES)
    assert query["redirect_uri"] == [config.redirect_uri]


def test_import_client_document_writes_to_keychain_without_changing_file(tmp_path) -> None:
    source = tmp_path / "client_secret.json"
    source.write_text(client_document(), encoding="utf-8")
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    config = import_oauth_client_file(source, MacOSKeychainSecretStore(runner))

    assert config.project_id == "xiaoyu-youtube"
    assert source.read_text(encoding="utf-8") == client_document()
    assert calls[0][0][:3] == ["/usr/bin/security", "add-generic-password", "-U"]
    assert client_document() in calls[0][0]


def test_missing_keychain_item_returns_none() -> None:
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 44, stdout="", stderr="not found")

    assert MacOSKeychainSecretStore(runner).get("service", "account") is None


def test_client_status_is_redacted_and_reports_legacy_source(tmp_path) -> None:
    source = tmp_path / "client_secret.json"
    source.write_text(client_document(), encoding="utf-8")

    class Store:
        def get(self, service, account):
            return client_document()

    status = oauth_client_status(source, Store(), can_manage=True)

    assert status["configured"] is True
    assert status["can_manage"] is True
    assert status["legacy_file_available"] is True
    assert status["project_id"] == "xiaoyu-youtube"
    assert status["credential_ref"].startswith("keychain://")
    assert "secret-value" not in json.dumps(status)


def test_oauth_state_is_single_use_and_expires() -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    states = OAuthStateStore(ttl_seconds=300, clock=lambda: now)
    state = states.create("channel-internal-id")

    assert states.consume(state).channel_id == "channel-internal-id"
    with pytest.raises(ValueError, match="无效或已经使用"):
        states.consume(state)

    expired = states.create("another-channel")
    states._clock = lambda: now + timedelta(seconds=301)
    with pytest.raises(ValueError, match="已过期"):
        states.consume(expired)


def test_youtube_channel_must_match_requested_channel() -> None:
    payload = {
        "items": [
            {"id": "UC-one", "snippet": {"title": "One"}},
            {"id": "UC-two", "snippet": {"title": "Two"}},
        ]
    }

    assert choose_youtube_channel(payload, "UC-two")["id"] == "UC-two"
    with pytest.raises(ValueError, match="不一致"):
        choose_youtube_channel(payload, "UC-missing")


def test_youtube_channel_identity_uses_title_and_highest_avatar() -> None:
    title, avatar_url = youtube_channel_identity(
        {
            "snippet": {
                "title": "Actual Channel",
                "thumbnails": {
                    "default": {"url": "https://img.example/default.jpg"},
                    "high": {"url": "https://img.example/high.jpg"},
                },
            }
        }
    )

    assert title == "Actual Channel"
    assert avatar_url == "https://img.example/high.jpg"


def test_oauth_token_is_saved_in_keychain_and_returns_reference() -> None:
    writes = []

    class Store:
        def put(self, service, account, value):
            writes.append((service, account, json.loads(value)))

    credential_ref = save_oauth_token(
        Store(),
        "grant-id",
        {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
    )

    assert credential_ref.endswith("/grant-id")
    assert writes[0][1] == "grant-id"
    assert writes[0][2]["refresh_token"] == "refresh"


def test_completed_authorization_binds_exact_channel_without_storing_tokens(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'oauth.db'}")
    Base.metadata.create_all(engine)
    writes = {}

    class Store:
        def get(self, service, account):
            return writes.get((service, account))

        def put(self, service, account, value):
            writes[(service, account)] = value

    with Session(engine) as session:
        channel = Channel(
            youtube_channel_id="UC-target",
            original_name="Target",
            timezone="Asia/Shanghai",
            daily_publish_count=1,
            status="new",
        )
        session.add(channel)
        session.commit()
        binding = complete_channel_authorization(
            session,
            Store(),
            channel_id=channel.id,
            identity={"sub": "google-sub", "email": "owner@example.com", "name": "Owner"},
            token={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
            youtube_payload={
                "items": [
                    {
                        "id": "UC-target",
                        "snippet": {
                            "title": "Actual Target",
                            "thumbnails": {"high": {"url": "https://img.example/avatar.jpg"}},
                        },
                    }
                ]
            },
        )

        grant = session.scalar(select(OAuthGrant))
        assert isinstance(binding, AccountChannelAuthorization)
        assert binding.verified_youtube_channel_id == "UC-target"
        assert grant.credential_ref.startswith("keychain://")
        assert "access" not in grant.credential_ref
        assert "refresh" not in grant.credential_ref
        session.refresh(channel)
        assert channel.original_name == "Actual Target"
        assert channel.youtube_avatar_url == "https://img.example/avatar.jpg"
