"""New work orders inherit the general repair while old runs retain snapshots."""
from copy import deepcopy
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_v14_api import client, store
from test_v21_creative_queue import clone
from zhiju.database import TenantSession
from zhiju.models import Drama, OperationTask
from zhiju.models.v14 import V14Run, WorkflowSkillVersion
from zhiju.services import workflow_versions


def test_new_task_default_flows_into_real_stage_input_without_rewriting_old_run(client, store):
    path = Path(os.environ.get('ZHJ_V21_R3_ARCHIVE',
        Path(__file__).resolve().parents[4] / 'outputs/交接/运营包-V21-r3/V21-修订3-封面场景-Skill草稿.zip'))
    if not path.is_file():
        pytest.skip('Set ZHJ_V21_R3_ARCHIVE to the V21 r3 package')
    old = client.post('/api/v3/tasks/task-a/start-v14').raise_for_status().json()
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        previous = deepcopy(s.get(V14Run, old['run_id']).rules_snapshot)
        previous_input = deepcopy(s.get(V14Run, old['run_id']).input_snapshot)
        drama = s.get(Drama, 'drama-a')
        s.add(clone(drama, id='new-drama', drama_code='NEW', drama_number=99,
            chinese_title='独立新剧', normalized_title='独立新剧', source_language='zh',
            content_summary='女飞行员在暴雨中救援乘客。', plot_archive='女机长识破冒领功劳并完成紧急备降。',
            plot_pattern='逆袭、女性成长', core_personas='女机长、同事'))
        task = s.get(OperationTask, 'task-a')
        s.add(clone(task, id='new-task', drama_id='new-drama', status='pending_dispatch',
                    schedule_id=None, idempotency_key='new-unique-task'))
        s.add(WorkflowSkillVersion(id='new-r3', label='V21', revision=3,
                                  status='published', archive=path.read_bytes()))
        s.commit()
        workflow_versions.select_default(s, 'new-r3')
    new = client.post('/api/v3/tasks/new-task/start-v14').raise_for_status().json()
    claims = [client.post('/api/v3/executor/claims', json={
        'host_id': 'device-a', 'claim_id': str(uuid4()), 'executor_protocol': 13
    }).raise_for_status().json()['run'] for _ in range(2)]
    claim = next(row for row in claims if row['run_id'] == new['run_id'])
    assert claim['rules_snapshot']['skill_bundle']['revision'] == 3
    base = f"/api/v3/v14/runs/{claim['run_id']}/attempts"
    identity = {'claim_id': claim['claim_id']}

    def begin(node):
        id = client.post(base, json={**identity, 'node_type': node,
            'executor_protocol': 13}).raise_for_status().json()['attempt_id']
        url = base+'/'+id
        stage = client.post(url+'/input', json=identity).raise_for_status().json()
        return url, stage

    url, find = begin('search')
    found = {'plot_payload': find['context']['plot_payload'], 'external_evidence': {'titles': []}}
    client.put(url, json={**identity, 'outcome': 'accepted', 'result': found}).raise_for_status()
    _, title = begin('title')
    creative = title['rules']['title_creation']['prompt']
    assert '女机长识破冒领功劳并完成紧急备降。' in creative
    assert '女飞行员在暴雨中救援乘客。' in creative
    assert title['rules']['title_creation']['schema']['properties']['directions']['minItems'] == 3
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert s.get(V14Run, old['run_id']).rules_snapshot == previous
        assert s.get(V14Run, old['run_id']).input_snapshot == previous_input
