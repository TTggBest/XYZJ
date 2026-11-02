from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from sqlalchemy import select
from test_channel_analysis_runs import session,valid_result
from test_v14_api import client,PRINCIPAL
from test_v14_runs import store
from zhiju.services import channel_analysis as service
from zhiju.services import channel_analysis_sources as sources
from zhiju.services.identity import ConflictError
from zhiju.v14_executor.channel_analysis import drain,mirror


def authorize(s,c):
    from datetime import datetime,timezone
    from zhiju.models import AccountChannelAuthorization,OAuthGrant
    grant=OAuthGrant(account_id='cold-account',provider_subject='cold-subject',credential_ref='unused',status='active')
    s.add(grant);s.flush()
    s.add(AccountChannelAuthorization(account_id='cold-account',channel_id=c.id,oauth_grant_id=grant.id,
        status='active',verified_youtube_channel_id=c.youtube_channel_id,verified_at=datetime.now(timezone.utc)))
    s.commit()


def authorize_client(store):
    from zhiju.database import TenantSession
    from zhiju.models import Channel
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        authorize(s,s.get(Channel,'channel-a'))


def create(s,c):
    authorize(s,c)
    return service.create_run(s,c.id,mode='initial',cold_start=True,
        initial_facts={'chinese_meaning':'测试频道','language':'en','market':'美国'})


def result_for(run):
    result=valid_result(run)
    result['generation_spec']=result['generation_spec'].replace('未配置','美国')
    result['profile']='冷启动，未经数据验证\n'+'\n'.join('## '+name+'\n待验证的初始假设，实测指标 unavailable。' for name in service.PROFILE_SECTIONS)
    result['diagnosis']='冷启动，未经数据验证\n'+'\n'.join('## '+name+'\n待验证的编辑方向。' for name in service.DIAGNOSIS_SECTIONS)
    strategy={'channel_id':run.input_snapshot['channel']['youtube_channel_id'],'updated_at':'2026-11-02',
        'data_window':{'recent_28d':'unavailable','recent_90d':'unavailable'},'strategy_confidence':'low',
        'channel_stage':'exploration','audience_core':'unavailable','traffic_type':'unavailable'}
    for key in ('content_priority','content_secondary','content_explore','content_avoid','title_priority','title_reduce','cover_priority','cover_reduce','description_focus','community_focus','hashtag_focus','scheduling_notes'):strategy[key]=[]
    result['diagnosis']+='\n```yaml\n'+yaml.safe_dump({'channel_strategy':strategy},allow_unicode=True,sort_keys=False)+'```'
    result['normalized_snapshot']=service.cold_start_snapshot(run.input_snapshot['channel'],run.input_snapshot['initial_facts'])
    return result


def test_cold_start_has_frozen_actual_skill_without_api_or_assets(session,monkeypatch):
    s,c=session
    monkeypatch.setattr(sources,'verify_authorization',lambda *a:pytest.fail('cold start must not call live authorization API'))
    run=create(s,c)
    assert run.input_snapshot['skill_version']['label']=='channel-initial-audience'
    assert '新频道冷启动定位' in run.input_snapshot['skill_version']['files']['SKILL.md']
    assert 'authorization.md' not in run.input_snapshot['rules']
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    sources.collect(s,run.id,claim['claim_id'],fetcher=lambda *a:pytest.fail('no external API'))
    accepted=service.submit_result(s,run.id,claim['claim_id'],result=result_for(run))
    assert accepted.status=='ready'
    assert accepted.materials==[]
    assert accepted.result['normalized_snapshot']['snapshot_status']=='cold_start_no_analytics'


def test_cold_start_rejects_measured_report(session):
    s,c=session
    from zhiju.models import ChannelAnalysisReport
    s.add(ChannelAnalysisReport(channel_id=c.id,version_number=1,report_type='periodic',status='completed',generated_by='codex'))
    s.commit()
    with pytest.raises(ConflictError,match='实测'):
        create(s,c)


@pytest.mark.parametrize('mutation',['metric_zero','sections','confidence'])
def test_cold_start_rejects_fabricated_metrics_and_invalid_contract(session,mutation):
    s,c=session;run=create(s,c);service.start_run(s,run.id);claim=service.claim_run(s,'host')
    result=result_for(run)
    if mutation=='metric_zero':result['normalized_snapshot']['trend']=0
    if mutation=='sections':result['profile']=result['profile'].replace('Channel basics','fake')
    if mutation=='confidence':result['diagnosis']=result['diagnosis'].replace('strategy_confidence: low','strategy_confidence: high')
    with pytest.raises(ConflictError):service.submit_result(s,run.id,claim['claim_id'],result=result)


def registered_workspace(tmp_path,c):
    folder=tmp_path/'channels/Test';folder.mkdir(parents=True)
    registry=tmp_path/'运营/工作流运营/公用/频道注册表.json';registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'channels':[{'url':'https://www.youtube.com/channel/'+c.youtube_channel_id,'channel_dir':str(folder)}]}))
    (folder/'频道初始定位.md').write_text('用户已确认：女性逆袭初始题材。')
    return folder


