from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import (
    AccountChannelAuthorization,
    Channel,
    Drama,
    GoogleAccount,
    OAuthGrant,
    OperationTask,
    YoutubeVideo,
)
from zhiju.services.youtube_channel_sync import (
    ensure_grant_access_token,
    fetch_channel_upload_videos,
    parse_youtube_duration,
    sync_authorized_channel_videos,
)


ROOT = Path(__file__).resolve().parents[2]


def _remote_video(video_id: str, title: str, duration: str = "PT1H2M3S") -> dict[str, object]:
    return {
        "id": video_id,
        "etag": f"etag-{video_id}",
        "snippet": {
            "title": title,
            "description": f"{title} description",
            "publishedAt": "2026-08-28T12:00:00Z",
        },
        "status": {"privacyStatus": "public", "uploadStatus": "processed"},
        "contentDetails": {"duration": duration},
    }


def test_youtube_channel_video_sync_route_does_not_offer_direct_drama_binding() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "post" in paths["/api/v3/channels/{channel_id}/youtube-videos/sync"]
    assert "/api/v3/youtube/videos/{video_id}/drama-binding" not in paths
    assert 'data-action="sync-youtube-videos"' in source


def test_youtube_duration_parser_handles_hours_minutes_and_seconds() -> None:
    assert parse_youtube_duration("PT1H2M3S") == 3723
    assert parse_youtube_duration("PT44M40S") == 2680
    assert parse_youtube_duration("PT35S") == 35


def test_expired_grant_token_is_refreshed_and_saved_without_losing_refresh_token() -> None:
    now = datetime.now(timezone.utc)
    writes: list[dict[str, object]] = []

    class Store:
        def get(self, service: str, account: str) -> str:
            return '{"access_token":"expired","refresh_token":"keep-me"}'

        def put(self, service: str, account: str, value: str) -> None:
            writes.append(json.loads(value))

    class Grant:
        id = "grant-id"
        token_expires_at = now - timedelta(minutes=1)
        last_refreshed_at = None

    class SessionStub:
        commits = 0

        def commit(self) -> None:
            self.commits += 1

    session = SessionStub()
    grant = Grant()

    token = ensure_grant_access_token(
        session,
        Store(),
        grant,
        now=now,
        refresher=lambda refresh_token: {
            "access_token": f"new-for-{refresh_token}",
            "expires_in": 3600,
        },
    )

    assert token == "new-for-keep-me"
    assert writes == [
        {
            "access_token": "new-for-keep-me",
            "refresh_token": "keep-me",
            "expires_in": 3600,
        }
    ]
    assert grant.token_expires_at == now + timedelta(hours=1)
    assert grant.last_refreshed_at == now
    assert session.commits == 1


def test_upload_playlist_fetcher_follows_pages_and_reads_video_details() -> None:
    calls: list[str] = []

    def requester(url: str, access_token: str) -> dict[str, object]:
        assert access_token == "access"
        calls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/channels"):
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU-test"}}}]}
        if parsed.path.endswith("/playlistItems"):
            if "pageToken" not in query:
                return {
                    "items": [{"contentDetails": {"videoId": "video-one1"}}],
                    "nextPageToken": "page-2",
                }
            return {"items": [{"contentDetails": {"videoId": "video-two2"}}]}
        if parsed.path.endswith("/videos"):
            return {"items": [_remote_video(video_id, video_id) for video_id in query["id"][0].split(",")]}
        raise AssertionError(f"unexpected URL: {url}")

    videos = fetch_channel_upload_videos("access", "UC-test", requester=requester)

    assert [video["id"] for video in videos] == ["video-one1", "video-two2"]
    assert any("pageToken=page-2" in url for url in calls)


def test_channel_sync_exactly_binds_known_video_id_and_leaves_unknown_unbound() -> None:
    suffix = uuid4().hex[:12]
    known_video_id = f"K{suffix[:10]}"
    unknown_video_id = f"U{suffix[:10]}"
    now = datetime.now(timezone.utc)
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    class Store:
        def get(self, service: str, account: str) -> str | None:
            if account == grant.id:
                return '{"access_token":"test-access","refresh_token":"test-refresh"}'
            return None

        def put(self, service: str, account: str, value: str) -> None:
            raise AssertionError("unexpired token must not be refreshed")

    try:
        channel = Channel(
            youtube_channel_id=f"UC-{suffix}",
            original_name=f"Sync channel {suffix}",
            timezone="Asia/Shanghai",
            daily_publish_count=1,
            status="authorized",
        )
        drama = Drama(
            drama_number=-(int(suffix[:8], 16) + 1000),
            drama_code=f"SYNC-{suffix}",
            chinese_title=f"频道同步测试剧-{suffix}",
            normalized_title=f"频道同步测试剧-{suffix}",
            source_type="manual",
            status="active",
        )
        account = GoogleAccount(
            nickname=f"Owner {suffix}",
            google_email=f"{suffix}@example.com",
            status="active",
            authorization_status="authorized",
        )
        session.add_all([channel, drama, account])
        session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            provider_subject=f"subject-{suffix}",
            credential_ref=f"keychain://test/{suffix}",
            status="active",
            token_expires_at=now + timedelta(hours=1),
        )
        session.add(grant)
        session.flush()
        authorization = AccountChannelAuthorization(
            account_id=account.id,
            channel_id=channel.id,
            oauth_grant_id=grant.id,
            status="active",
            verified_youtube_channel_id=channel.youtube_channel_id,
            verified_at=now,
        )
        task = OperationTask(
            channel_id=channel.id,
            drama_id=drama.id,
            task_date=date(2026, 8, 28),
            target_publish_date=date(2026, 8, 29),
            community_count=0,
            source="import",
            status="completed",
            idempotency_key=f"youtube-sync-{suffix}",
            source_video_id=known_video_id,
        )
        session.add_all([authorization, task])
        session.commit()

        calls: list[tuple[str, str]] = []

        def fetcher(access_token: str, youtube_channel_id: str) -> list[dict[str, object]]:
            calls.append((access_token, youtube_channel_id))
            return [
                _remote_video(known_video_id, "Known drama"),
                _remote_video(unknown_video_id, "Unknown drama", "PT44M40S"),
            ]

        result = sync_authorized_channel_videos(
            session,
            Store(),
            channel_id=channel.id,
            fetcher=fetcher,
            now=now,
        )

        videos = {
            video.youtube_video_id: video
            for video in session.scalars(
                select(YoutubeVideo).where(YoutubeVideo.channel_id == channel.id)
            )
        }
        assert calls == [("test-access", channel.youtube_channel_id)]
        assert result == {
            "fetched": 2,
            "inserted": 2,
            "updated": 0,
            "bound": 1,
            "unmatched": 1,
        }
        assert videos[known_video_id].drama_id == drama.id
        assert videos[known_video_id].source == "youtube_sync"
        assert videos[known_video_id].duration_seconds == 3723
        assert videos[unknown_video_id].drama_id is None
        assert videos[unknown_video_id].duration_seconds == 2680
    finally:
        session.close()
        transaction.rollback()
        connection.close()
