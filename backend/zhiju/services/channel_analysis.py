"""Channel analysis lifecycle. No model call or external sync occurs on reads."""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import yaml
from sqlalchemy import select, func, or_
from zhiju.config import get_settings
from zhiju.models import (Channel, ChannelProfile, ChannelPlaylist, ChannelAnalysisRun,
    ChannelAnalysisReport, ChannelAudienceProfile, ChannelDnaVersion, YoutubeVideo,
    YoutubeChannelDailyMetric)
from zhiju.models.v14 import V14Setting
from zhiju.services.identity import ConflictError, _audit
from zhiju.tenant_repository import require_tenant_entity
from zhiju.channel_analysis_rules.validate_generation_spec import validate_text

RULES_ROOT = Path(__file__).resolve().parents[1] / 'channel_analysis_rules/references'
KINDS = {'studio_zip', 'videos', 'audience', 'posts', 'ab'}


def get_run(session, run_id, lock=False):
    return require_tenant_entity(session, ChannelAnalysisRun, run_id, lock=lock)


def list_runs(session, channel_id):
    require_tenant_entity(session, Channel, channel_id)
    ids=list(session.scalars(select(ChannelAnalysisRun.id).where(
        ChannelAnalysisRun.channel_id == channel_id).order_by(ChannelAnalysisRun.created_at.desc()).limit(30)))
    rows={r.id:r for r in session.scalars(select(ChannelAnalysisRun).where(ChannelAnalysisRun.id.in_(ids)))}
    return [rows[key] for key in ids]


def run_read(run):
    return {key: getattr(run, key) for key in ('id','channel_id','host_id','mode','status','phase',
        'claim_id','heartbeat_at','input_snapshot','materials','result','error','report_id','dna_id',
        'mirror_status','attempts','created_at','updated_at')}


def create_run(session, channel_id, *, mode, positioning='', posts_not_applicable=False,
               ab_not_applicable=False):
    channel = require_tenant_entity(session, Channel, channel_id, lock=True)
    if channel.deleted_at or mode not in {'initial','periodic'}:
        raise ConflictError('频道或分析类型无效')
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel_id))
    positioning = positioning.strip() or (profile.positioning if profile else '') or ''
    if mode == 'initial' and not positioning:
        raise ConflictError('冷启动分析需要明确的初始定位')
    if mode == 'initial' and (session.scalar(select(YoutubeVideo.id).where(
        YoutubeVideo.channel_id == channel_id, YoutubeVideo.privacy_status == 'public',
        YoutubeVideo.deleted_at.is_(None)).limit(1)) or session.scalar(select(YoutubeChannelDailyMetric.id).where(
        YoutubeChannelDailyMetric.channel_id == channel_id, or_(
            *(getattr(YoutubeChannelDailyMetric,key)>0 for key in (
                'views','watch_time_minutes','subscribers_gained','subscribers_lost','impressions','ctr'))
        )).limit(1))):
        raise ConflictError('频道已有公开运营数据，请使用正式数据分析')
    existing = session.scalar(select(ChannelAnalysisRun).where(ChannelAnalysisRun.channel_id == channel_id,
        ChannelAnalysisRun.status.in_(['draft','queued','running'])))
    if existing:
        raise ConflictError('频道已有未结束的分析任务，请继续或取消该任务')
    setting = session.scalar(select(V14Setting))
    if not setting:
        raise ConflictError('请先配置系统 Codex 执行主机和模型')
    playlists = list(session.scalars(select(ChannelPlaylist).where(ChannelPlaylist.channel_id == channel_id)))
    previous_id = session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id == channel_id,
        ChannelAnalysisRun.status == 'applied').order_by(ChannelAnalysisRun.created_at.desc()).limit(1))
    previous=session.get(ChannelAnalysisRun,previous_id) if previous_id else None
    snapshot = {'mode':mode, 'positioning':positioning,
        'channel':{k:getattr(channel,k) for k in ('id','youtube_channel_id','original_name','default_language',
            'country_name_zh','default_genre','drama_type','timezone')},
        'profile':{k:getattr(profile,k) for k in ('positioning','description','title_template','fixed_symbol')} if profile else {},
        'playlists':[{'name':p.local_name,'url':p.url} for p in playlists],
        'previous_analysis':copy.deepcopy(previous.result) if previous else None,
        'existing_material':copy.deepcopy(setting.payload.get('channel_inputs',{}).get(channel_id,{})),
        'posts_not_applicable':posts_not_applicable, 'ab_not_applicable':ab_not_applicable,
        'model':setting.payload['default_model'],'account_profile':setting.payload['account_profile'],
        'rules':{p.name:p.read_text() for p in RULES_ROOT.glob('*.md')}}
    if mode=='periodic':
        from zhiju.services.channel_analysis_sources import verify_authorization
        _,identity,_=verify_authorization(session,snapshot['channel'])
        snapshot['authorization_evidence']={'identity':identity,'verified_at':datetime.now(timezone.utc).isoformat()}
    run = ChannelAnalysisRun(channel_id=channel_id,host_id=setting.payload['host_id'],mode=mode,
        status='draft',phase='materials',input_snapshot=snapshot,materials=[])
    if mode=='initial':
        snapshot['rules']={k:v for k,v in snapshot['rules'].items() if k in {'output-contract.md','generation-spec-contract.md'}}
        snapshot['rules']['cold-start.md']='只依据已确认的初始定位、语言、市场和固定资料建立假设。不得推断真实年龄性别或高CTR结论。三文件均保留数据缺口与冷启动标记，尚无API、ZIP、截图标记为not_applicable，不伪造正式运营诊断。'
    session.add(run); session.commit(); session.refresh(run)
    return run


