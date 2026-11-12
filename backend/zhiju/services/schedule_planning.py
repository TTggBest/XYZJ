"""AI selects stories; the server owns eligibility, times and atomic persistence."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import yaml
from sqlalchemy import and_, func, select, or_, case
from zhiju.models import (Channel, ChannelSchedulePlan, ChannelScheduleEntry, ChannelPublishSlot,
    Drama, DramaProductionState, ChannelDnaVersion, ChannelPlaylist, ScheduleCandidate, ScheduleChangeHistory, Language, PublishCadenceTemplateSlot)
from zhiju.channel_analysis_rules.strategy import strategy_yaml_block
from zhiju.models.v14 import V14Setting
from zhiju.services import channel_guidance, operations, schedule_batch, skill_catalog
from zhiju.services.identity import ConflictError, _audit
from zhiju.tenant_repository import require_tenant_entity
from zhiju.services.schedule_youtube import LANGUAGES
from zhiju.scheduling_rules.contract import SLOT_TOPICS_PROTOCOL, REFERENCE_PROTOCOL, CONTINUITY_PROTOCOL

PLOT_FIELDS=('content_summary','plot_archive','plot_pattern','core_personas')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def read(plan, *, summary=False):
    result={key:getattr(plan,key) for key in ('id','channel_id','host_id','status','claim_id','heartbeat_at','progress',
        'dna_id','input_snapshot','result','error','created_at','updated_at')}
    if summary:
        result['input_snapshot']={k:plan.input_snapshot[k] for k in ('channel','start_date','end_date','daily_count')}
        result['result']=None
    return result


def get_plan(session, plan_id, lock=False):
    return require_tenant_entity(session,ChannelSchedulePlan,plan_id,lock=lock)


def list_plans(session, channel_id):
    require_tenant_entity(session,Channel,channel_id)
    ids=list(session.scalars(select(ChannelSchedulePlan.id).where(ChannelSchedulePlan.channel_id==channel_id)
        .order_by(ChannelSchedulePlan.created_at.desc(),ChannelSchedulePlan.id.desc()).limit(20)))
    # Keep large frozen story snapshots out of MySQL's filesort buffer.
    rows={row.id:row for row in session.scalars(select(ChannelSchedulePlan).where(ChannelSchedulePlan.id.in_(ids)))}
    return [rows[id] for id in ids]


def workspace(session,page=1,page_size=20,status='active',search=''):
    r=ChannelSchedulePlan;c=Channel
    join=(c.id==r.channel_id)&(c.tenant_id==r.tenant_id)
    condition=[c.deleted_at.is_(None)]
    if status=='active':condition.append(r.status.in_(['queued','running','failed','ready']))
    elif status!='all':condition.append(r.status==status)
    if search.strip():condition.append(or_(c.original_name.contains(search.strip()),c.operational_name.contains(search.strip())))
    stats=dict(session.execute(select(r.status,func.count()).join(c,join).where(c.deleted_at.is_(None)).group_by(r.status)).all())
    total=session.scalar(select(func.count()).select_from(r).join(c,join).where(*condition))
    pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    # Sorting only IDs keeps full candidate plots and generated previews out of filesort.
    ids=list(session.scalars(select(r.id).join(c,join).where(*condition).order_by(
        case((r.status=='running',0),(r.status=='queued',1),(r.status=='failed',2),else_=3),r.created_at.desc(),r.id.desc())
        .offset((page-1)*page_size).limit(page_size)))
    array_length=func.json_length if session.get_bind().dialect.name=='mysql' else func.json_array_length
    records=session.execute(select(r.id,r.channel_id,r.status,r.progress,r.heartbeat_at,r.error,r.created_at,
        c.original_name,c.operational_name,
        r.input_snapshot['start_date'].as_string().label('start_date'),
        r.input_snapshot['end_date'].as_string().label('end_date'),
        r.input_snapshot['daily_count'].as_integer().label('daily_count'),
        array_length(r.input_snapshot['candidates']).label('candidate_count'),
        array_length(r.input_snapshot['targets']).label('target_count'))
        .join(c,join).where(r.id.in_(ids))).mappings()
    rows={row['id']:dict(row,channel_name=row['operational_name'] or row['original_name']) for row in records}
    from zhiju.services.executor_queue import counts
    return {'items':[rows[id] for id in ids],'total':total,'page':page,'pages':pages,'page_size':page_size,
            'stats':{key:stats.get(key,0) for key in ('running','queued','failed','ready','applied')},'executor':counts(session)}


def language_aliases(session):
    aliases={k.casefold():v.casefold() for k,v in LANGUAGES.items()}
    for language in session.scalars(select(Language)):
        for name in (language.code,language.name_zh,language.native_name):
            if name:aliases[name.strip().casefold()]=language.code.casefold()
    return aliases


def language_code(aliases, value):
    key=(value or '').strip().casefold()
    return aliases.get(key,key)


def candidate_pool(session,channel):
    used=set(session.scalars(select(ChannelScheduleEntry.drama_id).where(
        ChannelScheduleEntry.channel_id==channel.id,ChannelScheduleEntry.status.not_in(['cancelled','replaced']))))
    states={r.drama_id:r for r in session.scalars(select(DramaProductionState))}
    aliases=language_aliases(session)
    language=language_code(aliases,channel.default_language)
    if not language:raise ConflictError('频道未配置语言')
    pool=[];excluded={'history':0,'language_unknown':0,'language_unfinished':0,'plot_missing':0,'duration_short':0}
    for drama in operations.list_schedulable_dramas(session):
        if drama['id'] in used:excluded['history']+=1;continue
        state=states[drama['id']]
        if state.finished_languages is None:excluded['language_unknown']+=1;continue
        if language not in {language_code(aliases,v) for v in state.finished_languages}:
            excluded['language_unfinished']+=1;continue
        if not any(str(drama.get(k) or '').strip() for k in PLOT_FIELDS):excluded['plot_missing']+=1;continue
        duration=state.total_duration_seconds
        if duration is not None and duration<1800:excluded['duration_short']+=1;continue
        pool.append({k:drama.get(k) for k in ('id','chinese_title','drama_code','source_language',*PLOT_FIELDS)} | {
            'duration_seconds':duration,'expires_at':drama['expires_at'].isoformat() if drama['expires_at'] else None,
            'finished_languages':state.finished_languages})
    return pool,excluded


def cadence_slots(session,channel_id,daily_count):
    channel=require_tenant_entity(session,Channel,channel_id)
    slots=list(session.scalars(select(PublishCadenceTemplateSlot).where(
        PublishCadenceTemplateSlot.daily_publish_count==daily_count)
        .order_by(PublishCadenceTemplateSlot.slot_number)))
    if len(slots)!=daily_count:
        raise ConflictError(f'所选{daily_count}更的统一档期模板未配置完整，请在频道档期表中配置')
    return [{'id':r.id,'slot_type':r.slot_type,'slot_number':r.slot_number,
             'local_time':r.local_video_time.isoformat(),'timezone':channel.timezone} for r in slots]


def occupied_targets(session,channel_id,slots,dates,*,date_basis=None):
    """Match saved schedule definitions to template slots, including historical archived slots."""
    if not dates:return set()
    if date_basis == 'beijing':
        start = datetime.combine(min(dates), datetime.min.time())
        end = datetime.combine(max(dates) + timedelta(days=1), datetime.min.time())
        condition = and_(ChannelScheduleEntry.planned_beijing_time >= start,
                         ChannelScheduleEntry.planned_beijing_time < end)
        day = lambda row: row.planned_beijing_time.date()
    else:
        condition = ChannelScheduleEntry.publish_date.in_(dates)
        day = lambda row: row.publish_date
    rows=[(day(row), stored) for row,stored in session.execute(select(ChannelScheduleEntry,ChannelPublishSlot).outerjoin(
        ChannelPublishSlot,ChannelPublishSlot.id==ChannelScheduleEntry.publish_slot_id).where(
        ChannelScheduleEntry.channel_id==channel_id,condition)) if day(row) in dates]
    occupied=set()
    counts={}
    for scheduled_day,_ in rows:
        counts[scheduled_day]=counts.get(scheduled_day,0)+1
    for scheduled_day,stored in rows:
        if counts[scheduled_day]>=len(slots):
            occupied.update((scheduled_day.isoformat(),slot['id']) for slot in slots)
            continue
        if stored is None:raise ConflictError('已有排期缺少档位记录，请先核对该日期的排期')
        same_type=[slot for slot in slots if slot['slot_type']==stored.slot_type]
        if len(same_type)==1:
            occupied.add((scheduled_day.isoformat(),same_type[0]['id']))
        elif same_type:
            matches=[slot for slot in same_type if slot['local_time']==stored.local_time.isoformat()
                     and slot['timezone']==stored.timezone]
            if len(matches)!=1:
                raise ConflictError('所选日期已有辅档排期与当前统一模板不一致，请先核对已有排期')
            occupied.add((scheduled_day.isoformat(),matches[0]['id']))
    return occupied


def stored_slot(session,channel_id,template_slot):
    """Reuse an identical frozen definition; never reactivate or edit historical slots."""
    from datetime import time
    clock=time.fromisoformat(template_slot['local_time'])
    slot=session.scalar(select(ChannelPublishSlot).where(ChannelPublishSlot.channel_id==channel_id,
        ChannelPublishSlot.slot_type==template_slot['slot_type'],ChannelPublishSlot.local_time==clock,
        ChannelPublishSlot.timezone==template_slot['timezone']).order_by(
            (ChannelPublishSlot.status!='archived'),ChannelPublishSlot.slot_number).limit(1))
    if slot is None:
        number=(session.scalar(select(func.max(ChannelPublishSlot.slot_number)).where(
            ChannelPublishSlot.channel_id==channel_id,ChannelPublishSlot.slot_type==template_slot['slot_type'])) or 0)+1
        slot=ChannelPublishSlot(channel_id=channel_id,slot_type=template_slot['slot_type'],slot_number=number,
            local_time=clock,timezone=template_slot['timezone'],status='archived')
        session.add(slot);session.flush()
    return slot


def analysis_topics(guidance, youtube_channel_id):
    if not guidance['report_id']:
        raise ConflictError('排期 Skill v2 需要先应用当前频道的初步分析或正式分析')
    block = strategy_yaml_block(guidance['diagnosis'])
    if not block:
        raise ConflictError('已生效分析缺少题材策略，请补齐并应用新版分析')
    try:
        strategy = yaml.safe_load(block['body'])['channel_strategy']
        if strategy['channel_id'] != youtube_channel_id:
            raise ValueError('频道不一致')
        topics = {
            'primary': strategy['content_priority'],
            'secondary': strategy['content_secondary'],
        }
        if any(not isinstance(items, list) or any(not isinstance(item, str) or not item.strip()
               for item in items) for items in topics.values()):
            raise ValueError('题材应为非空文字条目组成的列表')
    except (yaml.YAMLError, TypeError, KeyError, ValueError) as exc:
        raise ConflictError('已生效分析的频道或题材策略无效，请补齐并应用新版分析') from exc
    return {kind: list(dict.fromkeys(item.strip() for item in items)) for kind, items in topics.items()}


def available_playlists(session, channel_id, *, lock=False):
    query = select(ChannelPlaylist).where(ChannelPlaylist.channel_id == channel_id,
        ChannelPlaylist.status == 'active', ChannelPlaylist.youtube_playlist_id.is_not(None),
        ChannelPlaylist.url.is_not(None)).order_by(ChannelPlaylist.sort_order, ChannelPlaylist.id)
    if lock:
        query = query.with_for_update()
    from zhiju.services.feishu_sync import youtube_playlist_id_from_url
    return [
        {'id': p.id, 'youtube_playlist_id': p.youtube_playlist_id, 'url': p.url,
         'name': p.local_name, 'description': p.local_description or ''}
        for p in session.scalars(query)
        if p.youtube_playlist_id and urlsplit(p.url).scheme == 'https' and urlsplit(p.url).hostname in {'youtube.com', 'www.youtube.com', 'studio.youtube.com'}
        and youtube_playlist_id_from_url(p.url) == p.youtube_playlist_id
    ]


def create_plan(session,channel_id,start_date,end_date,daily_count,slot_topics=None,*,executor_protocol=None):
    channel = operations._active_channel(session, channel_id, lock=True)
    if end_date<start_date or (end_date-start_date).days>=31 or not 1<=daily_count<=10:
        raise ConflictError('请选择 1～31 天的日期范围和有效每日更新数量')
    skill_version = skill_catalog.scheduling_snapshot(session)
    uses_v2 = skill_version['label'] == 'channel-scheduling' and skill_version['revision'] >= 2
    uses_reference = uses_v2 and skill_version['revision'] >= 3
    uses_continuity = uses_reference and skill_version['revision'] >= 4
    if uses_continuity and executor_protocol is not None and executor_protocol < CONTINUITY_PROTOCOL:
        raise ConflictError('请先更新本机执行器至支持修订4观众承接对比的版本')
    if uses_reference and executor_protocol is not None and executor_protocol < REFERENCE_PROTOCOL:
        raise ConflictError('请先更新本机执行器至支持排期修订 3 的版本')
    if session.scalar(select(ChannelSchedulePlan.id).where(ChannelSchedulePlan.channel_id==channel_id,
        ChannelSchedulePlan.status.in_(['queued','running'])).limit(1)):
        raise ConflictError('频道已有排期规划任务，请先完成或取消')
    setting=session.scalar(select(V14Setting))
    if not setting:raise ConflictError('请先配置 Codex 执行主机和模型')
    slots = cadence_slots(session, channel_id, daily_count)
    if uses_v2 and slot_topics is None:
        raise ConflictError('AI 排期需要为每个档位选择主题材或辅题材')
    guidance = channel_guidance.resolve(session, channel_id, use_plan_snapshot=not uses_v2)
    if slot_topics is not None:
        if set(slot_topics) != {slot['id'] for slot in slots} or set(slot_topics.values()) - {'primary', 'secondary'}:
            raise ConflictError('请为当前每日更新模板的每个档位选择主题材或辅题材；若档期已变化，请重新打开规划')
        if guidance['dna_id'] and not uses_v2:
            dna = require_tenant_entity(session, ChannelDnaVersion, guidance['dna_id'])
            guidance['secondary_genre'] = dna.secondary_genre or guidance.get('secondary_genre')
    if uses_reference:
        reference = channel_guidance.applied_reference(session, channel_guidance.active_dna(session, channel_id))
        if not reference:
            raise ConflictError('请先应用包含八栏运营参考的频道分析；仍可手动排期')
        playlists = available_playlists(session, channel_id)
        if not playlists:
            raise ConflictError('当前频道没有可用播放列表，请在频道运营配置中补齐')
        topics = {kind: reference['sections']['topics'][kind] for kind in ('primary', 'secondary')}
    else:
        topics = analysis_topics(guidance, channel.youtube_channel_id) if uses_v2 else None
    pool,excluded=candidate_pool(session,channel)
    existing=list(session.scalars(select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id==channel_id)))
    dates=[start_date+timedelta(days=offset) for offset in range((end_date-start_date).days+1)]
    occupied=occupied_targets(session,channel_id,slots,set(dates),date_basis='beijing')
    targets=[]
    for offset in range((end_date-start_date).days+1):
        day=(start_date+timedelta(days=offset)).isoformat()
        for slot in slots:
            # Existing rows, including cancelled records, are never overwritten.
            if (day,slot['id']) not in occupied:targets.append({'publish_date':day,'publish_slot_id':slot['id']})
    if not targets:raise ConflictError('所选日期的档位已有排期，没有可新增的空档位')
    if not pool:raise ConflictError('没有可用候选剧：请核对最终合成、频道语言成片清单、历史排期与剧情资料')
    snapshot={'channel':{k:getattr(channel,k) for k in ('id','youtube_channel_id','original_name','default_language','timezone','default_genre')},
        'start_date':start_date.isoformat(),'end_date':end_date.isoformat(),'daily_count':daily_count,'date_basis':'beijing',
        'first_scheduled_date':min([start_date]+[r.planned_beijing_time.date() for r in existing if r.status not in {'cancelled','replaced'}]).isoformat(),
        'guidance':guidance,'slots':slots,'targets':targets,'candidates':pool,'excluded':excluded,
        'history':[{'drama_id':r.drama_id,'publish_date':r.planned_beijing_time.date().isoformat(),'status':r.status} for r in existing],
        'skill_version':skill_version,
        'model':setting.payload['default_model'],'account_profile':setting.payload['account_profile']}
    if slot_topics is not None:
        snapshot['slot_topics'] = slot_topics
    if topics is not None:
        snapshot['analysis_topics'] = topics
    if uses_reference:
        batch = schedule_batch.identity(language_code(language_aliases(session), channel.default_language),
                                        channel, targets, slots, date_basis='beijing')
        first, last, blocked = schedule_batch.reservations(session, channel_id, batch)
        snapshot.update(operating_reference=reference, playlists=playlists, batch=batch,
                        batch_window={'first': first.isoformat(), 'last': last.isoformat()},
                        batch_blocked=blocked)
    if uses_continuity:
        snapshot['selection_method'] = 'audience-continuity-v1'
    plan=ChannelSchedulePlan(channel_id=channel_id,host_id=setting.payload['host_id'],input_snapshot=snapshot)
    session.add(plan);session.commit();session.refresh(plan);return plan


def claimable_plans(query, executor_protocol):
    if executor_protocol < CONTINUITY_PROTOCOL:
        query = query.where(ChannelSchedulePlan.input_snapshot['selection_method'].as_string().is_(None))
    if executor_protocol < REFERENCE_PROTOCOL:
        query = query.where(ChannelSchedulePlan.input_snapshot['batch']['registered_on'].as_string().is_(None))
    if executor_protocol < SLOT_TOPICS_PROTOCOL:
        query = query.where(ChannelSchedulePlan.input_snapshot['slot_topics'].as_string().is_(None))
    return query


def claim_plan(session,host_id,*,claim_id=None,plan_id=None,executor_protocol=CONTINUITY_PROTOCOL):
    preferred_id=plan_id
    setting=session.scalar(select(V14Setting))
    if not setting or setting.payload['host_id']!=host_id:raise ConflictError('执行主机与公司配置不符')
    from zhiju.services.executor_queue import admission
    if not admission(session):return None
    queued = select(ChannelSchedulePlan.id).where(ChannelSchedulePlan.host_id==host_id,
        ChannelSchedulePlan.status=='queued')
    if preferred_id:
        queued = queued.where(ChannelSchedulePlan.id==preferred_id)
    plan_id=session.scalar(claimable_plans(queued, executor_protocol)
        .order_by(ChannelSchedulePlan.created_at).with_for_update(skip_locked=True).limit(1))
    if plan_id is None:return None
    row=get_plan(session,plan_id,True)
    row.status='running';row.claim_id=claim_id or str(uuid4());row.progress=None;row.heartbeat_at=datetime.now(timezone.utc)
    from zhiju.services.executor_queue import reserve
    reserve(session,'channel_scheduling',row)
    session.commit();return {**read(row),'tenant_id':row.tenant_id}


def claimed(session,plan_id,claim_id):
    row=get_plan(session,plan_id,True);session.refresh(row)
    if row.status!='running' or row.claim_id!=claim_id:raise ConflictError('排期规划领取已失效')
    return row


def freeze_evidence(session, plan_id, claim_id):
    row = claimed(session, plan_id, claim_id)
    snapshot = deepcopy(row.input_snapshot)
    if snapshot.get('selection_method') != 'audience-continuity-v1':
        raise ConflictError('旧任务保持原快照，不补写修订4证据')
    if snapshot.get('selection_evidence'):
        return read(row)
    # OAuth refresh and API IO must not retain a planning row lock.
    session.commit()
    from zhiju.services.schedule_evidence import collect
    evidence = collect(session, snapshot)
    row = claimed(session, plan_id, claim_id)
    if not row.input_snapshot.get('selection_evidence'):
        row.input_snapshot = {**row.input_snapshot, 'selection_evidence': evidence}
        session.commit()
    return read(row)


def validate_result(plan,result):
    from zhiju.scheduling_rules.contract import validate_result as validate_plan
    try:
        return validate_plan(plan.input_snapshot,result)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc


def submit_result(session,plan_id,claim_id,*,result=None,error=None):
    row=claimed(session,plan_id,claim_id)
    if error:
        row.error=str(error)[:4000];row.status='failed'
    else:
        row.result=validate_result(row,result);row.status='ready';row.error=None
    session.commit();return row


def cancel_plan(session,plan_id):
    row=get_plan(session,plan_id,True)
    if row.status=='applied':raise ConflictError('已保存的排期不能在此取消')
    row.status='cancelled';row.claim_id=None;session.commit();return row


def resume_plan(session,plan_id,stopped_confirmed):
    row=get_plan(session,plan_id,True)
    if not stopped_confirmed or row.status not in {'failed','running','cancelled'}:
        raise ConflictError('确认旧执行已停止后才能恢复失败或中断的规划')
    from zhiju.services.executor_queue import release_stopped_run
    release_stopped_run(session,'channel_scheduling',row.id)
    row.claim_id=None;row.status='queued';row.error=None;row.progress=None;row.heartbeat_at=None;session.commit();return row


def apply_plan(session,plan_id):
    schedule_batch.lock_confirmations(session)
    row=get_plan(session,plan_id,True)
    if row.status=='applied':return row
    if row.status!='ready':raise ConflictError('规划尚未完成，不能保存')
    channel=operations._active_channel(session,row.channel_id,lock=True)
    snapshot=row.input_snapshot
    batch = snapshot.get('batch')
    if channel.default_language!=snapshot['channel']['default_language']:
        raise ConflictError('频道语言已变化，请重新规划')
    if cadence_slots(session,channel.id,snapshot['daily_count'])!=snapshot['slots']:
        raise ConflictError('频道档位已变化，请重新规划')
    result=validate_result(row,row.result)
    selected=[r for r in result['rows'] if r['drama_id']]
    if not selected:raise ConflictError('所有档位均缺少合格剧目，没有可保存的排期')
    if batch:
        current_batch = schedule_batch.identity(language_code(language_aliases(session), channel.default_language),
                                                channel, snapshot['targets'], snapshot['slots'], date_basis=snapshot.get('date_basis'))
        if current_batch != batch:
            raise ConflictError('频道录入日期或同批身份已变化，请重新规划')
        _, _, blocked = schedule_batch.reservations(session, channel.id, batch)
        schedule_batch.check(selected, blocked)
        available = {p['id']: p for p in available_playlists(session, channel.id, lock=True)}
        frozen_playlists = {p['id']: p for p in snapshot['playlists']}
        for entry in selected:
            pid = entry['playlist_id']
            if not available.get(pid) or available[pid] != frozen_playlists[pid]:
                raise ConflictError('排期指定的播放列表已失效或变更，请重新预览')

    elif schedule_batch.default_uses_batch(session):
        schedule_batch.guard_confirmed_rows(session, channel, selected)

    current={d['id']:d for d in candidate_pool(session,channel)[0]}
    frozen={d['id']:d for d in snapshot['candidates']}
    for entry in selected:
        if entry['drama_id'] not in current:raise ConflictError('候选剧已失效或已排入本频道，请重新规划')
        if current[entry['drama_id']]!=frozen[entry['drama_id']]:raise ConflictError('候选剧资料已变化，请重新规划')
    existing=occupied_targets(session,channel.id,snapshot['slots'],
        {date.fromisoformat(r['publish_date']) for r in selected},date_basis=snapshot.get('date_basis'))
    if any((r['publish_date'],r['publish_slot_id']) in existing for r in selected):
        raise ConflictError('预览后的档位已被占用，请重新规划；未保存任何新排期')
    guidance=snapshot['guidance'];dna_id=guidance['dna_id']
    try:
        if not dna_id or guidance.get('source')=='legacy_reference':
            version=(session.scalar(select(func.max(ChannelDnaVersion.version_number)).where(ChannelDnaVersion.channel_id==channel.id)) or 0)+1
            dna=ChannelDnaVersion(channel_id=channel.id,version_number=version,status='draft',language=channel.default_language,
                primary_genre=channel.default_genre or '冷启动定位',audience_summary=guidance['profile'],reference_summary=guidance['generation_spec'])
            session.add(dna);session.flush();dna_id=dna.id
        definitions={slot['id']:slot for slot in snapshot['slots']}
        selected_slot_ids={r['publish_slot_id'] for r in selected}
        saved_slots={key:stored_slot(session,channel.id,slot) for key,slot in definitions.items()
                     if key in selected_slot_ids}
        schedules=[]
        for entry in selected:
            schedule=ChannelScheduleEntry(channel_id=channel.id,drama_id=entry['drama_id'],channel_dna_version_id=dna_id,
                publish_slot_id=saved_slots[entry['publish_slot_id']].id,
                publish_date=datetime.fromisoformat(entry['planned_local_time']).date(),
                planned_local_time=datetime.fromisoformat(entry['planned_local_time']),
                planned_utc_time=datetime.fromisoformat(entry['planned_utc_time']),
                planned_beijing_time=datetime.fromisoformat(entry['planned_beijing_time']),
                playlist_id=entry.get('playlist_id') if batch else None,
                community_count=0,status='planned',priority=100,source_type='system',idempotency_key=f'plan:{row.id}:{entry["publish_date"]}:{entry["publish_slot_id"]}')
            session.add(schedule);session.flush();schedules.append(schedule)
            session.add(ScheduleCandidate(schedule_id=schedule.id,drama_id=schedule.drama_id,candidate_type='primary',rank_number=1,
                reason=entry['reason']+'\n剧情依据：'+entry['plot_evidence']+'\n编排理由：'+entry['pairing_reason'],status='selected'))
            session.add(ScheduleChangeHistory(schedule_id=schedule.id,new_drama_id=schedule.drama_id,
                new_planned_utc_time=schedule.planned_utc_time,new_status='planned',reason=f'确认AI排期预览 {row.id}',
                actor_type='system',changed_at=datetime.now(timezone.utc)))
        from zhiju.services.community_requirements import initialize_schedule_community
        # Count after every selected row is flushed so the same day is complete.
        for schedule in schedules:
            initialize_schedule_community(session, schedule)
        row.dna_id = dna_id
        row.result = {**result, 'schedule_ids': [schedule.id for schedule in schedules]}
        row.status = 'applied'
        _audit(session,'schedule_plan.applied','channel_schedule_plan',row.id)
        session.commit()
    except Exception:
        session.rollback();raise
    return row
