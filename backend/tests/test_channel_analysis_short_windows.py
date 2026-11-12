"""Real Studio windows must survive upload, collection and model input separately."""
from datetime import date, timedelta
from io import BytesIO
from zipfile import ZipFile
from types import SimpleNamespace
import pytest
from PIL import Image
from test_channel_analysis_runs import session
from zhiju.services import channel_analysis as service, channel_analysis_sources as sources
from zhiju.services.channel_analysis_normalize import normalize_sources, formal_snapshot, studio_screenshot_window
from zhiju.services.identity import ConflictError
from zhiju.v14_executor.channel_analysis import analysis_prompt_snapshot, stage_for


def studio_zip(days, end=date(2026, 11, 10), *, views=70, impressions=1000, ctr=7, columns=None):
    headings = columns or '内容,观看次数,缩略图展示次数,缩略图点击率 (%),平均观看时长,平均观看百分比 (%)'
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('表格数据.csv', headings + f'\n总计,{views},{impressions},{ctr},10:00,25\nv1,{views},{impressions},{ctr},10:00,25\n')
        archive.writestr('总计.csv', '日期,观看次数\n' + ''.join(f'{end-timedelta(days=i)},1\n' for i in range(days)))
    return stream.getvalue()


def draft(session, monkeypatch, tmp_path):
    s, c = session
    from zhiju.services import skill_catalog
    original=skill_catalog.analysis_snapshot
    monkeypatch.setattr(skill_catalog,'analysis_snapshot',lambda *a:{**original(*a),'revision':5})
    monkeypatch.setattr(sources, 'verify_authorization', lambda *a: ('token', {}, {}))
    monkeypatch.setattr(service, 'get_settings', lambda: SimpleNamespace(artifact_root=tmp_path))
    run = service.create_run(s, c.id, mode='periodic', posts_not_applicable=True, ab_not_applicable=True)
    image = BytesIO(); Image.new('RGB', (2, 2)).save(image, 'PNG')
    for kind in ('videos', 'audience'):
        service.add_material(s, run.id, kind, kind+'.png', image.getvalue())
    return s, run


def test_upload_requires_both_windows_and_keeps_each_when_replaced(session, monkeypatch, tmp_path):
    s, run = draft(session, monkeypatch, tmp_path)
    service.add_material(s, run.id, 'studio_zip', '28.zip', studio_zip(28))
    with pytest.raises(ConflictError, match='7天'):
        service.start_run(s, run.id)
    service.add_material(s, run.id, 'studio_zip', '7.zip', studio_zip(7))
    service.add_material(s, run.id, 'studio_zip', '7-replace.zip', studio_zip(7, views=80))
    service.add_material(s, run.id, 'studio_zip', 'previous7.zip', studio_zip(7, date(2026, 11, 3)))
    assert {m['name'] for m in run.materials if m['kind']=='studio_zip'} == {'28.zip', '7-replace.zip', 'previous7.zip'}
    assert service.start_run(s, run.id).status == 'queued'


@pytest.mark.parametrize('end,columns,message', [
    (date(2026, 11, 9), None, '截止日'),
    (date(2026, 11, 10), '内容,观看次数,其他展示,其他CTR,平均观看时长,平均观看百分比 (%)', '指标'),
])
def test_mismatched_windows_or_metrics_do_not_queue(session, monkeypatch, tmp_path, end, columns, message):
    s, run = draft(session, monkeypatch, tmp_path)
    service.add_material(s, run.id, 'studio_zip', '28.zip', studio_zip(28))
    service.add_material(s, run.id, 'studio_zip', '7.zip', studio_zip(7, end, columns=columns))
    with pytest.raises(ConflictError, match=message):
        service.start_run(s, run.id)
    assert run.status == 'draft'


