from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from zhiju.database import TenantSession
from zhiju.models import Base, Channel
from zhiju.models.v14 import V14Setting
from zhiju.services import channel_analysis as service
from zhiju.services.identity import ConflictError


@pytest.fixture
def session():
    from sqlalchemy.pool import StaticPool
    engine = create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={'tenant_id': 'tenant-analysis'}) as s:
        c = Channel(original_name='Test', youtube_channel_id='UCtest', default_language='en',
                    default_genre='女性逆袭', timezone='Asia/Shanghai', status='active')
        s.add(c)
        s.add(V14Setting(tenant_id='tenant-analysis', payload={
            'host_id':'host', 'account_profile':'current', 'default_model':'test-model',
            'available_models':['test-model'], 'rules':{}, 'workflow_version_id':'builtin-v14',
            'channel_inputs':{}}))
        s.commit()
        yield s, c
    engine.dispose()


def test_cold_start_requires_explicit_positioning_and_never_collects_api(session):
    s, c = session
    with pytest.raises(ConflictError, match='初始定位'):
        service.create_run(s, c.id, mode='initial', positioning='')
    run = service.create_run(s, c.id, mode='initial', positioning='女性重新掌握人生')
    service.start_run(s, run.id)
    assert run.status == 'queued'
    assert run.input_snapshot['mode'] == 'initial'
    assert run.input_snapshot['channel']['youtube_channel_id'] == 'UCtest'
    assert run.input_snapshot['positioning'] == '女性重新掌握人生'


def test_periodic_missing_assets_cannot_start_or_silently_become_initial(session,monkeypatch):
    from zhiju.services import channel_analysis_sources
    monkeypatch.setattr(channel_analysis_sources,'verify_authorization',lambda *args:('token',{},{}))
    s, c = session
    run = service.create_run(s, c.id, mode='periodic', positioning='已有频道')
    with pytest.raises(ConflictError, match='ZIP|截图'):
        service.start_run(s, run.id)
    assert run.status == 'draft'
    assert run.mode == 'periodic'


def test_duplicate_start_and_wrong_host_claim(session):
    s, c = session
    run = service.create_run(s, c.id, mode='initial', positioning='初始定位')
    service.start_run(s, run.id)
    assert service.start_run(s, run.id).id == run.id
    with pytest.raises(ConflictError):
        service.claim_run(s, 'other-host')
    claim = service.claim_run(s, 'host')
    assert claim['id'] == run.id
    assert claim['claim_id']
    assert service.claim_run(s, 'host') is None
    service.cancel_run(s, run.id)
    with pytest.raises(ConflictError):
        service.submit_result(s, run.id, claim['claim_id'], result={})


def test_scope_and_read_does_not_create_work(session):
    s, c = session
    run = service.create_run(s, c.id, mode='initial', positioning='初始定位')
    before = service.list_runs(s, c.id)
    assert len(before) == 1
    with TenantSession(s.bind, info={'tenant_id':'other'}) as other:
        with pytest.raises(Exception):
            service.get_run(other, run.id)
    assert run.status == 'draft'


def test_report_rejects_broken_spec_and_partial_result(session):
    s, c = session
    run = service.create_run(s, c.id, mode='initial', positioning='初始定位')
    service.start_run(s, run.id)
    claim = service.claim_run(s, 'host')
    with pytest.raises(ConflictError):
        service.submit_result(s, run.id, claim['claim_id'], result={'profile':'fake'})
    assert service.get_run(s, run.id).status == 'running'


