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
from zhiju.v14_executor.channel_analysis import drain,stage_for


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
            if path.endswith('/result'):return service.run_read(service.submit_result(s,run.id,body['claim_id'],result=body.get('result'),error=body.get('error')))
            if path.endswith('/mirror-complete'):
                run.mirror_status='completed';self.paths=body['paths'];s.commit();return {}
            return service.run_read(run)
        def download_analysis_material(self,run_id,material_id):return service.material_path(run,material_id).read_bytes()
    class Model:
        account_profile='current'
        def generate(self,stage,model):
            assert 'columnHeaders' not in stage.prompt
            assert '展示点击率 (%)' in stage.prompt
            assert '900' in stage.prompt or '100' in stage.prompt
            assert 'sources.fact_snapshot' in stage.prompt
            result=formal_result(run)
            result['normalized_snapshot']='{"fabricated":999}'
            result['material_checks']=json.dumps(result['material_checks'])
            return result
    cloud=Cloud();drain(cloud,Model(),{'analysis_workspace_root':str(tmp_path)},tmp_path/'cache',once=True)
    assert run.status=='ready',run.error
    assert run.mirror_status=='completed'
    assert set(cloud.paths)=={'profile','diagnosis','generation_spec','normalized_snapshot'}
    assert (directory/'频道用户画像与长期经营档案.md').read_text()==run.result['profile']
    history=next((directory/'分析数据').iterdir())
    assert (history/'更新前文件/频道用户画像与长期经营档案.md').read_text()=='旧报告'
    assert len(list((history/'截图/A_B测试').iterdir()))==1
    assert (history/'API原始数据/28:daily.json').is_file()
    facts=run.result['normalized_snapshot']
    assert 'fabricated' not in facts
    assert facts['impression_weighted_ctr']['value_percent']==pytest.approx(1.9)
    assert facts['data_windows']['recent_28d']['end']==str(end)
    if uploads_available:assert 'historical' in facts['unmatched_video_ids']
    else:assert facts['video_inventory_coverage']=={'status':'unavailable','reason':'uploads 数据集不可用'}
    assert any('likes%2Ccomments%2Cshares' in url for url in requests)
    assert len([url for url in requests if '/playlistItems?' in url])==(2 if uploads_available else 1)
    result=formal_result(run);result['normalized_snapshot']={**facts,'concentration_28d':0}
    with pytest.raises(ConflictError,match='事实快照'):service.validate_result(run,result)
    result=formal_result(run);result['diagnosis']=result['diagnosis'].replace('title_priority: []','title_priority: fabricated')
    with pytest.raises(ConflictError,match='字符串列表'):service.validate_result(run,result)
    (directory/'频道用户画像与长期经营档案.md').write_text('更新的报告不应被旧缓存覆盖')
    drain(cloud,Model(),{'analysis_workspace_root':str(tmp_path)},tmp_path/'cache',once=True)
    assert (directory/'频道用户画像与长期经营档案.md').read_text()=='更新的报告不应被旧缓存覆盖'


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
    assert older.mirror_status=='pending'
    assert newer.status=='ready'


def test_later_report_supersedes_pending_older_delivery(session):
    from test_channel_analysis_runs import complete
    s,c=session
    older=complete(s,c);older.mirror_status='failed';s.commit()
    newer=complete(s,c)
    assert older.mirror_status=='superseded'
    # An explicit user selection can still re-deliver that version.
    service.apply_result(s,older.id)
    assert older.mirror_status=='pending'


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
    assert (directory/'频道用户画像与长期经营档案.md').read_text().endswith('版本A')
