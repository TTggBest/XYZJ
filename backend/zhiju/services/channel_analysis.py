"""Channel analysis lifecycle. No model call or external sync occurs on reads."""
import copy
import json
import re
from zhiju.channel_analysis_rules.strategy import strategy_yaml_block
from zhiju.channel_analysis_rules.operating_reference import (
    LEGACY_PLAYLIST_ERROR, is_reference_revision, selection_reference, uses_selection_guidance, validate_reference,
)
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import yaml
from sqlalchemy import select, func, or_, literal, union_all
from sqlalchemy.orm import aliased
from zhiju.config import get_settings
from zhiju.models import (Channel, ChannelProfile, ChannelPlaylist, ChannelAnalysisRun,
    ChannelAnalysisReport, ChannelAudienceProfile, ChannelDnaVersion, YoutubeVideo,
    YoutubeChannelDailyMetric, AccountChannelAuthorization, OAuthGrant)
from zhiju.models.v14 import V14Setting
from zhiju.services.identity import ConflictError, _audit, channel_order_columns
from zhiju.tenant_repository import require_tenant_entity
from zhiju.channel_analysis_rules.validate_generation_spec import validate_text

KINDS = {'studio_zip', 'videos', 'audience', 'posts', 'ab'}


def get_run(session, run_id, lock=False):
    return require_tenant_entity(session, ChannelAnalysisRun, run_id, lock=lock)


def list_runs(session, channel_id):
    require_tenant_entity(session, Channel, channel_id)
    ids=list(session.scalars(select(ChannelAnalysisRun.id).where(
        ChannelAnalysisRun.channel_id == channel_id,ChannelAnalysisRun.status!='deleted').order_by(ChannelAnalysisRun.created_at.desc()).limit(30)))
    rows={r.id:r for r in session.scalars(select(ChannelAnalysisRun).where(ChannelAnalysisRun.id.in_(ids)))}
    return [rows[key] for key in ids]


def production_analysis_id(session,channel_id):
    setting=session.scalar(select(V14Setting))
    return ((setting.payload.get('channel_inputs',{}).get(channel_id,{}) if setting else {}).get('analysis_version') or {}).get('run_id')


def run_summaries(session,ids,current_id):
    r=ChannelAnalysisRun
    keys=('id','channel_id','host_id','mode','status','phase','claim_id','heartbeat_at','progress','materials','error','report_id','dna_id','mirror_status','created_at','updated_at')
    rows=session.execute(select(*(getattr(r,key) for key in keys),
        r.input_snapshot['model'].as_string().label('model'),
        r.input_snapshot['channel'].label('channel'),
        r.input_snapshot['skill_version']['revision'].as_integer().label('skill_revision'),
        r.input_snapshot['skill_version']['id'].as_string().label('skill_id'),
        r.input_snapshot['skill_version']['label'].as_string().label('skill_label'),
        ChannelAnalysisReport.version_number.label('report_version'),
        r.result['profile'].as_string().is_not(None).label('result_available'))
        .outerjoin(ChannelAnalysisReport,(ChannelAnalysisReport.id==r.report_id)&(ChannelAnalysisReport.tenant_id==r.tenant_id))
        .where(r.id.in_(ids))).mappings()
    summaries={row['id']:dict({key:row[key] for key in keys},input_snapshot={'model':row['model'],'channel':row['channel']},
                 kind='task',skill_id=row['skill_id'],skill_revision=row['skill_revision'],skill_label=row['skill_label'],report_version=row['report_version'],
                 is_current=row['id']==current_id,result={'available':True} if row['result_available'] else None) for row in rows}
    return [summaries[key] for key in ids if key in summaries]


def list_run_summaries(session,channel_id):
    require_tenant_entity(session,Channel,channel_id)
    r=ChannelAnalysisRun
    ids=list(session.scalars(select(r.id).where(r.channel_id==channel_id,r.status!='deleted').order_by(r.created_at.desc(),r.id.desc()).limit(30)))
    return run_summaries(session,ids,production_analysis_id(session,channel_id))


