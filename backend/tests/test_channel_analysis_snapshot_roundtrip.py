"""An executor must receive the persisted JSON representation, not pre-storage floats."""
import copy,json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_channel_analysis_runs import session
from zhiju.api import channel_analysis as api
from zhiju.api.v14 import operator
from zhiju.auth_context import get_tenant_db
from zhiju.services import channel_analysis as service


@pytest.mark.parametrize('endpoint',['collect','screenshot-checks'])
def test_fact_checkpoint_returns_database_roundtrip_representation(session,monkeypatch,endpoint):
    s,c=session;s.expire_on_commit=False
    run=service.create_run(s,c.id,mode='initial',positioning='fixture')
    run.status='running';run.claim_id='claim';s.commit()
    original=0.36227649877293444;persisted=0.3622764987729344
    def checkpoint(*args):
        snapshot=copy.deepcopy(run.input_snapshot)
        snapshot['sources']={'fact_snapshot':{'derived_metric':original}}
        run.input_snapshot=snapshot;s.commit()
        stored=copy.deepcopy(snapshot);stored['sources']['fact_snapshot']['derived_metric']=persisted
        # Model MySQL JSON's numeric representation after storage, while the ORM still
        # holds the originally computed Python object (expire_on_commit=False).
        s.execute(text('UPDATE channel_analysis_runs SET input_snapshot=:snapshot WHERE id=:id'),
                  {'snapshot':json.dumps(stored),'id':run.id});s.commit()
        assert run.input_snapshot['sources']['fact_snapshot']['derived_metric']==original
        return run
    if endpoint=='collect':monkeypatch.setattr(api,'collect',checkpoint)
    else:monkeypatch.setattr(service,'record_screenshot_checks',checkpoint)
    app=FastAPI();app.include_router(api.router,prefix='/api')
    app.dependency_overrides[get_tenant_db]=lambda:s
    app.dependency_overrides[operator]=lambda:SimpleNamespace(tenant_id='tenant-analysis',device_id='host')
    with TestClient(app) as client:
        response=client.post(f'/api/v3/analysis-runs/{run.id}/{endpoint}',json={'claim_id':'claim','result':{}})
        assert response.status_code==200
        assert response.json()['input_snapshot']['sources']['fact_snapshot']['derived_metric']==persisted


def test_snapshot_delivery_failure_keeps_generated_documents(tmp_path):
    from zhiju.v14_executor.channel_analysis import reject_document_checkpoints
    for key in ('profile','diagnosis','generation_spec'):
        (tmp_path/f'analysis-{key}.json').write_text('completed document')
    reject_document_checkpoints(tmp_path,'正式分析事实快照与采集来源不一致，不能使用模型生成指标')
    assert all((tmp_path/f'analysis-{key}.json').read_text()=='completed document' for key in ('profile','diagnosis','generation_spec'))
    assert not (tmp_path/'analysis-retry.json').exists()
