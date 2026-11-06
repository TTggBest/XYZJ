"""Exercise task delivery without models, production claims or external services."""
from copy import deepcopy
import io
import json
import sys
import threading

import pytest
import sqlalchemy as sa

from test_v14_api import client, store
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Run, V14Attempt


def claim_staged(client):
    run = client.post('/api/v3/work-orders/work-a/v14-runs').json()
    response = client.post('/api/v3/v14/claims', json={
        'host_id': 'device-a', 'executor_protocol': 5,
        'claim_id': '11111111-1111-4111-8111-111111111111'})
    assert response.status_code == 200, response.text
    return run, response.json()


def test_staged_claim_never_builds_or_transmits_full_history(client, monkeypatch):
    from zhiju.services import v14_runs
    client.post('/api/v3/work-orders/work-a/v14-runs').raise_for_status()
    monkeypatch.setattr(v14_runs, 'envelope', lambda *_: pytest.fail('claim loaded full history'))
    _, claim = claim_staged(client)
    assert claim['staged_inputs'] is True
    assert 'creative_history' not in claim and 'input_snapshot' not in claim
    assert claim['rules_snapshot']['skill_bundle']['archive']
    assert claim['accepted_nodes'] == []


def test_lost_claim_response_reuses_same_run_and_claim(client, store):
    _, first = claim_staged(client)
    again = client.post('/api/v3/v14/claims', json={
        'host_id': 'device-a', 'executor_protocol': 5, 'claim_id': first['claim_id']})
    assert again.status_code == 200
    assert again.json()['run_id'] == first['run_id']
    assert again.json()['claim_id'] == first['claim_id']
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(V14Run)) == 1


def test_stage_delivery_keeps_exact_model_request_but_not_validator_history(client, store):
    from zhiju.services import v14_runs
    from zhiju.v14_runtime.contract import build_stage_input
    _, claim = claim_staged(client)
    begin = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts", json={
        'claim_id': claim['claim_id'], 'node_type': 'search', 'executor_protocol': 5})
    assert begin.status_code == 200, begin.text
    attempt = begin.json()['attempt_id']
    # A lost begin response must not leave a second attempt or poison the claim.
    again = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts", json={
        'claim_id': claim['claim_id'], 'node_type': 'search', 'executor_protocol': 5})
    assert again.json()['attempt_id'] == attempt
    evidence = {'status': 'failed', 'reason': 'offline test', 'videos': []}
    response = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts/{attempt}/input",
                          json={'claim_id': claim['claim_id'], 'external_evidence': evidence})
    assert response.status_code == 200, response.text
    actual = response.json()
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = s.get(V14Run, claim['run_id'])
        original = v14_runs.envelope(s, run)
        expected = build_stage_input({**original, 'external_evidence': evidence}, 'search')
        assert len(v14_runs.attempts(s, run)) == 1
    for key in ('node_type', 'prompt', 'schema', 'item', 'rules'):
        assert actual[key] == getattr(expected, key)
    assert actual['context'] == {'plot_payload': expected.context['plot_payload']}
    assert 'skill_bundle' not in actual and 'creative_history' not in actual
    wrong = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts/{attempt}/input",
                        json={'claim_id': 'other'})
    assert wrong.status_code == 409
    rejected = client.put(f"/api/v3/v14/runs/{claim['run_id']}/attempts/{attempt}", json={
        'claim_id': claim['claim_id'], 'outcome': 'accepted', 'result': {'wrong': 'shape'}})
    assert rejected.status_code == 409
    assert rejected.json()['detail'].startswith('V14 验收失败: 剧情事实与智矩输入不一致')