def analysis_history(session,channel_id,page=1,page_size=10):
    require_tenant_entity(session,Channel,channel_id)
    r=ChannelAnalysisRun;report=ChannelAnalysisReport
    condition=(r.channel_id==channel_id,r.status!='deleted')
    # Manual/initialization reports can exist without an analysis task. Keep them in history.
    unlinked=(report.channel_id==channel_id,~select(r.id).where(r.report_id==report.id,r.tenant_id==report.tenant_id).exists())
    index=union_all(select(r.id,r.created_at,literal('task').label('kind')).where(*condition),
                    select(report.id,report.created_at,literal('report').label('kind')).where(*unlinked)).subquery()
    total=session.scalar(select(func.count()).select_from(index))
    pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    entries=session.execute(select(index.c.id,index.c.kind).order_by(index.c.created_at.desc(),index.c.id.desc())
                            .offset((page-1)*page_size).limit(page_size)).all()
    current_id=production_analysis_id(session,channel_id)
    task_ids=[id for id,kind in entries if kind=='task']
    summaries={row['id']:row for row in run_summaries(session,task_ids,current_id)}
    report_ids=[id for id,kind in entries if kind=='report']
    for row in session.execute(select(report.id,report.channel_id,report.version_number,report.created_at,report.report_type)
                               .where(report.id.in_(report_ids))).mappings():
        summaries[row['id']]={'id':row['id'],'channel_id':row['channel_id'],'kind':'report',
            'report_version':row['version_number'],'created_at':row['created_at'],'mode':row['report_type'],
            'status':'legacy_report','is_current':False,'result':{'available':True},'mirror_status':'not_applicable',
            'skill_revision':None,'skill_label':None,'materials':[],'input_snapshot':{'model':'历史报告'}}
    current_ids=list(session.scalars(select(r.id).where(*condition,r.id==current_id))) if current_id else []
    current=run_summaries(session,current_ids,current_id)
    items=[summaries[id] for id,kind in entries]
    for row in items:
        row['can_apply']=row['status']=='ready' and (not current or row['created_at']>=current[0]['created_at'])
    return {'items':items,'total':total,'page':page,'page_size':page_size,'pages':pages,
            'current':current[0] if current else None}


def analysis_workspace(session,view='results',page=1,page_size=20,search=''):
    """Tenant-wide lightweight channel results and live task monitor."""
    r=ChannelAnalysisRun;c=Channel
    counts=dict(session.execute(select(r.status,func.count()).where(r.status!='deleted').group_by(r.status)).all())
    stats={key:counts.get(key,0) for key in ('running','queued','failed')}
    stats['worker_limit']=10
    setting=session.scalar(select(V14Setting));inputs=setting.payload.get('channel_inputs',{}) if setting else {}
    def enrich(ids):
        rows=run_summaries(session,ids,None)
        for row in rows:row['is_current']=row['id']==((inputs.get(row['channel_id'],{}).get('analysis_version') or {}).get('run_id'))
        return {row['id']:row for row in rows}
    if view=='progress':
        condition=(r.status.in_(['queued','running','failed']),c.deleted_at.is_(None))
        total=session.scalar(select(func.count()).select_from(r).join(c,(c.id==r.channel_id)&(c.tenant_id==r.tenant_id)).where(*condition))
        pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
        selected=session.execute(select(r.id,c.id.label('channel_id'),c.original_name,c.operational_name)
            .join(c,(c.id==r.channel_id)&(c.tenant_id==r.tenant_id)).where(*condition)
            .order_by(r.created_at.desc(),r.id.desc()).offset((page-1)*page_size).limit(page_size)).mappings().all()
        runs=enrich([row['id'] for row in selected])
        items=[{'channel_id':row['channel_id'],'channel_name':row['operational_name'] or row['original_name'],'run':runs[row['id']]} for row in selected]
    else:
        condition=[c.deleted_at.is_(None)]
        if search.strip():condition.append(or_(c.original_name.contains(search.strip()),c.operational_name.contains(search.strip())))
        total=session.scalar(select(func.count()).select_from(c).where(*condition))
        pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
        channels=session.execute(select(c.id,c.original_name,c.operational_name).where(*condition)
            .order_by(*channel_order_columns()).offset((page-1)*page_size).limit(page_size)).mappings().all()
        channel_ids=[row['id'] for row in channels]
        ranked=select(r.id,r.channel_id,func.row_number().over(partition_by=r.channel_id,order_by=(r.created_at.desc(),r.id.desc())).label('position'))            .where(r.channel_id.in_(channel_ids),r.status!='deleted').subquery()
        latest=dict(session.execute(select(ranked.c.channel_id,ranked.c.id).where(ranked.c.position==1)).all())
        current={id:(inputs.get(id,{}).get('analysis_version') or {}).get('run_id') for id in channel_ids}
        ids=list(dict.fromkeys([id for id in [*latest.values(),*current.values()] if id]))
        runs=enrich(ids)
        items=[{'channel_id':row['id'],'channel_name':row['operational_name'] or row['original_name'],
                'current':runs.get(current[row['id']]),'latest':runs.get(latest.get(row['id']))} for row in channels]
    return {'items':items,'total':total,'page':page,'pages':pages,'page_size':page_size,'stats':stats}


