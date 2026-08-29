from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import (
    AccountChannelAuthorization,
    Channel,
    ChannelPlaylist,
    GoogleAccount,
    OAuthGrant,
)
def test_authorized_channel_creates_youtube_playlist_and_backfills_link() -> None:
    from zhiju.services.youtube_channel_sync import create_authorized_channel_playlist

    suffix = uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    class Store:
        def get(self, service: str, account: str) -> str | None:
            if account == grant.id:
                return '{"access_token":"playlist-access","refresh_token":"playlist-refresh"}'
            return None

        def put(self, service: str, account: str, value: str) -> None:
            raise AssertionError("未过期令牌不应刷新")

    try:
        channel = Channel(
            youtube_channel_id=f"UC-PLAYLIST-{suffix}",
            original_name=f"Playlist channel {suffix}",
            timezone="Asia/Shanghai",
            status="authorized",
        )
        account = GoogleAccount(
            nickname=f"Owner {suffix}",
            google_email=f"playlist-{suffix}@example.com",
            status="active",
            authorization_status="authorized",
        )
        session.add_all([channel, account])
        session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            provider_subject=f"playlist-subject-{suffix}",
            credential_ref=f"keychain://test/{suffix}",
            status="active",
            token_expires_at=now + timedelta(hours=1),
        )
        session.add(grant)
        session.flush()
        session.add(
            AccountChannelAuthorization(
                account_id=account.id,
                channel_id=channel.id,
                oauth_grant_id=grant.id,
                status="active",
                verified_youtube_channel_id=channel.youtube_channel_id,
                verified_at=now,
            )
        )
        playlist = ChannelPlaylist(
            channel_id=channel.id,
            local_name="Revenge Stories",
            local_description="Fast-paced revenge dramas",
            sort_order=1,
            status="draft",
        )
        session.add(playlist)
        session.commit()

        calls: list[tuple[str, str, str]] = []

        def creator(access_token: str, title: str, description: str) -> dict[str, object]:
            calls.append((access_token, title, description))
            return {"id": f"PL-{suffix}"}

        created = create_authorized_channel_playlist(
            session,
            Store(),
            channel_id=channel.id,
            playlist_id=playlist.id,
            creator=creator,
            now=now,
        )

        assert calls == [("playlist-access", "Revenge Stories", "Fast-paced revenge dramas")]
        assert created.youtube_playlist_id == f"PL-{suffix}"
        assert created.url == f"https://www.youtube.com/playlist?list=PL-{suffix}"
        assert created.status == "active"
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_youtube_playlist_creation_route_is_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "post" in paths[
        "/api/v3/channels/{channel_id}/playlists/{playlist_id}/create-youtube"
    ]