def test_short_metrics_are_isolated_and_used_in_model_input():
    # Upload order deliberately starts with 7d, not 28d.
    raw = {'api': {}, 'windows': {'28': {'start':'2026-10-14','end':'2026-11-10'}, '90': {}}, 'studio': {
        'seven': sources.parse_studio_zip(studio_zip(7, views=70, impressions=1000, ctr=7)),
        'long': sources.parse_studio_zip(studio_zip(28, views=1000, impressions=10000, ctr=10)),
        'prior': sources.parse_studio_zip(studio_zip(7, date(2026,11,3), views=200, impressions=4000, ctr=5)),
    }}
    raw['studio_windows'] = {key: sources.studio_period(files) for key,files in raw['studio'].items()}
    raw['normalized'] = normalize_sources(raw, {}, 'periodic')
    facts = raw['fact_snapshot'] = formal_snapshot(raw, {})
    assert facts['channel_totals_28d']['metrics']['views'] == 1000
    assert len(facts['studio_content']) == 1
    assert studio_screenshot_window(raw)['span_days'] == 28
    short = facts['studio_short_windows']
    assert short['recent_7d']['totals']['metrics']['impressions'] == 1000
    assert short['previous_7d']['totals']['metrics']['impressions'] == 4000
    assert facts['short_window_comparison']['impressions_change_pct'] == -75
    assert facts['short_window_comparison']['ctr_change_pp'] == 2
    prompt = analysis_prompt_snapshot({'sources': raw})['sources']['fact_snapshot']
    assert prompt['studio_short_windows'] == short
    run = {'mode':'periodic','materials':[], 'input_snapshot':{'sources':raw}}
    assert 'studio_short_windows.recent_7d' in stage_for(run, tmp_path_placeholder()).prompt


def tmp_path_placeholder():
    from pathlib import Path
    return Path('/tmp/unused-analysis-test')


def test_missing_previous_export_is_explicit_not_a_28d_ctr_substitute():
    raw={'api':{},'windows':{'28':{},'90':{}},'studio':{
        'long': sources.parse_studio_zip(studio_zip(28)),
        'seven': sources.parse_studio_zip(studio_zip(7))}}
    raw['normalized']=normalize_sources(raw,{},'periodic')
    facts=formal_snapshot(raw,{})
    assert facts['studio_short_windows']['previous_7d']['status']=='unavailable'
    assert facts['short_window_comparison']['ctr_change_pp']=='unavailable'


def test_existing_single_zip_task_can_still_start(session, monkeypatch, tmp_path):
    s, run = draft(session, monkeypatch, tmp_path)
    snapshot=dict(run.input_snapshot);snapshot.pop('studio_required_periods');run.input_snapshot=snapshot;s.commit()
    service.add_material(s, run.id, 'studio_zip', '28.zip', studio_zip(28))
    assert service.start_run(s, run.id).status=='queued'


