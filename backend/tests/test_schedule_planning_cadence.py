from datetime import date, time
from sqlalchemy import select
from test_schedule_planning import data, configured
from zhiju.models import (ChannelPublishSlot, PublishCadenceTemplateSlot, Drama, DramaProductionState,
                          ChannelScheduleEntry)
from zhiju.services import schedule_planning as service


def test_ai_double_release_uses_the_same_templates_as_cadence_table_with_archived_slots(data):
    configured(data)
    s,c,main_drama,_,_=data
    c.timezone='America/Sao_Paulo';c.daily_publish_count=2
    old_main=ChannelPublishSlot(channel_id=c.id,slot_type='main',slot_number=1,local_time=time(18),
                               timezone=c.timezone,status='archived')
    old_aux=ChannelPublishSlot(channel_id=c.id,slot_type='aux',slot_number=1,local_time=time(10),
                              timezone=c.timezone,status='archived')
    aux_template=PublishCadenceTemplateSlot(daily_publish_count=2,slot_type='aux',slot_number=1,
                                           local_video_time=time(10),engagement_offset_minutes=120)
    main_template=PublishCadenceTemplateSlot(daily_publish_count=2,slot_type='main',slot_number=2,
                                            local_video_time=time(18),engagement_offset_minutes=120)
    aux_drama=Drama(drama_number=2,drama_code='D2',chinese_title='夺回家产',normalized_title='夺回家产',
                    status='active',content_summary='女主揭穿骗局，夺回家产。')
    s.add_all([old_main,old_aux,aux_template,main_template,aux_drama]);s.flush()
    s.add(DramaProductionState(drama_id=aux_drama.id,production_completion_status='completed',
                               finished_languages=['en'],total_duration_seconds=3600));s.commit()
    plan=service.create_plan(s,c.id,date(2026,11,10),date(2026,11,10),2)
    cadence=next(r for r in service.operations.list_cadence_overview(s,on_date=date(2026,11,10)) if r['channel_id']==c.id)
    assert [(r['id'],r['local_time'][:5],r['timezone']) for r in plan.input_snapshot['slots']]==[
        (aux_template.id,'10:00','America/Sao_Paulo'),(main_template.id,'18:00','America/Sao_Paulo')]
    assert [r['local_time'][:5] for r in plan.input_snapshot['slots']]==[r['local_video_time'] for r in cadence['slots']]
    assert len(list(s.scalars(select(ChannelPublishSlot))))==2,'预览不能新建或启用独立档位'
    claim=service.claim_plan(s,'host')
    service.submit_result(s,plan.id,claim['claim_id'],result={'rows':[
        {'publish_date':'2026-11-10','publish_slot_id':aux_template.id,'drama_id':aux_drama.id,
         'reason':'女主夺回权利','plot_evidence':'女主揭穿骗局，夺回家产。','pairing_reason':'同日以反击串联'},
        {'publish_date':'2026-11-10','publish_slot_id':main_template.id,'drama_id':main_drama.id,
         'reason':'女主主动反击','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'主档呈现较长完整故事'}]})
    assert [r['planned_beijing_time'] for r in plan.result['rows']]==['2026-11-10T21:00:00','2026-11-11T05:00:00']
    service.apply_plan(s,plan.id)
    rows=list(s.scalars(select(ChannelScheduleEntry).order_by(ChannelScheduleEntry.planned_utc_time)))
    assert [r.publish_slot_id for r in rows]==[old_aux.id,old_main.id]
    assert old_main.status==old_aux.status=='archived'
    assert len(list(s.scalars(select(ChannelPublishSlot))))==2


def test_template_time_change_after_preview_requires_replanning_without_touching_history(data):
    import pytest
    from zhiju.services.identity import ConflictError
    from test_schedule_planning import ready
    s,c,d,template,_=data
    plan=ready(data)
    historical=ChannelPublishSlot(channel_id=c.id,slot_type='main',slot_number=1,local_time=time(20),
                                  timezone=c.timezone,status='archived')
    s.add(historical);template.local_video_time=time(21);s.commit()
    with pytest.raises(ConflictError,match='档位已变化'):service.apply_plan(s,plan.id)
    assert list(s.scalars(select(ChannelScheduleEntry)))==[]
    assert historical.status=='archived' and historical.local_time==time(20)


def test_existing_historical_main_blocks_the_same_template_slot_even_if_clock_time_changed(data):
    import pytest
    from zhiju.services.identity import ConflictError
    configured(data);s,c,d,_,_=data
    historical=ChannelPublishSlot(channel_id=c.id,slot_type='main',slot_number=1,local_time=time(18),
                                  timezone=c.timezone,status='archived')
    s.add(historical);s.flush()
    from datetime import datetime
    existing=ChannelScheduleEntry(channel_id=c.id,drama_id=d.id,publish_slot_id=historical.id,
        publish_date=date(2026,11,10),planned_local_time=datetime(2026,11,10,18),
        planned_beijing_time=datetime(2026,11,11,7),planned_utc_time=datetime(2026,11,10,23),
        status='published',source_type='feishu',idempotency_key='old-feishu-row')
    s.add(existing);s.commit()
    with pytest.raises(ConflictError,match='没有可新增'):service.create_plan(s,c.id,date(2026,11,10),date(2026,11,10),1)
    assert list(s.scalars(select(ChannelScheduleEntry)))==[existing]
    assert existing.publish_slot_id==historical.id


def test_missing_unified_template_does_not_fall_back_to_old_active_slots(data):
    import pytest
    from zhiju.services.identity import ConflictError
    configured(data);s,c,_,_,_=data
    s.add(ChannelPublishSlot(channel_id=c.id,slot_type='aux',slot_number=1,local_time=time(8),
                            timezone=c.timezone,status='active'));s.commit()
    with pytest.raises(ConflictError,match='2更的统一档期模板'):
        service.create_plan(s,c.id,date(2026,11,10),date(2026,11,10),2)


def test_switching_to_single_release_cannot_add_a_second_release_to_an_occupied_day(data):
    import pytest
    from datetime import datetime
    from zhiju.services.identity import ConflictError
    configured(data);s,c,d,_,_=data
    historical=ChannelPublishSlot(channel_id=c.id,slot_type='aux',slot_number=1,local_time=time(8),
                                  timezone=c.timezone,status='archived')
    s.add(historical);s.flush()
    existing=ChannelScheduleEntry(channel_id=c.id,drama_id=d.id,publish_slot_id=historical.id,
        publish_date=date(2026,11,10),planned_local_time=datetime(2026,11,10,8),
        planned_beijing_time=datetime(2026,11,10,21),planned_utc_time=datetime(2026,11,10,13),
        status='planned',source_type='feishu',idempotency_key='existing-auxiliary')
    s.add(existing);s.commit()
    with pytest.raises(ConflictError,match='没有可新增'):
        service.create_plan(s,c.id,date(2026,11,10),date(2026,11,10),1)
    assert len(list(s.scalars(select(ChannelScheduleEntry))))==1
