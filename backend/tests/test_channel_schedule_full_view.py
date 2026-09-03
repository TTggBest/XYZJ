from datetime import date, datetime, time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju import models
from zhiju.app import app
from zhiju.database import database_router
from zhiju.services import operations


ROOT = Path(__file__).resolve().parents[2]


def test_channel_schedule_page_supports_search_sort_and_total() -> None:
    list_page = getattr(operations, "list_channel_schedule_page", None)
    assert callable(list_page)
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = models.Channel(
            youtube_channel_id=f"UC-FULL-{suffix}",
            original_name=f"完整排期频道-{suffix}",
            timezone="Asia/Shanghai",
            daily_publish_count=1,
            status="active",
        )
        first_drama = models.Drama(
            drama_number=-int(f"4{suffix[:7]}", 16),
            drama_code=f"FULL-A-{suffix}",
            chinese_title=f"较早剧目-{suffix}",
            normalized_title=f"较早剧目-{suffix}".casefold(),
            source_type="manual",
            status="active",
        )
        second_drama = models.Drama(
            drama_number=-int(f"5{suffix[:7]}", 16),
            drama_code=f"FULL-B-{suffix}",
            chinese_title=f"较晚剧目-{suffix}",
            normalized_title=f"较晚剧目-{suffix}".casefold(),
            source_type="manual",
            status="active",
        )
        session.add_all([channel, first_drama, second_drama])
        session.flush()
        slot = models.ChannelPublishSlot(
            channel_id=channel.id,
            slot_type="main",
            slot_number=1,
            local_time=time(20, 0),
            timezone="Asia/Shanghai",
            status="active",
        )
        session.add(slot)
        session.flush()
        session.add_all([
            models.ChannelScheduleEntry(
                channel_id=channel.id,
                drama_id=first_drama.id,
                publish_slot_id=slot.id,
                publish_date=date(2026, 8, 29),
                planned_local_time=datetime(2026, 8, 29, 20, 0),
                planned_beijing_time=datetime(2026, 8, 29, 20, 0),
                planned_utc_time=datetime(2026, 8, 29, 12, 0),
                status="published",
                idempotency_key=f"full-a-{suffix}",
                source_type="feishu",
                source_sheet_id="sheet-full",
                source_row_number=2,
                source_video_id="IQ7Cw_wpiqE",
                source_video_url="https://youtu.be/IQ7Cw_wpiqE",
                is_uploaded=True,
                is_published=True,
                is_task_written=True,
            ),
            models.ChannelScheduleEntry(
                channel_id=channel.id,
                drama_id=second_drama.id,
                publish_slot_id=slot.id,
                publish_date=date(2026, 8, 30),
                planned_local_time=datetime(2026, 8, 30, 20, 0),
                planned_beijing_time=datetime(2026, 8, 30, 20, 0),
                planned_utc_time=datetime(2026, 8, 30, 12, 0),
                status="planned",
                idempotency_key=f"full-b-{suffix}",
                source_type="manual",
            ),
        ])
        session.commit()

        ascending = list_page(session, channel_id=channel.id, page=1, page_size=50)
        descending = list_page(
            session,
            channel_id=channel.id,
            sort_order="desc",
            page=1,
            page_size=50,
        )
        searched = list_page(
            session,
            channel_id=channel.id,
            query="IQ7Cw_wpiqE",
            page=1,
            page_size=50,
        )

        assert ascending["total"] == 2
        assert [item["chinese_title"] for item in ascending["items"]] == [
            first_drama.chinese_title,
            second_drama.chinese_title,
        ]
        assert [item["chinese_title"] for item in descending["items"]] == [
            second_drama.chinese_title,
            first_drama.chinese_title,
        ]
        assert searched["total"] == 1
        assert searched["items"][0]["source_video_url"] == "https://youtu.be/IQ7Cw_wpiqE"
        assert searched["items"][0]["is_published"] is True
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_channel_schedule_page_route_restricts_page_sizes() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()

    assert "get" in schema["paths"]["/api/v3/schedules/channel-view"]
    valid = client.get(
        "/api/v3/schedules/channel-view",
        params={"channel_id": "missing", "page_size": 50},
    )
    assert valid.status_code == 200
    response = client.get(
        "/api/v3/schedules/channel-view",
        params={"channel_id": "missing", "page_size": 60},
    )
    assert response.status_code == 422


def test_schedule_frontend_has_full_channel_view_and_read_only_sync_controls() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    for marker in (
        "频道完整排期",
        "按日查看",
        "全部频道当日",
        'data-mode="all-day"',
        "sync-feishu-channel-schedules",
        "scheduleFullSearch",
        "scheduleFullSortOrder",
        "scheduleFullPageSize",
        'value="50"',
        'value="100"',
        'value="150"',
        "Video ID / 链接",
        "已上传",
        "已上线",
        "已写任务",
        "数据来源",
        "同步时间",
        "sourceVideoForm",
        "edit-schedule-video",
        "edit-task-video",
        "/source-video",
        "待补充",
    ):
        assert marker in source
    assert 'api("/feishu-sync/channel-schedules", { method: "POST" })' in source
    assert "window.confirm" in source

    styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
    assert ".channel-schedule-table" in styles
    assert "overflow-y: visible" in styles
