"""Formal analysis public lifecycle: complete sources, canonical facts, delivered files."""
from datetime import datetime,timedelta
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs
from zipfile import ZipFile
import json
import pytest
import yaml
from PIL import Image
from test_channel_analysis_runs import session,valid_result
from test_channel_cold_start import registered_workspace
from zhiju.services import channel_analysis as service,channel_analysis_sources as sources
from zhiju.services.identity import ConflictError
from zhiju.v14_executor.channel_analysis import drain,stage_for,bind_analysis_result


def zip_data(end,complete=True):
    stream=BytesIO()
    with ZipFile(stream,'w') as archive:
        archive.writestr('表格数据.csv','视频 ID,展示次数,展示点击率 (%)\nv1,100,10\nv2,900,1\n')
        dates=range(28) if complete else (0,27)
        archive.writestr('图表数据.csv','日期,观看次数\n'+''.join(f'{end-timedelta(days=i)},1\n' for i in dates))
    return stream.getvalue()


def test_rejects_span_with_missing_days_and_duplicate_rows():
    end=datetime.now().date()-timedelta(days=1)
    with pytest.raises(ConflictError,match='28天'):sources.parse_studio_zip(zip_data(end,False))
    assert sources.parse_studio_zip(zip_data(end))


def formal_result(run):
    result=valid_result(run)
    result['profile']='\n'.join('## '+name+'\n来源 api/28:daily，缺失指标 unavailable。' for name in service.PROFILE_SECTIONS)
    result['diagnosis']='\n'.join('## '+name+'\n依据本次来源，建议待后续验证。' for name in service.DIAGNOSIS_SECTIONS)
    strategy={'channel_id':'UCtest','updated_at':'2026-11-02',
              'data_window':run.input_snapshot['sources']['fact_snapshot']['data_windows'],
              'strategy_confidence':'low','channel_stage':'exploration','audience_core':'unavailable','traffic_type':'unavailable'}
    for key in ('content_priority','content_secondary','content_explore','content_avoid','title_priority','title_reduce','cover_priority','cover_reduce','description_focus','community_focus','hashtag_focus','scheduling_notes'):strategy[key]=[]
    result['diagnosis']+='\n```yaml\n'+yaml.safe_dump({'channel_strategy':strategy},allow_unicode=True)+'```'
    result['normalized_snapshot']=run.input_snapshot['sources']['fact_snapshot']
    result['material_checks']={m['id']:{'identity_matches':True,'page_matches':True,'window_matches':True,'evidence':'Test UCtest，所选周期可见'} for m in run.materials if m['kind']!='studio_zip'}
    return result


