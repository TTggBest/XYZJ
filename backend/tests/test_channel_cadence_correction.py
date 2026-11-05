from datetime import date,datetime,timezone
from sqlalchemy import select
import pytest
from test_schedule_planning import data,configured
from zhiju.models import ChannelScheduleEntry,ChannelSchedulePlan,ChannelPublishSlot,ChannelDnaVersion
from zhiju.services import schedule_planning,channel_guidance
from zhiju.services.channel_cadence_correction import correct_timezone
from zhiju.services.identity import ConflictError


@pytest.mark.parametrize('zone,expected_day,expected_time',[
 ('Asia/Manila',9,'10:00'),('Europe/Paris',10,'01:00'),('America/Mexico_City',10,'08:00'),('Asia/Bangkok',9,'19:00')])
def test_correct_audience_timezone_and_future_times_preserving_plot_and_history(data,zone,expected_day,expected_time):
    s,c,d,template,_=data;configured(data)
    plan=schedule_planning.create_plan(s,c.id,date(2026,11,9),date(2026,11,9),1)
    claim=schedule_planning.claim_plan(s,'host')
    result={'rows':[{'publish_date':'2026-11-09','publish_slot_id':template.id,'drama_id':d.id,'reason':'符合定位','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'单更'}]}
    schedule_planning.submit_result(s,plan.id,claim['claim_id'],result=result);schedule_planning.apply_plan(s,plan.id)
    row=s.scalar(select(ChannelScheduleEntry));original_slot=s.get(ChannelPublishSlot,row.publish_slot_id);old_zone=original_slot.timezone
    # Manila main remains local18 => Beijing18; the other dates exercise DST/cross-day conversion.
    expected_time='18:00' if zone=='Asia/Manila' else expected_time
    corrected=correct_timezone(s,c.id,zone,date(2026,11,5));s.commit()
    assert row.drama_id==d.id and row.status=='planned'
    assert row.planned_beijing_time.day==expected_day and row.planned_beijing_time.strftime('%H:%M')==expected_time
    assert original_slot.timezone==old_zone
    assert plan.status=='applied' and plan.input_snapshot['channel']['timezone']==old_zone
    assert corrected['schedules_updated']==[row.id]
    assert not correct_timezone(s,c.id,zone,date(2026,11,5))['schedules_updated']


def test_language_correction_invalidates_unapplied_preview_and_rejects_old_active_analysis(data):
    s,c,*_=data;configured(data)
    plan=schedule_planning.create_plan(s,c.id,date(2026,11,9),date(2026,11,9),1)
    plan.status='ready';c.default_language='th'
    s.add(ChannelDnaVersion(channel_id=c.id,version_number=1,status='active',language='en',primary_genre='old',audience_summary='old',reference_summary='old'))
    s.commit()
    result=correct_timezone(s,c.id,'Asia/Bangkok',date(2026,11,5));s.commit()
    assert plan.status=='cancelled' and result['invalidated_plans']==[plan.id]
    with pytest.raises(ConflictError,match='语言'):channel_guidance.resolve(s,c.id)
    dna=s.scalar(select(ChannelDnaVersion).where(ChannelDnaVersion.channel_id==c.id))
    with pytest.raises(ConflictError,match='语言'):channel_guidance.resolve(s,c.id,dna.id)


def test_active_slot_definition_is_preserved_for_published_history(data):
    s,c,d,template,_=data;configured(data)
    from datetime import time
    template=ChannelPublishSlot(channel_id=c.id,slot_type='main',slot_number=1,local_time=time(18),timezone='America/New_York',status='active')
    s.add(template);s.commit()
    old_zone,old_time=template.timezone,template.local_time
    corrected=correct_timezone(s,c.id,'Asia/Bangkok',date(2026,11,5));s.commit()
    assert template.timezone==old_zone and template.local_time==old_time
    assert template.status=='archived'
    active=list(s.scalars(select(ChannelPublishSlot).where(ChannelPublishSlot.channel_id==c.id,ChannelPublishSlot.status=='active')))
    assert active and all(slot.timezone=='Asia/Bangkok' for slot in active)
