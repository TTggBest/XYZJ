"""Deleting abandoned analysis tasks must not affect production versions or executor replay."""
import pytest
from test_channel_analysis_runs import session
from zhiju.services import channel_analysis as service
from zhiju.services.identity import ConflictError


@pytest.mark.parametrize('status',['draft','failed','cancelled'])
def test_delete_abandoned_task_hides_it_and_prevents_resume(session,status):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='误操作')
    run.status=status;run.claim_id='old-claim';s.commit()
    snapshot=run.input_snapshot
    service.delete_run(s,run.id)
    assert service.list_runs(s,c.id)==[]
    assert service.list_run_summaries(s,c.id)==[]
    assert run.status=='deleted' and run.claim_id is None
    assert run.input_snapshot==snapshot
    with pytest.raises(ConflictError):service.resume_run(s,run.id,True)
    with pytest.raises(ConflictError):service.cancel_run(s,run.id)
    assert service.delete_run(s,run.id).status=='deleted'


@pytest.mark.parametrize('status',['queued','running','ready','applied','superseded'])
def test_delete_protects_executing_and_completed_versions(session,status):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='保留')
    run.status=status;s.commit()
    with pytest.raises(ConflictError):service.delete_run(s,run.id)
    assert run.status==status


def test_delete_endpoint_is_tenant_scoped_and_requires_operator(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from zhiju.api.channel_analysis import router
    from zhiju.api.v14 import operator
    from zhiju.auth_context import get_tenant_db
    from zhiju.tenant_scope import TENANT_ROUTES
    assert ('DELETE','/api/v3/analysis-runs/{run_id}') in TENANT_ROUTES
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='误建')
    app=FastAPI();app.include_router(router,prefix='/api')
    app.dependency_overrides[get_tenant_db]=lambda:s
    app.dependency_overrides[operator]=lambda:SimpleNamespace(tenant_id='tenant-analysis',device_id='host')
    with TestClient(app) as client:
        response=client.delete(f'/api/v3/analysis-runs/{run.id}')
        assert response.status_code==200 and response.json()['status']=='deleted'
        assert client.get(f'/api/v3/channels/{c.id}/analysis-runs').json()==[]


def test_delete_cannot_access_other_company(session):
    from fastapi import HTTPException
    from zhiju.database import TenantSession
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='保留')
    with TenantSession(s.bind,info={'tenant_id':'other-company'}) as other:
        with pytest.raises(HTTPException) as error:service.delete_run(other,run.id)
        assert error.value.status_code==404
    assert run.status=='draft'


def test_delete_requires_company_admin(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from zhiju.api.channel_analysis import router
    from zhiju.api.v14 import get_current_principal
    from zhiju.auth_context import get_tenant_db
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='保留')
    app=FastAPI();app.include_router(router,prefix='/api')
    app.dependency_overrides[get_tenant_db]=lambda:s
    app.dependency_overrides[get_current_principal]=lambda:SimpleNamespace(platform_role=None,membership_role='member')
    with TestClient(app) as client:
        assert client.delete(f'/api/v3/analysis-runs/{run.id}').status_code==403
    assert run.status=='draft'


def test_deleted_task_does_not_block_cached_executor_replay(session,tmp_path):
    import json
    from types import SimpleNamespace
    from zhiju.v14_executor.channel_analysis import drain
    from zhiju.v14_executor.client import CloudConflict
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='误建')
    run.status='failed';run.claim_id='old';s.commit();service.delete_run(s,run.id)
    root=tmp_path/run.id;root.mkdir()
    (root/'pending.json').write_text(json.dumps({'run_id':run.id,'body':{'claim_id':'old','error':'old failure'}}))
    class Cloud:
        tenant_id='tenant-analysis';host_id='host'
        def request(self,method,path,body=None):
            if path=='/auth/me':return {'tenant_id':self.tenant_id}
            if path=='/channel-analysis/claims':return service.claim_run(s,self.host_id)
            if method=='PUT':raise CloudConflict('deleted claim')
            return service.run_read(run)
    def no_model(*args):raise AssertionError('deleted task must not run a model')
    drain(Cloud(),SimpleNamespace(generate=no_model),{},tmp_path,once=True)
    assert (root/'abandoned.json').is_file() and not (root/'pending.json').exists()
    assert run.status=='deleted'