def test_real_executor_adapter_to_service_delivers_four_files_before_apply(session,tmp_path):
    s,c=session;run=create(s,c);service.start_run(s,run.id)
    directory=registered_workspace(tmp_path,c)
    class Cloud:
        host_id='host';tenant_id='tenant-analysis'
        def request(self,method,path,body=None,**kwargs):
            if path=='/auth/me':return {'tenant_id':self.tenant_id}
            if path=='/channel-analysis/claims':return service.claim_run(s,self.host_id)
            if path.endswith('/collect'):return service.run_read(sources.collect(s,run.id,body['claim_id'],fetcher=lambda *a:pytest.fail('no API')))
            if path.endswith('/heartbeat'):return {}
            if path.endswith('/result'):
                return service.run_read(service.submit_result(s,run.id,body['claim_id'],result=body.get('result'),error=body.get('error')))
            if path.endswith('/mirror-complete'):
                self.paths=body.get('paths');return {}
            return service.run_read(service.get_run(s,run.id))
    class Model:
        account_profile='current'
        def generate(self,stage,model):
            if stage.node_type=='channel_generation_spec':
                assert json.loads(stage.prompt.split('\n',1)[1])['profile']==result_for(run)['profile']
                return {'generation_spec':result_for(run)['generation_spec']}
            assert 'channel-initial-audience' in stage.prompt
            assert '女性逆袭初始题材' in stage.prompt
            assert not stage.images
            result=result_for(run)
            result['normalized_snapshot']='{}' # The executor supplies authoritative facts, never model metrics.
            result['material_checks']='{}'
            return result
    cloud=Cloud()
    drain(cloud,Model(),{'analysis_workspace_root':str(tmp_path)},tmp_path/'cache',once=True)
    assert service.get_run(s,run.id).status=='ready'
    assert set(cloud.paths)=={'profile','diagnosis','generation_spec','normalized_snapshot'}
    assert all(Path(p).is_file() for p in cloud.paths.values())
    snapshot=json.loads(Path(cloud.paths['normalized_snapshot']).read_text())
    assert snapshot['snapshot_status']=='cold_start_no_analytics'
    assert snapshot['trend']=='unavailable'
    assert 'existing_positioning_document' in snapshot['initial_facts']
    history=Path(cloud.paths['normalized_snapshot']).parents[1]
    assert not (history/'API原始数据').exists()
    assert not (history/'截图').exists()
    assert (directory/'频道初始定位.md').read_text()=='用户已确认：女性逆袭初始题材。'
    assert len(list((history/'最终文件快照').iterdir()))==3


def test_local_mirror_refuses_measured_files(session,tmp_path):
    s,c=session;run=create(s,c);directory=registered_workspace(tmp_path,c)
    original=directory/'频道用户画像与长期经营档案.md';original.write_text('已有真实数据报告，不得覆盖')
    data=service.run_read(run);data['result']=result_for(run)
    with pytest.raises(OSError,match='非冷启动'):mirror(data,tmp_path/'cache',tmp_path)
    assert original.read_text()=='已有真实数据报告，不得覆盖'


def test_cold_start_user_api_queues_without_material_form(client,store):
    authorize_client(store)
    response=client.post('/api/v3/channels/channel-a/cold-start',json={'language':'en','market':'美国'})
    assert response.status_code==200,response.text
    assert response.json()['status']=='queued'
    assert response.json()['input_snapshot']['cold_start'] is True


def test_local_registry_fills_market_before_missing_input_prompt(session,tmp_path):
    from zhiju.v14_executor.channel_analysis import prepare_cold_start
    s,c=session
    authorize(s,c)
    run=service.create_run(s,c.id,mode='initial',cold_start=True)
    registered_workspace(tmp_path,c)
    registry=tmp_path/'运营/工作流运营/公用/频道注册表.json'
    data=json.loads(registry.read_text());data['channels'][0].update(language='en',market='美国')
    registry.write_text(json.dumps(data))
    normalized=prepare_cold_start(service.run_read(run),tmp_path)
    assert normalized['channel']['country_name_zh']=='美国'
    assert normalized['snapshot_status']=='cold_start_no_analytics'


def test_cloud_accepts_bound_executor_confirmed_local_market_before_collect(client,store):
    authorize_client(store)
    run=client.post('/api/v3/channels/channel-a/cold-start',json={}).json()
    assert run['status']=='queued'
    claim=client.post('/api/v3/channel-analysis/claims',json={'host_id':'device-a'}).json()
    response=client.post(f"/api/v3/analysis-runs/{run['id']}/collect",json={
        'claim_id':claim['claim_id'],'initial_context':{'channel':{'country_name_zh':'美国','default_language':'en'},'source_manifest':[{'type':'local_registry'}]}})
    assert response.status_code==200,response.text
    assert response.json()['input_snapshot']['channel']['country_name_zh']=='美国'
    assert response.json()['input_snapshot']['sources_complete'] is True


