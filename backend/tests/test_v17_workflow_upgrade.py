from copy import deepcopy
from dataclasses import replace

import pytest
from test_v14_api import client, PRINCIPAL
from test_v14_runs import store, configure
from test_v14_contract import envelope
from test_v17_scene_execution import scene_bundle, SEQUENCE
from zhiju import auth_context
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Run, V14Attempt
from zhiju.services import v14_runs as runs, workflow_versions as versions, production
from zhiju.workflow_bundles import BASELINE


def prepare(client, store, corrected=False):
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, platform_role='super_admin')
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        configure(s)
        old = versions.upload(s, 'V16', 'legacy', BASELINE.read_bytes())
        versions.publish(s, old.id)
        run = runs.create_run(s, 'work-a', workflow_version_id=old.id)
        run.status, run.error = 'interrupted', 'Codex 退出码 1'
        for node, payload in envelope()['accepted_results'].items():
            s.add(V14Attempt(run_id=run.id, claim_id='old', node_type=node,
                             sequence=1, outcome='accepted', payload=payload))
            production._latest_node(s, run.work_order_id, node).status = 'completed'
        s.add(V14Attempt(run_id=run.id, claim_id='old', node_type='cover',
                         sequence=1, outcome='system_error', error=run.error))
        cover = production._latest_node(s, run.work_order_id, 'cover')
        cover.status, cover.worker_key = 'running', 'device-a'
        if corrected:
            previous = versions.upload(s, 'V16', 'input fix', BASELINE.read_bytes())
            versions.publish(s, previous.id)
            run.input_snapshot = {**run.input_snapshot, 'workflow_recovery': {
                'version': {'id': previous.id, 'label': 'V16', 'revision': previous.revision},
                'reason': 'previous input fix', 'corrected_at': '2026-10-31T10:00:00Z'}}
        target = versions.upload(s, 'V17', 'planning', scene_bundle())
        versions.publish(s, target.id)
        s.commit()
        return run.id, target.id, deepcopy(run.input_snapshot), deepcopy(run.rules_snapshot)


@pytest.mark.parametrize('corrected', [False, True])
def test_upgrade_keeps_results_and_previous_correction_and_resumes_at_planning(client, store, corrected):
    rid, vid, original_input, original_rules = prepare(client, store, corrected)
    body = {'workflow_version_id': vid, 'stopped_confirmed': True, 'reason': '3号切换V17'}
    url = f'/api/v3/v14/runs/{rid}/workflow-upgrade'
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['workflow_version']['id'] == vid
    assert response.json()['status'] == 'interrupted'
    assert client.post(url, json=body).status_code == 200
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = s.get(V14Run, rid)
        assert run.rules_snapshot == original_rules
        assert {k: v for k, v in run.input_snapshot.items() if k != 'workflow_recovery'} == {
            k: v for k, v in original_input.items() if k != 'workflow_recovery'}
        assert run.input_snapshot['workflow_recovery'].get('previous') == original_input.get('workflow_recovery')
        nodes = production._latest_nodes(s, run.work_order_id)
        assert tuple(n.node_type for n in nodes) == SEQUENCE
        assert nodes[2].status == 'queued' and nodes[3].status == 'pending'
        assert len(runs.attempts(s, run)) == 3
        assert runs.envelope(s, run)['accepted_results'] == envelope()['accepted_results']
    client.post(f'/api/v3/v14/runs/{rid}/resume', json={'stopped_confirmed': True}).raise_for_status()
    assert client.post('/api/v3/v14/claims', json={'host_id': 'device-a', 'executor_protocol': 2}).status_code == 409
    claim = client.post('/api/v3/v14/claims', json={'host_id': 'device-a', 'executor_protocol': 3}).json()
    assert claim['node_sequence'] == list(SEQUENCE)
    response = client.post(f'/api/v3/v14/runs/{rid}/attempts',
                           json={'claim_id': claim['claim_id'], 'node_type': 'cover_scene'})
    assert response.status_code == 200, response.text
    assert 'planning_context' in response.json()


def test_upgrade_rejects_active_run_and_missing_stop_confirmation(client, store):
    rid, vid, _, _ = prepare(client, store)
    url = f'/api/v3/v14/runs/{rid}/workflow-upgrade'
    body = {'workflow_version_id': vid, 'stopped_confirmed': False, 'reason': 'V17'}
    assert client.post(url, json=body).status_code == 409
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        s.get(V14Run, rid).status = 'running'
        s.commit()
    body['stopped_confirmed'] = True
    assert client.post(url, json=body).status_code == 409


def test_deferred_batch_upgrade_can_roll_back_nodes_and_metadata_together(client, store):
    rid, vid, original, _ = prepare(client, store)
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        runs.upgrade_workflow(s, rid, vid, True, 'batch preflight', commit=False)
        s.rollback()
        run = s.get(V14Run, rid)
        assert run.input_snapshot == original
        assert len(production._latest_nodes(s, run.work_order_id)) == 6


def test_manual_scene_retry_after_upgrade_uses_the_effective_v17_order(client, store):
    rid, vid, _, _ = prepare(client, store)
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        runs.upgrade_workflow(s, rid, vid, True, 'V17')
        run = s.get(V14Run, rid)
        for number in range(1, 4):
            s.add(V14Attempt(run_id=rid, claim_id='old-scene', node_type='cover_scene',
                             sequence=number, outcome='content_error', error='scene review failed'))
        run.status = 'needs_user_review'
        s.commit()
        runs.resume_run(s, rid, True, retry_content=True)
        assert run.input_snapshot['manual_content_retry_after'] == {'cover_scene': 3}


def test_zero_community_supplement_after_upgrade_keeps_cover_planning(client, store):
    from zhiju.models import WorkOrder, OperationTask, OperationPackage
    from zhiju.services.community_requirements import update_community
    rid, vid, _, _ = prepare(client, store)
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        runs.upgrade_workflow(s, rid, vid, True, 'V17')
        run = s.get(V14Run, rid)
        run.input_snapshot = {**run.input_snapshot, 'community_count': 0}
        run.status = 'text_ready'
        s.get(WorkOrder, run.work_order_id).community_count = 0
        s.get(OperationTask, 'task-a').community_count = 0
        s.get(OperationPackage, run.package_id).status = 'review_pending'
        for node in SEQUENCE[2:]:
            s.add(V14Attempt(run_id=rid, claim_id='v17', node_type=node,
                             sequence=2, outcome='accepted', payload={'saved': node}))
            production._latest_node(s, run.work_order_id, node).status = 'completed'
        s.commit()
        update_community(s, 'tasks', 'task-a', 1)
        nodes = {n.node_type: n for n in production._latest_nodes(s, run.work_order_id)}
        assert nodes['community_scene'].status == 'queued' and nodes['community_scene'].attempt_number == 2
        assert nodes['community'].status == 'pending' and nodes['merge'].status == 'pending'
        assert nodes['cover_scene'].attempt_number == 1