@pytest.mark.parametrize('uploads_available',[True,False])
def test_formal_pipeline_paginates_inventory_and_delivers_without_apply(session,tmp_path,monkeypatch,uploads_available):
    s,c=session
    from zoneinfo import ZoneInfo
    end=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=3)
    item={'id':'UCtest','snippet':{'title':'Test','publishedAt':'2020-01-01T00:00:00Z'},
          'contentDetails':{'relatedPlaylists':{'uploads':'UUtest'}}}
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{'items':[item]},item))
    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(artifact_root=tmp_path/'artifacts'))
    run=service.create_run(s,c.id,mode='periodic',posts_not_applicable=True)
    service.add_material(s,run.id,'studio_zip','Studio.zip',zip_data(end))
    image=BytesIO();Image.new('RGB',(4,4)).save(image,format='PNG')
    for kind in ('videos','audience','ab'):service.add_material(s,run.id,kind,kind+'.png',image.getvalue())
    service.start_run(s,run.id)
    directory=registered_workspace(tmp_path,c)
    (directory/'频道用户画像与长期经营档案.md').write_text('旧报告')
    requests=[]
    def fetch(url,token):
        requests.append(url);q=parse_qs(urlparse(url).query)
        if '/playlistItems?' in url:
            if not uploads_available:raise ValueError('uploads 数据集不可用')
            if 'pageToken' not in q:return {'items':[{'contentDetails':{'videoId':'v1'}}],'nextPageToken':'next'}
            return {'items':[{'contentDetails':{'videoId':'historical'}}]}
        if '/videos?' in url:return {'items':[{'id':v,'snippet':{'title':'video '+v}} for v in q['id'][0].split(',')]}
        dimension=q['dimensions'][0]
        return {'columnHeaders':[{'name':dimension},{'name':'views'},{'name':'estimatedMinutesWatched'},{'name':'subscribersGained'}],
                'rows':[['v1' if dimension=='video' else str(end),5,10,1]]}
    class Cloud:
        tenant_id='tenant-analysis';host_id='host'
        def request(self,method,path,body=None,**kwargs):
            if path=='/auth/me':return {'tenant_id':self.tenant_id}
            if path=='/channel-analysis/claims':return service.claim_run(s,self.host_id)
            if path.endswith('/collect'):return service.run_read(sources.collect(s,run.id,body['claim_id'],fetcher=fetch))
            if path.endswith('/heartbeat'):return {}
            if path.endswith('/screenshot-checks'):return service.run_read(service.record_screenshot_checks(s,run.id,body['claim_id'],body['result']))
            if path.endswith('/result'):return service.run_read(service.submit_result(s,run.id,body['claim_id'],result=body.get('result'),error=body.get('error')))
            if path.endswith('/mirror-complete'):
                run.mirror_status='completed';self.paths=body['paths'];s.commit();return {}
            return service.run_read(run)
        def download_analysis_material(self,run_id,material_id):return service.material_path(run,material_id).read_bytes()
    class Model:
        account_profile='current'
        def generate(self,stage,model):
            if stage.node_type=='channel_generation_spec':
                assert json.loads(stage.prompt.split('\n',1)[1])['profile']==formal_result(run)['profile']
                return {'generation_spec':formal_result(run)['generation_spec']}
            if stage.node_type=='channel_analysis_screenshots':
                checks=formal_result(run)['material_checks']
                for material in run.materials:
                    if material['kind']=='studio_zip':continue
                    check=checks[material['id']]
                    check['observations']=[{'metric':'visible_test_metric','subject':'test','value':123,
                        'status':'available','unit':'count','scope':'test card','window':'selected window','evidence':'test fixture'}]
                    if material['kind']=='ab':check['window_matches']=False
                return {'checks':{key:checks[key] for key in stage.schema['properties']['checks']['properties']}}
            assert 'columnHeaders' not in stage.prompt
            assert '展示点击率 (%)' in stage.prompt
            assert '900' in stage.prompt or '100' in stage.prompt
            assert 'sources.fact_snapshot' in stage.prompt
            assert stage.images==[]
            assert set(stage.schema['properties']) in ({'profile'},{'diagnosis'})
            result=formal_result(run)
            result['normalized_snapshot']='{"fabricated":999}'
            result['material_checks']={}
            return result
    cloud=Cloud();drain(cloud,Model(),{'analysis_workspace_root':str(tmp_path)},tmp_path/'cache',once=True)
    assert run.status=='ready',run.error
    assert not list((tmp_path/'cache').iterdir())
    block=__import__('re').search(r'```yaml\s*\n(.*?)```',run.result['diagnosis'],__import__('re').S)
    assert yaml.safe_load(block[1])['channel_strategy']['channel_id']=='UCtest'
    assert (directory/'频道用户画像与长期经营档案.md').read_text()=='旧报告'
    assert not (directory/'分析数据').exists()

def test_missing_numeric_sources_remain_unavailable():
    from zhiju.services.channel_analysis_normalize import normalize_sources,formal_snapshot
    raw={'api':{'28:videos':{'status':'unavailable','reason':'API failure','pages':[]}},
         'windows':{'28':{},'90':{}},'studio':{}}
    raw['normalized']=normalize_sources(raw,{'youtube_channel_id':'UCtest'},'periodic')
    facts=formal_snapshot(raw,{'youtube_channel_id':'UCtest'})
    assert facts['concentration_28d']=='unavailable'
    assert facts['traffic_28d_video_pct']['shares_percent']=='unavailable'
    assert facts['channel_totals_28d']=='unavailable'


def test_explicit_apply_delivers_selected_older_completed_version(session,tmp_path):
    from test_channel_analysis_runs import complete
    s,c=session
    older=complete(s,c);older.mirror_status='completed';s.commit()
    newer=complete(s,c);newer.mirror_status='completed';s.commit()
    service.apply_result(s,older.id)
    assert older.status=='applied'
    assert older.mirror_status=='completed'
    assert newer.status=='ready'


def test_later_report_supersedes_pending_older_delivery(session):
    from test_channel_analysis_runs import complete
    s,c=session
    older=complete(s,c);older.mirror_status='failed';s.commit()
    newer=complete(s,c)
    assert older.mirror_status=='superseded'
    # An explicit user selection can still re-deliver that version.
    service.apply_result(s,older.id)
    assert older.mirror_status=='superseded'


def test_studio_ctr_survives_unavailable_api_video_report():
    from zhiju.v14_executor.channel_analysis import analysis_prompt_snapshot
    data={'sources':{'fact_snapshot':{'video_inventory':[], 'studio_content':[
        {'video_id':'studio-only','values':{'观看次数':'100','展示点击率 (%)':'3.4'},'source':'studio/table.csv','scope':'exported_content_row'}]}}}
    prompt=analysis_prompt_snapshot(data)
    assert prompt['sources']['fact_snapshot']['studio_content'][0]['video_id']=='studio-only'


