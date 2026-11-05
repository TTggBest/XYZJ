from datetime import datetime,timezone
import json
from sqlalchemy import select
from test_v14_api import client,store
from zhiju.database import TenantSession
from zhiju.models import ChannelSchedulePlan


def test_workspace_is_lightweight_tenant_scoped_searchable_and_paginated(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        for i in range(23):
            s.add(ChannelSchedulePlan(id=f'plan-{i:02}',channel_id='channel-a',host_id='device-a',status='running' if i==0 else 'ready',
                claim_id='claim' if i==0 else None,
                input_snapshot={'start_date':'2026-11-09','end_date':'2026-11-18','daily_count':2,
                    'candidates':[{'plot':'large private story '*10000},{'plot':'second'}],'targets':[{},{}]},
                progress={'stage':'assessing','completed_items':1,'total_items':2}))
        s.commit()
    with TenantSession(store,info={'tenant_id':'tenant-b'}) as s:
        s.add(ChannelSchedulePlan(channel_id='channel-b',host_id='device-b',status='queued',input_snapshot={}))
        s.commit()
    data=client.get('/api/v3/schedule-planning/workspace',params={'page_size':10}).json()
    assert data['total']==23 and len(data['items'])==10 and data['pages']==3
    assert data['items'][0]['id']=='plan-00'
    assert data['items'][0]['candidate_count']==2 and data['items'][0]['target_count']==2
    assert data['items'][0]['progress']['completed_items']==1
    assert 'large private story' not in json.dumps(data)
    assert data['stats']['running']==1 and data['stats']['queued']==0
    assert data['executor']['worker_limit']==10
    running=client.get('/api/v3/schedule-planning/workspace',params={'status':'running'}).json()
    assert running['total']==1
    assert client.get('/api/v3/schedule-planning/workspace',params={'search':'不存在频道'}).json()['total']==0
    page=client.get('/api/v3/schedule-planning/workspace',params={'page_size':10,'page':3}).json()
    assert len(page['items'])==3
    assert client.get('/api/v3/schedule-planning/workspace',params={'status':'invalid'}).status_code==422


def test_claim_bound_heartbeat_reports_real_progress(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        s.add(ChannelSchedulePlan(id='progress',channel_id='channel-a',host_id='device-a',status='running',claim_id='claim',
            input_snapshot={},heartbeat_at=datetime.now(timezone.utc)))
        s.commit()
    progress={'stage':'planning','completed_items':156,'total_items':156,'current_item':'编排第 2 / 3 次尝试','elapsed_seconds':120}
    path='/api/v3/schedule-plans/progress/heartbeat'
    assert client.post(path,json={'claim_id':'stale','progress':progress}).status_code==409
    assert client.post(path,json={'claim_id':'claim','progress':progress}).status_code==200
    saved=client.get('/api/v3/schedule-planning/workspace').json()['items'][0]
    assert saved['progress']==progress
    assert saved['heartbeat_at']


def test_progress_migration_can_upgrade_and_downgrade():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[1]/'alembic/versions/f23a20261105_schedule_progress.py'
    spec=importlib.util.spec_from_file_location('progress_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE channel_schedule_plans (id VARCHAR(36) PRIMARY KEY)')
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert 'progress' in {c['name'] for c in sa.inspect(conn).get_columns('channel_schedule_plans')}
            assert 'executor_claims' in sa.inspect(conn).get_table_names()
            assert {'tenant_id','claim_id','released_at'} <= {c['name'] for c in sa.inspect(conn).get_columns('executor_claims')}
            migration.downgrade()
            assert 'executor_claims' not in sa.inspect(conn).get_table_names()
            assert 'progress' not in {c['name'] for c in sa.inspect(conn).get_columns('channel_schedule_plans')}
    engine.dispose()
