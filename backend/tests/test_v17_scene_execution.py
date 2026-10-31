"""Orchestration only: a tiny trusted archive avoids any model/network calls."""
from copy import deepcopy
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
import sqlalchemy as sa
from test_v14_runs import store, configure
from zhiju.database import TenantSession
from zhiju.models import ProductionNodeRun
from zhiju.models.v14 import V14Attempt

SEQUENCE = ('search', 'title', 'cover_scene', 'cover', 'description', 'community_scene', 'community', 'merge')


def scene_bundle():
    files = {
        'zhiju-workflow.json': json.dumps({'entrypoint': 'bridge.py', 'skills': ['scene-v17'],
            'nodes': SEQUENCE, 'executor_protocol': 3}),
        'scene-v17/SKILL.md': 'Scene planning protocol fixture; no creative content.',
        'bridge.py': '''import json,sys
r=json.load(sys.stdin)
if r['action']=='prepare':
 e=r['envelope']; item={'language':'ar','community_count':e['input_snapshot']['community_count']}
 result={'node_type':r['node'],'item':item,'context':{'planning_history':[]},'schema':{'type':'object'},'rules':{},'prompt':'protocol fixture'}
else: result={'issues':[],'result':r['result']}
print(json.dumps(result))
''',
    }
    stream = BytesIO()
    with ZipFile(stream, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    return stream.getvalue()


def create_scene_run(s):
    from zhiju.services import workflow_versions, v14_runs
    configure(s)
    version = workflow_versions.upload(s, 'V17', 'scene planning fixture', scene_bundle())
    workflow_versions.publish(s, version.id)
    return v14_runs.create_run(s, 'work-a', workflow_version_id=version.id)


def test_only_new_bundle_creates_eight_ordered_nodes(store):
    from zhiju.services import v14_runs as runs, production
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = create_scene_run(s)
        nodes = production._latest_nodes(s, run.work_order_id)
        assert tuple(node.node_type for node in nodes) == SEQUENCE
        assert production.summarize_node_progress(nodes)['total_nodes'] == 8
        assert tuple(runs.envelope(s, run)['node_sequence']) == SEQUENCE
    with TenantSession(store, info={'tenant_id': 'tenant-b'}) as s:
        assert tuple(node.node_type for node in production._latest_nodes(s, 'work-b')) == (
            'search', 'title', 'cover', 'description', 'community', 'merge')


def test_planner_result_survives_cover_failure_and_resume(store):
    from zhiju.services import v14_runs as runs, production
    from zhiju.schemas.v14 import AttemptSubmission
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = create_scene_run(s)
        claimed = runs.claim_run(s, 'device-a', executor_protocol=3)
        for node in ('search', 'title'):
            s.add(V14Attempt(run_id=run.id, claim_id=claimed['claim_id'], node_type=node,
                sequence=1, outcome='accepted', payload={}))
            record = production._latest_node(s, run.work_order_id, node)
            record.status = 'completed'
        production._latest_node(s, run.work_order_id, 'cover_scene').status = 'queued'
        s.commit()
        attempt = runs.begin_attempt(s, run.id, claimed['claim_id'], 'cover_scene')
        result = {'section': 'cover_scene', 'plans': [{'index': 1, 'scene': 'accepted scene decision'}]}
        runs.submit_attempt(s, run.id, attempt.id, AttemptSubmission(
            claim_id=claimed['claim_id'], outcome='accepted', result=result))
        assert production._latest_node(s, run.work_order_id, 'cover').status == 'queued'
        cover = runs.begin_attempt(s, run.id, claimed['claim_id'], 'cover')
        runs.submit_attempt(s, run.id, cover.id, AttemptSubmission(
            claim_id=claimed['claim_id'], outcome='system_error', error='offline test failure'))
        runs.resume_run(s, run.id, True)
        resumed = runs.claim_run(s, 'device-a', executor_protocol=3)
        assert resumed['accepted_results']['cover_scene'] == result
        assert 'cover' not in resumed['accepted_results']
        assert runs.begin_attempt(s, run.id, resumed['claim_id'], 'cover')
        assert len([a for a in runs.attempts(s, run) if a.node_type == 'cover_scene']) == 1


def test_old_executor_does_not_claim_new_step_workflow(store):
    from zhiju.services import v14_runs as runs
    from zhiju.services.identity import ConflictError
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = create_scene_run(s)
        with pytest.raises(ConflictError, match='执行器'):
            runs.claim_run(s, 'device-a', executor_protocol=2)
        s.refresh(run)
        assert run.status == 'queued' and run.claim_id is None


def test_executor_calls_planners_in_order_and_reuses_accepted_decisions(tmp_path):
    from zhiju.v14_executor.runner import run_once
    from zhiju.workflow_bundles import snapshot
    from test_v14_contract import envelope
    e = envelope()
    e.update(tenant_id='t1', claim_id='claim', account_profile='current', node_sequence=SEQUENCE)
    e['rules_snapshot'] = {'skill_bundle': snapshot(scene_bundle(), version_id='scene-fixture', label='V17', revision=1)}
    e['accepted_results'] = {'search': {}, 'title': {}}
    generated, begun = [], []
    class Cloud:
        def claim(self): return deepcopy(e)
        def begin(self, envelope, node):
            begun.append(node)
            return f'attempt-{node}'
        def heartbeat(self, envelope): return {'status': 'running'}
        def submit(self, envelope, attempt_id, body):
            assert body['outcome'] == 'accepted', body.get('error')
            return {'status': 'text_ready' if attempt_id == 'attempt-merge' else 'running'}
    class Model:
        account_profile = 'current'
        def generate(self, stage, model):
            generated.append(stage.node_type)
            return {'section': stage.node_type, 'plans': []}
    assert run_once(Cloud(), Model(), cache_root=tmp_path, recover=False, retry_delay=0)
    assert begun == list(SEQUENCE[2:])
    assert generated == ['cover_scene', 'cover', 'description', 'community_scene', 'community']
    # Restart after a saved planning result: do not call it a second time.
    e['accepted_results']['cover_scene'] = {'plans': [{'index': 1}]}
    generated.clear(); begun.clear()
    assert run_once(Cloud(), Model(), cache_root=tmp_path, recover=False, retry_delay=0)
    assert 'cover_scene' not in generated and begun[0] == 'cover'
    # Zero community skips both paid model calls, while accepting empty steps.
    e['input_snapshot']['community_count'] = 0
    generated.clear(); begun.clear()
    assert run_once(Cloud(), Model(), cache_root=tmp_path, recover=False, retry_delay=0)
    assert 'community_scene' not in generated and 'community' not in generated


def test_node_constraint_upgrade_preserves_old_rows_and_allows_scene_steps():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('scene_node_migration',
        Path(__file__).parents[1] / 'alembic/versions/f17a20261031_add_scene_planning_nodes.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE production_node_runs (id INTEGER PRIMARY KEY, node_type VARCHAR(20), CONSTRAINT ck_production_node_runs_valid_node_type CHECK (node_type IN ('search','title','cover','description','community','merge')))")
        conn.exec_driver_sql("INSERT INTO production_node_runs VALUES (1,'title')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.exec_driver_sql('SELECT * FROM production_node_runs').all() == [(1, 'title')]
        conn.exec_driver_sql("INSERT INTO production_node_runs VALUES (2,'cover_scene'),(3,'community_scene')")
        assert conn.exec_driver_sql('SELECT count(*) FROM production_node_runs').scalar() == 3
    # Production is MySQL; inspect its actual migration DDL without connecting.
    import io
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name='mysql', opts={'as_sql': True, 'output_buffer': buffer})
    with Operations.context(context):
        migration.upgrade()
    sql = buffer.getvalue()
    assert 'DROP CHECK ck_production_node_runs_valid_node_type' in sql
    assert "'cover_scene'" in sql and "'community_scene'" in sql
    assert 'DROP TABLE' not in sql


def test_begin_client_receives_the_planner_history_selected_by_cloud():
    from zhiju.v14_executor.client import CloudClient
    client = CloudClient('http://localhost', 'unused-test-token', 'device', 'tenant')
    context = {'creative_history': [{'run_id': 'recent'}],
               'planning_history_ids': {'cover_scene': ['recent:cover:group1']}}
    def request(method, path, body):
        assert body['node_type'] == 'cover_scene'
        return {'attempt_id': 'a1', 'planning_context': context}
    client.request = request
    data = {'run_id': 'r1', 'claim_id': 'claim', 'creative_history': []}
    assert client.begin(data, 'cover_scene') == 'a1'
    assert data['creative_history'] == context['creative_history']
    assert data['planning_history_ids'] == context['planning_history_ids']


def test_begin_api_delivers_frozen_planning_ids_without_starting_a_model(store):
    from fastapi.testclient import TestClient
    from zhiju import auth_context
    from zhiju.app import create_app
    from test_v14_api import PRINCIPAL
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = create_scene_run(s)
        from zhiju.services import v14_runs as runs, production
        claim = runs.claim_run(s, 'device-a', executor_protocol=3)
        rid, claim_id = run.id, claim['claim_id']
        for name in ('search', 'title'):
            s.add(V14Attempt(run_id=rid, claim_id=claim_id, node_type=name,
                             sequence=1, outcome='accepted', payload={}))
            production._latest_node(s, run.work_order_id, name).status = 'completed'
        production._latest_node(s, run.work_order_id, 'cover_scene').status = 'queued'
        s.commit()
    app = create_app()
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    def db():
        with TenantSession(store, info={'tenant_id': 'tenant-a', 'principal': PRINCIPAL}) as s:
            yield s
    app.dependency_overrides[auth_context.get_tenant_db] = db
    with TestClient(app) as client:
        response = client.post(f'/api/v3/v14/runs/{rid}/attempts',
                               json={'claim_id': claim_id, 'node_type': 'cover_scene'})
        assert response.status_code == 200, response.text
        assert response.json()['planning_context']['planning_history_ids'] == {'cover_scene': []}
        assert response.json()['planning_context']['creative_history'] == []
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        attempt = s.get(V14Attempt, response.json()['attempt_id'])
        assert attempt.outcome == 'running' and attempt.payload == {'history_reference_ids': []}


def test_adding_community_to_completed_zero_post_run_replans_only_community(store):
    from zhiju.services import v14_runs as runs, production
    from zhiju.services.community_requirements import update_community
    from zhiju.models import WorkOrder, OperationTask, OperationPackage
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        s.get(WorkOrder, 'work-a').community_count = 0
        s.get(OperationTask, 'task-a').community_count = 0
        s.commit()
        run = create_scene_run(s)
        run.status = 'text_ready'
        s.get(OperationPackage, run.package_id).status = 'review_pending'
        for node in SEQUENCE:
            s.add(V14Attempt(run_id=run.id, claim_id='old', node_type=node,
                sequence=1, outcome='accepted', payload={'saved': node}))
            production._latest_node(s, run.work_order_id, node).status = 'completed'
        s.commit()
        update_community(s, 'tasks', 'task-a', 1)
        current = runs.envelope(s, run)
        assert set(current['accepted_results']) == {'search', 'title', 'cover_scene', 'cover', 'description'}
        nodes = {n.node_type: n for n in production._latest_nodes(s, run.work_order_id)}
        assert nodes['cover_scene'].attempt_number == 1
        assert nodes['community_scene'].sequence_number == 6 and nodes['community_scene'].status == 'queued'
        assert nodes['community'].sequence_number == 7 and nodes['community'].status == 'pending'
        assert nodes['merge'].sequence_number == 8 and nodes['merge'].status == 'pending'
