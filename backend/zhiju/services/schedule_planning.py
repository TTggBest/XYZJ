"""AI selects stories; the server owns eligibility, times and atomic persistence."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from zhiju.models import (Channel, ChannelSchedulePlan, ChannelScheduleEntry, ChannelPublishSlot,
    Drama, DramaProductionState, ChannelDnaVersion, ScheduleCandidate, ScheduleChangeHistory, Language)
from zhiju.models.v14 import V14Setting
from zhiju.services import channel_guidance, operations, skill_catalog
from zhiju.services.identity import ConflictError, _audit
from zhiju.tenant_repository import require_tenant_entity
from zhiju.services.schedule_youtube import LANGUAGES

PLOT_FIELDS=('content_summary','plot_archive','plot_pattern','core_personas')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def read(plan, *, summary=False):
    result={key:getattr(plan,key) for key in ('id','channel_id','host_id','status','claim_id','heartbeat_at',
        'dna_id','input_snapshot','result','error','created_at','updated_at')}
    if summary:
        result['input_snapshot']={k:plan.input_snapshot[k] for k in ('channel','start_date','end_date','daily_count')}
        result['result']=None
    return result


def get_plan(session, plan_id, lock=False):
    return require_tenant_entity(session,ChannelSchedulePlan,plan_id,lock=lock)


def list_plans(session, channel_id):
    require_tenant_entity(session,Channel,channel_id)
    return list(session.scalars(select(ChannelSchedulePlan).where(ChannelSchedulePlan.channel_id==channel_id)
        .order_by(ChannelSchedulePlan.created_at.desc(),ChannelSchedulePlan.id.desc()).limit(20)))


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
        pool.append({k:drama.get(k) for k in ('id','chinese_title','drama_code',*PLOT_FIELDS)} | {
            'duration_seconds':duration,'expires_at':drama['expires_at'].isoformat() if drama['expires_at'] else None,
            'finished_languages':state.finished_languages})
    return pool,excluded


def active_slots(session,channel_id,daily_count):
    slots=list(session.scalars(select(ChannelPublishSlot).where(ChannelPublishSlot.channel_id==channel_id,
        ChannelPublishSlot.status=='active').order_by(ChannelPublishSlot.local_time,ChannelPublishSlot.id)))
    if len(slots)<daily_count:
        raise ConflictError('频道启用档位不足，请先配置所需数量的频道档期')
    # A one-release plan uses the explicit main slot; larger plans add configured auxiliary slots.
    slots=sorted(slots,key=lambda r:(r.slot_type!='main',r.slot_number,r.local_time))[:daily_count]
    slots.sort(key=lambda r:(r.local_time,r.id))
    return [{'id':r.id,'slot_type':r.slot_type,'slot_number':r.slot_number,'local_time':r.local_time.isoformat(),
             'timezone':r.timezone} for r in slots]


def create_plan(session,channel_id,start_date,end_date,daily_count):
    channel=operations._active_channel(session,channel_id,lock=True)
    if end_date<start_date or (end_date-start_date).days>=31 or not 1<=daily_count<=10:
        raise ConflictError('请选择 1～31 天的日期范围和有效每日更新数量')
    if session.scalar(select(ChannelSchedulePlan.id).where(ChannelSchedulePlan.channel_id==channel_id,
        ChannelSchedulePlan.status.in_(['queued','running'])).limit(1)):
        raise ConflictError('频道已有排期规划任务，请先完成或取消')
    setting=session.scalar(select(V14Setting))
    if not setting:raise ConflictError('请先配置 Codex 执行主机和模型')
    guidance=channel_guidance.resolve(session,channel_id)
    slots=active_slots(session,channel_id,daily_count)
    pool,excluded=candidate_pool(session,channel)
    existing=list(session.scalars(select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id==channel_id)))
    occupied={(r.publish_date.isoformat(),r.publish_slot_id) for r in existing}
    targets=[]
    for offset in range((end_date-start_date).days+1):
        day=(start_date+timedelta(days=offset)).isoformat()
        for slot in slots:
            # Existing rows, including cancelled records, are never overwritten.
            if (day,slot['id']) not in occupied:targets.append({'publish_date':day,'publish_slot_id':slot['id']})
    if not targets:raise ConflictError('所选日期的档位已有排期，没有可新增的空档位')
    if not pool:raise ConflictError('没有可用候选剧：请核对最终合成、频道语言成片清单、历史排期与剧情资料')
    snapshot={'channel':{k:getattr(channel,k) for k in ('id','youtube_channel_id','original_name','default_language','timezone','default_genre')},
        'start_date':start_date.isoformat(),'end_date':end_date.isoformat(),'daily_count':daily_count,
        'first_scheduled_date':min([start_date]+[r.publish_date for r in existing if r.status not in {'cancelled','replaced'}]).isoformat(),
        'guidance':guidance,'slots':slots,'targets':targets,'candidates':pool,'excluded':excluded,
        'history':[{'drama_id':r.drama_id,'publish_date':r.publish_date.isoformat(),'status':r.status} for r in existing],
        'skill_version':skill_catalog.scheduling_snapshot(session),
        'model':setting.payload['default_model'],'account_profile':setting.payload['account_profile']}
    plan=ChannelSchedulePlan(channel_id=channel_id,host_id=setting.payload['host_id'],input_snapshot=snapshot)
    session.add(plan);session.commit();session.refresh(plan);return plan


def claim_plan(session,host_id):
    setting=session.scalar(select(V14Setting))
    if not setting or setting.payload['host_id']!=host_id:raise ConflictError('执行主机与公司配置不符')
    row=session.scalar(select(ChannelSchedulePlan).where(ChannelSchedulePlan.host_id==host_id,
        ChannelSchedulePlan.status=='queued').order_by(ChannelSchedulePlan.created_at)
        .with_for_update(skip_locked=True).limit(1))
    if row is None:return None
    row.status='running';row.claim_id=str(uuid4());row.heartbeat_at=datetime.now(timezone.utc)
    session.commit();return {**read(row),'tenant_id':row.tenant_id}


def claimed(session,plan_id,claim_id):
    row=get_plan(session,plan_id,True);session.refresh(row)
    if row.status!='running' or row.claim_id!=claim_id:raise ConflictError('排期规划领取已失效')
    return row


def validate_result(plan,result):
    from datetime import time
    snapshot=plan.input_snapshot
    if not isinstance(result,dict) or not isinstance(result.get('rows'),list):raise ConflictError('排期输出缺少 rows')
    targets={(r['publish_date'],r['publish_slot_id']) for r in snapshot['targets']}
    candidates={d['id']:d for d in snapshot['candidates']}
    slots={r['id']:r for r in snapshot['slots']}
    seen=set();used=set();rows=[]
    for row in result['rows']:
        if not isinstance(row,dict):raise ConflictError('排期行格式错误')
        key=(row.get('publish_date'),row.get('publish_slot_id'))
        if key not in targets or key in seen:raise ConflictError('排期日期档位缺失、重复或超出本次范围')
        seen.add(key)
        if not str(row.get('reason') or '').strip():raise ConflictError('每个排期或缺口须说明原因')
        drama_id=row.get('drama_id')
        if drama_id is None:
            rows.append({'publish_date':key[0],'publish_slot_id':key[1],'drama_id':None,'reason':row['reason'],'status':'blocked'});continue
        if drama_id not in candidates or drama_id in used:raise ConflictError('选剧不在候选池或同频道重复')
        used.add(drama_id);drama=candidates[drama_id];slot=slots[key[1]]
        evidence=str(row.get('plot_evidence') or '').strip()
        if len(evidence)<4 or not any(evidence in (drama.get(k) or '') for k in PLOT_FIELDS):
            raise ConflictError('选剧须引用真实剧情原文，不能仅凭剧名或编造剧情')
        if not str(row.get('pairing_reason') or '').strip():raise ConflictError('缺少同日搭配或编排理由')
        duration=drama['duration_seconds']
        if slot['slot_type']=='main' and (duration is None or duration<6000):
            raise ConflictError('主档不足100分钟或时长未知，请标记缺口而非静默替代')
        local=datetime.combine(date.fromisoformat(key[0]),time.fromisoformat(slot['local_time']),ZoneInfo(slot['timezone']))
        instant=local.astimezone(timezone.utc)
        # A nonexistent DST clock time has no matching round trip.
        if instant.astimezone(ZoneInfo(slot['timezone'])).replace(tzinfo=None)!=local.replace(tzinfo=None):
            raise ConflictError('档位落在夏令时跳过的当地时间，请调整档位后重新规划')
        if drama['expires_at'] and utc(datetime.fromisoformat(drama['expires_at']))<=instant:
            raise ConflictError('剧目在计划发布时间已到期')
        rows.append({**row,'chinese_title':drama['chinese_title'],'duration_seconds':duration,
            'finished_languages':drama['finished_languages'],'status':'planned','slot_type':slot['slot_type'],
            'planned_local_time':local.replace(tzinfo=None).isoformat(),
            'planned_utc_time':instant.replace(tzinfo=None).isoformat(),
            'planned_beijing_time':instant.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None).isoformat(),
            'warnings':['辅档时长未验证'] if duration is None else []})
    if seen!=targets:raise ConflictError('输出没有覆盖所有空档位；无合格剧目时也须逐档说明缺口')
    return {'rows':sorted(rows,key=lambda r:(r['publish_date'],slots[r['publish_slot_id']]['local_time'])),
            'schedule_ids':[]}


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
    row.claim_id=None;row.status='queued';row.error=None;session.commit();return row


def apply_plan(session,plan_id):
    row=get_plan(session,plan_id,True)
    if row.status=='applied':return row
    if row.status!='ready':raise ConflictError('规划尚未完成，不能保存')
    channel=operations._active_channel(session,row.channel_id,lock=True)
    snapshot=row.input_snapshot
    if channel.default_language!=snapshot['channel']['default_language']:
        raise ConflictError('频道语言已变化，请重新规划')
    if active_slots(session,channel.id,snapshot['daily_count'])!=snapshot['slots']:
        raise ConflictError('频道档位已变化，请重新规划')
    result=validate_result(row,row.result)
    selected=[r for r in result['rows'] if r['drama_id']]
    if not selected:raise ConflictError('所有档位均缺少合格剧目，没有可保存的排期')
    current={d['id']:d for d in candidate_pool(session,channel)[0]}
    frozen={d['id']:d for d in snapshot['candidates']}
    for entry in selected:
        if entry['drama_id'] not in current:raise ConflictError('候选剧已失效或已排入本频道，请重新规划')
        if current[entry['drama_id']]!=frozen[entry['drama_id']]:raise ConflictError('候选剧资料已变化，请重新规划')
    existing={(r.publish_date.isoformat(),r.publish_slot_id) for r in session.scalars(select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id==channel.id))}
    if any((r['publish_date'],r['publish_slot_id']) in existing for r in selected):
        raise ConflictError('预览后的档位已被占用，请重新规划；未保存任何新排期')
    guidance=snapshot['guidance'];dna_id=guidance['dna_id']
    try:
        if not dna_id or guidance.get('source')=='legacy_reference':
            version=(session.scalar(select(func.max(ChannelDnaVersion.version_number)).where(ChannelDnaVersion.channel_id==channel.id)) or 0)+1
            dna=ChannelDnaVersion(channel_id=channel.id,version_number=version,status='draft',language=channel.default_language,
                primary_genre=channel.default_genre or '冷启动定位',audience_summary=guidance['profile'],reference_summary=guidance['generation_spec'])
            session.add(dna);session.flush();dna_id=dna.id
        ids=[]
        for entry in selected:
            schedule=ChannelScheduleEntry(channel_id=channel.id,drama_id=entry['drama_id'],channel_dna_version_id=dna_id,
                publish_slot_id=entry['publish_slot_id'],publish_date=date.fromisoformat(entry['publish_date']),
                planned_local_time=datetime.fromisoformat(entry['planned_local_time']),
                planned_utc_time=datetime.fromisoformat(entry['planned_utc_time']),
                planned_beijing_time=datetime.fromisoformat(entry['planned_beijing_time']),
                community_count=0,status='planned',priority=100,source_type='system',idempotency_key=f'plan:{row.id}:{entry["publish_date"]}:{entry["publish_slot_id"]}')
            session.add(schedule);session.flush();ids.append(schedule.id)
            session.add(ScheduleCandidate(schedule_id=schedule.id,drama_id=schedule.drama_id,candidate_type='primary',rank_number=1,
                reason=entry['reason']+'\n剧情依据：'+entry['plot_evidence']+'\n编排理由：'+entry['pairing_reason'],status='selected'))
            session.add(ScheduleChangeHistory(schedule_id=schedule.id,new_drama_id=schedule.drama_id,
                new_planned_utc_time=schedule.planned_utc_time,new_status='planned',reason=f'确认AI排期预览 {row.id}',
                actor_type='system',changed_at=datetime.now(timezone.utc)))
        row.dna_id=dna_id;row.result={**result,'schedule_ids':ids};row.status='applied'
        _audit(session,'schedule_plan.applied','channel_schedule_plan',row.id)
        session.commit()
    except Exception:
        session.rollback();raise
    return row