def run_read(run):
    return {key: getattr(run, key) for key in ('id','channel_id','host_id','mode','status','phase',
        'claim_id','heartbeat_at','progress','input_snapshot','materials','result','error','report_id','dna_id',
        'mirror_status','attempts','created_at','updated_at')}


def create_run(session, channel_id, *, mode, positioning='', posts_not_applicable=False,
               ab_not_applicable=False, cold_start=False, initial_facts=None):
    channel = require_tenant_entity(session, Channel, channel_id, lock=True)
    if channel.deleted_at or mode not in {'initial','periodic'}:
        raise ConflictError('频道或分析类型无效')
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel_id))
    positioning = positioning.strip() or (profile.positioning if profile else '') or ''
    if cold_start:
        authorization=verify_cold_start_authorization(session,channel_id)
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
    formal_skill = analysis_snapshot(session)
    skill_version = cold_start_skill(session) if cold_start else formal_skill
    reference_required = is_reference_revision(formal_skill)
    selection_guidance = uses_selection_guidance(formal_skill)
    if cold_start and selection_guidance:
        skill_version['files']['SKILL.md'] += (
            '\n\n使用当前冻结输出契约的八栏运营参考。第七栏 selection_guidance 只写题材边界、选择理由和试验方向。'
            '八栏均为 cold_start_hypothesis，证据来自已登记身份、已确认定位和初始题材，或标明待取证据。'
            'PLAYLIST 段仅声明使用工作流确认的归属，禁止生成播放列表建议。'
        )
        for filename in ('references/output-contract.md', 'references/generation-spec-contract.md',
                         'assets/generation-spec-template.md'):
            skill_version['files'][filename] = formal_skill['files'][filename]
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
    if selection_guidance:
        snapshot.pop('playlists')
    if reference_required:
        snapshot['operating_reference_required'] = True
        snapshot['operating_reference_skill'] = {key: formal_skill[key] for key in ('id', 'label', 'revision')}
        if cold_start:
            snapshot['rules']['output-contract.md'] = formal_skill['files']['references/output-contract.md']
            snapshot['rules']['operating-reference-cold-start.md'] = (
                '按冻结输出契约填写 channel_strategy.operating_reference 八栏。'
                '八栏的 status 均为 cold_start_hypothesis，证据仅来自登记身份、用户确认定位和初始题材，'
                '或写出待取得证据。保留三份文档和不可用的事实指标。'
            )
    if mode=='periodic':
        from zhiju.services.channel_analysis_sources import verify_authorization
        _,identity,_=verify_authorization(session,snapshot['channel'])
        snapshot['authorization_evidence']={'identity':identity,'verified_at':datetime.now(timezone.utc).isoformat()}
    run = ChannelAnalysisRun(channel_id=channel_id,host_id=setting.payload['host_id'],mode=mode,
        status='draft',phase='materials',input_snapshot=snapshot,materials=[])
    if cold_start:
        facts=initial_facts or {}
        snapshot['cold_start']=True
        snapshot['authorization_evidence']=authorization
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


