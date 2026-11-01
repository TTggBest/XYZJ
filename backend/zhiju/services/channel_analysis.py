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
               ab_not_applicable=False, cold_start=False, initial_facts=None):
    channel = require_tenant_entity(session, Channel, channel_id, lock=True)
    if channel.deleted_at or mode not in {'initial','periodic'}:
        raise ConflictError('频道或分析类型无效')
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel_id))
    positioning = positioning.strip() or (profile.positioning if profile else '') or ''
    if cold_start:
        assert_no_measured_report(session,channel_id)
        positioning = positioning or '仅依据频道名称与已确认信息建立冷启动假设'
    if mode == 'initial' and not positioning:
        raise ConflictError('冷启动分析需要明确的初始定位')
    if mode == 'initial' and ((not cold_start and session.scalar(select(YoutubeVideo.id).where(
        YoutubeVideo.channel_id == channel_id, YoutubeVideo.privacy_status == 'public',
        YoutubeVideo.deleted_at.is_(None)).limit(1))) or session.scalar(select(YoutubeChannelDailyMetric.id).where(
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
    from zhiju.services.skill_catalog import analysis_snapshot
    skill_version = cold_start_skill(session) if cold_start else analysis_snapshot(session)
    snapshot = {'mode':mode, 'positioning':positioning,
        'channel':{k:getattr(channel,k) for k in ('id','youtube_channel_id','original_name','default_language',
            'country_name_zh','default_genre','drama_type','timezone')},
        'profile':{k:getattr(profile,k) for k in ('positioning','description','title_template','fixed_symbol')} if profile else {},
        'playlists':[{'name':p.local_name,'url':p.url} for p in playlists],
        'previous_analysis':copy.deepcopy(previous.result) if previous else None,
        'existing_material':copy.deepcopy(setting.payload.get('channel_inputs',{}).get(channel_id,{})),
        'posts_not_applicable':posts_not_applicable, 'ab_not_applicable':ab_not_applicable,
        'model':setting.payload['default_model'],'account_profile':setting.payload['account_profile'],
        'skill_version':skill_version,
        'rules':{Path(name).name:body for name,body in skill_version['files'].items() if name.startswith('references/') and name.endswith('.md')}}
    if mode=='periodic':
        from zhiju.services.channel_analysis_sources import verify_authorization
        _,identity,_=verify_authorization(session,snapshot['channel'])
        snapshot['authorization_evidence']={'identity':identity,'verified_at':datetime.now(timezone.utc).isoformat()}
    run = ChannelAnalysisRun(channel_id=channel_id,host_id=setting.payload['host_id'],mode=mode,
        status='draft',phase='materials',input_snapshot=snapshot,materials=[])
    if cold_start:
        facts=initial_facts or {}
        snapshot['cold_start']=True
        snapshot['initial_facts']={k:str(facts.get(k) or '').strip() for k in ('chinese_meaning','positioning','language','market')}
        snapshot['initial_facts']['chinese_meaning'] = snapshot['initial_facts']['chinese_meaning'] or channel.chinese_meaning or ''
        snapshot['initial_facts']['positioning'] = snapshot['initial_facts']['positioning'] or (profile.positioning if profile else '') or channel.default_genre or ''
        for field,key in (('default_language','language'),('country_name_zh','market')):
            if snapshot['initial_facts'][key]:snapshot['channel'][field]=snapshot['initial_facts'][key]
        snapshot['rules']['channel-initial-audience.md']=skill_version['files']['SKILL.md']
    if mode=='initial' and not cold_start:
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
    if not stopped_confirmed or run.status not in {'failed','running','cancelled'}:
        raise ConflictError('继续前请确认旧执行已停止')
    run.claim_id=None;run.error=None
    run.status='draft' if run.phase=='materials' else 'queued'
    session.commit();return run


def validate_screenshot_checks(run,checks):
    for material in run.materials:
        if material['kind']=='studio_zip':continue
        check=checks.get(material['id'],{})
        identity_and_page=all(check.get(key) is True for key in ('identity_matches','page_matches'))
        window_verified=isinstance(check.get('window_matches'),bool) if material['kind']=='ab' else check.get('window_matches') is True
        if not identity_and_page or not window_verified or not isinstance(check.get('evidence'),str) or not check['evidence'].strip():
            raise ConflictError('截图频道、页面或周期未核实：'+material['name'])


def record_screenshot_checks(session,run_id,claim_id,checks):
    from zhiju.services.channel_analysis_normalize import validate_screenshot_observations,formal_snapshot
    run=claimed(session,run_id,claim_id)
    if run.mode!='periodic':raise ConflictError('仅正式分析需要读取截图')
    validate_screenshot_checks(run,checks)
    try:validate_screenshot_observations(checks)
    except ValueError as exc:raise ConflictError(str(exc)) from exc
    known_ids={item['id'] for item in run.input_snapshot['sources']['fact_snapshot'].get('video_inventory',[])}
    for check in checks.values():
        for item in [check]+check.get('observations',[]):
            if item.get('video_id') is not None and item['video_id'] not in known_ids:
                raise ConflictError('截图视频ID不在已确认视频清单中')
    snapshot=copy.deepcopy(run.input_snapshot)
    snapshot['sources']['screenshot_checks']=copy.deepcopy(checks)
    snapshot['sources']['fact_snapshot']=formal_snapshot(snapshot['sources'],snapshot['channel'])
    run.input_snapshot=snapshot;run.phase='analysis';session.commit();return run


def validate_result(run,result):
    for key in ('profile','diagnosis','generation_spec'):
        if not isinstance(result.get(key),str) or not result[key].strip():raise ConflictError('缺少完整三份分析文件')
    if not isinstance(result.get('normalized_snapshot'),dict):raise ConflictError('缺少归一数据快照')
    for key,count in (('profile',10),('diagnosis',7)):
        if len(re.findall(r'^##\s+',result[key],re.M))!=count:
            raise ConflictError(f'{key} 必须包含完整{count}节')
    channel=run.input_snapshot['channel']
    if run.input_snapshot.get('cold_start'):
        validate_cold_start_result(run,result)
    issues=validate_text(result['generation_spec'],expected_channel_name=channel['original_name'],
        expected_language=channel['default_language'],expected_market=channel.get('country_name_zh') or '未配置')
    if issues:raise ConflictError('生成规范校验失败：'+'；'.join(issues))
    try:
        block=re.search(r'```(?:yaml|yml)\s*\n(.*?)```',result['diagnosis'],re.S)
        strategy=yaml.safe_load(block[1])['channel_strategy']
        if not isinstance(strategy,dict):raise ValueError()
    except Exception as exc:raise ConflictError('诊断 YAML 缺失或格式错误') from exc
    if strategy.get('channel_id') != channel['youtube_channel_id']:
        raise ConflictError('诊断 YAML 频道身份不符：channel_id 必须使用当前 YouTube Channel ID，不能使用智矩内部 ID')
    required={'channel_id','updated_at','data_window','strategy_confidence','channel_stage','audience_core','traffic_type',
        'content_priority','content_secondary','content_explore','content_avoid','title_priority','title_reduce',
        'cover_priority','cover_reduce','description_focus','community_focus','hashtag_focus','scheduling_notes'}
    if required-set(strategy):raise ConflictError('诊断 YAML 缺少字段：'+', '.join(sorted(required-set(strategy))))
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
        validate_formal_result(run,result,strategy)
        if not run.input_snapshot.get('sources_complete'):
            raise ConflictError('正式分析尚未完成数据采集')
        validate_screenshot_checks(run,result.get('material_checks',{}))
    result=copy.deepcopy(result)
    if run.mode!='periodic':
        result['normalized_snapshot']['authoritative_sources']=run.input_snapshot.get('sources',{})
    return result


def submit_result(session,run_id,claim_id,*,result=None,error=None):
    run=get_run(session,run_id,True)
    if run.status=='failed' and run.claim_id==claim_id and error and run.error==error[:4000]:return run
    if run.status in {'ready','applied','superseded'} and run.claim_id==claim_id and result is not None:
        if run.result==validate_result(run,result):return run
    run=claimed(session,run_id,claim_id)
    if run.input_snapshot.get('cold_start') and not error:
        assert_no_measured_report(session,run.channel_id)
    if error:
        run.status='failed';run.error=error[:4000]
    else:
        run.result=validate_result(run,result or {});run.status='ready';run.phase='ready'
        # A failed older delivery must not overwrite a later completed report on retry.
        for older in session.scalars(select(ChannelAnalysisRun).where(
            ChannelAnalysisRun.channel_id==run.channel_id,ChannelAnalysisRun.id!=run.id,
            ChannelAnalysisRun.status=='ready',ChannelAnalysisRun.created_at<run.created_at)):
            if older.mirror_status!='completed':older.mirror_status='superseded'
    run.attempts=list(run.attempts or [])+[{'claim_id':claim_id,'outcome':run.status,
        'error':run.error,'raw_result':result,'at':datetime.now(timezone.utc).isoformat()}]
    session.commit();return run


def apply_result(session,run_id):
    run=get_run(session,run_id,True)
    if run.status=='applied':return run
    if run.status!='ready':raise ConflictError('分析结果尚未完成')
    channel=require_tenant_entity(session,Channel,run.channel_id,lock=True)
    if run.input_snapshot.get('cold_start'):assert_no_measured_report(session,run.channel_id)
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
    run.mirror_status='pending'  # Explicit selection must deliver this version even if delivered before.
    for other in session.scalars(select(ChannelAnalysisRun).where(
        ChannelAnalysisRun.channel_id==channel.id,ChannelAnalysisRun.id!=run.id,ChannelAnalysisRun.status=='ready')):
        if other.mirror_status!='completed':other.mirror_status='superseded'
    _audit(session,'channel_analysis.applied','channel',channel.id)
    session.commit();return run


PROFILE_SECTIONS = ('Channel basics','Overall performance','Audience profile','Traffic profile','Content profile',
                    'Packaging profile','Consumption profile','Stable audience preferences','Current channel positioning','Long-term strategy')
DIAGNOSIS_SECTIONS = ('Current-stage diagnosis','What the current audience rewards','Current content priority','Current title guidance',
                      'Current cover guidance','Current description/community/hashtag guidance','Current decision summary')
COLD_DOMAINS = ('channel_totals_28d','trend','audience_28d','traffic_28d_video_pct','retention_intro_30s_pct',
                'top_videos_28d','low_videos_28d','concentration_28d','community_posts','ab_testing','unmatched_video_ids')


def assert_no_measured_report(session,channel_id):
    measured=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==channel_id,
        ChannelAnalysisRun.mode=='periodic',ChannelAnalysisRun.status.in_(['ready','applied','superseded'])).limit(1))
    report=session.scalar(select(ChannelAnalysisReport.id).where(ChannelAnalysisReport.channel_id==channel_id,
        ChannelAnalysisReport.report_type!='initial',ChannelAnalysisReport.status=='completed').limit(1))
    if measured or report:raise ConflictError('已有实测分析报告，不能使用冷启动覆盖，请使用正式频道分析')


def cold_start_skill(session):
    from zhiju.models import Skill,SkillVersion
    from zhiju.services.skill_catalog import BUNDLE,files
    skill=session.scalar(select(Skill).where(Skill.code=='channel-initial-audience'))
    version=session.scalar(select(SkillVersion).where(SkillVersion.skill_id==skill.id,SkillVersion.is_current.is_(True))) if skill else None
    base=files(BUNDLE.read_bytes())
    content={k:v for k,v in base.items() if k in {'references/output-contract.md','references/generation-spec-contract.md',
        'assets/generation-spec-template.md','scripts/validate_generation_spec.py'}}
    content['SKILL.md']=version.body_original if version else (Path(__file__).resolve().parents[1]/'skill_catalog_bundles/channel-initial-audience.md').read_text()
    return {'id':version.id if version else 'builtin-channel-initial-audience','label':'channel-initial-audience',
            'revision':version.version_number if version else 1,'files':content}


def cold_start_snapshot(channel,facts,sources=None):
    return {'schema_version':2,'snapshot_status':'cold_start_no_analytics','generated_at':datetime.now(timezone.utc).isoformat(),
        'channel':channel,'initial_facts':facts,'data_windows':{'recent_28d':'unavailable','recent_90d':'unavailable'},
        'availability_rules':['unavailable is not zero','cold-start assumptions are not measured facts'],
        **{key:'unavailable' for key in COLD_DOMAINS},
        'source_manifest':sources or [{'type':'confirmed_platform_channel','channel_id':channel['id']} ]}


def validate_cold_start_result(run,result):
    for key,expected in (('profile',PROFILE_SECTIONS),('diagnosis',DIAGNOSIS_SECTIONS)):
        sections=re.split(r'^##\s+',result.get(key,''),flags=re.M)[1:]
        titles=[re.sub(r'^\d+[.、)．]\s*','',part.splitlines()[0].strip()) for part in sections]
        if titles!=list(expected) or any(len(part.split('\n',1))<2 or not part.split('\n',1)[1].strip() for part in sections):
            raise ConflictError('冷启动报告章节名称、顺序或正文不完整：'+key)
    snapshot=result.get('normalized_snapshot',{})
    if snapshot.get('snapshot_status')!='cold_start_no_analytics' or any(snapshot.get(key)!='unavailable' for key in COLD_DOMAINS):
        raise ConflictError('冷启动事实快照必须标记无实测数据，指标域只能为 unavailable')
    block=re.search(r'```(?:yaml|yml)\s*\n(.*?)```',result['diagnosis'],re.S)
    try:
        strategy=yaml.safe_load(block[1])['channel_strategy']
        if strategy['strategy_confidence']!='low' or strategy['channel_stage']!='exploration':raise ValueError()
        if strategy['audience_core']!='unavailable' or strategy['traffic_type']!='unavailable':raise ValueError()
        if strategy['data_window']!={'recent_28d':'unavailable','recent_90d':'unavailable'}:raise ValueError()
    except Exception as exc:raise ConflictError('冷启动策略须为低置信度探索期，受众/流量/窗口不可编造') from exc


def validate_formal_result(run,result,strategy):
    for key,expected in (('profile',PROFILE_SECTIONS),('diagnosis',DIAGNOSIS_SECTIONS)):
        sections=re.split(r'^##\s+',result[key],flags=re.M)[1:]
        titles=[re.sub(r'^\d+[.、)．]\s*','',part.splitlines()[0].strip()) for part in sections]
        if titles!=list(expected) or any(not part.partition('\n')[2].strip() for part in sections):
            raise ConflictError('正式报告章节名称、顺序或正文不完整：'+key)
    facts=run.input_snapshot.get('sources',{}).get('fact_snapshot')
    if not facts or result['normalized_snapshot']!=facts:
        raise ConflictError('正式分析事实快照与采集来源不一致，不能使用模型生成指标')
    if strategy.get('data_window')!=facts['data_windows']:
        raise ConflictError('诊断 YAML 数据周期与采集周期不一致')
    if strategy.get('strategy_confidence') not in {'low','medium','high'}:
        raise ConflictError('诊断 YAML 置信度无效')
    for key in ('content_priority','content_secondary','content_explore','content_avoid','title_priority','title_reduce',
                'cover_priority','cover_reduce','description_focus','community_focus','hashtag_focus','scheduling_notes'):
        if not isinstance(strategy.get(key),list) or any(not isinstance(item,str) for item in strategy[key]):
            raise ConflictError('诊断 YAML 策略字段必须为字符串列表：'+key)
