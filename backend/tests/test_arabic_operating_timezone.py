from datetime import timedelta

import pytest
from sqlalchemy import create_engine

from test_youtube_channel_import_service import NOW, PRINCIPAL
from zhiju.database import TenantSession
from zhiju.models import Base, GoogleAccount, OAuthGrant, YouTubeChannelImportSession, YouTubeChannelImportCandidate
from zhiju.schemas.identity import ChannelCreate
from zhiju.services.identity import create_channel
from zhiju.services.youtube_channel_import import ChannelImportSelection, commit_channel_import


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as value:
        yield value
    engine.dispose()


@pytest.mark.parametrize("language,zone,expected", (
    ("ar", "Asia/Dubai", "Asia/Riyadh"),
    ("ar", "Asia/Shanghai", "Asia/Riyadh"),
    ("en", "America/New_York", "America/New_York"),
))
def test_new_channel_uses_saudi_time_only_for_arabic(session, language, zone, expected):
    channel = create_channel(session, ChannelCreate(
        youtube_channel_id="UC-timezone", original_name="测试频道",
        default_language=language, timezone=zone,
    ))
    assert channel.timezone == expected


def test_youtube_arabic_import_uses_saudi_time_even_with_uae_selection(session):
    session.add_all([
        GoogleAccount(id="account-a", nickname="Owner", google_email="owner@example.com", status="active", authorization_status="authorized"),
        OAuthGrant(id="grant-a", account_id="account-a", provider_subject="subject", credential_ref="db-encrypted://test", status="active"),
        YouTubeChannelImportSession(id="import-a", user_id="user-a", auth_session_id="auth-session-a", oauth_grant_id="grant-a", opaque_state="state", status="ready", expires_at=NOW + timedelta(minutes=10)),
        YouTubeChannelImportCandidate(id="candidate-a", import_session_id="import-a", youtube_channel_id="UC-arabic", title="Arabic"),
    ])
    session.commit()
    channels = commit_channel_import(session, PRINCIPAL, "import-a", [ChannelImportSelection(
        candidate_id="candidate-a", target_country_code="AE", default_genre="爱情",
        default_language="ar", timezone="Asia/Dubai", operational_name=None,
    )], now=NOW)
    assert channels[0].timezone == "Asia/Riyadh"
