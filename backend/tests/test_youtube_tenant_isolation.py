from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from zhiju.database import TenantSession
from zhiju.models import (
    AccountChannelAuthorization, Base, Channel, ChannelPlaylist, GoogleAccount,
    OAuthGrant, YoutubeComment, YoutubeVideo,
)
from zhiju.schemas.youtube import CommentUpsert
from zhiju.services.channel import NotFoundError
from zhiju.services.youtube import list_comments, list_videos, upsert_comment
from zhiju.services.youtube_channel_sync import (
    create_authorized_channel_playlist, sync_authorized_channel_videos,
)


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def youtube_store():
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        channel_b = Channel(
            id="channel-b", tenant_id="tenant-b", youtube_channel_id="UC-B",
            original_name="B", status="authorized",
        )
        account_b = GoogleAccount(
            id="account-b", tenant_id="tenant-b", nickname="B",
            google_email="b@example.com", status="active", authorization_status="authorized",
        )
        video_b = YoutubeVideo(
            id="video-b", tenant_id="tenant-b", youtube_video_id="remote-video-b",
            channel_id="channel-b", title="B video", url="https://youtu.be/remote-video-b",
            privacy_status="public", publish_status="published", source="youtube_sync",
            published_at=NOW, last_synced_at=NOW,
        )
        playlist_b = ChannelPlaylist(
            id="playlist-b", tenant_id="tenant-b", channel_id="channel-b",
            local_name="B playlist", status="draft",
        )
        session.add_all([channel_b, account_b, video_b, playlist_b])
        session.flush()
        grant_b = OAuthGrant(
            id="grant-b", tenant_id="tenant-b", account_id="account-b",
            provider_subject="subject-b", credential_ref="secret-b", status="active",
        )
        session.add(grant_b)
        session.flush()
        session.add_all([
            AccountChannelAuthorization(
                id="authorization-b", tenant_id="tenant-b", account_id="account-b",
                channel_id="channel-b", oauth_grant_id="grant-b", status="active",
                verified_youtube_channel_id="UC-B", verified_at=NOW,
            ),
            YoutubeComment(
                id="comment-b", tenant_id="tenant-b", youtube_comment_id="remote-comment-b",
                video_id="video-b", channel_id="channel-b", author_display_name="viewer",
                original_text="B comment", published_at=NOW, last_synced_at=NOW,
            ),
        ])
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def tenant_a(youtube_store):
    with TenantSession(
        youtube_store,
        info={"tenant_id": "tenant-a", "user_id": "user-a", "permissions": frozenset()},
    ) as session:
        yield session


def test_tenant_session_hides_foreign_youtube_video_comment_and_grant(tenant_a):
    assert list_videos(tenant_a) == []
    assert list_comments(tenant_a) == []
    assert tenant_a.get(YoutubeVideo, "video-b") is None
    assert tenant_a.get(OAuthGrant, "grant-b") is None
    assert tenant_a.get(AccountChannelAuthorization, "authorization-b") is None


def test_tenant_cannot_sync_or_create_playlist_for_foreign_channel(tenant_a):
    external_calls = []
    with pytest.raises(NotFoundError):
        sync_authorized_channel_videos(
            tenant_a, object(), channel_id="channel-b",
            fetcher=lambda *_: external_calls.append("sync") or [], now=NOW,
        )
    with pytest.raises(NotFoundError):
        create_authorized_channel_playlist(
            tenant_a, object(), channel_id="channel-b", playlist_id="playlist-b",
            creator=lambda *_: external_calls.append("playlist") or {"id": "unexpected"}, now=NOW,
        )
    assert external_calls == []


def test_tenant_cannot_write_comment_to_foreign_video(tenant_a):
    with pytest.raises(NotFoundError):
        upsert_comment(tenant_a, CommentUpsert(
            youtube_comment_id="attempt", video_id="video-b", channel_id="channel-b",
            author_display_name="A", original_text="cross tenant", published_at=NOW,
            last_synced_at=NOW,
        ))
    assert tenant_a.scalar(sa.select(sa.func.count()).select_from(YoutubeComment)) == 0


def test_remote_youtube_video_id_conflict_is_generic_and_does_not_name_owner(youtube_store):
    from zhiju.schemas.youtube import VideoUpsert
    from zhiju.services.identity import ConflictError
    from zhiju.services.youtube import upsert_video

    with Session(youtube_store) as setup:
        setup.add(Channel(
            id="channel-a", tenant_id="tenant-a", youtube_channel_id="UC-A",
            original_name="A", status="active",
        ))
        setup.commit()
    with TenantSession(
        youtube_store,
        info={"tenant_id": "tenant-a", "user_id": "user-a", "permissions": frozenset()},
    ) as session:
        with pytest.raises(ConflictError) as exc:
            upsert_video(session, VideoUpsert(
                youtube_video_id="remote-video-b", channel_id="channel-a", title="A attempt",
                url="https://youtu.be/remote-video-b", privacy_status="public",
                publish_status="published", published_at=NOW,
            ))
        assert "tenant-b" not in str(exc.value)
        assert "channel-b" not in str(exc.value)