def material_path(run, material_id):
    if not any(m['id'] == material_id for m in run.materials):
        raise ConflictError('分析素材不存在')
    return get_settings().artifact_root / 'channel-analysis' / run.tenant_id / run.id / material_id


def add_material(session, run_id, kind, name, content):
    run = get_run(session,run_id,True)
    if run.status != 'draft' or kind not in KINDS:
        raise ConflictError('只能在分析开始前上传指定类型素材')
    if not content or len(content) > 32*1024*1024:
        raise ConflictError('素材为空或超过 32MB')
    if kind == 'studio_zip':
        from zhiju.services.channel_analysis_sources import parse_studio_zip
        parse_studio_zip(content)  # Reject unreadable archives before the run is queued.
        suffix = '.zip'
    else:
        from io import BytesIO
        from PIL import Image
        try:
            with Image.open(BytesIO(content)) as picture:
                if picture.format not in {'PNG','JPEG','WEBP'}:
                    raise ValueError()
                suffix = {'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[picture.format]
                picture.verify()
        except Exception as exc:
            raise ConflictError('截图必须为有效 PNG、JPEG 或 WebP 图片') from exc
    # A named slot is replaceable before start; individual A/B tests are additive.
    materials = [m for m in run.materials if kind == 'ab' or m['kind'] != kind]
    item={'id':str(uuid4()),'kind':kind,'name':Path(name).name,'suffix':suffix,'size':len(content)}
    run.materials = materials + [item]
    path = material_path(run,item['id']);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    session.commit(); return run


def start_run(session, run_id):
    run=get_run(session,run_id,True)
    if run.status in {'queued','running','ready','applied'}:
        return run
    if run.status != 'draft':
        raise ConflictError('请使用继续分析入口')
    if run.mode == 'periodic':
        kinds={m['kind'] for m in run.materials}
        required={'studio_zip','videos','audience'}
        if not run.input_snapshot['posts_not_applicable']:required.add('posts')
        if not run.input_snapshot['ab_not_applicable']:required.add('ab')
        if required-kinds:raise ConflictError('缺少 Studio ZIP 或截图：'+', '.join(sorted(required-kinds)))
    run.status='queued';run.phase='authorization' if run.mode=='periodic' else 'analysis'
    session.commit();return run


def claim_run(session, host_id):
    setting=session.scalar(select(V14Setting))
    if not setting or setting.payload['host_id']!=host_id:raise ConflictError('执行主机与公司配置不符')
    run_id=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.host_id==host_id,
        ChannelAnalysisRun.status=='queued').order_by(ChannelAnalysisRun.created_at).with_for_update(skip_locked=True).limit(1))
    if run_id is None:return None
    run=get_run(session,run_id,True)
    run.claim_id=str(uuid4());run.status='running';run.heartbeat_at=datetime.now(timezone.utc)
    session.commit();return {**run_read(run),'tenant_id':run.tenant_id}