def test_claim_network_retry_has_stable_identity(monkeypatch):
    from zhiju.v14_executor.client import CloudClient
    cloud = CloudClient('http://localhost', 'test', 'device', 'tenant')
    sent = []
    def request(method, path, body=None, **kwargs):
        if path == '/auth/me':
            return {'tenant_id': 'tenant'}
        sent.append(deepcopy(body))
        if len(sent) == 1:
            raise ConnectionError('lost response after server accepted claim')
        return {'tenant_id': 'tenant', 'run_id': 'run'}
    monkeypatch.setattr(cloud, 'request', request)
    monkeypatch.setattr('zhiju.v14_executor.client.time.sleep', lambda *_: None, raising=False)
    assert cloud.claim()['run_id'] == 'run'
    assert len(sent) == 2 and sent[0] == sent[1]
    assert sent[0]['claim_id'] and sent[0]['executor_protocol'] == 6


def test_staged_runner_uses_cloud_requests_and_preserves_server_rejection(tmp_path):
    from zhiju.v14_executor.client import CloudConflict
    from zhiju.v14_executor.runner import run_once
    calls, submissions = [], []
    class Cloud:
        def claim(self):
            return {'run_id': 'r', 'work_order_id': 'w', 'claim_id': 'c',
                    'account_profile': 'current', 'model': 'fixed', 'staged_inputs': True,
                    'rules_snapshot': {}, 'accepted_nodes': ['search'],
                    'node_sequence': ['search', 'title', 'merge']}
        def begin(self, envelope, node):
            return node
        def stage_input(self, envelope, attempt, evidence=None):
            calls.append(attempt)
            return {'node_type': attempt, 'prompt': 'unchanged instruction', 'schema': {},
                    'item': {'community_count': 0}, 'context': {}, 'rules': {}}
        def submit(self, envelope, attempt, body):
            submissions.append(deepcopy(body))
            if len(submissions) == 1:
                raise CloudConflict('V14 结构或输入不完整: invalid structure')
            return {'status': 'interrupted'}
    class Model:
        account_profile = 'current'
        def generate(self, stage, model):
            assert stage.prompt == 'unchanged instruction' and model == 'fixed'
            return {'invalid': 'server must reject'}
    assert run_once(Cloud(), Model(), cache_root=tmp_path, recover=False)
    assert calls == ['title']
    assert [body['outcome'] for body in submissions] == ['accepted', 'content_error']
    assert not list(tmp_path.rglob('pending.json'))


def test_staged_content_repair_continues_without_local_retry_history(tmp_path):
    from zhiju.v14_executor.client import CloudConflict
    from zhiju.v14_executor.runner import run_once
    requests, outcomes = [], []
    class Cloud:
        def claim(self):
            return {'run_id': 'r', 'work_order_id': 'w', 'claim_id': 'c',
                    'account_profile': 'current', 'model': 'fixed', 'staged_inputs': True,
                    'rules_snapshot': {}, 'accepted_nodes': ['search'],
                    'node_sequence': ['search', 'title', 'merge']}
        def begin(self, envelope, node):
            return node
        def stage_input(self, envelope, attempt, evidence=None):
            requests.append(attempt)
            return {'node_type': attempt,
                    'prompt': 'server feedback' if 'content_error' in outcomes else 'first request',
                    'schema': {}, 'item': {}, 'context': {}, 'rules': {}}
        def submit(self, envelope, attempt, body):
            outcomes.append(body['outcome'])
            if len(outcomes) == 1:
                raise CloudConflict('V14 验收失败: title must be revised')
            return {'status': 'text_ready' if attempt == 'merge' else 'running'}
    class Model:
        account_profile = 'current'
        calls = 0
        def generate(self, stage, model):
            self.calls += 1
            assert stage.prompt == ('first request' if self.calls == 1 else 'server feedback')
            return {'attempt': self.calls}
    model = Model()
    assert run_once(Cloud(), model, cache_root=tmp_path, recover=False)
    assert model.calls == 2
    assert requests == ['title', 'title', 'merge']
    assert outcomes == ['accepted', 'content_error', 'accepted', 'accepted']
    assert not list(tmp_path.rglob('pending.json'))