def valid_result(run):
    from zhiju.channel_analysis_rules.validate_generation_spec import GLOBAL_FIELDS, PERMISSION
    channel=run.input_snapshot['channel']
    values=[channel['original_name'],channel['default_language'],'未配置','女频','剧情','en','无','自然表达',PERMISSION]
    spec='## [GLOBAL]\n\n'+'\n'.join(f'- {k}：{v}' for k,v in zip(GLOBAL_FIELDS,values))
    for section in ['TITLE','COVER','DESCRIPTION','HASHTAG','COMMUNITY','PLAYLIST']:
        spec+=f'\n\n## [{section}]\n\n只依据剧情事实表达，不编造。'
    import yaml
    strategy={'channel_id':'UCtest','updated_at':'2026-10-29','data_window':{'recent_28d':'not_applicable','recent_90d':'not_applicable'},
        'strategy_confidence':'low','channel_stage':'冷启动','audience_core':'假设','traffic_type':'unavailable'}
    for k in ['content_priority','content_secondary','content_explore','content_avoid','title_priority','title_reduce','cover_priority','cover_reduce','description_focus','community_focus','hashtag_focus','scheduling_notes']:
        strategy[k]=[]
    profile='冷启动，未经数据验证\n'+'\n'.join(f'## {i}. 资料\n未知项不可用' for i in range(1,11))
    diagnosis='冷启动，未经数据验证\n'+'\n'.join(f'## {i}. 诊断\n假设待验证' for i in range(1,8))
    diagnosis+='\n```yaml\n'+yaml.safe_dump({'channel_strategy':strategy},allow_unicode=True)+'```'
    snapshot={k:'unavailable' for k in ['schema_version','snapshot_status','generated_at','data_windows','availability_rules','channel_totals_28d','trend','audience_28d','traffic_28d_video_pct','retention_intro_30s_pct','top_videos_28d','low_videos_28d','concentration_28d','community_posts','ab_testing','source_manifest','unmatched_video_ids']}
    snapshot['channel']={'youtube_channel_id':'UCtest'}
    return {'profile':profile,'diagnosis':diagnosis,'generation_spec':spec,'normalized_snapshot':snapshot}


def complete(s,c):
    run=service.create_run(s,c.id,mode='initial',positioning='冷启动定位')
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    return service.submit_result(s,run.id,claim['claim_id'],result=valid_result(run))


def test_apply_versions_preserves_fixed_assets_and_old_runs(session):
    from zhiju.models import ChannelAnalysisReport,ChannelDnaVersion
    s,c=session
    setting=s.scalar(select(V14Setting));payload=dict(setting.payload)
    payload['channel_inputs']={c.id:{'language':'en','description_fixed_assets':{'keep':'verbatim'}}}
    setting.payload=payload;s.commit()
    run=complete(s,c);original=run.result.copy()
    service.apply_result(s,run.id);service.apply_result(s,run.id)
    assert len(list(s.scalars(select(ChannelAnalysisReport))))==1
    assert setting.payload['channel_inputs'][c.id]['description_fixed_assets']=={'keep':'verbatim'}
    assert setting.payload['channel_inputs'][c.id]['analysis_version']['run_id']==run.id
    new=complete(s,c);service.apply_result(s,new.id)
    assert run.status=='superseded'
    assert run.result==original
    assert len(list(s.scalars(select(ChannelDnaVersion).where(ChannelDnaVersion.status=='active'))))==1


def test_initial_collection_no_network_and_has_normalization_sources(session):
    from zhiju.services.channel_analysis_sources import collect
    s,c=session
    run=service.create_run(s,c.id,mode='initial',positioning='冷启动定位')
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    def forbidden(*args):raise AssertionError('冷启动不应访问Google')
    collect(s,run.id,claim['claim_id'],fetcher=forbidden)
    assert run.input_snapshot['sources']['api']['status']=='not_applicable'
    assert run.phase=='analysis'


def test_zip_retains_native_csvs_and_rejects_invalid_materials():
    from io import BytesIO
    from zipfile import ZipFile
    from zhiju.services.channel_analysis_sources import parse_studio_zip
    stream=BytesIO()
    with ZipFile(stream,'w') as archive:
        archive.writestr('表格数据.csv','视频 ID,观看次数\nv1,23\n')
        archive.writestr('图表数据.csv','日期,观看次数\n2026-10-01,1\n2026-10-28,23\n')
    assert parse_studio_zip(stream.getvalue())['表格数据.csv'][0]['观看次数']=='23'
    with pytest.raises(ConflictError):parse_studio_zip(b'not a zip')


def test_analysis_mirror_only_changes_live_documents_when_applied(session,tmp_path):
    from zhiju.v14_executor.channel_analysis import mirror
    s,c=session;run=complete(s,c)
    data=service.run_read(run)
    mirror(data,tmp_path/'cache',tmp_path)
    target=tmp_path/'频道分析/en/Test/频道用户画像与长期经营档案.md'
    assert not target.exists()
    data['status']='applied';mirror(data,tmp_path/'cache',tmp_path)
    assert target.read_text()==run.result['profile']


def test_analysis_routes_classified_and_optional_oauth_refresh_is_explicit():
    from zhiju.app import app
    from zhiju.tenant_scope import TENANT_ROUTES
    from fastapi.testclient import TestClient
    paths=TestClient(app).get('/openapi.json').json()['paths']
    entries=[(m.upper(),path) for path,methods in paths.items() if 'analysis-runs' in path or 'channel-analysis/claims' in path for m in methods]
    assert len(entries)==14
    for entry in entries:assert entry in TENANT_ROUTES


