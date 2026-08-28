from datetime import date, time
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from zhiju.database import database_router
from zhiju.models import Channel, ChannelPublishSlot, Drama, DramaProductionState
from zhiju.schemas.operations import ScheduleCreate
from zhiju.services import operations
from zhiju.services.identity import ConflictError


COMPLETED_STATUSES = {
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


def _drama(suffix: str, label: str, number: int) -> Drama:
    title = f"排期资格测试-{label}-{suffix}"
    return Drama(
        drama_number=number,
        drama_code=f"SCH-{label}-{suffix}",
        chinese_title=title,
        normalized_title=title.casefold(),
        source_type="manual",
        status="active",
    )


def test_schedulable_dramas_only_returns_completed_nonexcluded_active_dramas() -> None:
    list_schedulable_dramas = getattr(operations, "list_schedulable_dramas", None)
    assert callable(list_schedulable_dramas)

    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        completed = _drama(suffix, "complete", -int(f"1{suffix[:8]}", 16))
        incomplete = _drama(suffix, "incomplete", -int(f"2{suffix[:8]}", 16))
        excluded = _drama(suffix, "excluded", -int(f"3{suffix[:8]}", 16))
        final_only = _drama(suffix, "final-only", -int(f"5{suffix[:8]}", 16))
        session.add_all([completed, incomplete, excluded, final_only])
        session.flush()
        session.add_all(
            [
                DramaProductionState(drama_id=completed.id, **COMPLETED_STATUSES),
                DramaProductionState(drama_id=incomplete.id),
                DramaProductionState(
                    drama_id=excluded.id,
                    is_production_excluded=True,
                    **COMPLETED_STATUSES,
                ),
                DramaProductionState(
                    drama_id=final_only.id,
                    production_completion_status="completed",
                ),
            ]
        )
        session.commit()

        result = list_schedulable_dramas(session)

        matching_ids = {
            item["id"]
            for item in result
            if item["id"] in {completed.id, incomplete.id, excluded.id, final_only.id}
        }
        assert matching_ids == {completed.id}
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_create_schedule_rejects_drama_before_production_completion() -> None:
    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = Channel(
            youtube_channel_id=f"UC-SCHEDULE-{suffix}",
            original_name=f"排期资格频道-{suffix}",
            timezone="Asia/Shanghai",
            daily_publish_count=1,
            status="active",
        )
        drama = _drama(suffix, "blocked", -int(f"4{suffix[:8]}", 16))
        session.add_all([channel, drama])
        session.flush()
        slot = ChannelPublishSlot(
            channel_id=channel.id,
            slot_type="main",
            slot_number=1,
            local_time=time(20, 0),
            timezone="Asia/Shanghai",
            status="active",
        )
        session.add_all([slot, DramaProductionState(drama_id=drama.id)])
        session.commit()

        with pytest.raises(ConflictError, match="制剧全部完成"):
            operations.create_schedule(
                session,
                channel.id,
                ScheduleCreate(
                    drama_id=drama.id,
                    publish_slot_id=slot.id,
                    publish_date=date(2026, 9, 1),
                    idempotency_key=f"schedule-{suffix}",
                ),
            )
    finally:
        session.close()
        transaction.rollback()
        connection.close()
