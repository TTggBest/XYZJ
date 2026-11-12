from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import pytest
from sqlalchemy import event, select
from zhiju.database import TenantSession
from zhiju.models import YoutubeVideo, PackageTitle, PackageCoverVariant, PackageDescription, ChannelAnalysisRun
from zhiju.models.v14 import V14Run
from zhiju.services import channel_analysis
from test_v14_api import client, store
from test_current_analysis_context import setup


def seed(s):
    setup(s)
    run=channel_analysis.create_run(s,'channel-a',mode='initial',positioning='家庭')
    channel_analysis.start_run(s,run.id)
    claim=channel_analysis.claim_run(s,'device-a')
    for vid, channel, package in [('selected','channel-a','package-a'),('unselected','channel-a',None)]:
        s.add(YoutubeVideo(youtube_video_id=vid,channel_id=channel,operation_package_id=package,
            tenant_id='tenant-b' if channel=='channel-b' else 'tenant-a',title='current title',url='https://youtu.be/'+vid,
            privacy_status='public',publish_status='published',source='manual'))
    with TenantSession(s.bind,info={'tenant_id':'tenant-b'}) as other:
        other.add(YoutubeVideo(youtube_video_id='foreign',channel_id='channel-b',operation_package_id='package-b',
            title='foreign title',url='https://youtu.be/foreign',privacy_status='public',publish_status='published',source='manual'))
        other.commit()
    s.add(V14Run(id='frozen-run',package_id='package-a',work_order_id='work-a',host_id='device-a',account_profile='current',
        model='test-model',rules_snapshot={},input_snapshot={'drama':{'content_summary':'frozen real story'}}))
    s.add(PackageTitle(id='title-a',package_id='package-a',variant_number=1,localized_title='Generated family title',core_phrase='Protect family'))
    s.add(PackageCoverVariant(package_id='package-a',title_id='title-a',aspect_ratio='16:9',creative_prompt='prompt is not image'))
    s.add(PackageDescription(package_id='package-a',version_number=1,language='ar',localized_text='unrequested description secret'))
    s.commit()
    run.input_snapshot={**run.input_snapshot,'package_inquiry_contract':'question-led-v1','sources':{'fact_snapshot':{
        'video_inventory':[{'id':vid} for vid in ('selected','unselected','foreign')]}}}
    s.commit()
    return channel_analysis.run_read(run),claim


def ask(vid='selected',sections=None):
    return {'video_id':vid,'reason':'Studio recent_7d CTR declines while watch duration improves',
            'question':'Which title promise is actually supported by the frozen plot?',
            'sections':sections or ['plot_basis','titles_and_hooks','cover_images','adoption_history']}