def test_formal_collection_preserves_successful_datasets_after_auth_interruption(session,monkeypatch,tmp_path):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from io import BytesIO
    from zipfile import ZipFile
    from PIL import Image
    from types import SimpleNamespace
    from urllib.parse import urlparse,parse_qs
    from collections import Counter
    from zhiju.services import channel_analysis_sources as sources
    from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired
    s,c=session
    end=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=1)
    profile={'items':[{'id':'UCtest','snippet':{'title':'Test','publishedAt':str(end-timedelta(days=100))+'T00:00:00Z'}}]}
    monkeypatch.setattr(sources,'verify_authorization',lambda *args:('token',profile,profile['items'][0]))
    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(artifact_root=tmp_path))
    run=service.create_run(s,c.id,mode='periodic',posts_not_applicable=True,ab_not_applicable=True)
    stream=BytesIO()
    with ZipFile(stream,'w') as archive:
        archive.writestr('表格数据.csv','视频 ID,展示次数,展示点击率 (%)\nv1,100,10\nv2,900,1\n')
        archive.writestr('图表数据.csv',f'日期,观看次数\n{end-timedelta(days=27)},1\n{end},1\n')
    service.add_material(s,run.id,'studio_zip','内容.zip',stream.getvalue())
    image=BytesIO();Image.new('RGB',(2,2)).save(image,format='PNG')
    for kind in ('videos','audience'):service.add_material(s,run.id,kind,kind+'.png',image.getvalue())
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    calls=Counter();interrupted=False
    def fetch(url,token):
        nonlocal interrupted
        q=parse_qs(urlparse(url).query);key=(q.get('startDate',[''])[0],q.get('dimensions',[''])[0]);calls[key]+=1
        if q.get('dimensions')==['country'] and q['startDate']==[str(end-timedelta(days=89))] and not interrupted:
            interrupted=True;raise YouTubeAuthorizationRequired('模拟令牌权限失效')
        if '/videos?' in url:return {'items':[]}
        dimension=q['dimensions'][0]
        return {'columnHeaders':[{'name':dimension},{'name':'views'}],
                'rows':[['v1' if dimension=='video' else 'value',5]]}
    with pytest.raises(YouTubeAuthorizationRequired):sources.collect(s,run.id,claim['claim_id'],fetcher=fetch)
    assert run.input_snapshot['sources']['api']['28:daily']['status']=='available'
    sources.collect(s,run.id,claim['claim_id'],fetcher=fetch)
    assert calls[(str(end-timedelta(days=27)),'day')]==1
    assert run.input_snapshot['sources']['normalized']['impression_weighted_ctr']['value_percent']==pytest.approx(1.9)
    before=calls.copy();sources.collect(s,run.id,claim['claim_id'],fetcher=fetch)
    assert before==calls


def test_initial_drain_replay_does_not_regenerate_or_create_packages(session,tmp_path):
    import json
    from types import SimpleNamespace
    from zhiju.v14_executor.channel_analysis import drain
    from zhiju.services.channel_analysis_sources import collect
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='新频道')
    service.start_run(s,run.id)
    class Client:
        tenant_id='tenant-analysis';host_id='host'
        def request(self,method,path,body=None,**kwargs):
            if path=='/auth/me':return {'tenant_id':self.tenant_id}
            if path=='/channel-analysis/claims':return service.claim_run(s,self.host_id)
            if path.endswith('/collect'):return service.run_read(collect(s,run.id,body['claim_id']))
            if path.endswith('/heartbeat'):return {'status':service.claimed(s,run.id,body['claim_id']).status}
            if path.endswith('/result'):
                return service.run_read(service.submit_result(s,run.id,body['claim_id'],result=body.get('result'),error=body.get('error')))
            if path==f'/analysis-runs/{run.id}':return service.run_read(run)
            if path.endswith('/mirror-complete'):return {'status':'completed'}
            raise AssertionError(path)
    calls=[]
    def generate(stage,model):
        calls.append(model);data=valid_result(run)
        data['normalized_snapshot']=json.dumps(data['normalized_snapshot']);data['material_checks']='{}'
        return data
    model=SimpleNamespace(account_profile='current',generate=generate)
    config={'analysis_workspace_root':str(tmp_path/'workspace')}
    drain(Client(),model,config,tmp_path/'cache')
    assert run.status=='ready';assert len(calls)==1
    drain(Client(),model,config,tmp_path/'cache')
    assert len(calls)==1
    service.apply_result(s,run.id);drain(Client(),model,config,tmp_path/'cache')
    assert (tmp_path/'workspace/频道分析/en/Test/Test_生成规范.md').exists()


