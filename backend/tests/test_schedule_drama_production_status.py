import pytest
from sqlalchemy import create_engine

from test_schedule_video_edit import _schedule_fixture
from zhiju.database import TenantSession
from zhiju.models import Base, DramaProductionState
from zhiju.schemas.operations import ChannelSchedulePage, ScheduleOverview
from zhiju.services.operations import list_channel_schedule_page, list_schedule_overview


@pytest.mark.parametrize("statuses,expected", [
    (None, "not_started"),
    ({}, "not_started"),
    ({"tts_status": "in_progress"}, "in_progress"),
    ({"parameter_normalization_status": "completed"}, "in_progress"),
    ({"tts_status": "failed"}, "in_progress"),
    (dict.fromkeys([
        "cloud_download_status", "parameter_normalization_status", "youtube_upload_status",
        "copyright_verification_status", "subtitle_extraction_status", "guishou_upload_status",
        "role_extraction_status", "tts_status", "production_completion_status",
    ], "completed"), "completed"),
])
def test_schedule_views_expose_library_production_status(statuses, expected):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as session:
        schedule = _schedule_fixture(session)
        if statuses is not None:
            session.add(DramaProductionState(drama_id=schedule.drama_id, **statuses))
            session.commit()
        page = ChannelSchedulePage.model_validate(list_channel_schedule_page(
            session, channel_id=schedule.channel_id,
        ))
        overview = [ScheduleOverview.model_validate(item) for item in list_schedule_overview(session)]
        assert page.items[0].drama_production_status == expected
        assert overview[0].drama_production_status == expected
        assert page.items[0].schedule_status == "planned"
    engine.dispose()
