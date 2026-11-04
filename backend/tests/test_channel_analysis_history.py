from test_channel_analysis_runs import session,complete
from datetime import datetime
from zhiju.services import channel_analysis as service


def test_history_can_reach_older_than_thirty_and_pins_actual_production_binding(session):
    s,c=session;production=complete(s,c);service.apply_result(s,production.id)
    production.created_at=datetime(2020,1,1);s.commit()
    for i in range(35):
        row=service.create_run(s,c.id,mode='initial',positioning=str(i));service.cancel_run(s,row.id)
    first=service.analysis_history(s,c.id,1,10)
    assert first['total']==36 and first['pages']==4 and len(first['items'])==10
    assert first['current']['id']==production.id
    assert first['current']['is_current'] and first['current']['report_version']==1
    pages=[service.analysis_history(s,c.id,page,10) for page in range(1,5)]
    assert len({r['id'] for p in pages for r in p['items']})==36
    assert any(r['id']==production.id for r in pages[-1]['items'])
    service.delete_run(s,pages[0]['items'][0]['id'])
    assert service.analysis_history(s,c.id)['total']==35


def test_ready_and_superseded_results_have_distinct_version_meanings(session):
    s,c=session;old=complete(s,c);service.apply_result(s,old.id)
    pending=complete(s,c)
    new=complete(s,c);service.apply_result(s,new.id)
    rows={r['id']:r for r in service.analysis_history(s,c.id)['items']}
    assert rows[new.id]['report_version']==2 and rows[new.id]['is_current']
    assert rows[old.id]['report_version']==1 and rows[old.id]['status']=='superseded' and not rows[old.id]['is_current']
    assert rows[pending.id]['report_version'] is None and not rows[pending.id]['is_current']


def test_unlinked_manual_reports_remain_in_paginated_history_without_duplicate_applied_reports(session):
    from zhiju.models import ChannelAnalysisReport
    s,c=session;production=complete(s,c);service.apply_result(s,production.id)
    manual=ChannelAnalysisReport(channel_id=c.id,version_number=2,report_type='manual',status='completed',generated_by='manual',summary='人工历史正文')
    s.add(manual);s.commit()
    history=service.analysis_history(s,c.id)
    assert history['total']==2
    standalone=next(row for row in history['items'] if row['id']==manual.id)
    assert standalone['kind']=='report' and standalone['report_version']==2
    assert standalone['status']=='legacy_report' and not standalone['can_apply']
    assert history['current']['id']==production.id


def test_history_endpoint_pages_and_rejects_other_tenant(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from zhiju.api.channel_analysis import router
    from zhiju.auth_context import get_tenant_db
    from zhiju.tenant_scope import TENANT_ROUTES
    s,c=session;row=service.create_run(s,c.id,mode='initial',positioning='fixture')
    app=FastAPI();app.include_router(router,prefix='/api');app.dependency_overrides[get_tenant_db]=lambda:s
    with TestClient(app) as client:
        path=f'/api/v3/channels/{c.id}/analysis-history'
        assert client.get(path+'?page_size=51').status_code==422
        assert client.get(path+'?page=99').json()['page']==1
        assert client.get(path).json()['items'][0]['id']==row.id
        assert ('GET','/api/v3/channels/{channel_id}/analysis-history') in TENANT_ROUTES
        s.info['tenant_id']='different'
        assert client.get(path).status_code==404
