from datetime import date, datetime, time, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from zhiju.database import database_router
from zhiju.models import (
    Channel,
    ChannelDnaVersion,
    ChannelPublishSlot,
    Drama,
    DramaProductionState,
)
from zhiju.schemas.operations import ScheduleCreate
from zhiju.schemas.production import TaskCreate
from zhiju.services.operations import create_schedule
from zhiju.services.production import create_task, dispatch_task


COMPLETED_PRODUCTION = {
    "cloud_download_status": "completed",
    "parameter_normalization_status": "completed",
    "youtube_upload_status": "completed",
    "copyright_verification_status": "completed",
    "subtitle_extraction_status": "completed",
    "guishou_upload_status": "completed",
    "role_extraction_status": "completed",
    "tts_status": "completed",
    "production_completion_status": "completed",
}


def test_schedule_freezes_active_dna_and_propagates_it_to_work_order_and_package() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-DNA-FLOW-{suffix}",
            original_name=f"DNA Flow {suffix}",
            default_language="id",
            default_genre="女频逆袭",
            timezone="Asia/Jakarta",
            daily_publish_count=1,
            status="active",
        )
        drama = Drama(
            drama_number=-int(f"6{suffix[:8]}", 16),
            drama_code=f"DNA-FLOW-{suffix}",
            chinese_title=f"DNA版本传递-{suffix}",
            normalized_title=f"dna版本传递-{suffix}",
            source_type="manual",
            status="active",
        )
        session.add_all([channel, drama])
        session.flush()
        slot = ChannelPublishSlot(
            channel_id=channel.id,
            slot_type="main",
            slot_number=1,
            local_time=time(20, 0),
            timezone="Asia/Jakarta",
            status="active",
        )
        dna_v1 = ChannelDnaVersion(
            channel_id=channel.id,
            version_number=1,
            status="active",
            language="id",
            primary_genre="女频逆袭",
            reference_summary="运营参考 v1",
            effective_from=datetime.now(timezone.utc),
        )
        session.add_all(
            [slot, dna_v1, DramaProductionState(drama_id=drama.id, **COMPLETED_PRODUCTION)]
        )
        session.commit()

        schedule = create_schedule(
            session,
            channel.id,
            ScheduleCreate(
                drama_id=drama.id,
                publish_slot_id=slot.id,
                publish_date=date(2026, 9, 2),
                idempotency_key=f"dna-schedule-{suffix}",
            ),
        )
        assert schedule.channel_dna_version_id == dna_v1.id

        dna_v1.status = "superseded"
        dna_v1.effective_to = datetime.now(timezone.utc)
        dna_v2 = ChannelDnaVersion(
            channel_id=channel.id,
            version_number=2,
            status="active",
            language="id",
            primary_genre="女频逆袭",
            reference_summary="运营参考 v2",
            effective_from=datetime.now(timezone.utc),
        )
        session.add(dna_v2)
        session.commit()

        task = create_task(
            session,
            TaskCreate(
                schedule_id=schedule.id,
                task_date=date(2026, 9, 1),
                idempotency_key=f"dna-task-{suffix}",
            ),
        )
        detail = dispatch_task(session, task.id)

        assert detail["work_order"].channel_dna_version_id == dna_v1.id
        assert detail["package"].channel_dna_version_id == dna_v1.id
    finally:
        session.close()
        transaction.rollback()
        connection.close()
