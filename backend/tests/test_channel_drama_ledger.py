from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from zhiju.app import app
from zhiju.auth_context import Principal, get_current_principal, get_tenant_db
from zhiju.database import TenantSession
from zhiju.models import (
    Base, Channel, ChannelPublishSlot, ChannelScheduleEntry, Drama,
    DramaProductionState, DramaTranslation, Language, SyncWatermark, YoutubeVideo,
)


@pytest.fixture
def ledger(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = TenantSession(bind=engine, info={"tenant_id": "ledger-a"})
    channel = Channel(id="channel-a", youtube_channel_id="UC-ledger", original_name="法语频道",
                      default_language="fr", timezone="Europe/Paris", daily_publish_count=1, status="active")
    language = Language(id="fr", code="fr", name_zh="法语", status="active")
    other_language = Language(id="en", code="en", name_zh="英语", status="active")
    session.add_all([channel, language, other_language])
    session.flush()
    for number, title in enumerate(["甲剧", "乙剧", "只有英语", "未完成", "有翻译没素材"], 1):
        session.add(Drama(id=f"d{number}", drama_number=number, drama_code=f"DRM-20261015-0000000{number}",
                          chinese_title=title, normalized_title=title, source_type="manual", status="active"))
    session.flush()
    for number in range(1, 6):
        session.add(DramaProductionState(drama_id=f"d{number}", production_completion_status="in_progress" if number == 4 else "completed"))
        session.add(DramaTranslation(drama_id=f"d{number}", language_id="en" if number == 3 else "fr",
                                    translation_status="ready", asset_status="missing" if number == 5 else "ready"))
    slot = ChannelPublishSlot(id="slot", channel_id=channel.id, slot_type="main", slot_number=1,
                              local_time=time(19), timezone="Europe/Paris", status="active")
    session.add(slot)
    session.flush()
    session.add_all([
        YoutubeVideo(id="v1", channel_id=channel.id, drama_id="d1", youtube_video_id="public00001",
                     title="改过标题", url="https://youtu.be/public00001", privacy_status="public",
                     publish_status="published", uploaded_at=datetime(2026, 10, 1, 10),
                     published_at=datetime(2026, 10, 2, 10), upload_status="processed", source="youtube_sync"),
        YoutubeVideo(id="v2", channel_id=channel.id, drama_id="d1", youtube_video_id="failed00001",
                     title="甲剧_法语", url="https://youtu.be/failed00001", privacy_status="private",
                     publish_status="error", upload_status="failed", source="youtube_sync"),
        ChannelScheduleEntry(id="s1", channel_id=channel.id, drama_id="d1", publish_slot_id=slot.id,
                             publish_date=date(2026, 11, 1), planned_local_time=datetime(2026, 11, 1, 19),
                             planned_beijing_time=datetime(2026, 11, 2, 2), planned_utc_time=datetime(2026, 11, 1, 18),
                             source_video_id="failed00001", idempotency_key="s1", status="planned"),
    ])
    session.commit()
    principal = Principal(user_id="ledger-user", tenant_id="ledger-a", membership_role="owner",
                          platform_role=None, device_id=None, device_trust_level="normal",
                          permissions=frozenset({"channel.read"}))
    monkeypatch.setitem(app.dependency_overrides, get_current_principal, lambda: principal)
    monkeypatch.setitem(app.dependency_overrides, get_tenant_db, lambda: session)
    yield TestClient(app), session
    session.close()
    engine.dispose()


def test_channel_ledger_keeps_each_upload_and_only_ready_language_inventory(ledger):
    client, _ = ledger
    response = client.get("/api/v3/channels/channel-a/drama-ledger")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["channel_name"] == "法语频道"
    assert [(r["drama_title"], r["youtube_video_id"]) for r in data["items"]] == [
        ("甲剧", "public00001"), ("甲剧", "failed00001"), ("乙剧", None),
    ]
    public, failed, unused = data["items"]
    assert public["uploaded_at"].startswith("2026-10-01")
    assert public["is_public"] is True
    assert failed["failed"] is True and failed["failure_message"]
    assert failed["has_schedule"] is True and failed["schedule_id"] == "s1"
    assert unused["visibility"] == "not_uploaded" and unused["has_schedule"] is False


def test_filters_sorting_and_group_pagination_keep_repeated_drama_together(ledger):
    client, _ = ledger
    path = "/api/v3/channels/channel-a/drama-ledger"
    scheduled = client.get(path, params={"scheduled": "true"}).json()
    assert [r["youtube_video_id"] for r in scheduled["items"]] == ["failed00001"]
    unused = client.get(path, params={"visibility": "not_uploaded", "scheduled": "false"}).json()
    assert [r["drama_title"] for r in unused["items"]] == ["乙剧"]
    assert client.get(path, params={"visibility": "public", "scheduled": "true"}).json()["total"] == 0
    assert client.get(path, params={"query": "failed00001"}).json()["items"][0]["failed"] is True
    first = client.get(path, params={"page_size": 1}).json()
    assert len(first["items"]) == 2 and first["pages"] == 2
    second = client.get(path, params={"page_size": 1, "page": 2}).json()
    assert [r["drama_title"] for r in second["items"]] == ["乙剧"]
    desc = client.get(path, params={"sort_by": "drama_code", "sort_order": "desc"}).json()
    assert [r["drama_title"] for r in desc["items"]] == ["乙剧", "甲剧", "甲剧"]


def test_exact_filename_match_and_unmatched_uploads_are_both_visible(ledger):
    client, session = ledger
    session.add_all([
        YoutubeVideo(channel_id="channel-a", youtube_video_id="filename001", title="标题已经更改",
                     original_file_name="乙剧_法语.mp4", url="https://youtu.be/filename001",
                     privacy_status="private", publish_status="scheduled", upload_status="processed",
                     scheduled_publish_at=datetime(2026, 11, 5, 12), source="youtube_sync"),
        YoutubeVideo(channel_id="channel-a", youtube_video_id="unmatched01", title="剧库没有的标题",
                     url="https://youtu.be/unmatched01", privacy_status="private", publish_status="draft",
                     upload_status="uploaded", source="youtube_sync"),
    ])
    session.commit()
    rows = client.get("/api/v3/channels/channel-a/drama-ledger").json()["items"]
    matched = next(r for r in rows if r["youtube_video_id"] == "filename001")
    assert matched["drama_title"] == "乙剧" and matched["visibility"] == "scheduled"
    assert matched["scheduled_publish_at"].startswith("2026-11-05")
    unknown = next(r for r in rows if r["youtube_video_id"] == "unmatched01")
    assert unknown["needs_matching"] is True and unknown["drama_code"] is None
    assert unknown["uploaded_at"] is None and unknown["failed"] is False


def test_additional_schedules_are_not_hidden_by_an_earlier_public_upload(ledger):
    client, session = ledger
    for ident, status, day in [("future", "planned", 2), ("cancelled", "cancelled", 3)]:
        session.add(ChannelScheduleEntry(id=ident, channel_id="channel-a", drama_id="d1", publish_slot_id="slot",
                                        publish_date=date(2026, 11, day), planned_local_time=datetime(2026, 11, day, 19),
                                        planned_beijing_time=datetime(2026, 11, day, 19), planned_utc_time=datetime(2026, 11, day, 11),
                                        status=status, idempotency_key=ident))
    session.commit()
    rows = client.get("/api/v3/channels/channel-a/drama-ledger").json()["items"]
    assert len(rows) == 4
    assert [r["drama_id"] for r in rows] == ["d1", "d1", "d1", "d2"]
    future = next(r for r in rows if r["schedule_id"] == "future")
    assert future["visibility"] == "not_uploaded" and future["has_schedule"] is True


def test_ledger_is_tenant_scoped_and_rejects_invalid_parameters(ledger):
    client, session = ledger
    with TenantSession(bind=session.get_bind(), info={"tenant_id": "ledger-b"}) as other:
        other.add(Channel(id="channel-b", youtube_channel_id="UC-other", original_name="其他租户",
                          timezone="UTC", daily_publish_count=1, status="active"))
        other.commit()
    assert client.get("/api/v3/channels/channel-b/drama-ledger").status_code == 404
    assert client.get("/api/v3/channels/channel-a/drama-ledger", params={"sort_by": "arbitrary"}).status_code == 422
    assert client.get("/api/v3/channels/channel-a/drama-ledger", params={"page_size": 0}).status_code == 422


def test_missing_language_inventory_is_reported_not_presented_as_no_available_dramas(ledger):
    client, session = ledger
    from sqlalchemy import delete
    session.execute(delete(DramaTranslation))
    session.commit()
    data = client.get("/api/v3/channels/channel-a/drama-ledger").json()
    assert data["completed_drama_count"] == 4
    assert data["inventory_warning"]
    assert "语言" in data["inventory_warning"]
    assert len(data["items"]) == 2  # The real upload history is still available.


def test_upload_missing_from_latest_complete_sync_keeps_history_but_not_public_check(ledger):
    client, session = ledger
    session.add(SyncWatermark(channel_id="channel-a", data_type="videos", status="completed",
                              data_through_at=datetime(2026, 10, 28, 12)))
    session.commit()
    rows = client.get("/api/v3/channels/channel-a/drama-ledger").json()["items"]
    public = next(r for r in rows if r["youtube_video_id"] == "public00001")
    assert public["is_public"] is False and public["visibility"] == "unavailable"
    assert public["uploaded_at"].startswith("2026-10-01")
