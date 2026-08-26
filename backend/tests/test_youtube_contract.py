from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from zhiju.app import app
from zhiju.models import YoutubeVideo
from zhiju.schemas.youtube import VideoUpsert


def test_youtube_registry_and_sync_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v3/youtube/videos" in paths
    assert "/api/v3/youtube/comments" in paths
    assert "/api/v3/youtube/comment-replies" in paths
    assert "/api/v3/youtube/channel-daily-metrics" in paths
    assert "/api/v3/youtube/video-daily-metrics" in paths
    assert "/api/v3/youtube/analytics-breakdowns" in paths
    assert "/api/v3/youtube/sync-watermarks/{channel_id}/{data_type}/start" in paths
    assert "/api/v3/youtube/sync-watermarks/{channel_id}/{data_type}/complete" in paths
    assert "/api/v3/youtube/playlist-memberships" in paths
    assert "/api/v3/youtube/playlist-memberships/{membership_id}/order" in paths
    assert "/api/v3/youtube/playlists/{playlist_id}/order-history" in paths
    assert "/api/v3/youtube/comments/{comment_id}/analysis" in paths
    assert "/api/v3/youtube/comment-replies/{reply_id}/review" in paths
    assert "/api/v3/youtube/comment-replies/{reply_id}/status" in paths
    assert {"get", "post"}.issubset(paths["/api/v3/youtube/api-requests"])
    assert "get" in paths["/api/v3/youtube/quota-usage"]
    assert "get" in paths["/api/v3/youtube/quota-usage/summary"]


def test_comment_reply_creation_cannot_claim_external_publish_success() -> None:
    document = TestClient(app).get("/openapi.json").json()
    schema = document["components"]["schemas"]["CommentReplyCreate"]
    publish_status = schema["properties"]["publish_status"]
    assert set(publish_status["enum"]) == {"draft", "queued"}


def test_video_publication_requires_matching_timestamp() -> None:
    common = {
        "youtube_video_id": "video-123",
        "channel_id": "channel-id",
        "title": "标题",
        "url": "https://youtu.be/video-123",
    }
    with pytest.raises(ValidationError):
        VideoUpsert(**common, privacy_status="private", publish_status="scheduled")
    with pytest.raises(ValidationError):
        VideoUpsert(
            **common,
            privacy_status="public",
            publish_status="published",
        )

    row = VideoUpsert(
        **common,
        privacy_status="public",
        publish_status="published",
        published_at=datetime.now(timezone.utc),
    )
    assert row.published_at is not None


def test_one_operation_package_can_bind_only_one_youtube_video() -> None:
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in YoutubeVideo.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("operation_package_id",) in unique_column_sets
