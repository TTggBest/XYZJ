"""Bounded channel concurrency without live API/model calls."""
from collections import deque
from threading import Event,Lock,Thread
import time
from types import SimpleNamespace
from zhiju.v14_executor import channel_analysis as analysis


class Queue:
    def __init__(self,runs):self.runs=deque(runs);self.lock=Lock();self.claimed=[]
    def client(self):
        queue=self
        class Client:
            tenant_id='tenant';host_id='host'
            def request(self,method,path,body=None):
                if path=='/auth/me':return {'tenant_id':'tenant'}
                if path=='/channel-analysis/claims':
                    with queue.lock:
                        if not queue.runs:return None
                        run=queue.runs.popleft();queue.claimed.append(run['id']);return run
                raise AssertionError(path)
        return Client()
    def add(self,run):
        with self.lock:self.runs.append(run)


def run(id):return {'id':str(id),'tenant_id':'tenant','claim_id':'claim-'+str(id)}


def eventually(predicate):
    deadline=time.monotonic()+3
    while not predicate():
        if time.monotonic()>deadline:raise AssertionError('expected worker state not reached')
        Event().wait(.01)


def start(queue,tmp_path,errors):
    def work():
        try:analysis.drain_parallel(queue.client,lambda:SimpleNamespace(),{},tmp_path,workers=10,poll_interval=.01)
        except BaseException as exc:errors.append(exc)
    thread=Thread(target=work,daemon=True);thread.start();return thread


def test_ten_channels_run_together_and_eleventh_waits_for_capacity(tmp_path,monkeypatch):
    queue=Queue([run(i) for i in range(11)]);gates={str(i):Event() for i in range(11)}
    active=set();models=[];clients=[];started=[];lock=Lock();maximum=[0];errors=[]
    def process(client,model,config,root,item,stop_event=None):
        with lock:
            active.add(item['id']);started.append(item['id']);models.append(model);clients.append(client);maximum[0]=max(maximum[0],len(active))
        assert gates[item['id']].wait(4)
        with lock:active.remove(item['id'])
    monkeypatch.setattr(analysis,'process_claimed',process)
    thread=start(queue,tmp_path,errors)
    try:
        eventually(lambda:len(started)==10)
        assert len(queue.claimed)==10 and maximum[0]==10
        assert len({id(model) for model in models})==10 and len({id(client) for client in clients})==10
        gates['0'].set();eventually(lambda:'10' in started)
        assert maximum[0]==10
    finally:
        for gate in gates.values():gate.set()
        thread.join(4)
    assert not thread.is_alive() and not errors
    assert len(queue.claimed)==len(set(queue.claimed))==11


def test_new_channel_starts_while_existing_long_analysis_is_running(tmp_path,monkeypatch):
    queue=Queue([run('first')]);first=Event();second=Event();release=Event();errors=[]
    def process(client,model,config,root,item,stop_event=None):
        if item['id']=='first':first.set();assert release.wait(4)
        else:second.set()
    monkeypatch.setattr(analysis,'process_claimed',process)
    thread=start(queue,tmp_path,errors)
    try:
        assert first.wait(3);queue.add(run('later'))
        assert second.wait(3), 'idle capacity must accept channels added during another analysis'
        assert thread.is_alive()
    finally:release.set();thread.join(4)
    assert not thread.is_alive() and not errors


def test_recovery_runs_once_before_any_parallel_claim(tmp_path,monkeypatch):
    queue=Queue([run('a'),run('b')]);events=[]
    monkeypatch.setattr(analysis,'recover_cached',lambda *args:events.append('recover'))
    monkeypatch.setattr(analysis,'process_claimed',lambda *args:events.append('process'))
    analysis.drain_parallel(queue.client,lambda:SimpleNamespace(),{},tmp_path,poll_interval=.01)
    assert events[0]=='recover' and events.count('recover')==1 and events.count('process')==2


def test_expired_authorization_stops_other_active_channels(tmp_path,monkeypatch):
    import pytest
    queue=Queue([run('bad'),run('other')]);other_started=Event();other_stopped=Event()
    def process(client,model,config,root,item,stop_event=None):
        if item['id']=='bad':
            assert other_started.wait(3);raise PermissionError('expired')
        other_started.set();assert stop_event.wait(3);other_stopped.set()
    monkeypatch.setattr(analysis,'process_claimed',process)
    with pytest.raises(PermissionError,match='expired'):
        analysis.drain_parallel(queue.client,lambda:SimpleNamespace(),{},tmp_path,poll_interval=.01)
    assert other_stopped.is_set()