def claimed(session,run_id,claim_id):
    run=get_run(session,run_id,True)
    session.refresh(run)
    if run.status!='running' or run.claim_id!=claim_id:raise ConflictError('分析领取已失效或已取消')
    return run


def cancel_run(session,run_id):
    run=get_run(session,run_id,True)
    if run.status in {'ready','applied'}:raise ConflictError('分析已完成')
    run.status='cancelled';run.claim_id=None;session.commit();return run


def resume_run(session,run_id,stopped_confirmed=False):
    run=get_run(session,run_id,True)
    if not stopped_confirmed or run.status not in {'failed','running'}:
        raise ConflictError('继续前请确认旧执行已停止')
    run.claim_id=None;run.error=None;run.status='queued';session.commit();return run


def validate_result(run,result):
    for key in ('profile','diagnosis','generation_spec'):
        if not isinstance(result.get(key),str) or not result[key].strip():raise ConflictError('缺少完整三份分析文件')
    if not isinstance(result.get('normalized_snapshot'),dict):raise ConflictError('缺少归一数据快照')
    for key,count in (('profile',10),('diagnosis',7)):
        if len(re.findall(r'^##\s+',result[key],re.M))!=count:
            raise ConflictError(f'{key} 必须包含完整{count}节')
    channel=run.input_snapshot['channel']
    issues=validate_text(result['generation_spec'],expected_channel_name=channel['original_name'],
        expected_language=channel['default_language'],expected_market=channel.get('country_name_zh') or '未配置')
    if issues:raise ConflictError('生成规范校验失败：'+'；'.join(issues))
    try:
        block=re.search(r'```(?:yaml|yml)\s*\n(.*?)```',result['diagnosis'],re.S)
        strategy=yaml.safe_load(block[1])['channel_strategy']
        if strategy['channel_id'] != channel['youtube_channel_id']:raise ValueError()
        required={'channel_id','updated_at','data_window','strategy_confidence','channel_stage','audience_core','traffic_type',
            'content_priority','content_secondary','content_explore','content_avoid','title_priority','title_reduce',
            'cover_priority','cover_reduce','description_focus','community_focus','hashtag_focus','scheduling_notes'}
        if required-set(strategy):raise ValueError()
    except Exception as exc:raise ConflictError('诊断 YAML 缺失或频道身份不符') from exc
    if run.mode=='initial' and not all('冷启动' in result[k] and '未经数据验证' in result[k] for k in ('profile','diagnosis')):
        raise ConflictError('冷启动报告必须明确标注冷启动及未经数据验证')
    snap=result['normalized_snapshot']
    required={'schema_version','snapshot_status','generated_at','channel','data_windows','availability_rules',
        'channel_totals_28d','trend','audience_28d','traffic_28d_video_pct','retention_intro_30s_pct','top_videos_28d',
        'low_videos_28d','concentration_28d','community_posts','ab_testing','source_manifest','unmatched_video_ids'}
    if required-set(snap):raise ConflictError('归一快照缺少必要数据域')
    if snap.get('channel',{}).get('youtube_channel_id')!=channel['youtube_channel_id']:
        raise ConflictError('归一快照频道身份不符')
    if run.mode=='periodic':
        if not run.input_snapshot.get('sources_complete'):
            raise ConflictError('正式分析尚未完成数据采集')
        checks=result.get('material_checks',{})
        for material in run.materials:
            if material['kind']=='studio_zip':continue
            check=checks.get(material['id'],{})
            if not all(check.get(key) is True for key in ('identity_matches','page_matches','window_matches')):
                raise ConflictError('截图频道、页面或周期未核实：'+material['name'])
    result=copy.deepcopy(result)
    result['normalized_snapshot']['authoritative_sources']=run.input_snapshot.get('sources',{})
    return result


