from datetime import date

import pytest
from sqlalchemy import create_engine

from test_schedule_video_edit import _schedule_fixture
from zhiju.database import TenantSession
from zhiju.models import Base, OperationTask
from zhiju.services.operations import list_channel_schedule_page


@pytest.mark.parametrize("has_task", [True, False])
def test_task_generated_state_uses_actual_task_not_imported_feishu_flag(has_task):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as session:
        schedule = _schedule_fixture(session)
        schedule.is_task_written = not has_task
        if has_task:
            session.add(OperationTask(schedule_id=schedule.id, channel_id=schedule.channel_id,
                drama_id=schedule.drama_id, task_date=date(2026, 10, 27),
                target_publish_date=schedule.publish_date, source="schedule", status="completed",
                idempotency_key="actual-task"))
        session.commit()
        item = list_channel_schedule_page(session, channel_id=schedule.channel_id)["items"][0]
        assert item["is_task_written"] is has_task
        assert bool(item["task_id"]) is has_task
        assert schedule.is_task_written is (not has_task)  # Imported source data is untouched.
    engine.dispose()
