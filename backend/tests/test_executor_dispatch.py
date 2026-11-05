import threading
from collections import deque
import pytest
from zhiju.v14_executor import dispatch


def test_mixed_modules_share_ten_local_workers_and_release_only_after_stop(tmp_path,monkeypatch):
    tasks=deque({'task_type':['operation_package','channel_analysis','channel_scheduling'][i%3],
                 'run':{'id':str(i),'claim_id':str(i)}} for i in range(22))
    lock=threading.Lock();barrier=threading.Barrier(10,timeout=5)
    active=set();finished=set();released=set();peak=0
    class Cloud:
        def claim_any(self,claim_id=None):
            with lock:
                if not tasks:return None
                task=tasks.popleft();task['run']['claim_id']=claim_id
                return task
        def transport_request(self,method,path,body):
            assert path=='/executor/releases'
            with lock:
                assert body['claim_id'] in finished
                assert body['claim_id'] not in active
                released.add(body['claim_id'])
    def handle(run):
        nonlocal peak
        id=run['claim_id'];index=int(run['id'])
        with lock:active.add(id);peak=max(peak,len(active))
        try:
            if index<10:barrier.wait()
            if index==3:raise RuntimeError('one task failed')
        finally:
            with lock:active.remove(id);finished.add(id)
    monkeypatch.setattr(dispatch.channel_analysis,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch.schedule_planning,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch,'replay_pending',lambda *a:None)
    monkeypatch.setattr(dispatch,'run_once',lambda c,m,**kw:handle(kw['envelope']))
    monkeypatch.setattr(dispatch.channel_analysis,'process_claimed',lambda c,m,cfg,root,run,stop:handle(run))
    monkeypatch.setattr(dispatch.schedule_planning,'process_claimed',lambda c,m,cfg,root,run,stop:handle(run))
    dispatch.drain(Cloud,lambda:type('Model',(),{})(),{},tmp_path)
    assert peak==10 and len(finished)==22 and released==finished
    assert not list((tmp_path/'executor-releases').glob('*.json'))


def test_lost_release_is_retried_before_claiming_more_work(tmp_path,monkeypatch):
    run={'claim_id':'claim'}
    class Offline:
        def transport_request(self,*a):raise ConnectionError('offline')
    with pytest.raises(ConnectionError):dispatch.release_claim(Offline(),tmp_path,run)
    calls=[]
    class Cloud:
        def transport_request(self,*a):calls.append('released')
        def claim_any(self,claim_id=None):assert calls==['released'];return None
    monkeypatch.setattr(dispatch.channel_analysis,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch.schedule_planning,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch,'replay_pending',lambda *a:None)
    dispatch.drain(Cloud,lambda:type('Model',(),{})(),{},tmp_path)
    assert not list((tmp_path/'executor-releases').glob('*.json'))


def test_crashed_worker_claim_is_reclaimed_but_live_cli_keeps_its_slot(tmp_path,monkeypatch):
    import json
    folder=tmp_path/'executor-active';folder.mkdir()
    for claim,owner,model in [('stopped',111,None),('live-worker',222,333),('orphan-cli',111,333)]:
        (folder/(claim+'.json')).write_text(json.dumps({'claim_id':claim,'worker_pid':owner,'model_pid':model}))
    alive={222,333};released=[];killed=[]
    monkeypatch.setattr(dispatch,'process_alive',lambda pid:pid in alive)
    monkeypatch.setattr(dispatch.os,'killpg',lambda pid,sig:(killed.append(pid),alive.discard(pid)))
    class Cloud:
        def transport_request(self,m,p,b):
            assert b['claim_id']!='live-worker'
            if b['claim_id']=='orphan-cli':assert 333 not in alive
            released.append(b['claim_id'])
        def claim_any(self,claim_id=None):return None
    monkeypatch.setattr(dispatch.channel_analysis,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch.schedule_planning,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch,'replay_pending',lambda *a:None)
    dispatch.drain(Cloud,object,{},tmp_path)
    assert set(released)=={'stopped','orphan-cli'} and killed==[333]
    assert (folder/'live-worker.json').exists()


def test_release_network_recovery_does_not_require_worker_restart(tmp_path,monkeypatch):
    tasks=deque([{'task_type':'operation_package','run':{'id':'1'}}]);finished=threading.Event()
    releases=0;claims=0
    class Cloud:
        def claim_any(self,claim_id=None):
            nonlocal claims
            claims+=1
            if tasks:
                item=tasks.popleft();item['run']['claim_id']=claim_id;return item
            if releases<2:return {'waiting_for_capacity':True}
            return None
        def transport_request(self,*a):
            nonlocal releases
            releases+=1
            if releases==1:raise ConnectionError('temporary loss of release response')
    monkeypatch.setattr(dispatch.channel_analysis,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch.schedule_planning,'recover_cached',lambda *a:None)
    monkeypatch.setattr(dispatch,'replay_pending',lambda *a:None)
    monkeypatch.setattr(dispatch,'run_once',lambda *a,**kw:finished.set())
    dispatch.drain(Cloud,lambda:type('Model',(),{})(),{},tmp_path)
    assert finished.is_set() and releases>=2 and claims>=2
    assert not list((tmp_path/'executor-releases').glob('*.json'))
