from datetime import datetime,timedelta,timezone
from uuid import uuid4
from sqlalchemy import select
from test_v14_api import client,store
from zhiju.database import TenantSession
from zhiju.models import Channel,ChannelAnalysisRun,ChannelSchedulePlan,ExecutorClaim
from zhiju.models.v14 import V14Run
from zhiju.services.executor_queue import counts,release,admission


def seed(client,store):
    response=client.post('/api/v3/work-orders/work-a/v14-runs')
    assert response.status_code==200,response.text
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        base=datetime(2026,11,5,tzinfo=timezone.utc)
        operation=s.scalar(select(V14Run));operation.created_at=base;operation.updated_at=base
        s.add(ChannelAnalysisRun(channel_id='channel-a',host_id='device-a',mode='initial',status='queued',phase='analysis',
            input_snapshot={},materials=[],attempts=[],created_at=base-timedelta(days=5),updated_at=base+timedelta(seconds=1)))
        for i in range(10):
            s.add(ChannelSchedulePlan(channel_id='channel-a',host_id='device-a',status='queued',
                input_snapshot={},created_at=base+timedelta(seconds=i+2),updated_at=base+timedelta(seconds=i+2)))
        s.commit()


def claim(client,id=None):
    response=client.post('/api/v3/executor/claims',json={'host_id':'device-a','claim_id':id or str(uuid4()),'executor_protocol':5})
    assert response.status_code==200,response.text
    return response.json()


def test_mixed_modules_share_ten_slots_and_keep_fifo_idempotence(client,store):
    seed(client,store)
    request=str(uuid4());first=claim(client,request)
    assert first['task_type']=='operation_package'
    assert claim(client,request)['run']['run_id']==first['run']['run_id']
    second=claim(client);assert second['task_type']=='channel_analysis'
    rest=[claim(client) for _ in range(8)]
    assert all(r['task_type']=='channel_scheduling' for r in rest)
    assert claim(client)['waiting_for_capacity'] is True
    stats=client.get('/api/v3/executor/queue').json()
    assert stats['running']==10 and stats['queued']==2
    assert stats['types']['operation_package']['running']==1
    assert stats['types']['channel_analysis']['running']==1
    # A lost reply can recover the original claim even while all slots are occupied.
    assert claim(client,request)['run']['run_id']==first['run']['run_id']


def test_cancel_does_not_free_capacity_until_cli_confirms_stop(client,store):
    seed(client,store);items=[claim(client) for _ in range(10)]
    plan=items[-1]['run']
    assert client.post(f"/api/v3/schedule-plans/{plan['id']}/cancel").status_code==200
    assert claim(client)['waiting_for_capacity']
    assert client.post('/api/v3/executor/releases',json={'claim_id':plan['claim_id']}).status_code==200
    assert client.get('/api/v3/executor/queue').json()['running']==9
    next=claim(client)
    assert next['task_type']=='channel_scheduling' and next['run']['id']!=plan['id']
    client.post('/api/v3/executor/releases',json={'claim_id':plan['claim_id']})
    assert client.get('/api/v3/executor/queue').json()['running']==10


def test_legacy_claim_paths_cannot_bypass_shared_cap_and_tenant_scope(client,store):
    seed(client,store);[claim(client) for _ in range(10)]
    assert client.post('/api/v3/schedule-planning/claims',json={'host_id':'device-a','executor_protocol':5}).status_code==204
    assert client.post('/api/v3/channel-analysis/claims',json={'host_id':'device-a','executor_protocol':5}).status_code==204
    assert client.post('/api/v3/v14/claims',json={'host_id':'device-a','executor_protocol':5}).status_code==204
    with TenantSession(store,info={'tenant_id':'tenant-b'}) as s:
        assert counts(s)['running']==0
        held=s.scalar(select(ExecutorClaim));assert held is None
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        held=s.scalar(select(ExecutorClaim))
        release(s,'wrong-host',held.claim_id)
        assert counts(s)['running']==10


def test_confirmed_stopped_resume_reclaims_cancelled_claim_even_after_id_cleared(client,store):
    seed(client,store);items=[claim(client) for _ in range(10)]
    plan=items[-1]['run']
    assert client.post(f"/api/v3/schedule-plans/{plan['id']}/cancel").status_code==200
    from zhiju.services.schedule_planning import resume_plan
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        resume_plan(s,plan['id'],stopped_confirmed=True)
        assert counts(s)['running']==9
    assert claim(client)['task_type']=='channel_scheduling'


def test_old_executors_are_rejected_before_they_can_strand_capacity(client,store):
    seed(client,store)
    for path in ['v14/claims','channel-analysis/claims','schedule-planning/claims','executor/claims']:
        response=client.post('/api/v3/'+path,json={'host_id':'device-a','executor_protocol':4,'claim_id':str(uuid4())})
        assert response.status_code==409,response.text
        assert '更新' in response.json()['detail']
    assert client.get('/api/v3/executor/queue').json()['running']==0
    assert claim(client)['task_type']=='operation_package'
