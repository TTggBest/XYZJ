from datetime import date, datetime, time
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju.app import app
from zhiju.database import database_router
from zhiju.models import Channel, ChannelPublishSlot, ChannelScheduleEntry, Drama
from zhiju.schemas.operations import SourceVideoUpdate
from zhiju.schemas.production import TaskCreate
from zhiju.services.operations import list_schedule_overview
from zhiju.services.production import create_task
from zhiju.services.schedule_video import update_schedule_source_video, update_task_source_video


def _schedule_fixture(session: Session) -> ChannelScheduleEntry:
    suffix = uuid4().hex[:10]
    channel = Channel(
        youtube_channel_id=f"UC-VIDEO-EDIT-{suffix}",
        original_name=f"视频信息编辑-{suffix}",
        timezone="Asia/Shanghai",
        daily_publish_count=1,
        status="active",
    )
    drama = Drama(
        drama_number=-int(f"4{suffix[:7]}", 16),
        drama_code=f"VIDEO-EDIT-{suffix}",
        chinese_title=f"待补视频-{suffix}",
        normalized_title=f"待补视频-{suffix}".casefold(),
        source_type="manual",
        status="active",
    )
    session.add_all([channel, drama])
    session.flush()
    slot = ChannelPublishSlot(
        channel_id=channel.id,
        slot_type="main",
        slot_number=1,
        local_time=time(18, 0),
        timezone=channel.timezone,
        status="active",
    )
    session.add(slot)
    session.flush()
    schedule = ChannelScheduleEntry(
        channel_id=channel.id,
        drama_id=drama.id,
        publish_slot_id=slot.id,
        publish_date=date(2026, 9, 7),
        planned_local_time=datetime(2026, 9, 7, 18, 0),
        planned_beijing_time=datetime(2026, 9, 7, 18, 0),
        planned_utc_time=datetime(2026, 9, 7, 10, 0),
        community_count=0,
        status="planned",
        priority=100,
        idempotency_key=f"video-edit-schedule-{suffix}",
        source_type="feishu",
        source_video_id="oldVideo01A",
        source_video_url="https://youtu.be/oldVideo01A",
    )
    session.add(schedule)
    session.commit()
    return schedule


def test_task_created_from_schedule_inherits_video_identity() -> None:
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        schedule = _schedule_fixture(session)

        task = create_task(
            session,
            TaskCreate(
                schedule_id=schedule.id,
                task_date=date(2026, 9, 3),
                idempotency_key=f"video-task-{uuid4().hex}",
            ),
        )

        assert task.source_video_id == "oldVideo01A"
        assert task.source_video_url == "https://youtu.be/oldVideo01A"
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_schedule_video_edit_updates_existing_task_and_marks_manual_override() -> None:
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        schedule = _schedule_fixture(session)
        task = create_task(
            session,
            TaskCreate(
                schedule_id=schedule.id,
                task_date=date(2026, 9, 3),
                idempotency_key=f"video-task-{uuid4().hex}",
            ),
        )

        updated = update_schedule_source_video(
            session,
            schedule.id,
            SourceVideoUpdate(
                source_video_url="https://www.youtube.com/watch?v=IQ7Cw_wpiqE",
                source_video_id=None,
            ),
        )

        session.refresh(task)
        assert updated.source_video_id == "IQ7Cw_wpiqE"
        assert updated.source_video_url == "https://www.youtube.com/watch?v=IQ7Cw_wpiqE"
        assert updated.source_video_overridden is True
        assert task.source_video_id == "IQ7Cw_wpiqE"
        assert task.source_video_url == updated.source_video_url
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_task_video_edit_updates_linked_schedule() -> None:
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        schedule = _schedule_fixture(session)
        task = create_task(
            session,
            TaskCreate(
                schedule_id=schedule.id,
                task_date=date(2026, 9, 3),
                idempotency_key=f"video-task-{uuid4().hex}",
            ),
        )

        updated = update_task_source_video(
            session,
            task.id,
            SourceVideoUpdate(source_video_url=None, source_video_id=None),
        )

        session.refresh(schedule)
        assert updated.source_video_id is None
        assert updated.source_video_url is None
        assert schedule.source_video_id is None
        assert schedule.source_video_url is None
        assert schedule.source_video_overridden is True
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_schedule_and_task_video_edit_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "patch" in paths["/api/v3/schedules/{schedule_id}/source-video"]
    assert "patch" in paths["/api/v3/tasks/{task_id}/source-video"]


def test_daily_schedule_overview_exposes_editable_video_identity() -> None:
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        schedule = _schedule_fixture(session)

        items = list_schedule_overview(
            session,
            publish_date_from=schedule.publish_date,
            publish_date_to=schedule.publish_date,
        )
        item = next(candidate for candidate in items if candidate["schedule_id"] == schedule.id)

        assert item["source_video_id"] == "oldVideo01A"
        assert item["source_video_url"] == "https://youtu.be/oldVideo01A"
        assert item["source_video_overridden"] is False
    finally:
        session.close()
        transaction.rollback()
        connection.close()