def test_collection_uses_28d_for_screenshots_and_actual_api_cutoff(session,monkeypatch,tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from urllib.parse import parse_qs,urlparse
    from zhiju.v14_executor.channel_analysis import screenshot_stage
    end=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=1)
    observed=end-timedelta(days=2)
    s,run=draft(session,monkeypatch,tmp_path)
    item={'id':'UCtest','snippet':{'title':'Test','publishedAt':'2020-01-01T00:00:00Z'}}
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{'items':[item]},item))
    recent=studio_zip(7,end,views=70)
    # Distinct new video appears only in the recent export.
    with ZipFile(BytesIO(recent)) as z:
        files={n:z.read(n) for n in z.namelist()}
    changed=BytesIO()
    with ZipFile(changed,'w') as z:
        for n,data in files.items():z.writestr(n,data.replace(b'v1,',b'recent-only,'))
    service.add_material(s,run.id,'studio_zip','first.zip',changed.getvalue(),studio_role='recent_7d')
    service.add_material(s,run.id,'studio_zip','second.zip',studio_zip(28,end,views=1000),studio_role='recent_28d')
    service.start_run(s,run.id)
    assert service.claim_run(s,'host',executor_protocol=14) is None
    claim=service.claim_run(s,'host',executor_protocol=15)
    calls=[]
    def fetch(url,token):
        q=parse_qs(urlparse(url).query);calls.append(q)
        if '/videos?' in url:
            return {'items':[{'id':v,'snippet':{'title':'New '+v,'description':'actual packaging','thumbnails':{'default':{'url':'https://example.org/image.jpg'}}}} for v in q['id'][0].split(',')]}
        dimension=q['dimensions'][0];start=date.fromisoformat(q['startDate'][0]);stop=date.fromisoformat(q['endDate'][0])
        if dimension=='day':
            stop=min(stop,observed)
            rows=[[str(start+timedelta(days=i)),10,20,2,0] for i in range(max(0,(stop-start).days+1))]
        else:rows=[['recent-only' if dimension=='video' else 'BROWSE',10,20,2,0]]
        return {'columnHeaders':[{'name':dimension},{'name':'views'},{'name':'estimatedMinutesWatched'},{'name':'subscribersGained'},{'name':'subscribersLost'}],'rows':rows}
    sources.collect(s,run.id,claim['claim_id'],fetcher=fetch)
    raw=run.input_snapshot['sources'];facts=raw['fact_snapshot']
    assert raw['windows']['7']['end']==str(observed)
    assert raw['windows']['previous7']['end']==str(observed-timedelta(days=7))
    assert raw['api_observed_end']['requested_end']==str(end)
    assert facts['api_short_window_comparison']['views']['recent_7d']==70
    assert facts['short_window_comparison']['ctr_change_pp']=='unavailable'
    assert facts['studio_short_windows']['recent_7d']['window']['end']==str(end)
    assert studio_screenshot_window(raw)['span_days']==28
    assert str(end-timedelta(days=27)) in screenshot_stage(service.run_read(run),tmp_path).prompt
    assert all(raw['api'][key]['status']=='available' for key in ('7:daily','7:videos','7:traffic','previous7:daily','previous7:videos','previous7:traffic'))
    assert all('likes' not in q['metrics'][0] for q in calls if q.get('dimensions')==['day'] and q.get('startDate')==[raw['windows']['7']['start']])
    prompt=analysis_prompt_snapshot(run.input_snapshot)['sources']['fact_snapshot']
    new=next(v for v in prompt['video_inventory'] if v['id']=='recent-only')
    assert new['description']=='actual packaging' and new['thumbnails']
    count=len(calls);sources.collect(s,run.id,claim['claim_id'],fetcher=fetch)
    assert len(calls)==count


@pytest.mark.parametrize('same_scope',[False,True])
def test_previous_studio_reuse_requires_dates_metrics_and_confirmed_scope(session,monkeypatch,tmp_path,same_scope):
    s,old=draft(session,monkeypatch,tmp_path)
    service.add_material(s,old.id,'studio_zip','historical.zip',studio_zip(7,date(2026,11,3),impressions=4000,ctr=5),
        studio_role='recent_7d',filter_scope='videos only' if same_scope else '')
    old.status='ready';s.commit()
    _,current=draft(session,monkeypatch,tmp_path)
    service.add_material(s,current.id,'studio_zip','28.zip',studio_zip(28),studio_role='recent_28d',filter_scope='videos only')
    service.add_material(s,current.id,'studio_zip','7.zip',studio_zip(7),studio_role='recent_7d',filter_scope='videos only')
    studio={m['id']:sources.parse_studio_zip(service.material_path(current,m['id']).read_bytes()) for m in current.materials if m['kind']=='studio_zip'}
    raw={'studio':studio,'studio_windows':{k:sources.studio_period(v) for k,v in studio.items()},
        'studio_roles':sources.validate_studio_exports(studio,require_recent_7d=True),
        'studio_provenance':{m['id']:m for m in current.materials if m['kind']=='studio_zip'}}
    sources.reuse_previous_studio(s,current,raw)
    assert ('previous_7d' in raw['studio_roles'])==same_scope
    if same_scope:
        key=raw['studio_roles']['previous_7d']
        assert raw['studio_provenance'][key]['reused_from']['run_id']==old.id
        normalized=normalize_sources(raw,{},'periodic')
        assert normalized['studio_short_windows']['previous_7d']['totals']['metrics']['impressions']==4000


def test_period_slots_replace_only_selected_period_even_when_dates_change(session,monkeypatch,tmp_path):
    s,run=draft(session,monkeypatch,tmp_path)
    for role,days,offset in [('recent_7d',7,0),('recent_28d',28,0),('previous_7d',7,7)]:
        service.add_material(s,run.id,'studio_zip',role+'.zip',studio_zip(days,date(2026,11,10)-timedelta(days=offset)),studio_role=role)
    service.add_material(s,run.id,'studio_zip','new7.zip',studio_zip(7,date(2026,11,11)),studio_role='recent_7d')
    names={m['name'] for m in run.materials if m['kind']=='studio_zip'}
    assert names=={'new7.zip','recent_28d.zip','previous_7d.zip'}
    with pytest.raises(ConflictError,match='截止日'):service.start_run(s,run.id)
    with pytest.raises(ConflictError,match='所选周期'):service.add_material(s,run.id,'studio_zip','wrong.zip',studio_zip(28),studio_role='recent_7d')


