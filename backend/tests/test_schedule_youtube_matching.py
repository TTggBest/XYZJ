from datetime import datetime, timezone
from datetime import timedelta

import pytest

from sqlalchemy import create_engine

from test_schedule_video_edit import _schedule_fixture
from zhiju.database import TenantSession
from zhiju.models import Base, Channel, Drama, YoutubeVideo, SyncWatermark, ChannelScheduleEntry
from zhiju.services.schedule_youtube import reconcile_channel_schedules, schedule_video_reviews, select_schedule_video
from zhiju.services.identity import ConflictError


NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


@pytest.fixture
def fixture():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as session:
        schedule = _schedule_fixture(session)
        schedule.source_video_id = schedule.source_video_url = None
        session.get(Channel, schedule.channel_id).default_language = "ar"
        watermark = SyncWatermark(channel_id=schedule.channel_id, data_type="videos", status="completed", data_through_at=NOW)
        session.add(watermark)
        session.commit()
        yield session, schedule, watermark
    engine.dispose()


def add_video(session, schedule, video_id="candidate01", **changes):
    title = session.get(Drama, schedule.drama_id).chinese_title
    values = dict(youtube_video_id=video_id, channel_id=schedule.channel_id, title=title,
        original_file_name=f"{title}_阿拉伯语.mp4", uploaded_at=NOW - timedelta(days=1),
        upload_status="processed", privacy_status="private", publish_status="draft",
        url=f"https://youtu.be/{video_id}", source="youtube_sync", last_synced_at=NOW)
    values.update(changes)
    video = YoutubeVideo(**values)
    session.add(video)
    session.commit()
    return video


@pytest.mark.parametrize("privacy,scheduled,expected,warning", [
    ("private", None, "private", None),
    ("unlisted", None, "unlisted", None),
    ("private", datetime(2026, 9, 7, 10, tzinfo=timezone.utc), "scheduled", "schedule_overdue"),
    ("private", datetime(2026, 11, 7, 10, tzinfo=timezone.utc), "scheduled", "schedule_mismatch"),
    ("public", None, "public", "public_history"),
])
def test_publication_states_and_schedule_warnings(fixture, privacy, scheduled, expected, warning):
    session, schedule, _ = fixture
    add_video(session, schedule, privacy_status=privacy, scheduled_publish_at=scheduled)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert review["videos"][0]["state"] == expected
    if warning:
        assert warning in [w["code"] for w in review["warnings"]]
    assert schedule.is_published is False  # Old public videos are never assigned to this new schedule.
    assert bool(schedule.source_video_id) is (privacy != "public")


@pytest.mark.parametrize("privacy", ["private", "unlisted"])
def test_unscheduled_upload_before_publish_date_is_normal_but_overdue_still_warns(fixture, privacy):
    session, schedule, _ = fixture
    schedule.planned_utc_time = NOW + timedelta(days=10)
    session.commit()
    add_video(session, schedule, privacy_status=privacy)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert review["selected"]["state"] == privacy
    assert review["warnings"] == []
    overdue = schedule_video_reviews(session, [schedule], now=NOW + timedelta(days=11))[schedule.id]
    assert "publish_overdue" in [w["code"] for w in overdue["warnings"]]


def test_explicit_choice_survives_resync_and_cannot_be_used_by_another_schedule(fixture):
    session, schedule, _ = fixture
    add_video(session, schedule, "first-video")
    add_video(session, schedule, "later-video", uploaded_at=NOW)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    select_schedule_video(session, schedule.id, "later-video")
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    assert schedule.source_video_id == "later-video"
    assert schedule.source_video_overridden is True
    other = _schedule_fixture(session)
    other.channel_id, other.drama_id = schedule.channel_id, schedule.drama_id
    other.source_video_id = None
    session.commit()
    with pytest.raises(ConflictError):
        select_schedule_video(session, other.id, "later-video")


@pytest.mark.parametrize("change,warning", [
    ({"original_file_name": "{title}_英语.mp4"}, "language_error"),
    ({"original_file_name": None}, "language_unknown"),
    ({"upload_status": "uploaded"}, "video_processing"),
    ({"upload_status": "rejected", "publish_status": "error"}, "video_error"),
])
def test_uncertain_or_wrong_uploads_are_not_automatically_bound(fixture, change, warning):
    session, schedule, _ = fixture
    title = session.get(Drama, schedule.drama_id).chinese_title
    change = {k: v.replace("{title}", title) if isinstance(v, str) else v for k, v in change.items()}
    add_video(session, schedule, **change)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert schedule.source_video_id is None
    assert warning in [w["code"] for w in review["warnings"]]


def test_language_error_cannot_be_overridden_by_selection(fixture):
    session, schedule, _ = fixture
    title = session.get(Drama, schedule.drama_id).chinese_title
    add_video(session, schedule, original_file_name=f"{title}_英语.mp4")
    with pytest.raises(ConflictError):
        select_schedule_video(session, schedule.id, "candidate01", confirm_unknown=True)
    assert schedule.source_video_id is None


def test_absent_unbound_upload_does_not_remain_a_candidate_or_warning(fixture):
    session, schedule, _ = fixture
    add_video(session, schedule, last_synced_at=NOW - timedelta(days=1))
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert review["videos"] == []
    assert review["warnings"] == []
    assert review["empty_label"] == "本次未上传"


