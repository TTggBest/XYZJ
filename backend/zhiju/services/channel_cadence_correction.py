"""Apply an explicitly selected audience timezone to future unpublished schedules."""
from datetime import datetime,time,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select,func
from zhiju.models import Channel,ChannelPublishSlot,ChannelScheduleEntry,ChannelSchedulePlan,ScheduleChangeHistory
from zhiju.tenant_repository import require_tenant_entity
from zhiju.services import schedule_planning,operations
from zhiju.services.identity import ConflictError,_audit


def correct_timezone(session,channel_id,zone,on_date):
    ZoneInfo(zone)
    c=require_tenant_entity(session,Channel,channel_id,lock=True)
    c.timezone=zone
    for slot in list(session.scalars(select(ChannelPublishSlot).where(ChannelPublishSlot.channel_id==c.id,ChannelPublishSlot.status=='active'))):
        if slot.slot_type in {'aux','main'}:
            clock=time(10 if slot.slot_type=='aux' else 18)
            if slot.timezone==zone and slot.local_time==clock:continue
            slot.status='archived'
            number=(session.scalar(select(func.max(ChannelPublishSlot.slot_number)).where(ChannelPublishSlot.channel_id==c.id,ChannelPublishSlot.slot_type==slot.slot_type)) or 0)+1
            session.add(ChannelPublishSlot(channel_id=c.id,slot_type=slot.slot_type,slot_number=number,local_time=clock,timezone=zone,status='active'))
            session.flush()
    changed=[];external=[]
    for row in session.scalars(select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id==c.id,
            ChannelScheduleEntry.publish_date>=on_date,ChannelScheduleEntry.status.in_(['planned','reserved','confirmed']),ChannelScheduleEntry.is_published.is_(False))):
        old=require_tenant_entity(session,ChannelPublishSlot,row.publish_slot_id)
        if old.slot_type not in {'main','aux'}:continue
        clock=time(10 if old.slot_type=='aux' else 18)
        local=datetime.combine(row.publish_date,clock,tzinfo=ZoneInfo(zone))
        beijing=local.astimezone(ZoneInfo('Asia/Shanghai'));utc=local.astimezone(timezone.utc)
        if row.planned_utc_time.replace(tzinfo=timezone.utc)==utc:continue
        if row.is_uploaded:external.append(row.id);continue
        slot=schedule_planning.stored_slot(session,c.id,{'slot_type':old.slot_type,'local_time':clock.isoformat(),'timezone':zone})
        session.add(ScheduleChangeHistory(schedule_id=row.id,old_drama_id=row.drama_id,new_drama_id=row.drama_id,
            old_planned_utc_time=row.planned_utc_time,new_planned_utc_time=utc,old_status=row.status,new_status=row.status,
            reason='用户确认频道受众时区及辅档10:00、主档18:00',actor_type='user',changed_at=datetime.now(timezone.utc)))
        row.publish_slot_id=slot.id;row.planned_local_time=local;row.planned_beijing_time=beijing;row.planned_utc_time=utc;changed.append(row.id)
    invalidated=[]
    for plan in session.scalars(select(ChannelSchedulePlan).where(ChannelSchedulePlan.channel_id==c.id,ChannelSchedulePlan.status.in_(['queued','running','ready','failed']))):
        snapshot=plan.input_snapshot.get('channel',{})
        if snapshot.get('default_language')!=c.default_language or snapshot.get('timezone')!=zone:
            plan.status='cancelled';plan.claim_id=None;plan.error='频道语言或受众时区已纠正，请按当前配置重新生成预览';invalidated.append(plan.id)
    _audit(session,'channel.cadence_corrected','channel',c.id,'用户确认时区 '+zone)
    return {'channel_id':c.id,'timezone':zone,'schedules_updated':changed,'uploaded_requires_review':external,'invalidated_plans':invalidated}