def claim_run(session, host_id, *, claim_id=None, run_id=None):
    setting=session.scalar(select(V14Setting).with_for_update())
    if not setting or setting.payload['host_id']!=host_id:raise ConflictError('执行主机与公司配置不符')
    from zhiju.services.executor_queue import admission
    if not admission(session):return None
    preferred_id=run_id
    other=aliased(ChannelAnalysisRun)
    busy=select(other.id).where(other.tenant_id==ChannelAnalysisRun.tenant_id,
        other.channel_id==ChannelAnalysisRun.channel_id,other.status=='running').exists()
    run_id=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.host_id==host_id,
        ChannelAnalysisRun.status=='queued',~busy,*( [ChannelAnalysisRun.id==preferred_id] if preferred_id else [])).order_by(ChannelAnalysisRun.created_at).with_for_update(skip_locked=True).limit(1))
    if run_id is None:return None
    run=get_run(session,run_id,True)
    run.claim_id=claim_id or str(uuid4());run.status='running';run.heartbeat_at=datetime.now(timezone.utc)
    from zhiju.services.executor_queue import reserve
    reserve(session,'channel_analysis',run)
    session.commit();return {**run_read(run),'tenant_id':run.tenant_id}


def claimed(session,run_id,claim_id):
    run=get_run(session,run_id,True)
    session.refresh(run)
    if run.status!='running' or run.claim_id!=claim_id:raise ConflictError('分析领取已失效或已取消')
    return run


def cancel_run(session,run_id):
    run=get_run(session,run_id,True)
    if run.status in {'ready','applied','superseded','deleted'}:raise ConflictError('分析已完成或已删除')
    run.status='cancelled';run.claim_id=None;session.commit();return run


def delete_run(session,run_id):
    run=get_run(session,run_id,True)
    if run.status=='deleted':return run
    if run.status not in {'draft','failed','cancelled'} or run.report_id or run.dna_id:
        raise ConflictError('仅可删除草稿、失败或已取消的任务；执行中的任务请先取消，已完成版本需保留')
    # Keep the tombstone so an executor with a saved submission can discard it safely.
    run.status='deleted';run.claim_id=None
    _audit(session,'channel_analysis.deleted','channel_analysis_run',run.id,'从分析任务列表删除，保留材料与历史记录')
    session.commit();return run


def resume_run(session,run_id,stopped_confirmed=False):
    run=get_run(session,run_id)
    require_tenant_entity(session,Channel,run.channel_id,lock=True)
    run=get_run(session,run_id,True);session.refresh(run)
    if not stopped_confirmed or run.status not in {'failed','running','cancelled'}:
        raise ConflictError('继续前请确认旧执行已停止')
    existing=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==run.channel_id,
        ChannelAnalysisRun.id!=run.id,ChannelAnalysisRun.status.in_(['draft','queued','running'])).with_for_update().limit(1))
    if existing:raise ConflictError('频道已有未结束的分析任务，请先完成或取消该任务')
    from zhiju.services.executor_queue import release_stopped_run
    release_stopped_run(session,'channel_analysis',run.id)
    if run.status=='failed' and run.mode=='periodic' and run.error==LEGACY_PLAYLIST_ERROR and run.attempts:
        raw = (run.attempts[-1].get('raw_result') or {}).copy()
        raw.pop('executor_checkpoints', None)
        try:
            recovered = validate_result(run, raw)
        except ConflictError:
            pass  # Any other validation error still follows normal checkpoint recovery.
        else:
            previous_claim = run.claim_id
            run.claim_id = None
            run.error = None
            _accept_result(session, run, recovered)
            _audit(session,'channel_analysis.recovered_result','channel_analysis_run',run.id,previous_claim)
            session.commit()
            return run
    run.claim_id=None;run.error=None
    run.status='draft' if run.phase=='materials' else 'queued'
    session.commit();return run