def test_http_upload_freezes_r5_and_preserves_source_periods(session,monkeypatch,tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from zhiju.api.channel_analysis import router
    from zhiju.api.v14 import operator
    from zhiju.auth_context import get_tenant_db
    s,run=draft(session,monkeypatch,tmp_path)
    app=FastAPI();app.include_router(router,prefix='/api')
    app.dependency_overrides[get_tenant_db]=lambda:s
    app.dependency_overrides[operator]=lambda:SimpleNamespace(tenant_id='tenant-analysis',device_id='host')
    with TestClient(app) as client:
        url=f'/api/v3/analysis-runs/{run.id}'
        for days,role in [(7,'recent_7d'),(28,'recent_28d')]:
            response=client.post(url+'/materials',data={'kind':'studio_zip','studio_role':role,'filter_scope':'all videos'},
                files={'file':('arbitrary.zip',studio_zip(days),'application/zip')})
            assert response.status_code==200,response.text
        body=response.json()
        assert body['input_snapshot']['studio_required_periods']==[28,7]
        assert len([m for m in body['materials'] if m['kind']=='studio_zip'])==2
        assert all(m['filter_verification']=='user_confirmed' for m in body['materials'] if m['kind']=='studio_zip')
        assert client.post(url+'/start').json()['status']=='queued'
        assert client.post('/api/v3/channel-analysis/claims',json={'host_id':'host','executor_protocol':14}).status_code==204
        assert client.post('/api/v3/channel-analysis/claims',json={'host_id':'host','executor_protocol':15}).json()['id']==run.id


def test_incomplete_api_days_cannot_claim_a_complete_week():
    from zhiju.services.channel_analysis_normalize import api_short_comparison,api_coverage
    w={'start':'2026-11-04','end':'2026-11-10'}
    rows=[{'day':'2026-11-10','views':0}]
    result=api_short_comparison({k:{'status':'available','rows':rows,'coverage':api_coverage(rows,w)} for k in ('7:daily','previous7:daily')})
    assert result['status']=='unavailable'
    assert result['views']['change_pct']=='unavailable'


def test_actual_r5_archive_import_freezes_the_new_input_contract(session,monkeypatch,tmp_path):
    from pathlib import Path
    from zhiju.models import SkillBundleVersion
    from zhiju.services import skill_catalog
    s,c=session
    s.add(SkillBundleVersion(category_id=skill_catalog.ANALYSIS,label='xy-yt-report-v2',revision=4,status='published',archive=skill_catalog.BUNDLE.read_bytes(),change_summary='prior revision'))
    s.commit()
    data=(Path(__file__).resolve().parents[1]/'zhiju/skill_catalog_bundles/xy-yt-report-v2-r5.zip').read_bytes()
    row=skill_catalog.upload(s,skill_catalog.ANALYSIS,'xy-yt-report-v2','dual Studio input',data)
    assert row['revision']==5
    skill_catalog.publish(s,skill_catalog.ANALYSIS,row['id']);skill_catalog.select_default(s,skill_catalog.ANALYSIS,row['id'])
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{},{}))
    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(artifact_root=tmp_path))
    run=service.create_run(s,c.id,mode='periodic',posts_not_applicable=True,ab_not_applicable=True)
    assert run.input_snapshot['studio_input_contract']=='dual-window-v1'
    assert run.input_snapshot['skill_version']['id']==row['id']
    assert 'Two native Studio' in run.input_snapshot['skill_version']['files']['SKILL.md']
    assert 'Do not require a separate 7-day ZIP' not in run.input_snapshot['rules']['asset-contract.md']
    service.add_material(s,run.id,'studio_zip','28.zip',studio_zip(28))
    image=BytesIO();Image.new('RGB',(2,2)).save(image,'PNG')
    for kind in ('videos','audience'):service.add_material(s,run.id,kind,kind+'.png',image.getvalue())
    with pytest.raises(ConflictError,match='7天'):service.start_run(s,run.id)
    service.add_material(s,run.id,'studio_zip','7.zip',studio_zip(7))
    assert service.start_run(s,run.id).status=='queued'


