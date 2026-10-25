from datetime import timedelta

import pytest

from test_schedule_youtube_matching import NOW, fixture
from zhiju.models import AccountChannelAuthorization, Channel, Drama, GoogleAccount, OAuthGrant, YoutubeVideo
from zhiju.services.schedule_youtube import reconcile_channel_schedules, schedule_video_reviews
from zhiju.services.youtube_channel_sync import sync_authorized_channel_videos


@pytest.fixture
def sync_review(fixture):
    session, schedule, _ = fixture
    channel = session.get(Channel, schedule.channel_id)
    schedule.planned_utc_time = NOW + timedelta(days=10)
    account = GoogleAccount(nickname="Owner", google_email="owner@example.com", status="active", authorization_status="authorized")
    session.add(account)
    session.flush()
    grant = OAuthGrant(account_id=account.id, provider_subject="owner", credential_ref="keychain://test/owner",
                       status="active", token_expires_at=NOW + timedelta(days=2))
    session.add(grant)
    session.flush()
    session.add(AccountChannelAuthorization(account_id=account.id, channel_id=channel.id, oauth_grant_id=grant.id,
        status="active", verified_youtube_channel_id=channel.youtube_channel_id, verified_at=NOW))
    session.commit()
    title = session.get(Drama, schedule.drama_id).chinese_title

    class Store:
        def get(self, service, account):
            return '{"access_token":"test-access"}'

    def run(resources, minute):
        at = NOW + timedelta(minutes=minute)
        sync_authorized_channel_videos(session, Store(), channel_id=channel.id, fetcher=lambda *_: resources, now=at)
        reconcile_channel_schedules(session, channel.id, now=at)
        return schedule_video_reviews(session, [schedule], now=at)[schedule.id]

    def resource(video_id, restriction=None):
        return {"id": video_id, "snippet": {"title": title},
            "fileDetails": {"fileName": f"{title}_阿拉伯语.mp4"},
            "status": {"uploadStatus": "processed", "privacyStatus": "private"},
            "contentDetails": {"duration": "PT1H", **({"regionRestriction": restriction} if restriction is not None else {})},
            "upload_recorded_at": "2026-10-15T01:00:00Z" if video_id == "duplicate01" else "2026-10-15T00:00:00Z"}

    return session, schedule, run, resource


@pytest.mark.parametrize("restriction", [{"blocked": ["US", "SA"]}, {"allowed": []}, {"allowed": ["US"]}])
def test_blocked_upload_is_red_and_unblocking_clears_it(sync_review, restriction):
    session, schedule, sync, resource = sync_review
    blocked = sync([resource("blocked001", restriction)], 1)
    assert blocked["warning_level"] == "error"
    assert "youtube_blocked" in [w["code"] for w in blocked["warnings"]]
    assert blocked["videos"][0]["selectable"] is False
    assert schedule.source_video_id is None
    cleared = sync([resource("blocked001")], 2)
    assert cleared["warnings"] == []
    assert cleared["warning_level"] is None
    assert schedule.source_video_id == "blocked001"


def test_deleted_duplicate_disappears_after_successful_sync(sync_review):
    _, schedule, sync, resource = sync_review
    duplicate = sync([resource("firstvideo1"), resource("duplicate01")], 1)
    assert duplicate["warning_level"] == "warning"
    assert schedule.source_video_id == "firstvideo1"
    cleared = sync([resource("firstvideo1")], 2)
    assert [v["video_id"] for v in cleared["videos"]] == ["firstvideo1"]
    assert cleared["warnings"] == []
    assert cleared["warning_level"] is None


def test_deleted_blocked_duplicate_does_not_leave_a_red_warning(sync_review):
    _, _, sync, resource = sync_review
    assert sync([resource("firstvideo1"), resource("blocked001", {"blocked": ["US"]})], 1)["warning_level"] == "error"
    cleared = sync([resource("firstvideo1")], 2)
    assert cleared["warning_level"] is None
    assert cleared["warnings"] == []


def test_missing_bound_video_keeps_identity_but_not_uploaded_claim(sync_review):
    _, schedule, sync, resource = sync_review
    sync([resource("firstvideo1")], 1)
    missing = sync([], 2)
    assert schedule.source_video_id == "firstvideo1"
    assert missing["warning_level"] == "error"
    assert missing["selected"]["state"] == "unavailable"
    assert schedule.is_uploaded is False
    assert schedule.is_published is False


def test_unblocking_with_duplicate_downgrades_red_to_yellow(sync_review):
    _, _, sync, resource = sync_review
    assert sync([resource("firstvideo1"), resource("duplicate01", {"blocked": ["US"]})], 1)["warning_level"] == "error"
    review = sync([resource("firstvideo1"), resource("duplicate01")], 2)
    assert review["warning_level"] == "warning"
    assert "youtube_blocked" not in [w["code"] for w in review["warnings"]]


def test_resync_does_not_clear_an_independent_operator_ban(sync_review):
    session, _, sync, resource = sync_review
    sync([resource("firstvideo1", {"blocked": ["US"]})], 1)
    from sqlalchemy import select
    video = session.scalar(select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == "firstvideo1"))
    video.is_blocked = True
    session.commit()
    review = sync([resource("firstvideo1", {"blocked": []})], 2)
    assert "youtube_blocked" not in [w["code"] for w in review["warnings"]]
    assert "blocked" in [w["code"] for w in review["warnings"]]
    assert review["videos"][0]["selectable"] is False