def validate_screenshot_checks(run,checks,partial=False):
    allowed={m['id'] for m in run.materials if m['kind']!='studio_zip'}
    if set(checks)-allowed:raise ConflictError('截图材料ID不属于本次任务')
    for material in run.materials:
        if partial and material['id'] not in checks:continue
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
    validate_screenshot_checks(run,checks,partial=True)
    try:validate_screenshot_observations(checks)
    except ValueError as exc:raise ConflictError(str(exc)) from exc
    known_ids={item['id'] for item in run.input_snapshot['sources']['fact_snapshot'].get('video_inventory',[])}
    known_ids.update(row['video_id'] for row in run.input_snapshot['sources']['fact_snapshot'].get('studio_content',[]) if row.get('content_type','video')=='video')
    for check in checks.values():
        for item in [check]+check.get('observations',[]):
            if item.get('video_id') is not None and item['video_id'] not in known_ids:
                raise ConflictError('截图视频ID不在已确认视频清单中')
    snapshot=copy.deepcopy(run.input_snapshot)
    snapshot['sources']['screenshot_checks']={**snapshot['sources'].get('screenshot_checks',{}),**copy.deepcopy(checks)}
    if len(snapshot['sources']['screenshot_checks'])==sum(m['kind']!='studio_zip' for m in run.materials):
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
        block=strategy_yaml_block(result['diagnosis'])
        strategy=yaml.safe_load(block['body'])['channel_strategy']
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
    # The same validated YAML supplies every consumer. The caller cannot
    # submit a separate payload that differs from the report.
    result.pop('operating_reference', None)
    if run.input_snapshot.get('operating_reference_required'):
        try:
            result['operating_reference'] = validate_reference(
                strategy, cold_start=run.mode == 'initial',
                skill=run.input_snapshot.get('operating_reference_skill') or {},
            )
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
    if run.mode!='periodic':
        result['normalized_snapshot']['authoritative_sources']=run.input_snapshot.get('sources',{})
    return result


def _accept_result(session, run, result):
    run.result = result
    run.status = run.phase = 'ready'
    # A failed older delivery must not overwrite a later completed report on retry.
    for older in session.scalars(select(ChannelAnalysisRun).where(
        ChannelAnalysisRun.channel_id==run.channel_id,ChannelAnalysisRun.id!=run.id,
        ChannelAnalysisRun.status=='ready',ChannelAnalysisRun.created_at<run.created_at)):
        if older.mirror_status!='completed':older.mirror_status='superseded'


def submit_result(session,run_id,claim_id,*,result=None,error=None):
    run=get_run(session,run_id,True)
    if run.status=='failed' and run.claim_id==claim_id and error and run.error==error[:4000]:
        # A previous executor may have acknowledged only the error; retain its completed work in cloud.
        if result and 'executor_checkpoints' in result and run.attempts:
            attempts=copy.deepcopy(run.attempts)
            attempts[-1]['raw_result']={**(attempts[-1].get('raw_result') or {}),
                'executor_checkpoints':result['executor_checkpoints']}
            run.attempts=attempts;session.commit()
        return run
    if run.status in {'ready','applied','superseded'} and run.claim_id==claim_id and result is not None:
        stored = run.result
        if stored and stored.get('operating_reference'):
            stored = {**stored, 'operating_reference': selection_reference(stored['operating_reference'])}
        if stored==validate_result(run,result):return run
    run=claimed(session,run_id,claim_id)
    if run.input_snapshot.get('cold_start') and not error:
        verify_cold_start_authorization(session,run.channel_id,run.input_snapshot['channel']['youtube_channel_id'])
        assert_no_measured_report(session,run.channel_id)
    if error:
        run.status='failed';run.error=error[:4000]
    else:
        _accept_result(session, run, validate_result(run, result or {}))
    run.attempts=list(run.attempts or [])+[{'claim_id':claim_id,'outcome':run.status,
        'error':run.error,'raw_result':result,'at':datetime.now(timezone.utc).isoformat()}]
    session.commit();return run