def test_http_selected_sections_and_missing_links_do_not_leak_other_channel(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s: run,claim=seed(s)
    path=f"/api/v3/analysis-runs/{run['id']}/package-inquiries"
    body={'claim_id':claim['claim_id'],'drilldown_requests':[ask(),ask('unselected'),ask('foreign')]}
    response=client.post(path,json=body);assert response.status_code==200,response.text
    data=response.json();selected,missing,foreign=data['results']
    assert selected['sections']['plot_basis']['drama']['content_summary']=='frozen real story'
    assert selected['sections']['titles_and_hooks']['titles'][0]['localized_title']=='Generated family title'
    assert 'description' not in selected['sections'] and 'unrequested description secret' not in response.text
    assert selected['sections']['cover_images'][0]['gap']=='no_ready_image_asset'
    assert 'historical_title_cover_adoption_unavailable' in selected['gaps']
    assert missing['gaps']==['historical_title_cover_adoption_unavailable','no_package_link']
    assert foreign['gaps']==['video_not_registered_in_this_channel']
    assert 'package-b' not in response.text
    assert client.post(path,json=body).json()==data
    assert client.post(path,json={**body,'claim_id':'stale'}).status_code==409
    assert client.post(path,json={**body,'drilldown_requests':[ask('not-in-sources')]}).status_code==409


def test_executor_metrics_then_inquiry_then_continuation_uses_returned_detail(client,store,tmp_path):
    from zhiju.v14_executor.channel_analysis import investigate_packages,generate_documents
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s: run,claim=seed(s)
    run['mode']='periodic'
    run['input_snapshot']['sources']['screenshot_checks']={'reviewed':{'evidence':'Studio screenshots were read'}}
    statements=[]
    def trace(conn,cursor,statement,parameters,context,executemany): statements.append(statement)
    event.listen(store,'before_cursor_execute',trace)
    calls=[]
    class Cloud:
        def request(self,method,path,body):
            calls.append(('http',path,deepcopy(body)))
            response=client.request(method,'/api/v3'+path,json=body)
            response.raise_for_status();return response.json()
    def generate(stage,model):
        calls.append(('model',stage.node_type,stage.prompt))
        if stage.node_type=='channel_analysis_inquiry':
            if not any(c[0]=='http' for c in calls):
                assert not any('package_titles' in sql or 'package_cover_variants' in sql for sql in statements)
                assert 'Generated family title' not in stage.prompt
                return {'initial_findings':'Question from metric divergence, not a preloaded package', 'drilldown_requests':[ask()]}
            assert 'Generated family title' in stage.prompt and 'no_ready_image_asset' in stage.prompt
            return {'initial_findings':'Generated promise found; actual adoption and visual evidence unknown', 'drilldown_requests':[]}
        if 'profile' in stage.schema['required']:
            assert 'frozen real story' in stage.prompt and 'Generated family title' in stage.prompt
            assert 'unrequested description secret' not in stage.prompt
            return {'profile':'Investigated plot supports family promise; no claim of actual adoption.'}
        if 'diagnosis' in stage.schema['required']:
            return {'diagnosis':'Cover effect remains unknown without actual image/adoption.'}
        return {'generation_spec':'Use only the current supported family promise.'}
    try:
        investigated=investigate_packages(Cloud(),SimpleNamespace(generate=generate),run,tmp_path)
        result=generate_documents(SimpleNamespace(generate=generate),investigated,tmp_path)
    finally:event.remove(store,'before_cursor_execute',trace)
    assert 'unknown' in result['diagnosis']
    assert len([c for c in calls if c[0]=='http'])==2
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        frozen=s.get(ChannelAnalysisRun,run['id']).input_snapshot['sources']['package_inquiries']
        assert frozen[0]['requests']==[ask()] and frozen[1]['requests']==[]
    assert not any('package_descriptions' in sql for sql in statements)


def test_registered_image_is_downloaded_attached_and_reviewed_before_continuation(client,store,tmp_path,monkeypatch):
    from PIL import Image
    from zhiju.models import MediaAsset, ImageWorkspaceSetting
    from zhiju.services import image_processing
    from zhiju.v14_executor.channel_analysis import investigate_packages
    monkeypatch.setattr(image_processing,'get_settings',lambda:SimpleNamespace(shared_root=tmp_path))
    root=tmp_path/'tenants/tenant-a/workspace'
    path=root/'tenants/tenant-a/cover.png';path.parent.mkdir(parents=True)
    Image.new('RGB',(40,20),'blue').save(path)
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        run,claim=seed(s)
        s.add(ImageWorkspaceSetting(id='workspace',root_path='tenants/tenant-a/workspace'))
        s.add(MediaAsset(id='actual-image',channel_id='channel-a',operation_package_id='package-a',storage_provider='local',
            storage_key='tenants/tenant-a/cover.png',asset_type='image',asset_role='thumbnail',sha256='0'*64,
            file_size_bytes=path.stat().st_size,mime_type='image/png',status='ready'))
        cover=s.scalar(select(PackageCoverVariant));cover.asset_id='actual-image';cover.status='rendered';s.commit()
    run['mode']='periodic';calls=[]
    class Cloud:
        def request(self,method,path,body):
            response=client.request(method,'/api/v3'+path,json=body);response.raise_for_status();return response.json()
        def download_analysis_package_image(self,asset_id):
            response=client.get(f'/api/v3/media-assets/{asset_id}/content');response.raise_for_status();return response.content
    def model(stage,model):
        calls.append(stage.node_type)
        if stage.node_type=='channel_analysis_package_images':
            assert len(stage.images)==1 and stage.images[0].is_file()
            with Image.open(stage.images[0]) as image:assert image.getpixel((0,0))==(0,0,255)
            return {'observations':[{'asset_id':'actual-image','observation':'Uniform blue image, no visible characters; cannot infer a story or actual adoption.'}]}
        if len(calls)==1:return {'initial_findings':'Need visual evidence', 'drilldown_requests':[ask(sections=['cover_images'])]}
        assert 'Uniform blue image' in stage.prompt
        return {'initial_findings':'Image is unrelated to the plot; effect unknown without adoption history', 'drilldown_requests':[]}
    output=investigate_packages(Cloud(),SimpleNamespace(generate=model),run,tmp_path)
    assert calls==['channel_analysis_inquiry','channel_analysis_package_images','channel_analysis_inquiry']
    assert output['input_snapshot']['sources']['package_inquiries'][0]['image_review'][0]['status']=='viewed'
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        assert s.get(ChannelAnalysisRun,run['id']).input_snapshot['sources']['package_inquiries'][0]['image_review'][0]['status']=='viewed'


def test_video_present_only_in_short_studio_window_can_be_inquired(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        run,claim=seed(s)
        row=s.get(ChannelAnalysisRun,run['id'])
        snapshot=deepcopy(row.input_snapshot)
        snapshot['sources']['fact_snapshot']={'studio_short_windows':{'recent_7d':{'content':[{'video_id':'selected','content_type':'video'}]}}}
        row.input_snapshot=snapshot;s.commit()
    response=client.post(f"/api/v3/analysis-runs/{run['id']}/package-inquiries",json={
        'claim_id':claim['claim_id'],'drilldown_requests':[ask(sections=['titles_and_hooks'])]})
    assert response.status_code==200,response.text
    assert response.json()['results'][0]['package']['id']=='package-a'


def test_process_claimed_executes_inquiry_before_documents(client,store,tmp_path):
    """Run the real worker entry; transport supplies an isolated collected fixture."""
    from zhiju.v14_executor.channel_analysis import process_claimed
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:run,claim=seed(s)
    run['mode']='periodic';run['materials']=[]
    order=[];submitted=[]
    class Cloud:
        def request(self,method,path,body=None,**kwargs):
            if path.endswith('/collect'):
                order.append('collected');return deepcopy(run)
            if path.endswith('/heartbeat'):return {'status':'running'}
            if path.endswith('/result'):
                submitted.append(body);return {'status':'ready'}
            response=client.request(method,'/api/v3'+path,json=body);response.raise_for_status();return response.json()
    def generate(stage,model):
        order.append(stage.node_type)
        if stage.node_type=='channel_analysis_inquiry':
            if order.count(stage.node_type)==1:return {'initial_findings':'metric divergence','drilldown_requests':[ask(sections=['titles_and_hooks'])]}
            assert 'Generated family title' in stage.prompt
            return {'initial_findings':'adoption unknown','drilldown_requests':[]}
        key=stage.schema['required'][0]
        assert key in ('profile','diagnosis','generation_spec')
        if key!='generation_spec':assert 'Generated family title' in stage.prompt
        return {key:'current '+key}
    model=SimpleNamespace(generate=generate,account_profile='current')
    process_claimed(Cloud(),model,{},tmp_path,run)
    assert order[:3]==['collected','channel_analysis_inquiry','channel_analysis_inquiry']
    assert order[3:]==['channel_analysis','channel_analysis','channel_generation_spec']
    assert submitted[0].get('error') is None and submitted[0]['result']['profile']=='current profile'
