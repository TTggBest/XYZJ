from datetime import datetime, time
import pytest
from uuid import uuid4
from dataclasses import replace
from copy import deepcopy
from sqlalchemy import select
from test_v14_api import client, PRINCIPAL
from test_v14_runs import store
from zhiju import auth_context
from zhiju.database import TenantSession
from zhiju.models import Channel, ChannelPublishSlot, Drama, DramaProductionState, ChannelAnalysisReport, ChannelDnaVersion, ChannelScheduleEntry, OperationPackage, OperationTask, WorkOrder, PublishCadenceTemplateSlot
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


@pytest.mark.parametrize('entry', ['start', 'dispatch', 'previously_dispatched'])
def test_new_production_uses_current_guidance_over_archived_schedule(client, store, entry):
    from zhiju.models.v14 import V14Run
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        config = s.scalar(select(V14Setting)).payload
        original = config['channel_inputs']['channel-a']['generation_spec']
        latest = original + '\n新版附加指导'
        s.get(Channel, 'channel-a').default_language = 'ar'
        old = ChannelDnaVersion(id='old-dna', channel_id='channel-a', version_number=1,
            status='active', language='en', primary_genre='旧方向', reference_summary=original)
        publish_at = datetime(2026, 11, 9, 19)
        schedule = ChannelScheduleEntry(id='existing-schedule', channel_id='channel-a', drama_id='drama-a',
            channel_dna_version_id=old.id, publish_slot_id='existing-slot', publish_date=publish_at.date(),
            planned_local_time=publish_at, planned_beijing_time=publish_at, planned_utc_time=publish_at,
            idempotency_key='existing-schedule')
        s.add_all([old, schedule, OperationTask(id='pending-task', channel_id='channel-a', drama_id='drama-a',
            batch_id='batch-a', schedule_id=schedule.id, task_date=publish_at.date(),
            target_publish_date=publish_at.date(), source='schedule', idempotency_key='pending-task')])
        s.commit()
    if entry == 'previously_dispatched':
        response = client.post('/api/v3/tasks/pending-task/dispatch')
        assert response.status_code == 200, response.text
        work_id = response.json()['work_order']['id']

    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        s.get(ChannelDnaVersion, 'old-dna').status = 'archived'
        s.add(ChannelAnalysisReport(id='new-report', channel_id='channel-a', version_number=2,
            report_type='periodic', status='completed'))
        s.add(ChannelDnaVersion(id='new-dna', channel_id='channel-a', version_number=2,
            status='active', language='ar', primary_genre='新方向', reference_summary=latest,
            analysis_report_id='new-report'))
        s.commit()

    if entry == 'dispatch':
        response = client.post('/api/v3/tasks/pending-task/dispatch')
        assert response.status_code == 200, response.text
        work = response.json()['work_order']
        work_id = work['id']
        assert work['channel_dna_version_id'] == 'new-dna'
    if entry == 'previously_dispatched':
        response = client.post(f'/api/v3/work-orders/{work_id}/v14-runs')
    else:
        response = client.post('/api/v3/tasks/pending-task/start-v14')
    assert response.status_code == 200, response.text
    run_id = response.json()['run_id']
    work_id = response.json()['work_order_id']
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = s.get(V14Run, run_id)
        assert run.input_snapshot['channel']['generation_spec'] == latest
        assert run.input_snapshot['channel']['analysis_version']['report_id'] == 'new-report'
        assert s.get(WorkOrder, work_id).channel_dna_version_id == 'new-dna'
        assert s.get(OperationPackage, run.package_id).channel_dna_version_id == 'new-dna'
        assert s.get(ChannelScheduleEntry, 'existing-schedule').channel_dna_version_id == 'old-dna'
        s.get(ChannelDnaVersion, 'new-dna').status = 'archived'
        s.add(ChannelDnaVersion(id='later-dna', channel_id='channel-a', version_number=3,
            status='active', language='ar', primary_genre='后续方向', reference_summary=latest+'\n后续指导'))
        s.commit()
    retry = client.post('/api/v3/tasks/pending-task/start-v14')
    assert retry.status_code == 200, retry.text
    assert retry.json()['run_id'] == run_id
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert s.get(V14Run, run_id).input_snapshot['channel']['analysis_version']['dna_id'] == 'new-dna'
        assert s.get(WorkOrder, work_id).channel_dna_version_id == 'new-dna'


