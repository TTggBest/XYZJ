import json
import time
from datetime import datetime,timedelta,timezone

import pytest
from test_v14_api import client,start
from test_v14_runs import store
from test_v14_launcher import manager,config
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Run


@pytest.mark.parametrize('local_state,expected,recovered',[
    ('active','running',False),('unknown','heartbeat_delayed',False),('stopped','queued',True)])
def test_bound_executor_checks_before_recovering_silent_claim(client,store,local_state,expected,recovered):
    _,claim=start(client)
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        s.get(V14Run,claim['run_id']).heartbeat_at=datetime.now(timezone.utc)-timedelta(seconds=151)
        s.commit()
    response=client.post(f"/api/v3/v14/runs/{claim['run_id']}/connection-check",json={
        'claim_id':claim['claim_id'],'local_state':local_state})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['status']==expected and result['recovered'] is recovered
    if recovered:
        assert result['claim_id'] is None
        again=client.post(f"/api/v3/v14/runs/{claim['run_id']}/connection-check",json={
            'claim_id':claim['claim_id'],'local_state':'stopped'})
        assert again.json()['recovered'] is False


def test_probe_does_not_recover_fresh_or_cancelled_claim(client):
    _,claim=start(client)
    url=f"/api/v3/v14/runs/{claim['run_id']}/connection-check"
    body={'claim_id':claim['claim_id'],'local_state':'stopped'}
    assert client.post(url,json=body).json()['recovered'] is False
    client.post(f"/api/v3/v14/runs/{claim['run_id']}/cancel")
    assert client.post(url,json=body).json()['status']=='cancelled'
    assert client.post(url,json=body).json()['recovered'] is False


@pytest.mark.parametrize('worker_alive,model_alive',[(True,False),(False,True),(False,False)])
def test_local_probe_checks_worker_and_model_processes(manager,tmp_path,monkeypatch,worker_alive,model_alive):
    from zhiju.v14_executor import launcher
    manager.settings['cache_root']=str(tmp_path/'cache')
    root=tmp_path/'cache/tenant-a/host-a/run-a';root.mkdir(parents=True)
    record={'run_id':'run-a','work_order_id':'work-a','claim_id':'claim-a','worker_pid':11,
        'model_pid':22,'finished':False,'last_heartbeat':time.time()-151}
    (root/'execution.json').write_text(json.dumps(record))
    monkeypatch.setattr(launcher,'process_alive',lambda pid:{11:worker_alive,22:model_alive}.get(pid,False))
    calls=[];starts=[]
    class Cloud:
        def __init__(self,*a):pass
        def request(self,method,path,body):
            calls.append(body)
            active=body['local_state']=='active'
            return {'status':'running' if active else 'queued','claim_id':'claim-a' if active else None,'recovered':not active}
    monkeypatch.setattr(launcher,'CloudClient',Cloud)
    monkeypatch.setattr(manager,'start',lambda cfg:starts.append(cfg))
    manager.check_connections(config(),11)
    assert calls==[{'claim_id':'claim-a','local_state':'active' if worker_alive or model_alive else 'stopped'}]
    assert len(starts)==(0 if worker_alive or model_alive else 1)


def test_recovery_replays_pending_result_before_requeue(manager,tmp_path,monkeypatch):
    from zhiju.v14_executor import launcher
    manager.settings['cache_root']=str(tmp_path/'cache')
    root=tmp_path/'cache/tenant-a/host-a/run-a';root.mkdir(parents=True)
    record={'run_id':'run-a','work_order_id':'work-a','claim_id':'claim-a','worker_pid':11,
        'model_pid':None,'finished':False,'last_heartbeat':time.time()-151}
    (root/'execution.json').write_text(json.dumps(record))
    (root/'pending.json').write_text(json.dumps({'envelope':record,'attempt_id':'attempt-a','body':{'result':{'keep':'generated'}}}))
    monkeypatch.setattr(launcher,'process_alive',lambda pid:False)
    calls=[]
    class Cloud:
        def __init__(self,*a):pass
        def current(self,*a):return {'status':'heartbeat_delayed','claim_id':'claim-a'}
        def submit(self,envelope,attempt,body):
            calls.append('submit');assert body['result']=={'keep':'generated'}
            return {'status':'running'}
        def request(self,*a):calls.append('check');return {'status':'queued','claim_id':None,'recovered':True}
    monkeypatch.setattr(launcher,'CloudClient',Cloud)
    monkeypatch.setattr(manager,'start',lambda cfg:calls.append('start'))
    manager.check_connections(config(),11)
    assert calls==['submit','check','start']
    assert not (root/'pending.json').exists()


def test_unreachable_probe_never_requeues_work(manager,tmp_path,monkeypatch):
    from zhiju.v14_executor import launcher
    manager.settings['cache_root']=str(tmp_path/'cache')
    root=tmp_path/'cache/tenant-a/host-a/run-a';root.mkdir(parents=True)
    record={'run_id':'run-a','claim_id':'claim-a','worker_pid':11,'model_pid':None,
        'finished':False,'last_heartbeat':time.time()-151}
    path=root/'execution.json';path.write_text(json.dumps(record))
    monkeypatch.setattr(launcher,'process_alive',lambda pid:False)
    starts=[]
    class Cloud:
        def __init__(self,*a):pass
        def request(self,*a):raise ConnectionError('temporarily unavailable')
    monkeypatch.setattr(launcher,'CloudClient',Cloud)
    monkeypatch.setattr(manager,'start',lambda cfg:starts.append(cfg))
    with pytest.raises(ConnectionError):manager.check_connections(config(),11)
    assert starts==[]
    assert json.loads(path.read_text())['finished'] is False