def test_truncated_output_and_incomplete_yaml_never_become_ready(session):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='定位')
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    data=valid_result(run);data['profile']='一句话假装报告'
    with pytest.raises(ConflictError,match='10节'):service.submit_result(s,run.id,claim['claim_id'],result=data)
    data=valid_result(run);data['diagnosis']=data['diagnosis'].replace('strategy_confidence: low\n','')
    with pytest.raises(ConflictError,match='YAML'):service.submit_result(s,run.id,claim['claim_id'],result=data)


def test_actual_image_paths_passed_to_codex_cli(tmp_path):
    import sys,json
    from types import SimpleNamespace
    from zhiju.v14_executor.codex import CodexClient
    binary=tmp_path/'fake-cli'
    binary.write_text(f'#!{sys.executable}\nimport sys,json,pathlib\na=sys.argv\npathlib.Path(a[a.index("--output-last-message")+1]).write_text(json.dumps(a))\n')
    binary.chmod(0o700)
    picture=tmp_path/'screenshot.png';picture.write_bytes(b'fixture')
    stage=SimpleNamespace(prompt='仅测试参数',schema={},rules={},images=[picture],skill_bundle=None,node_type='channel_analysis')
    args=CodexClient(binary=str(binary)).generate(stage,'fake-model')
    assert args[args.index('--image')+1]==str(picture)


def test_lost_failed_submission_ack_replays_idempotently(session):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='新频道')
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    service.submit_result(s,run.id,claim['claim_id'],error='模拟模型失败')
    repeated=service.submit_result(s,run.id,claim['claim_id'],error='模拟模型失败')
    assert repeated.status=='failed'
    assert len(run.attempts)==1
    service.resume_run(s,run.id,True)
    with pytest.raises(ConflictError):service.submit_result(s,run.id,claim['claim_id'],error='模拟模型失败')


def test_http_analysis_lifecycle_and_applied_input_are_connected(session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from zhiju.api.channel_analysis import router
    from zhiju.api.v14 import operator
    from zhiju.auth_context import get_tenant_db
    s,c=session
    app=FastAPI();app.include_router(router,prefix='/api')
    app.dependency_overrides[get_tenant_db]=lambda:s
    app.dependency_overrides[operator]=lambda:SimpleNamespace(tenant_id='tenant-analysis',device_id='host')
    with TestClient(app) as client:
        response=client.post(f'/api/v3/channels/{c.id}/analysis-runs',json={'mode':'initial','positioning':'初始定位'})
        assert response.status_code==200
        run_id=response.json()['id']
        assert client.post(f'/api/v3/analysis-runs/{run_id}/start').json()['status']=='queued'
        claim=client.post('/api/v3/channel-analysis/claims',json={'host_id':'host'}).json()
        assert client.post(f'/api/v3/analysis-runs/{run_id}/collect',json={'claim_id':claim['claim_id']}).status_code==200
        run=service.get_run(s,run_id);body={'claim_id':claim['claim_id'],'result':valid_result(run)}
        assert client.put(f'/api/v3/analysis-runs/{run_id}/result',json=body).json()['status']=='ready'
        assert client.put(f'/api/v3/analysis-runs/{run_id}/result',json=body).status_code==200
        assert client.post(f'/api/v3/analysis-runs/{run_id}/apply').json()['status']=='applied'
        setting=s.scalar(select(V14Setting))
        assert setting.payload['channel_inputs'][c.id]['analysis_version']['run_id']==run_id
        listing=client.get(f'/api/v3/channels/{c.id}/analysis-runs').json()[0]
        assert 'sources' not in listing['input_snapshot']
        assert listing['result']=={'available':True}


def test_analysis_migration_adds_only_run_table_and_can_downgrade():
    from pathlib import Path
    import importlib.util
    from sqlalchemy import inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from zhiju.models import ChannelAnalysisRun
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    ChannelAnalysisRun.__table__.drop(engine)
    path=Path(__file__).resolve().parents[1]/'alembic/versions/e94a1c729b30_channel_analysis_runs.py'
    spec=importlib.util.spec_from_file_location('analysis_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with engine.begin() as connection:
        before=set(inspect(connection).get_table_names())
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert set(inspect(connection).get_table_names())==before|{'channel_analysis_runs'}
            columns={c['name'] for c in inspect(connection).get_columns('channel_analysis_runs')}
            assert columns==set(ChannelAnalysisRun.__table__.columns.keys())
            migration.downgrade()
            assert set(inspect(connection).get_table_names())==before
    engine.dispose()
