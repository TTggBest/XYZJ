from datetime import date, datetime, time
from pathlib import Path

from zhiju.services.operations import (
    ALLOWED_SCHEDULE_TRANSITIONS,
    build_cadence_time_projection,
    normalize_drama_title,
)
from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.schemas.operations import ChannelCadenceUpdate, CommunitySlotRead


def test_drama_title_matching_normalizes_width_case_and_spaces() -> None:
    assert normalize_drama_title("  ＡＢＣ   测试剧  ") == "abc 测试剧"


def test_published_schedule_is_terminal() -> None:
    assert "published" not in ALLOWED_SCHEDULE_TRANSITIONS
    assert "reserved" not in ALLOWED_SCHEDULE_TRANSITIONS["confirmed"]


def test_channel_community_slot_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    collection = "/api/v3/channels/{channel_id}/community-slots"
    status_path = "/api/v3/community-slots/{community_slot_id}/status"

    assert {"get", "post"}.issubset(paths[collection])
    assert "patch" in paths[status_path]


def test_channel_publish_slot_management_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/publish-slots/overview"]
    assert "patch" in paths[
        "/api/v3/channels/{channel_id}/publish-slots/{publish_slot_id}"
    ]


def test_publish_slot_management_is_available_from_schedule_page() -> None:
    app_source = (
        Path(__file__).resolve().parents[2] / "assets" / "app.js"
    ).read_text(encoding="utf-8")

    assert 'publishSlots: ["排期", "频道档期表"]' in app_source
    assert 'data-action="go-publish-slots"' in app_source
    assert 'data-action="go-channel-cadence"' in app_source


def test_cadence_routes_and_views_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/cadence-templates"]
    assert "put" in paths[
        "/api/v3/cadence-templates/{daily_publish_count}"
    ]
    assert "patch" in paths["/api/v3/channels/{channel_id}/cadence"]
    assert "get" in paths["/api/v3/cadence-overview"]

    app_source = (
        Path(__file__).resolve().parents[2] / "assets" / "app.js"
    ).read_text(encoding="utf-8")
    assert '["cadence", "档期配置", "clock-3"]' in app_source
    assert 'channelCadence: ["排期", "频道更新配置"]' in app_source
    assert 'data-action="go-channel-cadence"' in app_source
    assert "[1,2,3,4,5].map" in app_source
    assert '"当地社群发布", "北京时间社群发布"' in app_source
    assert '"cadence-table-wrap"' in app_source
    assert 'cadence-time-box is-local' in app_source
    assert 'cadence-time-box is-beijing' in app_source
    assert "channel.slots.forEach" not in app_source


def test_single_publish_cadence_is_valid() -> None:
    payload = ChannelCadenceUpdate(daily_publish_count=1)

    assert payload.daily_publish_count == 1


def test_bangladesh_cadence_projects_to_beijing_with_second_exposure() -> None:
    result = build_cadence_time_projection(
        on_date=date(2026, 8, 25),
        local_video_time=time(10, 0),
        channel_timezone="Asia/Dhaka",
        engagement_offset_minutes=120,
    )

    assert result["local_video_time"] == "10:00"
    assert result["beijing_video_time"] == "12:00"
    assert result["local_engagement_time"] == "12:00"
    assert result["beijing_engagement_time"] == "14:00"


def test_archived_community_slot_can_be_read() -> None:
    row = CommunitySlotRead.model_validate(
        {
            "id": "slot-1",
            "channel_id": "channel-1",
            "publish_slot_id": None,
            "schedule_mode": "fixed",
            "local_time": "09:30:00",
            "timezone": "Asia/Shanghai",
            "offset_minutes": 0,
            "status": "archived",
            "created_at": datetime(2026, 8, 16),
            "updated_at": datetime(2026, 8, 16),
        }
    )

    assert row.status == "archived"


def test_drama_translation_matrix_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    drama_translations = "/api/v3/dramas/{drama_id}/translations"
    language_translation = (
        "/api/v3/dramas/{drama_id}/translations/{language_id}"
    )

    assert "get" in paths[drama_translations]
    assert "put" in paths[language_translation]
    assert "get" in paths["/api/v3/drama-translations"]
    assert "get" in paths["/api/v3/drama-translations/matrix"]


def test_schedule_candidate_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "get" in paths["/api/v3/schedules/overview"]
    collection = "/api/v3/schedules/{schedule_id}/candidates"
    selection = (
        "/api/v3/schedules/{schedule_id}/candidates/{candidate_id}/select"
    )

    assert {"get", "post"}.issubset(paths[collection])
    assert "post" in paths[selection]