def test_formal_analysis_still_archives_original_zip_and_screenshot(session,tmp_path):
    s,c=session
    run=service.create_run(s,c.id,mode='initial',positioning='legacy')
    data=service.run_read(run);data['materials']=[{'id':'zip','suffix':'.zip','kind':'studio_zip','name':'原始.zip'},{'id':'shot','suffix':'.png','kind':'audience','name':'观众.png'}]
    data['result']=valid_result(run);data['status']='ready'
    root=tmp_path/'cache';(root/'materials').mkdir(parents=True)
    (root/'materials/zip.zip').write_bytes(b'zip-original')
    (root/'materials/shot.png').write_bytes(b'png-original')
    mirror(data,root,tmp_path)
    archives=list(tmp_path.glob('频道分析/*/*/分析数据/*'))
    assert len(archives)==1
    assert (archives[0]/'Studio导出数据/zip_原始.zip').read_bytes()==b'zip-original'
    assert (archives[0]/'截图/shot_观众.png').read_bytes()==b'png-original'


def test_completed_cold_start_cache_does_not_overwrite_later_root_documents(tmp_path):
    cache=tmp_path/'cache';accepted=cache/'old';accepted.mkdir(parents=True)
    (accepted/'submitted.json').write_text(json.dumps({'run_id':'old','body':{}}))
    class Cloud:
        host_id='host';tenant_id='tenant'
        def request(self,method,path,*a,**kw):
            if path=='/analysis-runs/old':return {'id':'old','status':'ready','mirror_status':'completed','input_snapshot':{'cold_start':True}}
            if path=='/auth/me':return {'tenant_id':'tenant'}
            if path=='/channel-analysis/claims':return None
            pytest.fail('completed cold start must not attempt delivery')
    drain(Cloud(),None,{'analysis_workspace_root':str(tmp_path)},cache,once=True)


def test_public_video_metadata_without_analytics_can_use_new_cold_start(session):
    from zhiju.models import YoutubeVideo
    s,c=session
    s.add(YoutubeVideo(channel_id=c.id,youtube_video_id='new-video',url='https://youtu.be/new-video',title='首条视频',privacy_status='public',publish_status='published',source='manual'))
    s.commit()
    assert create(s,c).input_snapshot['cold_start'] is True


def test_measured_daily_metrics_cannot_be_replaced_by_cold_start(session):
    from datetime import date,datetime,timezone
    from zhiju.models import YoutubeChannelDailyMetric
    s,c=session
    s.add(YoutubeChannelDailyMetric(channel_id=c.id,metric_date=date(2026,11,1),views=1,synced_at=datetime.now(timezone.utc)))
    s.commit()
    with pytest.raises(ConflictError,match='公开运营数据'):create(s,c)


@pytest.mark.parametrize('state',['missing','wrong_id','revoked_binding','revoked_grant','missing_id'])
def test_cold_start_requires_existing_matching_authorization(session,state):
    from zhiju.models import AccountChannelAuthorization,OAuthGrant
    s,c=session
    if state!='missing':
        authorize(s,c)
        auth=s.scalar(select(AccountChannelAuthorization))
        if state=='wrong_id':auth.verified_youtube_channel_id='UCother'
        if state=='revoked_binding':auth.status='revoked'
        if state=='revoked_grant':s.get(OAuthGrant,auth.oauth_grant_id).status='revoked'
        if state=='missing_id':c.youtube_channel_id=''
        s.commit()
    with pytest.raises(ConflictError,match='授权|YouTube ID'):
        service.create_run(s,c.id,mode='initial',cold_start=True)
    from zhiju.models import ChannelAnalysisRun
    assert s.scalar(select(ChannelAnalysisRun.id)) is None


@pytest.mark.parametrize('stage',['collect','submit','apply'])
def test_cold_start_rechecks_revoked_authorization(session,stage):
    from zhiju.models import AccountChannelAuthorization,OAuthGrant
    s,c=session;run=create(s,c);service.start_run(s,run.id);claim=service.claim_run(s,'host')
    if stage=='apply':service.submit_result(s,run.id,claim['claim_id'],result=result_for(run))
    auth=s.scalar(select(AccountChannelAuthorization));s.get(OAuthGrant,auth.oauth_grant_id).status='revoked';s.commit()
    with pytest.raises(ConflictError,match='授权'):
        if stage=='collect':sources.collect(s,run.id,claim['claim_id'],fetcher=lambda *a:pytest.fail('no API'))
        elif stage=='submit':service.submit_result(s,run.id,claim['claim_id'],result=result_for(run))
        else:service.apply_result(s,run.id)


def test_cold_start_api_rejects_unlinked_channel(client):
    response=client.post('/api/v3/channels/channel-a/cold-start',json={})
    assert response.status_code==409,response.text
    assert '授权' in response.text
