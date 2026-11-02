"""Workflow-level cases independent of any production channel or model calls."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from io import BytesIO
from zipfile import ZipFile
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import json
import pytest
from PIL import Image
from test_channel_analysis_runs import session
from test_channel_cold_start import create,result_for,registered_workspace
from test_channel_formal_analysis import formal_result
from zhiju.services import channel_analysis as service,channel_analysis_sources as sources
from zhiju.services.channel_analysis_normalize import normalize_sources,formal_snapshot,studio_content_type
from zhiju.v14_executor.channel_analysis import prepare_formal_context,analysis_prompt_snapshot,screenshot_stage,generation_spec_stage
from zhiju.services.identity import ConflictError


@pytest.mark.parametrize('channel_identity',['UCtest','UCSecondChannel'])
@pytest.mark.parametrize('api_available',[False,True])
def test_studio_only_video_survives_api_gaps_and_binds_screenshot(session,tmp_path,monkeypatch,channel_identity,api_available):
    s,c=session;c.youtube_channel_id=channel_identity;s.commit()
    end=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=1)
    profile={'id':channel_identity,'snippet':{'title':'Test','publishedAt':'2020-01-01T00:00:00Z'},'statistics':{'viewCount':'123','hiddenSubscriberCount':True}}
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{'items':[profile]},profile))
    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(artifact_root=tmp_path/'artifacts'))
    run=service.create_run(s,c.id,mode='periodic',posts_not_applicable=True,ab_not_applicable=True)
    zipbytes=BytesIO()
    with ZipFile(zipbytes,'w') as z:
        z.writestr('表格数据.csv','内容,观看次数,内容类型\nc8C4kJ8TXDI,90,视频\n')
        z.writestr('图表数据.csv','日期,观看次数\n'+''.join(f'{end-timedelta(days=i)},1\n' for i in range(28)))
    service.add_material(s,run.id,'studio_zip','Studio.zip',zipbytes.getvalue())
    image=BytesIO();Image.new('RGB',(2,2)).save(image,'PNG')
    for kind in ('videos','audience'):service.add_material(s,run.id,kind,kind+'.png',image.getvalue())
    service.start_run(s,run.id);claim=service.claim_run(s,'host');requested=[]
    def fetch(url,token):
        if '/videos?' in url:
            requested.extend(parse_qs(urlparse(url).query)['id'][0].split(','))
            return {'items':[]} # Deleted/private video details may genuinely be unavailable.
        if not api_available:raise ValueError('Analytics dataset unavailable')
        return {'columnHeaders':[{'name':'day'},{'name':'views'}],'rows':[[str(end),1]]}
    sources.collect(s,run.id,claim['claim_id'],fetcher=fetch)
    assert 'c8C4kJ8TXDI' in requested
    facts=run.input_snapshot['sources']['fact_snapshot']
    assert facts['top_videos_28d']['rows'][0]['video']=='c8C4kJ8TXDI'
    assert facts['channel_public_data']['identity'][0]['statistics']==profile['statistics']
    assert facts['community_posts']=='not_applicable' and facts['ab_testing']=='not_applicable'
    schema=screenshot_stage(service.run_read(run),tmp_path).schema
    check=next(iter(schema['properties']['checks']['properties'].values()))
    assert 'c8C4kJ8TXDI' in check['properties']['video_id']['enum']
    result=formal_result(run)
    for check in result['material_checks'].values():check.update(video_id='c8C4kJ8TXDI',observations=[])
    service.record_screenshot_checks(s,run.id,claim['claim_id'],result['material_checks'])
    result['normalized_snapshot']=run.input_snapshot['sources']['fact_snapshot']
    result['diagnosis']=result['diagnosis'].replace('UCtest',channel_identity)
    assert service.submit_result(s,run.id,claim['claim_id'],result=result).status=='ready'


def test_mixed_export_separates_posts_from_video_ranking():
    raw={'api':{},'windows':{'28':{},'90':{}},'studio':{'zip':{'表格数据.csv':[
        {'内容':'总计','观看次数':'1010'},
        {'内容':'video','观看次数':'10','内容类型':'视频'},
        {'内容':'Ugpost','观看次数':'1000','内容类型':'帖子'}]}}}
    raw['normalized']=normalize_sources(raw,{},'periodic');facts=formal_snapshot(raw,{})
    assert facts['concentration_28d']['total_views']==10
    assert facts['top_videos_28d']['rows'][0]['video']=='video'
    assert facts['community_posts']['studio_rows'][0]['video_id']=='Ugpost'
    assert facts['video_metric_coverage']['studio_rows']==1
    assert facts['video_metric_coverage']['exported_content_rows']==2
    assert 'Ugpost' not in facts['video_metric_coverage']['unranked_studio_ids']
    assert all(row['video_id']!='Ugpost' for row in facts['video_source_coverage'])
    assert studio_content_type({'Content type':'Video'},'Ug123456789')=='video'


@pytest.mark.parametrize('stage',['submit','apply'])
def test_cold_start_cannot_overwrite_new_measurements(session,stage):
    from zhiju.models import YoutubeChannelDailyMetric
    s,c=session;run=create(s,c);service.start_run(s,run.id);claim=service.claim_run(s,'host')
    if stage=='apply':service.submit_result(s,run.id,claim['claim_id'],result=result_for(run))
    s.add(YoutubeChannelDailyMetric(channel_id=c.id,metric_date=datetime.now().date(),views=3,synced_at=datetime.now(timezone.utc)));s.commit()
    with pytest.raises(ConflictError,match='公开运营数据'):
        if stage=='submit':service.submit_result(s,run.id,claim['claim_id'],result=result_for(run))
        else:service.apply_result(s,run.id)


def test_local_drama_and_history_feed_sequential_spec_stage(session,tmp_path):
    s,c=session;run=service.create_run(s,c.id,mode='initial',positioning='legacy')
    folder=registered_workspace(tmp_path,c)
    (folder/'频道用户画像与长期经营档案.md').write_text('历史档案')
    drama=folder/'剧目/准确绑定';drama.mkdir(parents=True)
    (drama/'剧目元数据.json').write_text(json.dumps({'video_id':'c8C4kJ8TXDI','drama_name':'真实剧名'}))
    (drama/'飞书剧情原始行.json').write_text(json.dumps({'plot_fields':{'剧情':'真实剧情，不按标题猜测'}}))
    context=prepare_formal_context(service.run_read(run),tmp_path)
    assert context['drama_mapping'][0]['plot']=='真实剧情，不按标题猜测'
    data=service.run_read(run);data['input_snapshot']['local_analysis_context']=context
    data['input_snapshot']['previous_analysis']={'profile':'旧云端档案','normalized_snapshot':{'must_not_be_prompt':'large'}}
    stage=generation_spec_stage(data,{'profile':'本次档案','diagnosis':'本次诊断'})
    payload=json.loads(stage.prompt.split('\n',1)[1])
    assert payload['profile']=='本次档案' and payload['diagnosis']=='本次诊断'
    assert payload['previous_local_documents']['profile']=='历史档案'
    assert 'normalized_snapshot' not in payload['previous_analysis']
    assert stage.schema['required']==['generation_spec']


def test_spec_retry_reuses_analysis_but_changed_inputs_regenerate(session,tmp_path):
    from zhiju.v14_executor.channel_analysis import generate_documents
    s,c=session;run=create(s,c);data=service.run_read(run);calls=[]
    class Model:
        fail=True
        def generate(self,stage,model):
            calls.append(stage.node_type)
            if stage.node_type=='channel_generation_spec':
                if self.fail:raise RuntimeError('temporary model interruption')
                return {'generation_spec':'规范'}
            return {'profile':'档案','diagnosis':'诊断'}
    model=Model()
    with pytest.raises(RuntimeError):generate_documents(model,data,tmp_path)
    model.fail=False
    assert generate_documents(model,data,tmp_path)['generation_spec']=='规范'
    assert calls==['channel_analysis','channel_generation_spec','channel_generation_spec']
    data['input_snapshot']['positioning']='用户更新了初始定位'
    generate_documents(model,data,tmp_path)
    assert calls[-2:]==['channel_analysis','channel_generation_spec']


def test_frozen_retry_merges_local_context_without_new_api(session,monkeypatch):
    from copy import deepcopy
    s,c=session
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:('token',{},{}))
    run=service.create_run(s,c.id,mode='periodic');run.status='queued';s.commit();claim=service.claim_run(s,'host')
    raw={'api':{},'windows':{'28':{},'90':{}}};raw['normalized']=normalize_sources(raw,run.input_snapshot['channel'],'periodic');raw['fact_snapshot']=formal_snapshot(raw,run.input_snapshot['channel'])
    frozen_time=raw['fact_snapshot']['generated_at']
    run.input_snapshot={**run.input_snapshot,'sources':raw,'sources_complete':True,'normalization_revision':3,'local_analysis_context':{'drama_mapping':[{'youtube_video_id':'local-video','plot':'事实剧情','local_metadata_source':'confirmed metadata'}]}};s.commit()
    sources.collect(s,run.id,claim['claim_id'],fetcher=lambda *a:pytest.fail('frozen retry must not refetch'))
    assert run.input_snapshot['sources']['video_drama_mapping'][0]['plot']=='事实剧情'
    assert run.input_snapshot['sources']['fact_snapshot']['generated_at']==frozen_time
    frozen=deepcopy(run.input_snapshot['sources']['fact_snapshot'])
    sources.collect(s,run.id,claim['claim_id'],fetcher=lambda *a:pytest.fail('no refetch'))
    assert run.input_snapshot['sources']['fact_snapshot']==frozen


def test_cold_start_resume_preserves_frozen_sources_without_api(session):
    from copy import deepcopy
    s,c=session;run=create(s,c);service.start_run(s,run.id);claim=service.claim_run(s,'host')
    sources.collect(s,run.id,claim['claim_id'],fetcher=lambda *a:pytest.fail('cold start no API'))
    frozen=deepcopy(run.input_snapshot['sources'])
    service.submit_result(s,run.id,claim['claim_id'],error='generation_spec stage interrupted')
    service.resume_run(s,run.id,stopped_confirmed=True);claim=service.claim_run(s,'host')
    sources.collect(s,run.id,claim['claim_id'],fetcher=lambda *a:pytest.fail('no API'))
    assert run.input_snapshot['sources']==frozen


def test_formal_authorization_failure_prevents_task_creation(session,monkeypatch):
    from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired
    s,c=session
    def denied(*args):raise YouTubeAuthorizationRequired('缺少频道 Analytics 读取权限')
    monkeypatch.setattr(sources,'verify_authorization',denied)
    with pytest.raises(YouTubeAuthorizationRequired):service.create_run(s,c.id,mode='periodic')
    assert service.list_runs(s,c.id)==[]


def test_new_scope_revision_preserves_original_skill_archive():
    from zipfile import ZipFile
    root=Path(__file__).parents[1]/'zhiju/skill_catalog_bundles'
    with ZipFile(root/'xy-yt-report-v2.zip') as old,ZipFile(root/'xy-yt-report-v2-r2.zip') as new:
        assert old.read('SKILL.md')==new.read('SKILL.md')
        assert b'exact all-content 28-day totals' in old.read('references/analysis-rules.md')
        assert b'studio_exported_content' in new.read('references/analysis-rules.md')
        assert b'exported-content/video-only scopes' in new.read('references/output-contract.md')


def test_post_only_export_does_not_select_video_drama_fallback():
    snapshot={'sources':{'fact_snapshot':{'studio_content':[{'video_id':'post','content_type':'post','values':{'观看次数':'100'}}]},
        'video_drama_mapping':[{'youtube_video_id':'post','plot':'不能当作视频样本'}]}}
    prompt=analysis_prompt_snapshot(snapshot)
    assert prompt['sources']['video_drama_mapping']==[]


def test_analysis_stage_describes_already_verified_screenshot_evidence():
    from zhiju.v14_executor.channel_analysis import stage_for
    run={'mode':'periodic','materials':[{'id':'shot','kind':'videos','suffix':'.png'}],
        'input_snapshot':{'channel':{},'sources':{'fact_snapshot':{},'screenshot_checks':{'shot':{'identity_matches':True,'page_matches':True,'window_matches':True,'evidence':'频道和日期已核实'}}}}}
    stage=stage_for(run,Path('/tmp/unused'))
    assert stage.images==[]
    assert '截图已由前置阶段逐图核验' in stage.prompt
    assert '不得因本阶段无图片附件宣称全流程未提供或未核验截图' in stage.prompt
    assert '本机已提供实际截图附件' not in stage.prompt
