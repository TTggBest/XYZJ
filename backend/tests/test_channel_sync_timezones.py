"""Channel sync must preserve the timezone chosen for each audience."""
import pytest
from sqlalchemy import select
from test_v14_runs import store
from zhiju.database import TenantSession
from zhiju.models import Channel, ChannelPublishSlot
from zhiju.services import feishu_sync
from datetime import time


@pytest.mark.parametrize('existing_timezone', ['America/Los_Angeles', 'America/New_York', None])
def test_channel_sync_preserves_existing_timezone_and_defaults_new_channels(monkeypatch, store, existing_timezone):
    name = 'Timezone contract channel'
    external_id = 'UC-TIMEZONE-CONTRACT'
    master = [{'频道名': name, '语言': '英语', '申请成功日期': '2026/10/01'}]
    info = [{'频道名': name, '频道地址': f'https://www.youtube.com/channel/{external_id}'}]
    branding = [{'频道名': name}]
    monkeypatch.setattr(feishu_sync, '_client_rows', lambda *_: next(source_rows))
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        if existing_timezone:
            channel = Channel(youtube_channel_id=external_id, original_name=name, timezone=existing_timezone)
            session.add(channel)
            session.flush()
            session.add(ChannelPublishSlot(channel_id=channel.id, slot_type='aux', slot_number=1,
                timezone=existing_timezone, local_time=time(10), status='active'))
            session.commit()
        for _ in range(2):
            source_rows = iter([master, info, branding])
            feishu_sync.sync_channels(session)
            session.expire_all()
            channel = session.scalar(select(Channel).where(Channel.youtube_channel_id == external_id))
            assert channel.timezone == (existing_timezone or 'America/New_York')
            if existing_timezone:
                slot = session.scalar(select(ChannelPublishSlot).where(ChannelPublishSlot.channel_id == channel.id))
                assert slot.timezone == channel.timezone
                assert slot.local_time == time(10)
