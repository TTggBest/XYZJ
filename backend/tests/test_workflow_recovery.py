from copy import deepcopy
from dataclasses import replace

import sqlalchemy as sa

from test_v14_api import client, PRINCIPAL
from test_v14_runs import store
from zhiju import auth_context
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Attempt, V14Run
from zhiju.workflow_bundles import BASELINE


def prepare(client, store):
    from test_v14_contract import envelope
    accepted = envelope()['accepted_results']
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, platform_role='super_admin')
    run = client.post('/api/v3/work-orders/work-a/v14-runs').json()
    version = client.post('/api/v3/workflow-versions', data={'label': 'V14'},
                          files={'file': ('skills.zip', BASELINE.read_bytes())}).json()
    client.post(f"/api/v3/workflow-versions/{version['id']}/publish").raise_for_status()
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        row = s.get(V14Run, run['run_id'])
        row.status = 'interrupted'
        row.error = 'Codex 调用失败，退出码 1'
        for node in ('search', 'title'):
            s.add(V14Attempt(run_id=row.id, claim_id='old-claim', node_type=node,
                             sequence=1, outcome='accepted', payload=accepted[node]))
        s.add(V14Attempt(run_id=row.id, claim_id='old-claim', node_type='cover',
                         sequence=1, outcome='system_error', error=row.error))
        s.commit()
        original = deepcopy(row.rules_snapshot), deepcopy(row.input_snapshot)
    return run['run_id'], version['id'], original


def test_corrected_version_is_used_on_resume_without_replacing_original_or_outputs(client, store):
    rid, version_id, original = prepare(client, store)
    response = client.post(f'/api/v3/v14/runs/{rid}/workflow-recovery', json={
        'workflow_version_id': version_id, 'stopped_confirmed': True,
        'reason': '修复历史输入重复拼接',
    })
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'interrupted'
    assert response.json()['workflow_version']['id'] == version_id
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        row = s.get(V14Run, rid)
        assert row.rules_snapshot == original[0]
        assert {k: v for k, v in row.input_snapshot.items() if k != 'workflow_recovery'} == original[1]
        assert len(list(s.scalars(sa.select(V14Attempt)))) == 3
    client.post(f'/api/v3/v14/runs/{rid}/resume', json={'stopped_confirmed': True}).raise_for_status()
    claimed = client.post('/api/v3/v14/claims', json={'host_id': 'device-a', 'executor_protocol': 2}).json()
    assert claimed['rules_snapshot']['skill_bundle']['id'] == version_id
    from test_v14_contract import envelope
    assert claimed['accepted_results'] == envelope()['accepted_results']


def test_correction_requires_stopped_process_and_interrupted_run(client, store):
    rid, version_id, _ = prepare(client, store)
    body = {'workflow_version_id': version_id, 'stopped_confirmed': False, 'reason': '历史输入修复'}
    assert client.post(f'/api/v3/v14/runs/{rid}/workflow-recovery', json=body).status_code == 409
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        s.get(V14Run, rid).status = 'running'
        s.commit()
    body['stopped_confirmed'] = True
    assert client.post(f'/api/v3/v14/runs/{rid}/workflow-recovery', json=body).status_code == 409
