from datetime import date, datetime, time
import pytest

from test_v14_runs import store
from zhiju.database import TenantSession
from zhiju.models import Channel, ChannelPublishSlot, OperationTask, PublishCadenceTemplateSlot, ProductionNodeRun
from zhiju.schemas.production import CommunityBatchWrite
from zhiju.services.package_outputs import write_community, list_package_operation_overview


@pytest.mark.parametrize("imported", [False, True])
def test_community_uses_actual_video_slot_and_overview_exposes_unambiguous_utc(store, imported):
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        channel = s.get(Channel, "channel-a")
        channel.timezone, channel.daily_publish_count = "America/New_York", 2
        s.add(ChannelPublishSlot(id="slot-a", channel_id=channel.id, slot_number=1,
            slot_type="aux", local_time=time(13), timezone=channel.timezone, status="archived"))
        s.add(PublishCadenceTemplateSlot(daily_publish_count=2, slot_number=1,
            slot_type="aux", local_video_time=time(10), engagement_offset_minutes=120))
        task = s.get(OperationTask, "task-a")
        task.publish_slot_id, task.target_publish_date = "slot-a", date(2026, 10, 26)
        if imported:
            from zhiju.models import ChannelScheduleEntry, OperationPackage
            channel.daily_publish_count = 0
            for number, local, utc, beijing in [
                (1, datetime(2026,10,26,13), datetime(2026,10,26,17), datetime(2026,10,27,1)),
                (2, datetime(2026,10,26,21), datetime(2026,10,27,1), datetime(2026,10,27,9))]:
                s.add(ChannelScheduleEntry(id=f"schedule-{number}", channel_id=channel.id,
                    drama_id="drama-a", publish_slot_id=f"historical-{number}", publish_date=date(2026,10,26),
                    planned_local_time=local, planned_utc_time=utc, planned_beijing_time=beijing,
                    source_type="feishu", idempotency_key=f"schedule-{number}"))
            task.schedule_id = "schedule-1"
            s.get(OperationPackage, "package-a").schedule_id = "schedule-1"
        from sqlalchemy import select
        node = s.scalar(select(ProductionNodeRun).where(ProductionNodeRun.node_type == "community"))
        node.status = "running"
        s.commit()
        write_community(s, "package-a", CommunityBatchWrite(posts=[{
            "sequence_number": 1, "language": "en", "localized_text": "Keep this copy"}]))
        item = list_package_operation_overview(s)[0]
        assert item["channel_timezone"] == "America/New_York"
        assert item["planned_utc_time"].isoformat() == "2026-10-26T17:00:00+00:00"
        assert item["community_posts"][0]["planned_utc_time"].isoformat() == "2026-10-26T19:00:00+00:00"
        assert item["community_posts"][0]["localized_text"] == "Keep this copy"
