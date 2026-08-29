from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import Channel
from zhiju.schemas.channel import ChannelKeywordCreate
from zhiju.schemas.operations import PlaylistCreate, PlaylistUpdate
from zhiju.services.channel import add_keyword, deactivate_keyword
from zhiju.services.operations import create_playlist, update_playlist


ROOT = Path(__file__).resolve().parents[2]


def test_channel_manual_maintenance_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "delete" in paths["/api/v3/channels/{channel_id}/keywords/{keyword_id}"]
    assert "patch" in paths["/api/v3/channels/{channel_id}/playlists/{playlist_id}"]


def test_keyword_can_be_deactivated_and_playlist_can_be_updated() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-MANUAL-{suffix}",
            original_name=f"频道-{suffix}",
            timezone="Asia/Shanghai",
            status="active",
        )
        session.add(channel)
        session.commit()
        keyword = add_keyword(
            session,
            channel.id,
            ChannelKeywordCreate(
                keyword="逆袭",
                keyword_type="keyword",
                language="id",
            ),
        )
        playlist = create_playlist(
            session,
            channel.id,
            PlaylistCreate(local_name="复仇逆袭", status="draft"),
        )

        deactivated = deactivate_keyword(session, channel.id, keyword.id)
        updated = update_playlist(
            session,
            channel.id,
            playlist.id,
            PlaylistUpdate(
                chinese_name="复仇逆袭剧场",
                url="https://www.youtube.com/playlist?list=PL_TEST",
                status="active",
            ),
        )

        assert deactivated.status == "inactive"
        assert deactivated.effective_to is not None
        assert updated.chinese_name == "复仇逆袭剧场"
        assert updated.youtube_playlist_id == "PL_TEST"
        assert updated.status == "active"
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_detail_exposes_manual_maintenance_forms() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="channelKeywordForm"' in source
    assert 'id="channelPinnedCommentForm"' in source
    assert 'id="channelPlaylistForm"' in source
    assert 'data-action="delete-channel-keyword"' in source
    assert 'data-action="activate-pinned-comment"' in source
    assert 'data-action="edit-channel-playlist"' in source
