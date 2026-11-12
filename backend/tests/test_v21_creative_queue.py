"""Same-drama samples must see the previous channel's accepted title and cover."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import select

from test_v14_api import client, store
from zhiju.database import TenantSession
from zhiju.models import Channel, OperationPackage, OperationTask, WorkOrder
from zhiju.models.v14 import V14Attempt, V14Run
from zhiju.services import v14_runs
from zhiju.workflow_bundles import snapshot


def sample_bundle(revision):
    data = BytesIO()
    with ZipFile(data, 'w') as z:
        z.writestr('zhiju-workflow.json', json.dumps({
            'label': 'V21', 'entrypoint': 'entry.py', 'skills': ['sample'],
            'nodes': ['search', 'title', 'cover', 'description', 'community', 'merge'],
            'executor_protocol': 13}))
        z.writestr('sample/SKILL.md', '# Queue fixture')
        z.writestr('entry.py', '')
    return {'skill_bundle': snapshot(data.getvalue(), version_id='sample', label='V21', revision=revision)}


def clone(row, **changes):
    values = {col.name: deepcopy(getattr(row, col.name)) for col in row.__table__.columns}
    return type(row)(**{**values, **changes})


def queued_samples(client, store, revision=3):
    reply = client.post('/api/v3/work-orders/work-a/v14-runs')
    assert reply.status_code == 200, reply.text
    first_id = reply.json()['run_id']
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        base = s.get(V14Run, first_id)
        base.rules_snapshot = sample_bundle(revision)
        stamp = datetime(2026, 11, 12, tzinfo=timezone.utc)
        base.created_at = base.updated_at = stamp
        source_channel = s.get(Channel, 'channel-a')
        source_channel.sort_order = 1
        source_task = s.get(OperationTask, 'task-a')
        source_work = s.get(WorkOrder, 'work-a')
        source_package = s.get(OperationPackage, 'package-a')
        ids = [base.id]
        for n in (2, 3):
            key = f'peer-{n}'
            drama = source_work.drama_id if n == 2 else 'another-drama'
            s.add(clone(source_channel, id=key, youtube_channel_id=f'UC-{key}', sort_order=n))
            s.add(clone(source_task, id=key, channel_id=key, drama_id=drama,
                        idempotency_key=key, schedule_id=None))
            s.add(clone(source_work, id=key, task_id=key, channel_id=key, drama_id=drama))
            s.add(clone(source_package, id=key, work_order_id=key, channel_id=key, drama_id=drama))
            inputs = deepcopy(base.input_snapshot)
            inputs.update(channel_id=key, channel_name=key, drama_id=drama)
            other = clone(base, id=key, work_order_id=key, package_id=key,
                          input_snapshot=inputs, created_at=stamp + timedelta(seconds=n),
                          updated_at=stamp + timedelta(seconds=n))
            s.add(other)
            ids.append(other.id)
        s.commit()
    return ids


def claim(client):
    response = client.post('/api/v3/executor/claims', json={
        'host_id': 'device-a', 'claim_id': str(uuid4()), 'executor_protocol': 13})
    assert response.status_code == 200, response.text
    return response.json()


def test_same_drama_waits_for_cover_but_other_drama_can_run(client, store):
    first, same, different = queued_samples(client, store)
    one = claim(client)['run']
    assert one['run_id'] == first
    two = claim(client)['run']
    assert two['run_id'] == different
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert v14_runs.claim_run(s, 'device-a', executor_protocol=13,
                                 claim_id=str(uuid4()), run_id=same) is None
        for node, payload in (('title', {'directions': ['prior channel hook']}),
                              ('cover', {'titles': ['prior channel scene']})):
            s.add(V14Attempt(run_id=first, claim_id=one['claim_id'], node_type=node,
                             sequence=1, outcome='accepted', payload=payload))
        s.commit()
    three = claim(client)['run']
    assert three['run_id'] == same
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert s.get(V14Run, first).status == 'running'
        data = v14_runs.envelope(s, s.get(V14Run, same))
        assert {h['node_type'] for h in data['creative_history'] if h['run_id'] == first} == {'title', 'cover'}


def test_revision_2_keeps_existing_parallel_claims(client, store):
    first, same, _ = queued_samples(client, store, revision=2)
    assert claim(client)['run']['run_id'] == first
    assert claim(client)['run']['run_id'] == same


def test_only_blocked_peer_keeps_the_executor_polling(client, store):
    first, same, different = queued_samples(client, store)
    assert claim(client)['run']['run_id'] == first
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        s.get(V14Run, different).status = 'cancelled'
        s.commit()
    waiting = claim(client)
    assert waiting['waiting_for_capacity'] is True
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert s.get(V14Run, same).status == 'queued'