def submit_result(session,run_id,claim_id,*,result=None,error=None):
    run=get_run(session,run_id,True)
    if run.status=='failed' and run.claim_id==claim_id and error and run.error==error[:4000]:return run
    if run.status in {'ready','applied','superseded'} and run.claim_id==claim_id and result is not None:
        if run.result==validate_result(run,result):return run
    run=claimed(session,run_id,claim_id)
    if error:
        run.status='failed';run.error=error[:4000]
    else:
        run.result=validate_result(run,result or {});run.status='ready';run.phase='ready'
    run.attempts=list(run.attempts or [])+[{'claim_id':claim_id,'outcome':run.status,
        'error':run.error,'raw_result':result,'at':datetime.now(timezone.utc).isoformat()}]
    session.commit();return run


def apply_result(session,run_id):
    run=get_run(session,run_id,True)
    if run.status=='applied':return run
    if run.status!='ready':raise ConflictError('分析结果尚未完成')
    channel=require_tenant_entity(session,Channel,run.channel_id,lock=True)
    newer=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==channel.id,
        ChannelAnalysisRun.status=='applied',ChannelAnalysisRun.created_at>run.created_at).limit(1))
    if newer:raise ConflictError('已有更新的分析版本生效，不能覆盖')
    for previous in session.scalars(select(ChannelAnalysisRun).where(
        ChannelAnalysisRun.channel_id==channel.id,ChannelAnalysisRun.status=='applied')):
        previous.status='superseded'
    setting=session.scalar(select(V14Setting).with_for_update());assert setting
    result=validate_result(run,run.result)
    version=session.scalar(select(func.coalesce(func.max(ChannelAnalysisReport.version_number),0)).where(ChannelAnalysisReport.channel_id==channel.id))+1
    label='冷启动假设，未经数据验证' if run.mode=='initial' else '真实数据周期分析，见来源及样本范围'
    report=ChannelAnalysisReport(channel_id=channel.id,version_number=version,
        report_type=run.mode,status='completed',generated_by='codex',summary=result['profile'],
        recommendations=result['diagnosis'],risks=label)
    session.add(report);session.flush()
    session.add(ChannelAudienceProfile(report_id=report.id,profile_type='behavior',
        segment_value=label,rank_number=1,summary=result['profile']))
    for dna in session.scalars(select(ChannelDnaVersion).where(ChannelDnaVersion.channel_id==channel.id,ChannelDnaVersion.status=='active')):
        dna.status='archived';dna.effective_to=datetime.now(timezone.utc)
    dna_version=session.scalar(select(func.coalesce(func.max(ChannelDnaVersion.version_number),0)).where(ChannelDnaVersion.channel_id==channel.id))+1
    dna=ChannelDnaVersion(channel_id=channel.id,analysis_report_id=report.id,version_number=dna_version,
        status='active',language=channel.default_language,primary_genre=channel.default_genre or '未配置',
        audience_summary=result['profile'],reference_summary=result['generation_spec'],effective_from=datetime.now(timezone.utc))
    session.add(dna);session.flush()
    payload=copy.deepcopy(setting.payload);material=payload['channel_inputs'].setdefault(channel.id,{})
    if not material:
        material.update(language=channel.default_language,gender=channel.drama_type or '',
            direction=channel.default_genre or '',playlists=run.input_snapshot['playlists'])
    material['generation_spec']=result['generation_spec']
    material['analysis_version']={'run_id':run.id,'report_id':report.id,'dna_id':dna.id,'report_type':run.mode}
    setting.payload=payload;run.report_id=report.id;run.dna_id=dna.id;run.status='applied'
    _audit(session,'channel_analysis.applied','channel',channel.id)
    session.commit();return run