def test_model_failure_or_cancellation_is_confined_to_its_channel(tmp_path,monkeypatch):
    import copy
    from zhiju.v14_executor.client import CloudConflict
    for cancelled in (False,True):
        queue=Queue([run('bad'),run('good')]);submitted={};bad_finished=Event();models={}
        runs={id:dict(run(id),mode='initial',status='running',materials=[],input_snapshot={'model':'test','account_profile':'current'}) for id in ('bad','good')}
        queue=Queue(list(runs.values()))
        original_factory=queue.client
        def factory():
            base=original_factory()
            class Client:
                tenant_id='tenant';host_id='host'
                def request(self,method,path,body=None,**kwargs):
                    if path in ('/auth/me','/channel-analysis/claims'):return base.request(method,path,body)
                    id=path.split('/')[2]
                    if method=='GET':return dict(runs[id],status='cancelled',claim_id=None)
                    if path.endswith('/heartbeat'):
                        if cancelled and id=='bad':raise CloudConflict('cancelled')
                        return {}
                    if path.endswith('/collect'):return copy.deepcopy(runs[id])
                    if path.endswith('/result'):
                        if cancelled and id=='bad':bad_finished.set();raise CloudConflict('cancelled')
                        status='failed' if body.get('error') else 'ready';submitted[id]=status
                        if id=='bad':bad_finished.set()
                        return dict(runs[id],status=status,result=body.get('result'))
                    raise AssertionError(path)
            return Client()
        def generate(model,item,root,progress=None):
            models[item['id']]=model
            if item['id']=='bad':raise RuntimeError('only this model timed out')
            assert bad_finished.wait(3)
            assert not model.cancelled()
            return {'normalized_snapshot':'{}','profile':'profile','diagnosis':'diagnosis','generation_spec':'spec'}
        monkeypatch.setattr(analysis,'generate_documents',generate)
        monkeypatch.setattr(analysis,'bind_analysis_result',lambda result,item:result)
        analysis.drain_parallel(factory,lambda:SimpleNamespace(account_profile='current'),{},tmp_path/str(cancelled),poll_interval=.01)
        assert submitted['good']=='ready'
        if not cancelled:
            assert submitted['bad']=='failed' and models['bad'] is not models['good']
        else:assert not (tmp_path/str(cancelled)/'bad').exists()


def test_cli_selects_parallel_analysis_but_once_remains_single(tmp_path,monkeypatch):
    import json,sys
    from zhiju.v14_executor.__main__ import main
    config=tmp_path/'config.json';config.write_text(json.dumps({'task_type':'channel_analysis','tenant_id':'tenant','host_id':'host','base_url':'https://fixture','session_token':'fixture'}))
    calls=[]
    monkeypatch.setattr(analysis,'drain_parallel',lambda *args,**kwargs:calls.append(('parallel',kwargs['workers'])))
    monkeypatch.setattr(analysis,'drain',lambda *args,**kwargs:calls.append(('once',kwargs['once'])))
    monkeypatch.setattr(sys,'argv',['executor','--config',str(config),'--drain']);main()
    monkeypatch.setattr(sys,'argv',['executor','--config',str(config),'--once']);main()
    assert calls==[('parallel',10),('once',True)]


def test_interrupt_stops_active_workers_before_waiting_for_shutdown(tmp_path,monkeypatch):
    import pytest
    queue=Queue([run('active')]);started=Event();stopped=Event()
    def process(client,model,config,root,item,stop_event=None):
        started.set();assert stop_event.wait(3);stopped.set()
    def interrupt(*args,**kwargs):
        assert started.wait(3);raise KeyboardInterrupt()
    monkeypatch.setattr(analysis,'process_claimed',process)
    monkeypatch.setattr(analysis,'wait',interrupt)
    with pytest.raises(KeyboardInterrupt):analysis.drain_parallel(queue.client,lambda:SimpleNamespace(),{},tmp_path,poll_interval=.01)
    assert stopped.is_set()
