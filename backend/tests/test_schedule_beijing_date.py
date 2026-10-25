from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine

from test_schedule_video_edit import _schedule_fixture
from zhiju.database import TenantSession
from zhiju.models import Base, Channel
from zhiju.services.operations import list_schedule_overview


@pytest.mark.parametrize("single_channel", [False, True])
def test_overview_filters_and_orders_by_beijing_calendar_day(single_channel):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-a"}) as session:
        schedules = []
        for timestamp, zone in [
            ("2026-10-26T23:59:59", "Asia/Shanghai"),
            ("2026-10-27T00:00:00", "Europe/Paris"),
            ("2026-10-27T01:00:00", "America/New_York"),
            ("2026-10-27T05:00:00", "America/Sao_Paulo"),
            ("2026-10-27T09:00:00", "America/New_York"),
            ("2026-10-28T00:00:00", "Europe/Paris"),
        ]:
            schedule = _schedule_fixture(session)
            beijing = datetime.fromisoformat(timestamp).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            local = beijing.astimezone(ZoneInfo(zone)).replace(tzinfo=None)
            session.get(Channel, schedule.channel_id).timezone = zone
            schedule.publish_date = local.date()
            schedule.planned_local_time = local
            schedule.planned_beijing_time = beijing.replace(tzinfo=None)
            schedule.planned_utc_time = beijing.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            schedules.append(schedule)
        session.commit()
        scope = {"channel_id": schedules[1].channel_id} if single_channel else {}

        def ids(start, end):
            return [row["schedule_id"] for row in list_schedule_overview(
                session, publish_date_from=start, publish_date_to=end, **scope,
            )]

        assert ids(date(2026, 10, 26), date(2026, 10, 26)) == (
            [] if single_channel else [schedules[0].id]
        )
        expected = [schedules[1].id] if single_channel else [s.id for s in schedules[1:5]]
        assert ids(date(2026, 10, 27), date(2026, 10, 27)) == expected
        assert ids(None, date(2026, 10, 27)) == (
            expected if single_channel else [schedules[0].id, *expected]
        )
        assert ids(date(2026, 10, 27), None) == (
            expected if single_channel else [*expected, schedules[5].id]
        )
        # Filtering must not rewrite the channel's local scheduling date.
        assert schedules[1].publish_date == date(2026, 10, 26)
    engine.dispose()
