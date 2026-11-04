from datetime import datetime
from test_channel_analysis_runs import session,complete
from zhiju.services import channel_analysis as service
from zhiju.models import Channel
from zhiju.database import TenantSession


def test_workspace_lists_each_channel_and_its_actual_production_version(session):
    s,c=session;applied=complete(s,c);service.apply_result(s,applied.id)
    applied.created_at=datetime(2020,1,1);s.commit()
    pending=service.create_run(s,c.id,mode='initial',positioning='new')
    second=Channel(original_name='Another',youtube_channel_id='UCother');s.add(second);s.commit()
    data=service.analysis_workspace(s)
    rows={row['channel_id']:row for row in data['items']}
    assert data['total']==2
    assert rows[c.id]['current']['id']==applied.id and rows[c.id]['current']['report_version']==1
    assert rows[c.id]['latest']['id']==pending.id
    assert rows[second.id]['current'] is None and rows[second.id]['latest'] is None
    with TenantSession(s.bind,info={'tenant_id':'other'}) as other:
        assert service.analysis_workspace(other)['total']==0


def test_progress_monitor_keeps_queued_running_failed_and_individual_progress(session):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='test')
    run.status='running';run.progress={'stage':'screenshots','completed_items':3,'total_items':11};s.commit()
    data=service.analysis_workspace(s,'progress')
    assert data['stats']=={'running':1,'queued':0,'failed':0,'worker_limit':10}
    assert data['items'][0]['run']['progress']['completed_items']==3
    assert data['items'][0]['channel_id']==c.id
    run.status='failed';run.error='model timeout';s.commit()
    assert service.analysis_workspace(s,'progress')['items'][0]['run']['error']=='model timeout'
    service.delete_run(s,run.id)
    assert service.analysis_workspace(s,'progress')['total']==0


def test_workspace_uses_saved_channel_order(session):
    s,c=session;c.original_name='Z-last-alphabetically';c.sort_order=1
    second=Channel(original_name='A-first-alphabetically',youtube_channel_id='UC2',sort_order=2)
    s.add(second);s.commit()
    assert [row['channel_id'] for row in service.analysis_workspace(s)['items']]==[c.id,second.id]


def test_workspace_api_is_scoped_and_validates_page_limits(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from zhiju.api.channel_analysis import router
    from zhiju.auth_context import get_tenant_db
    from zhiju.tenant_scope import TENANT_ROUTES
    s,c=session;app=FastAPI();app.include_router(router,prefix='/api')
    app.dependency_overrides[get_tenant_db]=lambda:s
    assert ('GET','/api/v3/channel-analysis/workspace') in TENANT_ROUTES
    with TestClient(app) as client:
        path='/api/v3/channel-analysis/workspace'
        assert client.get(path).json()['total']==1
        assert client.get(path+'?view=progress').json()['total']==0
        assert client.get(path+'?page_size=100').status_code==422
        s.info['tenant_id']='other'
        assert client.get(path).json()['total']==0