def test_apply_cancels_other_pending_delivery_and_drain_keeps_selection(session,tmp_path,monkeypatch):
    from zhiju.services.channel_analysis_normalize import normalize_sources,formal_snapshot
    s,c=session
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{},{}))
    runs=[]
    for label in ('A','B'):
        run=service.create_run(s,c.id,mode='periodic')
        # Seed the accepted-source stage; full upload/collect validation is exercised above.
        run.status='queued';s.commit();claim=service.claim_run(s,'host')
        raw={'api':{},'windows':{'28':{},'90':{}}}
        raw['normalized']=normalize_sources(raw,run.input_snapshot['channel'],'periodic')
        raw['fact_snapshot']=formal_snapshot(raw,run.input_snapshot['channel'])
        run.input_snapshot={**run.input_snapshot,'sources':raw,'sources_complete':True}
        result=formal_result(run);result['profile']+='\n版本'+label
        run=service.submit_result(s,run.id,claim['claim_id'],result=result)
        run.mirror_status='completed' if label=='A' else 'failed';s.commit();runs.append(run)
        folder=tmp_path/'cache'/run.id;folder.mkdir(parents=True)
        (folder/'submitted.json').write_text(json.dumps({'run_id':run.id}))
    directory=registered_workspace(tmp_path,c)
    service.apply_result(s,runs[0].id)
    assert runs[1].mirror_status=='superseded'
    class Cloud:
        host_id='host';tenant_id='tenant-analysis'
        def request(self,method,path,body=None,**kwargs):
            if path=='/auth/me':return {'tenant_id':self.tenant_id}
            if path=='/channel-analysis/claims':return None
            run=service.get_run(s,path.split('/')[2])
            if path.endswith('/mirror-complete'):
                run.mirror_status='completed';s.commit();return {}
            return service.run_read(run)
    drain(Cloud(),SimpleNamespace(),{'analysis_workspace_root':str(tmp_path)},tmp_path/'cache')
    assert not (directory/'频道用户画像与长期经营档案.md').exists()
    assert not list((tmp_path/'cache').iterdir())


def test_result_binding_rejects_foreign_channel_and_keeps_program_facts():
    run={'input_snapshot':{'channel':{'id':'platform-id','youtube_channel_id':'UCcorrect'}}}
    original={'diagnosis':'## Strategy\n```yaml\nchannel_strategy:\n  channel_id: platform-id\n```',
        'material_checks':{'shot':{'basis':'Observed channel name and dates','identity_matches':True}},
        'normalized_snapshot':{'views':123}}
    result=bind_analysis_result(original,run)
    assert 'channel_id: UCcorrect' in result['diagnosis']
    assert 'channel_id: platform-id' in original['diagnosis']
    assert result['normalized_snapshot']==original['normalized_snapshot']
    assert result['material_checks']['shot']['evidence']=='Observed channel name and dates'
    original['diagnosis']=original['diagnosis'].replace('platform-id','UCforeign')
    with pytest.raises(ValueError,match='频道身份不符'):bind_analysis_result(original,run)


def test_main_screenshot_window_and_identity_remain_required(session):
    s,c=session
    run=service.create_run(s,c.id,mode='initial',positioning='新频道')
    run.mode='periodic'
    facts=valid_result(run)['normalized_snapshot']
    facts['data_windows']={'recent_28d':'test-window','recent_90d':'test-window'}
    run.input_snapshot={**run.input_snapshot,'sources_complete':True,'sources':{'fact_snapshot':facts}}
    run.materials=[{'id':'video','kind':'videos','name':'video.png'},{'id':'ab','kind':'ab','name':'ab.png'}]
    result=formal_result(run)
    result['material_checks']['ab']['window_matches']=False
    assert service.validate_result(run,result)
    result['material_checks']['video']['window_matches']=False
    with pytest.raises(ConflictError,match='video.png'):service.validate_result(run,result)
    result['material_checks']['video']['window_matches']=True
    result['material_checks']['ab']['identity_matches']=False
    with pytest.raises(ConflictError,match='ab.png'):service.validate_result(run,result)