def apply_result(session,run_id):
    setting=session.scalar(select(V14Setting).with_for_update())
    run=get_run(session,run_id,True)
    if run.status=='applied':return run
    if run.status!='ready':raise ConflictError('分析结果尚未完成')
    channel=require_tenant_entity(session,Channel,run.channel_id,lock=True)
    if run.input_snapshot.get('cold_start'):
        verify_cold_start_authorization(session,run.channel_id,run.input_snapshot['channel']['youtube_channel_id'])
        assert_no_measured_report(session,run.channel_id)
    newer=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==channel.id,
        ChannelAnalysisRun.status=='applied',ChannelAnalysisRun.created_at>run.created_at).limit(1))
    if newer:raise ConflictError('已有更新的分析版本生效，不能覆盖')
    for previous in session.scalars(select(ChannelAnalysisRun).where(
        ChannelAnalysisRun.channel_id==channel.id,ChannelAnalysisRun.status=='applied')):
        previous.status='superseded'
    assert setting
    result=validate_result(run,run.result)
    run.result=result
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


def verify_cold_start_authorization(session,channel_id,expected_id=None):
    """Use the existing verified login binding; cold start needs no live API or Analytics scope."""
    channel=require_tenant_entity(session,Channel,channel_id)
    if channel.deleted_at or not channel.youtube_channel_id:
        raise ConflictError('冷启动需要已登记的真实 YouTube ID')
    if expected_id is not None and channel.youtube_channel_id!=expected_id:
        raise ConflictError('频道 YouTube ID 已变化，请确认授权后重新创建分析')
    auth=session.scalar(select(AccountChannelAuthorization).join(OAuthGrant,
        AccountChannelAuthorization.oauth_grant_id==OAuthGrant.id).where(
        AccountChannelAuthorization.channel_id==channel_id,
        AccountChannelAuthorization.status=='active',OAuthGrant.status=='active',
        AccountChannelAuthorization.verified_youtube_channel_id==channel.youtube_channel_id
    ).order_by(AccountChannelAuthorization.verified_at.desc()).limit(1))
    if not auth:
        raise ConflictError('频道尚未完成有效授权或授权频道不一致，请先重新授权正确频道')
    return {'source':'verified_login_binding','authorization_id':auth.id,
        'youtube_channel_id':auth.verified_youtube_channel_id,
        'verified_at':auth.verified_at.isoformat()}


def assert_no_measured_report(session,channel_id):
    measured=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==channel_id,
        ChannelAnalysisRun.mode=='periodic',ChannelAnalysisRun.status.in_(['ready','applied','superseded'])).limit(1))
    report=session.scalar(select(ChannelAnalysisReport.id).where(ChannelAnalysisReport.channel_id==channel_id,
        ChannelAnalysisReport.report_type!='initial',ChannelAnalysisReport.status=='completed').limit(1))
    if measured or report:raise ConflictError('已有实测分析报告，不能使用冷启动覆盖，请使用正式频道分析')
    metric=session.scalar(select(YoutubeChannelDailyMetric.id).where(YoutubeChannelDailyMetric.channel_id==channel_id,
        or_(*(getattr(YoutubeChannelDailyMetric,key)>0 for key in (
            'views','watch_time_minutes','subscribers_gained','subscribers_lost','impressions','ctr')))).limit(1))
    if metric:raise ConflictError('已有公开运营数据，不能使用冷启动覆盖，请使用正式频道分析')


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
    block=strategy_yaml_block(result['diagnosis'])
    try:
        strategy=yaml.safe_load(block['body'])['channel_strategy']
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