def test_r5_normal_executor_submits_three_documents_with_all_periods(session,monkeypatch,tmp_path):
    import json,yaml
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from urllib.parse import urlparse,parse_qs
    from test_channel_formal_analysis import formal_result
    from zhiju.v14_executor.channel_analysis import drain
    s,run=draft(session,monkeypatch,tmp_path)
    end=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=1)
    profile={'id':'UCtest','snippet':{'title':'Test','publishedAt':'2020-01-01T00:00:00Z'}}
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{'items':[profile]},profile))
    for days in (7,28):service.add_material(s,run.id,'studio_zip',str(days)+'.zip',studio_zip(days,end,views=70 if days==7 else 1000))
    service.start_run(s,run.id)
    def fetch(url,token):
        if '/videos?' in url:return {'items':[]}
        q=parse_qs(urlparse(url).query);dimension=q['dimensions'][0]
        return {'columnHeaders':[{'name':dimension},{'name':'views'}],'rows':[[str(end) if dimension=='day' else 'v1',1]]}
    class Cloud:
        tenant_id='tenant-analysis';host_id='host'
        def request(self,method,path,body=None,**kwargs):
            if path=='/auth/me':return {'tenant_id':self.tenant_id}
            if path=='/channel-analysis/claims':return service.claim_run(s,self.host_id,executor_protocol=body['executor_protocol'])
            if path.endswith('/collect'):return service.run_read(sources.collect(s,run.id,body['claim_id'],fetcher=fetch))
            if path.endswith('/heartbeat'):return {}
            if path.endswith('/screenshot-checks'):return service.run_read(service.record_screenshot_checks(s,run.id,body['claim_id'],body['result']))
            if path.endswith('/result'):return service.run_read(service.submit_result(s,run.id,body['claim_id'],result=body.get('result'),error=body.get('error')))
            return service.run_read(run)
        def download_analysis_material(self,run_id,material_id):return service.material_path(run,material_id).read_bytes()
    seen=[]
    class Model:
        account_profile='current'
        def generate(self,stage,model):
            seen.append(stage.node_type)
            result=formal_result(run)
            if stage.node_type=='channel_analysis_screenshots':
                return {'checks':{key:{**value,'observations':[]} for key,value in result['material_checks'].items()}}
            if stage.node_type=='channel_generation_spec':return {'generation_spec':result['generation_spec']}
            assert 'studio_short_windows' in stage.prompt and '70.0' in stage.prompt and '1000.0' in stage.prompt
            strategy=yaml.safe_load(service.strategy_yaml_block(result['diagnosis'])['body'])['channel_strategy']
            reference={key:{'status':'retest','conclusion':'依据7天事实待复验','evidence':['studio/recent7 table']} for key in ('positioning','empathy','reusable_patterns','title','cover','selection_guidance','validation')}
            reference['topics']={'status':'retest','primary':[],'secondary':[],'boundary':'主线关系待真实样本验收','counterexamples':[],'evidence':['studio/recent7 table']}
            strategy['operating_reference']=reference
            block=service.strategy_yaml_block(result['diagnosis'])
            result['diagnosis']=result['diagnosis'][:block.start('body')]+yaml.safe_dump({'channel_strategy':strategy},allow_unicode=True)+result['diagnosis'][block.end('body'):]
            result['normalized_snapshot']='{}';result['material_checks']={}
            return result
    drain(Cloud(),Model(),{},tmp_path/'cache',once=True)
    assert run.status=='ready',run.error
    assert set(('profile','diagnosis','generation_spec'))<=run.result.keys()
    assert run.result['normalized_snapshot']['channel_totals_28d']['metrics']['views']==1000
    assert run.result['normalized_snapshot']['studio_short_windows']['recent_7d']['totals']['metrics']['views']==70
    assert run.result['normalized_snapshot']['short_window_comparison']['ctr_change_pp']=='unavailable'
    assert seen.count('channel_analysis')==2 and seen.count('channel_generation_spec')==1