def test_studio_aggregate_aliases_complete_ranking_and_api_observed_coverage():
    from zhiju.services.channel_analysis_normalize import normalize_sources,formal_snapshot
    row=lambda identity,views,impressions,ctr,duration,returning: {'内容':identity,'观看次数':str(views),
        '缩略图展示次数':str(impressions),'缩略图点击率 (%)':str(ctr),'时长':str(duration),
        '视频发布时间':'Oct 31, 2026','回访观看者人数':str(returning),'平均观看时长':'0:15:11'}
    raw={'api':{'28:daily':{'status':'available','window':{'start':'2026-10-04','end':'2026-10-31'},
        'pages':[{'columnHeaders':[{'name':'day'},{'name':'views'}],'rows':[['2026-10-30',100]]}]},
        '28:videos':{'status':'available','pages':[{'columnHeaders':[{'name':'video'},{'name':'views'}],'rows':[['other',100]]}]}},
        'windows':{'28':{'end':'2026-10-31'},'90':{}},
        'studio':{'zip':{'表格数据.csv':[row('总计',1000,2000,10,0,0),row('largest',900,1800,11,2100,8),row('short',100,200,1,60,2)],
            '总计.csv':[{'日期':'2026-10-04','回访观看者人数':'0'}]}}}
    raw['normalized']=normalize_sources(raw,{'id':'test'},'periodic')
    facts=formal_snapshot(raw,{'id':'test'})
    assert facts['channel_totals_28d']['metrics']['views']==1000
    assert facts['channel_totals_28d']['metrics']['average_view_duration_seconds']==911
    assert facts['channel_totals_28d']['metrics']['returning_viewers']=='unavailable'
    assert facts['channel_totals_28d']['metrics']['revenue']=='unavailable'
    assert facts['impression_weighted_ctr']['value_percent']==10
    assert facts['concentration_28d']['top_1_share_pct']==90
    assert facts['top_videos_28d']['rows'][0]['video']=='largest'
    ids=[{r['video'] for r in facts[k]['rows']} for k in ('top_videos_28d','middle_videos_28d','low_videos_28d')]
    assert not any(ids[a]&ids[b] for a,b in [(0,1),(0,2),(1,2)])
    assert facts['trend']['recent_28d']['coverage']['observed_end']=='2026-10-30'
    assert facts['trend']['recent_28d']['coverage']['requested_end_returned'] is False
    assert set(facts['comparable_video_groups'])=={'over_3_minutes/early','up_to_3_minutes/early'}


def test_screenshot_numbers_keep_scope_and_missing_values_are_not_zero():
    from zhiju.services.channel_analysis_normalize import normalize_sources,formal_snapshot,validate_screenshot_observations
    check={'identity_matches':True,'page_matches':True,'window_matches':True,'evidence':'Female 86.8%',
        'observations':[{'metric':'female_pct','subject':'female','value':86.8,'unit':'percent','status':'available',
        'scope':'audience gender card','window':'2026-10-04/2026-10-31','evidence':'女性86.8%'}]}
    raw={'api':{},'windows':{'28':{},'90':{}},'screenshots':[{'id':'shot','kind':'audience'}],'screenshot_checks':{'shot':check}}
    validate_screenshot_observations(raw['screenshot_checks'])
    raw['normalized']=normalize_sources(raw,{},'periodic');facts=formal_snapshot(raw,{})
    record=facts['audience_28d']['studio_segments']['observations'][0]
    assert record['value']==86.8 and record['source']=='screenshot/shot'
    assert record['scope']=='audience gender card'
    check['observations'][0]['status']='unavailable';check['observations'][0]['value']=0
    with pytest.raises(ValueError,match='缺失指标'):validate_screenshot_observations({'shot':check})


@pytest.mark.parametrize('fence',['```','~~~'])
def test_strategy_markdown_fences_validate_and_bind(session,fence):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='新频道')
    result=valid_result(run);result['diagnosis']=result['diagnosis'].replace('```',fence)
    result['material_checks']={}
    assert service.validate_result(run,result)
    result['diagnosis']=result['diagnosis'].replace('channel_id: UCtest','channel_id: '+run.channel_id)
    bound=bind_analysis_result(result,service.run_read(run))
    assert 'channel_id: UCtest' in bound['diagnosis']
    assert service.validate_result(run,bound)
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    service.submit_result(s,run.id,claim['claim_id'],result=bound)
    assert service.apply_result(s,run.id).status=='applied'


@pytest.mark.parametrize('window,same,within',[
    ('2026-10-04/2026-10-31（过去28天）',True,True),
    ('最新视频（过去365天）',False,None),('过去7天',False,None),
    ('2026-10-27－现在（自发布以来）',False,None),
    ('2026-10-27 21:00至2026-10-30 02:42',False,True),
    ('2026-10-31 21:01至2026-11-01 08:44',False,False),
    ('月度观众人数·2026-10-31',None,None)])
def test_each_screenshot_card_keeps_its_own_window(window,same,within):
    from zhiju.services.channel_analysis_normalize import observation_window_coverage
    actual=observation_window_coverage(window,{'start':'2026-10-04','end':'2026-10-31'})
    assert actual=={'matches_formal_window':same,'within_formal_window':within}