@pytest.mark.parametrize('failure', [ConnectionError, RuntimeError])
def test_one_connection_failure_does_not_cancel_other_workers(tmp_path, monkeypatch, failure):
    from zhiju.v14_executor import dispatch
    from types import SimpleNamespace
    from collections import deque
    ready=threading.Barrier(2);tasks=deque([1,2]);healthy_completed=[]
    class Cloud:
        def claim_any(self,claim_id=None):
            if not tasks:return None
            number=tasks.popleft()
            return {'task_type':'operation_package','run':{'id':number,'claim_id':claim_id}}
        def transport_request(self,*args):return {'released':True}
    def run_once(*args,stop_event,envelope,**kw):
        ready.wait(timeout=3)
        if envelope['id']==1:raise failure('one worker offline')
        assert not stop_event.is_set()
        healthy_completed.append(envelope['id'])
    monkeypatch.setattr(dispatch,'run_once',run_once)
    monkeypatch.setattr(dispatch,'replay_pending',lambda *_:None)
    monkeypatch.setattr(dispatch.channel_analysis,'recover_cached',lambda *_:None)
    monkeypatch.setattr(dispatch.schedule_planning,'recover_cached',lambda *_:None)
    dispatch.drain(Cloud,SimpleNamespace,{},tmp_path,workers=2)
    assert healthy_completed==[2]


def test_outbound_cache_contains_result_and_identity_not_full_task(tmp_path):
    from zhiju.v14_executor.runner import send_cached
    path = tmp_path / 'pending.json'
    envelope = {'run_id': 'r', 'work_order_id': 'w', 'claim_id': 'c',
                'rules_snapshot': {'archive': 'x' * 100000}, 'creative_history': ['history']}
    body = {'claim_id': 'c', 'outcome': 'accepted', 'result': {'complete': True}}
    class Offline:
        def submit(self, *args):
            raise ConnectionError('offline')
    with pytest.raises(ConnectionError):
        send_cached(Offline(), envelope, 'attempt', body, path, 0)
    saved = json.loads(path.read_text())
    assert saved['body'] == body
    assert saved['envelope'] == {k: envelope[k] for k in ('run_id', 'work_order_id', 'claim_id')}


def test_ten_workers_finish_over_http_after_one_lost_claim_response(tmp_path, monkeypatch):
    """Real urllib + threaded HTTP + executor pool, with no model invocation."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from zhiju.v14_executor import __main__ as cli
    lock = threading.Lock()
    assigned, completed = {}, []
    dropped = False
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def respond(self, value, code=200):
            data = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            self.respond({'tenant_id': 'tenant'})
        def do_POST(self):
            nonlocal dropped
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/claims'):
                with lock:
                    key = body['claim_id']
                    if key not in assigned and len(assigned) == 12:
                        self.respond(None, 204)
                        return
                    if key not in assigned:
                        assigned[key] = f'run-{len(assigned)}'
                    run_id = assigned[key]
                    if not dropped:
                        dropped = True
                        self.close_connection = True
                        return  # Server allocated the job; client lost its response.
                self.respond({'task_type':'operation_package','run':{'tenant_id': 'tenant', 'run_id': run_id, 'work_order_id': run_id,
                    'claim_id': key, 'model': 'never-called', 'account_profile': 'current',
                    'staged_inputs': True, 'node_sequence': ['merge'],
                    'accepted_nodes': [], 'rules_snapshot': {}}})
            elif self.path.endswith('/input'):
                self.respond({'node_type': 'merge', 'prompt': '', 'schema': {},
                              'item': {}, 'context': {}, 'rules': {}})
            else:
                self.respond({'attempt_id': 'merge'})
        def do_PUT(self):
            self.rfile.read(int(self.headers['Content-Length']))
            with lock:
                completed.append(self.path.split('/')[5])
            self.respond({'status': 'text_ready'})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(cli.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(sys, 'argv', ['v14', '--config-stdin', '--drain'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({
        'base_url': f'http://127.0.0.1:{server.server_port}', 'session_token': 'test',
        'host_id': 'device', 'tenant_id': 'tenant', 'cache_root': str(tmp_path)})))
    try:
        cli.main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert dropped and len(assigned) == 12
    assert sorted(completed) == sorted(assigned.values())
    assert not list(tmp_path.rglob('pending.json'))