def test_unknown_language_requires_explicit_confirmation(fixture):
    session, schedule, _ = fixture
    add_video(session, schedule, original_file_name=None)
    with pytest.raises(ConflictError):
        select_schedule_video(session, schedule.id, "candidate01")
    select_schedule_video(session, schedule.id, "candidate01", confirm_unknown=True)
    assert schedule.source_video_id == "candidate01"


def test_failed_sync_preserves_binding_and_does_not_claim_missing_upload(fixture):
    session, schedule, watermark = fixture
    add_video(session, schedule)
    select_schedule_video(session, schedule.id, "candidate01")
    watermark.status = "failed"
    session.commit()
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert schedule.source_video_id == "candidate01"
    assert review["sync_complete"] is False
    assert review["empty_label"] != "本次未上传"


def test_two_pending_schedules_for_same_drama_require_manual_allocation(fixture):
    session, schedule, _ = fixture
    other = _schedule_fixture(session)
    other.channel_id, other.drama_id = schedule.channel_id, schedule.drama_id
    other.source_video_id = None
    session.commit()
    add_video(session, schedule)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    assert schedule.source_video_id is None and other.source_video_id is None
    assert "multiple_schedules" in [w["code"] for w in schedule_video_reviews(session, [schedule])[schedule.id]["warnings"]]


def test_missing_upload_time_in_any_candidate_prevents_claiming_an_oldest_default(fixture):
    session, schedule, _ = fixture
    add_video(session, schedule, "known-time1")
    add_video(session, schedule, "unknown-time", uploaded_at=None)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    assert schedule.source_video_id is None


def test_single_verified_upload_does_not_need_a_time_to_disambiguate(fixture):
    session, schedule, _ = fixture
    add_video(session, schedule, uploaded_at=None)
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    assert schedule.source_video_id == "candidate01"


def test_wrong_language_scheduled_upload_has_urgent_warning_even_if_other_upload_is_valid(fixture):
    session, schedule, _ = fixture
    title = session.get(Drama, schedule.drama_id).chinese_title
    add_video(session, schedule, "bad-lang001", original_file_name=f"{title}_英语.mp4", scheduled_publish_at=NOW + timedelta(days=1))
    add_video(session, schedule, "good-lang01")
    reconcile_channel_schedules(session, schedule.channel_id, now=NOW)
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert schedule.source_video_id == "good-lang01"
    assert "wrong_language_scheduled" in [w["code"] for w in review["warnings"]]


def test_matching_schedule_in_other_timezone_does_not_warn_about_a_false_time_difference(fixture):
    session, schedule, _ = fixture
    schedule.planned_utc_time = NOW + timedelta(days=1)
    from zhiju.schemas.youtube import VideoUpsert
    payload = VideoUpsert(youtube_video_id="timezone01", channel_id=schedule.channel_id,
        title="测试", url="https://youtu.be/timezone01", privacy_status="private", publish_status="scheduled",
        scheduled_publish_at=(NOW + timedelta(days=1)).astimezone(timezone(timedelta(hours=3))))
    assert payload.scheduled_publish_at.hour == 0
    add_video(session, schedule, scheduled_publish_at=payload.scheduled_publish_at)
    session.commit()
    review = schedule_video_reviews(session, [schedule], now=NOW)[schedule.id]
    assert "schedule_mismatch" not in [w["code"] for w in review["warnings"]]


def test_sync_defaults_to_oldest_matching_language_and_exposes_duplicates():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as session:
        schedule = _schedule_fixture(session)
        schedule.source_video_id = None
        schedule.source_video_url = None
        session.get(Channel, schedule.channel_id).default_language = "ar"
        from zhiju.models import Drama
        title = session.get(Drama, schedule.drama_id).chinese_title
        for video_id, language, privacy, day in [
            ("old-public1", "阿拉伯语", "public", 1),
            ("new-private", "阿拉伯语", "private", 3),
            ("first-new01", "阿拉伯语", "private", 2),
            ("wrong-lang1", "英语", "private", 1),
        ]:
            session.add(YoutubeVideo(
                youtube_video_id=video_id, channel_id=schedule.channel_id,
                title=title, original_file_name=f"{title}_{language}.mp4",
                uploaded_at=datetime(2026, 10, day, tzinfo=timezone.utc),
                upload_status="processed", url=f"https://youtu.be/{video_id}",
                privacy_status=privacy, publish_status="published" if privacy == "public" else "draft",
                source="youtube_sync", last_synced_at=now,
            ))
        session.add(SyncWatermark(channel_id=schedule.channel_id, data_type="videos", status="completed", data_through_at=now))
        session.commit()
        reconcile_channel_schedules(session, schedule.channel_id, now=now)
        review = schedule_video_reviews(session, [schedule], now=now)[schedule.id]
        assert schedule.source_video_id == "first-new01"
        assert review["public_count"] == 1
        assert "multiple_candidates" in [w["code"] for w in review["warnings"]]
        wrong = next(v for v in review["videos"] if v["video_id"] == "wrong-lang1")
        assert wrong["language_check"] == "mismatch"
        assert wrong["selectable"] is False
