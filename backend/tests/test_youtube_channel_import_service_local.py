from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal
from zhiju.models import (
    AccountChannelAuthorization,
    Base,
    Channel,
    GoogleAccount,
    OAuthGrant,
    YouTubeChannelImportCandidate,
    YouTubeChannelImportSession,
)
from zhiju.services.identity import ConflictError
from zhiju.services.youtube_channel_import import (
    ChannelImportSelection,
    commit_channel_import,
    complete_channel_import_oauth,
    create_channel_import_state,
)


class MemoryTokenStore:
    def __init__(self) -> None:
        self.tokens: dict[str, dict[str, object]] = {}

    def put(self, grant_id: str, token: dict[str, object]) -> str:
        self.tokens[grant_id] = dict(token)
        return f"keychain://google-oauth/{grant_id}"

    def get(self, grant_id: str) -> dict[str, object] | None:
        token = self.tokens.get(grant_id)
        return dict(token) if token else None

NOW = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
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


def _session() -> tuple[object, Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, Session(engine, info={"tenant_id": "tenant-a", "user_id": "user-a"})


def _selection(candidate_id: str, country: str = "US") -> ChannelImportSelection:
    return ChannelImportSelection(
        candidate_id=candidate_id,
        operational_name=None,
        target_country_code=country,
        default_genre="爱情",
        default_language=None,
        timezone=None,
    )


def test_create_import_state_does_not_create_placeholder_channel() -> None:
    engine, session = _session()
    try:
        state = create_channel_import_state(session, PRINCIPAL, now=NOW)

        row = session.scalar(select(YouTubeChannelImportSession))
        assert row is not None
        assert row.opaque_state == state
        assert row.tenant_id == "tenant-a"
        assert session.scalar(select(func.count(Channel.id))) == 0
    finally:
        session.close()
        engine.dispose()


def test_complete_oauth_keeps_all_discovered_channels_and_stores_token_by_reference() -> None:
    engine, session = _session()
    try:
        state = create_channel_import_state(session, PRINCIPAL, now=NOW)
        store = MemoryTokenStore()

        import_id = complete_channel_import_oauth(
            session,
            store,
            opaque_state=state,
            identity={"sub": "google-sub", "email": "owner@example.com", "name": "Owner"},
            token={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
            youtube_payload={"items": [
                {"id": "UC-one", "snippet": {"title": "One"}},
                {"id": "UC-two", "snippet": {"title": "Two"}},
            ]},
            now=NOW,
        )

        imported = session.get(YouTubeChannelImportSession, import_id)
        candidates = list(session.scalars(select(YouTubeChannelImportCandidate)))
        grant = session.scalar(select(OAuthGrant))
        assert imported is not None and imported.status == "ready"
        assert [candidate.youtube_channel_id for candidate in candidates] == ["UC-one", "UC-two"]
        assert grant is not None and grant.credential_ref.startswith("keychain://")
        assert "access" not in grant.credential_ref
    finally:
        session.close()
        engine.dispose()


def test_reauthorization_reuses_existing_refresh_token_when_google_omits_it() -> None:
    engine, session = _session()
    try:
        store = MemoryTokenStore()
        first_state = create_channel_import_state(session, PRINCIPAL, now=NOW)
        complete_channel_import_oauth(
            session,
            store,
            opaque_state=first_state,
            identity={"sub": "google-sub", "email": "owner@example.com"},
            token={"access_token": "first", "refresh_token": "saved-refresh"},
            youtube_payload={"items": [{"id": "UC-one", "snippet": {"title": "One"}}]},
            now=NOW,
        )
        second_state = create_channel_import_state(
            session, PRINCIPAL, now=NOW + timedelta(minutes=1),
        )

        complete_channel_import_oauth(
            session,
            store,
            opaque_state=second_state,
            identity={"sub": "google-sub", "email": "owner@example.com"},
            token={"access_token": "second"},
            youtube_payload={"items": [{"id": "UC-one", "snippet": {"title": "One"}}]},
            now=NOW + timedelta(minutes=1),
        )

        grant = session.scalar(select(OAuthGrant))
        assert grant is not None
        assert store.get(grant.id)["refresh_token"] == "saved-refresh"
        assert store.get(grant.id)["access_token"] == "second"
    finally:
        session.close()
        engine.dispose()


def test_multi_select_import_is_atomic_when_one_channel_already_exists() -> None:
    engine, session = _session()
    try:
        account = GoogleAccount(
            id="account-a", tenant_id="tenant-a", nickname="Owner",
            google_email="owner@example.com", status="active", authorization_status="authorized",
        )
        grant = OAuthGrant(
            id="grant-a", tenant_id="tenant-a", account_id=account.id,
            provider_subject="google-sub", credential_ref="db-encrypted://google-oauth/grant-a",
            status="active",
        )
        import_session = YouTubeChannelImportSession(
            id="import-a", tenant_id="tenant-a", user_id="user-a",
            auth_session_id="auth-session-a", oauth_grant_id=grant.id,
            opaque_state="state-a", status="ready", expires_at=NOW + timedelta(minutes=10),
        )
        candidates = [
            YouTubeChannelImportCandidate(
                id="candidate-one", tenant_id="tenant-a", import_session_id=import_session.id,
                youtube_channel_id="UC-one", title="Actual One",
            ),
            YouTubeChannelImportCandidate(
                id="candidate-two", tenant_id="tenant-a", import_session_id=import_session.id,
                youtube_channel_id="UC-two", title="Actual Two",
            ),
        ]
        session.add_all([account, grant, import_session, *candidates, Channel(
            tenant_id="tenant-existing", youtube_channel_id="UC-two", original_name="Existing",
            timezone="Asia/Shanghai", status="authorized",
        )])
        session.commit()

        with pytest.raises(ConflictError, match="频道已被绑定"):
            commit_channel_import(
                session, PRINCIPAL, import_session.id,
                [_selection("candidate-one"), _selection("candidate-two", "BR")], now=NOW,
            )

        assert session.scalar(select(func.count(Channel.id))) == 1
        assert session.scalar(select(func.count(AccountChannelAuthorization.id))) == 0
    finally:
        session.close()
        engine.dispose()


def test_import_uses_catalog_country_and_youtube_identity() -> None:
    engine, session = _session()
    try:
        account = GoogleAccount(
            id="account-a", tenant_id="tenant-a", nickname="Owner",
            google_email="owner@example.com", status="active", authorization_status="authorized",
        )
        grant = OAuthGrant(
            id="grant-a", tenant_id="tenant-a", account_id=account.id,
            provider_subject="google-sub", credential_ref="db-encrypted://google-oauth/grant-a",
            status="active",
        )
        import_session = YouTubeChannelImportSession(
            id="import-a", tenant_id="tenant-a", user_id="user-a",
            auth_session_id="auth-session-a", oauth_grant_id=grant.id,
            opaque_state="state-a", status="ready", expires_at=NOW + timedelta(minutes=10),
        )
        candidate = YouTubeChannelImportCandidate(
            id="candidate-one", tenant_id="tenant-a", import_session_id=import_session.id,
            youtube_channel_id="UC-one", title="Actual One",
            avatar_url="https://img.example/one.jpg", custom_url="@one",
            youtube_default_language="en",
        )
        session.add_all([account, grant, import_session, candidate])
        session.commit()

        channels = commit_channel_import(
            session, PRINCIPAL, import_session.id, [_selection(candidate.id)], now=NOW,
        )

        assert len(channels) == 1
        assert channels[0].original_name == "Actual One"
        assert channels[0].country_code == "US"
        assert channels[0].country_name_zh == "美国"
        assert channels[0].default_language == "en"
        assert channels[0].timezone == "America/New_York"
        assert channels[0].status == "authorized"
        assert session.scalar(select(func.count(AccountChannelAuthorization.id))) == 1
        assert session.get(YouTubeChannelImportSession, import_session.id).status == "committed"
    finally:
        session.close()
        engine.dispose()
