from datetime import time
import pytest
from dataclasses import replace
from copy import deepcopy
from sqlalchemy import select
from test_v14_api import client, PRINCIPAL
from test_v14_runs import store
from zhiju import auth_context
from zhiju.database import TenantSession
from zhiju.models import Channel, ChannelPublishSlot, Drama, DramaProductionState, ChannelDnaVersion, WorkOrder, PublishCadenceTemplateSlot
from zhiju.models.v14 import V14Setting


def seed(store, daily_count=1):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        s.get(Channel,'channel-a').default_language='en'
        s.get(Channel,'channel-a').timezone='America/New_York'
        d=s.get(Drama,'drama-a');d.content_summary='女主遭到背叛后夺回公司。'
        s.add(DramaProductionState(drama_id='drama-a',production_completion_status='completed',
            finished_languages=['en'],total_duration_seconds=7200))
        s.add(PublishCadenceTemplateSlot(id='slot-plan',daily_publish_count=daily_count,slot_type='main',slot_number=1,
            local_video_time=time(20),engagement_offset_minutes=120))
        if daily_count == 2:
            s.add(Drama(id='drama-second', drama_number=3, drama_code='DR-second',
                chinese_title='第二部剧', normalized_title='第二部剧', content_summary=d.content_summary))
            s.add(DramaProductionState(drama_id='drama-second', production_completion_status='completed',
                finished_languages=['en'], total_duration_seconds=7200))
            s.add(PublishCadenceTemplateSlot(id='slot-plan-secondary', daily_publish_count=2,
                slot_type='aux', slot_number=2, local_video_time=time(19), engagement_offset_minutes=120))
        s.commit()


@pytest.mark.parametrize('daily_count,expected', [(1, 2), (2, 1)])
def test_http_preview_confirm_and_readback(client,store,daily_count,expected):
    seed(store,daily_count)
    response=client.post('/api/v3/channels/channel-a/schedule-plans',json={
        'start_date':'2026-11-03','end_date':'2026-11-03','daily_count':daily_count})
    assert response.status_code==200,response.text
    pid=response.json()['id']
    assert client.get('/api/v3/schedules').json()==[]
    assert client.post('/api/v3/schedule-planning/claims',json={'host_id':'wrong','executor_protocol':5}).status_code==403
    claim=client.post('/api/v3/schedule-planning/claims',json={'host_id':'device-a','executor_protocol':5})
    assert claim.status_code==200,claim.text
    result={'rows':[{'publish_date':'2026-11-03','publish_slot_id':'slot-plan','drama_id':'drama-a',
        'reason':'主线符合定位','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'单更首日建立方向'}]}
    if daily_count == 2:
        result['rows'].append({**result['rows'][0], 'publish_slot_id':'slot-plan-secondary',
                              'drama_id':'drama-second', 'pairing_reason':'辅档补充同题材'})
    body={'claim_id':claim.json()['claim_id'],'result':result}
    response=client.put(f'/api/v3/schedule-plans/{pid}/result',json=body)
    assert response.status_code==200,response.text
    assert response.json()['status']=='ready'
    assert client.get('/api/v3/schedules').json()==[]
    response=client.post(f'/api/v3/schedule-plans/{pid}/apply')
    assert response.status_code==200,response.text
    rows=client.get('/api/v3/schedules').json()
    assert len(rows)==daily_count
    assert [row['community_count'] for row in rows] == [expected] * daily_count
    rows.sort(key=lambda row: row['drama_id'] != 'drama-a')
    assert rows[0]['drama_id']=='drama-a'
    assert rows[0]['planned_beijing_time'].startswith('2026-11-04T09:00:00')
    assert client.post(f'/api/v3/schedule-plans/{pid}/apply').json()['status']=='applied'
    assert len(client.get('/api/v3/schedules').json())==daily_count
    overview=client.get('/api/v3/schedules/overview',params={
        'channel_id':'channel-a','date_from':'2026-11-04','date_to':'2026-11-04'})
    assert overview.status_code==200,overview.text
    main = next(row for row in overview.json() if row['slot_type']=='main')
    assert main['slot_local_time']=='20:00:00'
    task=client.post('/api/v3/tasks',json={'schedule_id':rows[0]['id'],'task_date':'2026-11-03',
        'idempotency_key':'planning-cadence-task'})
    assert task.status_code==201,task.text
    assert task.json()['publish_slot_id']==rows[0]['publish_slot_id']


def test_http_operator_and_tenant_boundaries(client,store):
    seed(store)
    assert client.post('/api/v3/channels/channel-b/schedule-plans',json={
        'start_date':'2026-11-03','end_date':'2026-11-03','daily_count':1}).status_code==404
    client.app.dependency_overrides[auth_context.get_current_principal]=lambda:replace(PRINCIPAL,membership_role='member')
    assert client.post('/api/v3/channels/channel-a/schedule-plans',json={
        'start_date':'2026-11-03','end_date':'2026-11-03','daily_count':1}).status_code==403


def test_production_uses_the_schedule_guidance_instead_of_new_current_spec(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        setting=s.scalar(select(V14Setting));config=deepcopy(setting.payload)
        original=config['channel_inputs']['channel-a']['generation_spec']
        dna=ChannelDnaVersion(channel_id='channel-a',version_number=1,status='archived',language='ar',
            primary_genre='频道方向',audience_summary='冷启动',reference_summary=original)
        s.add(dna);s.flush()
        s.get(WorkOrder,'work-a').channel_dna_version_id=dna.id
        config['channel_inputs']['channel-a']['generation_spec']=original+'\n新版附加指导'
        setting.payload=config;s.commit()
    response=client.post('/api/v3/work-orders/work-a/v14-runs')
    assert response.status_code==200,response.text
    envelope=client.post('/api/v3/v14/claims',json={'host_id':'device-a','executor_protocol':5})
    assert envelope.status_code==200,envelope.text
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        from zhiju.services.v14_runs import envelope as full_envelope,get_run
        assert full_envelope(s,get_run(s,envelope.json()['run_id']))['input_snapshot']['channel']['generation_spec']==original


def test_legacy_operating_reference_remains_usable_for_existing_work(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        dna=ChannelDnaVersion(channel_id='channel-a',version_number=1,status='active',language='ar',
            primary_genre='频道方向',audience_summary='冷启动',reference_summary='排期优先使用高冲突、强情绪的女频剧。')
        s.add(dna);s.flush();s.get(WorkOrder,'work-a').channel_dna_version_id=dna.id;s.commit()
    response=client.post('/api/v3/work-orders/work-a/v14-runs')
    assert response.status_code==200,response.text