def test_legacy_operating_reference_remains_usable_for_existing_work(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        dna=ChannelDnaVersion(channel_id='channel-a',version_number=1,status='active',language='ar',
            primary_genre='频道方向',audience_summary='冷启动',reference_summary='排期优先使用高冲突、强情绪的女频剧。')
        s.add(dna);s.flush();s.get(WorkOrder,'work-a').channel_dna_version_id=dna.id;s.commit()
    response=client.post('/api/v3/work-orders/work-a/v14-runs')
    assert response.status_code==200,response.text


def test_explicit_slot_topics_are_frozen_and_enforced_on_the_normal_queue(client, store):
    seed(store, 2)
    path = '/api/v3/channels/channel-a/schedule-plans'
    body = {'start_date': '2026-11-03', 'end_date': '2026-11-03', 'daily_count': 2}
    topics = {'slot-plan': 'secondary', 'slot-plan-secondary': 'primary'}
    assert client.post(path, json={**body, 'slot_topics': {'slot-plan': 'secondary'}}).status_code == 409
    response = client.post(path, json={**body, 'slot_topics': topics})
    assert response.status_code == 200, response.text
    plan_id = response.json()['id']
    assert response.json()['input_snapshot']['slot_topics'] == topics

    claim_body = {'host_id': 'device-a', 'executor_protocol': 8, 'claim_id': str(uuid4())}
    assert client.post('/api/v3/executor/claims', json=claim_body).status_code == 204
    assert client.post('/api/v3/schedule-planning/claims', json=claim_body).status_code == 204
    claim_id = str(uuid4())
    claim = client.post('/api/v3/executor/claims', json={**claim_body, 'executor_protocol': 9, 'claim_id': claim_id})
    assert claim.status_code == 200, claim.text
    assert claim.json()['run']['input_snapshot']['slot_topics'] == topics

    row = {'publish_date': '2026-11-03', 'publish_slot_id': 'slot-plan', 'drama_id': 'drama-a',
           'reason': '符合频道选题方向', 'plot_evidence': '女主遭到背叛后夺回公司。', 'pairing_reason': '按档位选题'}
    aux = {**row, 'publish_slot_id': 'slot-plan-secondary', 'drama_id': None, 'reason': '缺少主题材候选'}
    path = f'/api/v3/schedule-plans/{plan_id}/result'
    submission = {'claim_id': claim_id, 'result': {'rows': [{**row, 'drama_theme': 'primary'}, aux]}}
    rejected = client.put(path, json=submission)
    assert rejected.status_code == 409 and '题材与档位要求不符' in rejected.text
    submission['result']['rows'][0]['drama_theme'] = 'secondary'
    accepted = client.put(path, json=submission)
    assert accepted.status_code == 200, accepted.text
    assert {r['status'] for r in accepted.json()['result']['rows']} == {'planned', 'blocked'}
    assert client.get('/api/v3/schedules').json() == []
    applied = client.post(f'/api/v3/schedule-plans/{plan_id}/apply')
    assert applied.status_code == 200, applied.text
    assert len(client.get('/api/v3/schedules').json()) == 1


@pytest.mark.parametrize('mode', ['initial', 'periodic'])
def test_v2_uses_applied_analysis_topics_and_allows_mixed_slots_on_first_day(client, store, mode):
    from io import BytesIO
    from zipfile import ZipFile
    from zhiju.models import ChannelAnalysisReport, ChannelAnalysisRun, ChannelScheduleEntry
    from zhiju.services import skill_catalog

    seed(store, 2)
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        channel = s.get(Channel, 'channel-a')
        s.get(Drama, 'drama-a').content_summary = '她决定解除婚约，重新选择伴侣。'
        report = ChannelAnalysisReport(channel_id=channel.id, version_number=1,
            report_type=mode, status='completed')
        s.add(report)
        s.flush()
        dna = ChannelDnaVersion(channel_id=channel.id, version_number=1, language='en',
            status='active', primary_genre='旧频道标签', analysis_report_id=report.id)
        s.add(dna)
        s.flush()
        diagnosis = (
            '~~~yaml\nchannel_strategy:\n'
            f'  channel_id: "{channel.youtube_channel_id}"\n'
            '  content_priority: ["夺回事业"]\n'
            '  content_secondary: ["婚恋抉择"]\n~~~'
        )
        s.add(ChannelAnalysisRun(channel_id=channel.id, host_id='device-a', mode=mode,
            status='applied', dna_id=dna.id, report_id=report.id, input_snapshot={},
            result={'diagnosis': diagnosis}))
        s.add(ChannelAnalysisRun(channel_id=channel.id, host_id='device-a', mode='periodic',
            status='ready', input_snapshot={}, result={'diagnosis': '未应用，不得读取'}))
        report_id = report.id
        s.commit()
        archive = BytesIO()
        with ZipFile(archive, 'w') as z:
            z.writestr('SKILL.md', '# channel-scheduling v2')
        version = skill_catalog.upload(s, skill_catalog.SCHEDULING, 'channel-scheduling', '', archive.getvalue())
        assert version['revision'] == 2
        skill_catalog.publish(s, skill_catalog.SCHEDULING, version['id'])
        skill_catalog.select_default(s, skill_catalog.SCHEDULING, version['id'])

    path = '/api/v3/channels/channel-a/schedule-plans'
    day = '2026-11-03'
    body = {'start_date': day, 'end_date': day, 'daily_count': 2}
    assert client.post(path, json=body).status_code == 409
    response = client.post(path, json={**body,
        'slot_topics': {'slot-plan': 'secondary', 'slot-plan-secondary': 'primary'}})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan['input_snapshot']['guidance']['report_id'] == report_id
    assert plan['input_snapshot']['guidance']['mode'] == mode
    assert plan['input_snapshot']['analysis_topics'] == {'primary': ['夺回事业'], 'secondary': ['婚恋抉择']}
    claim = client.post('/api/v3/schedule-planning/claims', json={'host_id': 'device-a', 'executor_protocol': 9}).json()

    base = {'publish_date': day, 'reason': '符合档期选择',
            'plot_evidence': '女主遭到背叛后夺回公司。', 'pairing_reason': '按两档各自方向编排'}
    rows = [{**base, 'publish_slot_id': 'slot-plan', 'drama_id': 'drama-a',
             'drama_theme': 'secondary', 'theme_basis': '夺回事业',
             'plot_evidence': '她决定解除婚约，重新选择伴侣。'},
            {**base, 'publish_slot_id': 'slot-plan-secondary', 'drama_id': 'drama-second',
             'drama_theme': 'primary', 'theme_basis': '夺回事业'}]
    submit = f"/api/v3/schedule-plans/{plan['id']}/result"
    body = {'claim_id': claim['claim_id'], 'result': {'rows': rows}}
    assert client.put(submit, json=body).status_code == 409
    rows[0]['theme_basis'] = '婚恋抉择'
    accepted = client.put(submit, json=body)
    assert accepted.status_code == 200, accepted.text
    response = client.post(f"/api/v3/schedule-plans/{plan['id']}/apply")
    assert response.status_code == 200, response.text
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        schedules = s.scalars(select(ChannelScheduleEntry)).all()
        assert len(schedules) == 2
        assert all(row.channel_dna_version_id == plan['input_snapshot']['guidance']['dna_id'] for row in schedules)
