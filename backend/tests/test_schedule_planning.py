from datetime import date, datetime, time, timezone
import pytest
from sqlalchemy import create_engine, select
from zhiju.database import TenantSession
from zhiju.models import Base, Channel, ChannelPublishSlot, Drama, DramaProductionState, PublishCadenceTemplateSlot
from zhiju.services import operations


@pytest.fixture
def data():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={'tenant_id': 'planning-test'}) as s:
        channel = Channel(original_name='任意新频道', youtube_channel_id='UCplan',
                          default_language='en', timezone='America/New_York', status='active', daily_publish_count=1)
        drama = Drama(drama_number=1, drama_code='D1', chinese_title='重获人生', normalized_title='重获人生',
                      status='active', content_summary='女主遭到背叛后夺回公司。')
        s.add_all([channel, drama]); s.flush()
        slot = PublishCadenceTemplateSlot(daily_publish_count=1,slot_type='main',slot_number=1,
                                          local_video_time=time(20),engagement_offset_minutes=120)
        state = DramaProductionState(drama_id=drama.id, production_completion_status='completed',
                                     finished_languages=['en'], total_duration_seconds=7200)
        s.add_all([slot, state]); s.commit()
        yield s, channel, drama, slot, state
    engine.dispose()


def test_final_composition_is_the_scheduling_gate(data):
    s, channel, drama, slot, state = data
    assert [d['id'] for d in operations.list_schedulable_dramas(s)] == [drama.id]
    state.production_completion_status = 'in_progress'; s.commit()
    assert operations.list_schedulable_dramas(s) == []


def configured(data):
    from zhiju.models.v14 import V14Setting
    from zhiju.models import ChannelProfile
    s, c, *_ = data
    s.add(V14Setting(payload={'host_id':'host','account_profile':'current','default_model':'model',
        'channel_inputs':{c.id:{'generation_spec':'## [GLOBAL]\n冷启动，女主逆袭'}}}))
    s.add(ChannelProfile(channel_id=c.id, positioning='冷启动，未经数据验证。围绕女性逆袭选剧。'))
    s.commit()


@pytest.mark.parametrize('action',['history','claim'])
def test_large_story_snapshot_does_not_participate_in_database_sort(data,action):
    from datetime import timedelta
    from sqlalchemy import event
    from zhiju.models import ChannelSchedulePlan
    from zhiju.services import schedule_planning as service
    configured(data)
    s,c,*_=data
    plans=[]
    for i in range(22):
        plan=ChannelSchedulePlan(channel_id=c.id,host_id='host',status='queued' if i==0 else 'ready',
            created_at=datetime(2026,11,1,tzinfo=timezone.utc)+timedelta(minutes=i),
            input_snapshot={'candidates':[{'plot':'large frozen story '*20000}]})
        s.add(plan);plans.append(plan)
    s.commit()
    expected=[p.id for p in plans]
    def mysql_sort_limit(conn,cursor,statement,parameters,context,executemany):
        # Reproduce MySQL's wide-JSON filesort failure without a live database.
        if 'FROM channel_schedule_plans' in statement and 'ORDER BY' in statement:
            assert 'channel_schedule_plans.input_snapshot' not in statement,'large story JSON in database sort'
            assert 'channel_schedule_plans.result' not in statement,'large generated result in database sort'
    engine=s.get_bind()
    event.listen(engine,'before_cursor_execute',mysql_sort_limit)
    try:
        if action=='history':
            rows=service.list_plans(s,c.id)
            assert [p.id for p in rows]==list(reversed(expected))[:20]
            assert rows[0].input_snapshot['candidates'][0]['plot'].startswith('large frozen story')
        else:
            claim=service.claim_plan(s,'host')
            assert claim['id']==expected[0] and claim['status']=='running'
            assert claim['input_snapshot']['candidates'][0]['plot'].startswith('large frozen story')
    finally:event.remove(engine,'before_cursor_execute',mysql_sort_limit)


def test_preview_is_read_only_and_apply_is_atomic_idempotent_with_frozen_guidance(data):
    from zhiju.services import schedule_planning as service
    from zhiju.models import ChannelScheduleEntry, ChannelDnaVersion
    configured(data)
    s,c,d,slot,_ = data
    run=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    assert run.status=='queued'
    assert run.input_snapshot['guidance']['mode']=='initial'
    assert list(s.scalars(select(ChannelScheduleEntry)))==[]
    claim=service.claim_plan(s,'host')
    result={'rows':[{'publish_date':'2026-11-03','publish_slot_id':slot.id,'drama_id':d.id,
                     'reason':'女主主动夺回公司符合定位','plot_evidence':'女主遭到背叛后夺回公司。',
                     'pairing_reason':'首日以女主反击建立频道方向'}]}
    service.submit_result(s,run.id,claim['claim_id'],result=result)
    assert run.status=='ready'
    assert list(s.scalars(select(ChannelScheduleEntry)))==[]
    assert run.result['rows'][0]['planned_beijing_time']=='2026-11-03T09:00:00'
    service.apply_plan(s,run.id)
    rows=list(s.scalars(select(ChannelScheduleEntry)))
    assert len(rows)==1
    frozen=rows[0].channel_dna_version_id
    assert s.get(ChannelDnaVersion,frozen).reference_summary=='## [GLOBAL]\n冷启动，女主逆袭'
    service.apply_plan(s,run.id)
    assert len(list(s.scalars(select(ChannelScheduleEntry))))==1


def ready(data):
    from zhiju.services import schedule_planning as service
    configured(data)
    s,c,d,slot,_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    claim=service.claim_plan(s,'host')
    result={'rows':[{'publish_date':'2026-11-03','publish_slot_id':slot.id,'drama_id':d.id,
        'reason':'主线符合频道定位','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'首日单更建立频道方向'}]}
    service.submit_result(s,plan.id,claim['claim_id'],result=result)
    return plan


@pytest.mark.parametrize('change',['language','duration','expiry','slot','plot'])
def test_apply_rechecks_changed_inputs_and_writes_nothing(data,change):
    from zhiju.services import schedule_planning as service
    from zhiju.models import ChannelScheduleEntry
    from zhiju.services.identity import ConflictError
    s,c,d,slot,state=data
    plan=ready(data)
    if change=='language':state.finished_languages=[]
    if change=='duration':state.total_duration_seconds=1200
    if change=='expiry':d.expires_at=datetime(2026,11,1,tzinfo=timezone.utc)
    if change=='slot':slot.local_video_time=time(21)
    if change=='plot':d.content_summary='另一段完全不同的剧情'
    s.commit()
    with pytest.raises(ConflictError):service.apply_plan(s,plan.id)
    assert list(s.scalars(select(ChannelScheduleEntry)))==[]
    assert plan.status=='ready'


def test_all_existing_dates_and_slots_are_protected(data):
    from zhiju.services import schedule_planning as service
    from zhiju.models import ChannelScheduleEntry
    from zhiju.schemas.operations import ScheduleCreate
    from zhiju.services.identity import ConflictError
    s,c,d,slot,state=data
    plan=ready(data)
    stored=ChannelPublishSlot(channel_id=c.id,slot_type='main',slot_number=1,local_time=time(20),
                              timezone=c.timezone,status='active')
    s.add(stored);s.commit()
    operations.create_schedule(s,c.id,ScheduleCreate(drama_id=d.id,publish_slot_id=stored.id,
        publish_date=date(2026,11,3),idempotency_key='manual-existing'))
    with pytest.raises(ConflictError):service.apply_plan(s,plan.id)
    rows=list(s.scalars(select(ChannelScheduleEntry)))
    assert len(rows)==1 and rows[0].idempotency_key=='manual-existing'


def test_unknown_language_inventory_is_not_inferred_from_global_completion(data):
    from zhiju.services import schedule_planning as service
    s,c,d,slot,state=data
    state.finished_languages=None;s.commit()
    pool,excluded=service.candidate_pool(s,c)
    assert pool==[] and excluded['language_unknown']==1


def test_planner_rejects_duplicates_invented_evidence_and_expired_release(data):
    from copy import deepcopy
    from zhiju.services import schedule_planning as service
    from zhiju.services.identity import ConflictError
    plan=ready(data)
    result=deepcopy(plan.result)
    result['rows'][0]['plot_evidence']='原文没有发生过的事情'
    with pytest.raises(ConflictError,match='剧情'):service.validate_result(plan,result)
    result=deepcopy(plan.result);result['rows'].append(result['rows'][0])
    with pytest.raises(ConflictError,match='重复'):service.validate_result(plan,result)
    snapshot=deepcopy(plan.input_snapshot);snapshot['candidates'][0]['expires_at']='2026-11-03T00:00:00'
    from types import SimpleNamespace
    with pytest.raises(ConflictError,match='到期'):service.validate_result(SimpleNamespace(input_snapshot=snapshot),plan.result)


def test_missing_main_duration_becomes_a_visible_gap_without_fake_schedule(data):
    from zhiju.services import schedule_planning as service
    from zhiju.models import ChannelScheduleEntry
    from zhiju.services.identity import ConflictError
    configured(data);s,c,d,slot,state=data
    state.total_duration_seconds=None;s.commit()
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    claim=service.claim_plan(s,'host')
    service.submit_result(s,plan.id,claim['claim_id'],result={'rows':[{'publish_date':'2026-11-03',
        'publish_slot_id':slot.id,'drama_id':None,'reason':'主档候选时长未验证'}]})
    assert plan.result['rows'][0]['status']=='blocked'
    with pytest.raises(ConflictError,match='没有可保存'):service.apply_plan(s,plan.id)
    assert list(s.scalars(select(ChannelScheduleEntry)))==[]


def test_guidance_follows_applied_version_and_keeps_history(data):
    from zhiju.models import ChannelDnaVersion, ChannelAnalysisReport
    from zhiju.services import channel_guidance
    s,c,*_=data
    report=ChannelAnalysisReport(channel_id=c.id,version_number=1,report_type='periodic',
        status='completed',summary='实测画像',recommendations='实测诊断')
    s.add(report);s.flush()
    old=ChannelDnaVersion(channel_id=c.id,version_number=1,status='archived',language='en',
        primary_genre='逆袭',audience_summary='冷启动画像',reference_summary='冷启动生成规范')
    current=ChannelDnaVersion(channel_id=c.id,version_number=2,status='active',language='en',
        analysis_report_id=report.id,primary_genre='逆袭',reference_summary='实测生成规范')
    s.add_all([old,current]);s.commit()
    assert channel_guidance.resolve(s,c.id)['mode']=='periodic'
    assert channel_guidance.resolve(s,c.id)['diagnosis']=='实测诊断'
    assert channel_guidance.resolve(s,c.id,old.id)['operating_reference']=='冷启动生成规范'


def test_cancel_resume_retains_snapshot_and_rejects_stale_claim(data):
    from zhiju.services import schedule_planning as service
    from zhiju.services.identity import ConflictError
    configured(data);s,c,*_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    claim=service.claim_plan(s,'host');snapshot=plan.input_snapshot
    service.cancel_plan(s,plan.id)
    with pytest.raises(ConflictError):service.submit_result(s,plan.id,claim['claim_id'],error='late result')
    service.resume_plan(s,plan.id,True)
    assert plan.input_snapshot==snapshot and plan.status=='queued'
    new=service.claim_plan(s,'host')
    assert new['claim_id']!=claim['claim_id']


def test_tenant_cannot_read_or_claim_another_tenants_plan(data):
    from fastapi import HTTPException
    from zhiju.services import schedule_planning as service
    configured(data);s,c,*_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    with TenantSession(s.bind,info={'tenant_id':'other'}) as other:
        with pytest.raises(HTTPException):service.get_plan(other,plan.id)
        assert list(other.scalars(select(type(plan))))==[]


def test_forbidden_title_or_alias_cannot_reenter_from_stale_cache(data):
    from zhiju.models import DramaAlias
    from zhiju.services import schedule_planning as service
    s,c,d,*_=data
    s.add(DramaAlias(drama_id=d.id,alias='Tempting My Keeper',normalized_alias='tempting my keeper',source='manual'));s.commit()
    assert operations.list_schedulable_dramas(s)==[]
    assert service.candidate_pool(s,c)[0]==[]


def test_full_executor_flow_caches_assessments_and_delivers_preview(data,tmp_path):
    from zhiju.services import schedule_planning as service
    from zhiju.v14_executor.schedule_planning import drain
    configured(data);s,c,d,slot,_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    class Client:
        host_id='host';tenant_id='planning-test'
        def request(self,method,path,body=None):
            if path=='/schedule-planning/claims':return service.claim_plan(s,'host')
            if path.endswith('/heartbeat'):return {}
            if method=='PUT':return service.read(service.submit_result(s,plan.id,**body))
            raise AssertionError(path)
    class Model:
        account_profile='current';calls=0
        def generate(self,stage,model):
            self.calls+=1
            if self.calls==1:
                assert '女主遭到背叛后夺回公司。' in stage.prompt
                return {'rows':[{'drama_id':d.id,'eligible':True,'main_theme':True,'reason':'女主反击符合定位',
                                  'plot_evidence':'女主遭到背叛后夺回公司。'}]}
            return {'rows':[{'publish_date':'2026-11-03','publish_slot_id':slot.id,'drama_id':d.id,
                'reason':'主线符合定位','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'首日单更'}]}
    model=Model();drain(Client(),model,{},tmp_path,once=True)
    assert plan.status=='ready' and model.calls==2
    assert (tmp_path/plan.id/'submitted.json').exists()
    drain(Client(),model,{},tmp_path,once=True)
    assert model.calls==2


def test_resume_reuses_successful_story_assessment_but_replans_failed_output(data,tmp_path):
    from zhiju.services import schedule_planning as service
    from zhiju.v14_executor.schedule_planning import drain
    configured(data);s,c,d,slot,_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    class Client:
        host_id='host';tenant_id='planning-test'
        def request(self,method,path,body=None):
            if path=='/schedule-planning/claims':return service.claim_plan(s,'host')
            if path.endswith('/heartbeat'):return {}
            if method=='PUT':return service.read(service.submit_result(s,plan.id,**body))
            raise AssertionError(path)
    class Model:
        account_profile='current';calls=0;fixed=False
        def generate(self,stage,model):
            self.calls+=1
            if self.calls==1:return {'rows':[{'drama_id':d.id,'eligible':True,'main_theme':True,
                'reason':'女主逆袭','plot_evidence':'女主遭到背叛后夺回公司。'}]}
            if not self.fixed:return {'rows':[]}
            return {'rows':[{'publish_date':'2026-11-03','publish_slot_id':slot.id,'drama_id':d.id,
                'reason':'符合定位','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'首日单更'}]}
    model=Model();drain(Client(),model,{},tmp_path,once=True)
    assert plan.status=='failed' and model.calls==4
    service.resume_plan(s,plan.id,True);model.fixed=True
    drain(Client(),model,{},tmp_path,once=True)
    assert plan.status=='ready' and model.calls==5


def test_full_raw_analysis_snapshot_does_not_enter_planning_prompts(data,tmp_path):
    from copy import deepcopy
    from zhiju.services import schedule_planning as service
    from zhiju.v14_executor.schedule_planning import generate
    from zhiju.services.identity import ConflictError
    configured(data);s,c,d,slot,_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    snapshot=deepcopy(plan.input_snapshot)
    snapshot['guidance']['normalized_snapshot']={'studio_content':['raw_data_marker'*100_000]}
    plan.input_snapshot=snapshot;s.commit()
    claim=service.claim_plan(s,'host')
    class Model:
        calls=0
        def generate(self,stage,model):
            assert 'raw_data_marker' not in stage.prompt
            self.calls+=1
            if self.calls==1:return {'rows':[{'drama_id':d.id,'eligible':True,'main_theme':True,'reason':'逆袭',
                'plot_evidence':'女主遭到背叛后夺回公司。'}]}
            return {'rows':[{'publish_date':'2026-11-03','publish_slot_id':slot.id,'drama_id':d.id,
                'reason':'符合定位','plot_evidence':'女主遭到背叛后夺回公司。','pairing_reason':'首日单更'}]}
    updates=[]
    assert generate(Model(),claim,tmp_path,lambda *p:updates.append(p))['rows'][0]['drama_id']==d.id
    assert [(p[0],p[1],p[2]) for p in updates]==[
        ('assessing',0,1),('assessing',1,1),('planning',1,1),('validating',1,1)]


def test_scheduling_skill_selection_is_used_and_frozen(data):
    from io import BytesIO
    from zipfile import ZipFile
    from zhiju.services import skill_catalog, schedule_planning as service
    configured(data);s,c,*_=data
    content=BytesIO()
    with ZipFile(content,'w') as archive:archive.writestr('SKILL.md','# 排期修订\n优先展示女主主动行动，逐日解释配对。')
    version=skill_catalog.upload(s,skill_catalog.SCHEDULING,'修订规则','按业务需求修订',content.getvalue())
    skill_catalog.publish(s,skill_catalog.SCHEDULING,version['id'])
    skill_catalog.select_default(s,skill_catalog.SCHEDULING,version['id'])
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    skill_catalog.select_default(s,skill_catalog.SCHEDULING,skill_catalog.SCHEDULING_VERSION)
    assert plan.input_snapshot['skill_version']['id']==version['id']
    assert '女主主动行动' in plan.input_snapshot['skill_version']['files']['SKILL.md']


def test_schedule_plan_migration_can_upgrade_and_downgrade_in_isolation():
    import importlib.util
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    root=Path(__file__).resolve().parents[2]
    config=Config(str(root/'alembic.ini'));config.set_main_option('script_location',str(root/'backend/alembic'))
    assert ScriptDirectory.from_config(config).get_heads()==['f23a20261105']
    spec=importlib.util.spec_from_file_location('schedule_plan_migration',root/'backend/alembic/versions/f21e20261102_channel_schedule_plans.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        Base.metadata.tables['channels'].create(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {'dna_id','input_snapshot','result','claim_id'} <= {r['name'] for r in inspect(connection).get_columns('channel_schedule_plans')}
            migration.downgrade()
            assert 'channel_schedule_plans' not in inspect(connection).get_table_names()
    engine.dispose()


def test_one_release_uses_main_slot_without_changing_channel_cadence(data):
    from zhiju.services import schedule_planning as service
    configured(data);s,c,d,main,_=data
    c.daily_publish_count=2
    auxiliary=ChannelPublishSlot(channel_id=c.id,slot_type='aux',slot_number=1,
        local_time=time(8),timezone='America/New_York',status='active')
    s.add(auxiliary);s.commit()
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    assert plan.input_snapshot['targets']==[{'publish_date':'2026-11-03','publish_slot_id':main.id}]
    assert c.daily_publish_count==2 and auxiliary.status=='active'


def test_local_planning_runs_without_database_configuration(data,tmp_path):
    import json,os,subprocess,sys
    from pathlib import Path
    from zhiju.services import schedule_planning as service
    configured(data);s,c,d,slot,_=data
    plan=service.create_plan(s,c.id,date(2026,11,3),date(2026,11,3),1)
    run=service.claim_plan(s,'host')
    payload=tmp_path/'run.json';payload.write_text(json.dumps(run,default=str))
    root=Path(__file__).resolve().parents[2]
    env={k:v for k,v in os.environ.items() if not k.startswith('ZHJ_')}
    env['PYTHONPATH']=str(root/'backend')
    result=subprocess.run([sys.executable,'-c',r'''
import json,sys
from pathlib import Path
from zhiju.v14_executor.schedule_planning import generate
run=json.loads(Path(sys.argv[1]).read_text())
drama=run['input_snapshot']['candidates'][0];slot=run['input_snapshot']['targets'][0]
class Model:
    calls=0
    def generate(self,stage,model):
        self.calls+=1
        if self.calls==1:
            return {'rows':[{'drama_id':drama['id'],'eligible':True,'main_theme':True,'reason':'符合定位',
                             'plot_evidence':drama['content_summary']}]}
        return {'rows':[{**slot,'drama_id':drama['id'],'reason':'符合定位',
                        'plot_evidence':drama['content_summary'],'pairing_reason':'首日建立方向'}]}
result=generate(Model(),run,Path(sys.argv[1]).parent)
assert result['rows'][0]['drama_id']==drama['id']
assert 'zhiju.database' not in sys.modules
''',str(payload)],env=env,cwd=tmp_path,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('theme', ['primary', 'secondary'])
@pytest.mark.parametrize('uses_v2', [False, True])
def test_executor_uses_plot_assessment_for_explicit_slot_topic(data, tmp_path, theme, uses_v2):
    from zhiju.services import schedule_planning
    from zhiju.v14_executor.schedule_planning import generate

    configured(data)
    session, channel, drama, slot, _ = data
    day = date(2026, 11, 3)
    schedule_planning.create_plan(session, channel.id, day, day, 1, {slot.id: 'secondary'})
    claim = schedule_planning.claim_plan(session, 'host')
    directions = {'primary': ['公开反击'], 'secondary': ['事业重建']}
    if uses_v2:
        claim['input_snapshot']['analysis_topics'] = directions

    class Model:
        calls = 0

        def generate(self, stage, model):
            self.calls += 1
            if self.calls == 1:
                assert '以用户逐档指定题材为准' in stage.prompt
                judgment = {'drama_id': drama.id, 'eligible': True, 'theme': theme,
                    'reason': '根据频道资料归类', 'plot_evidence': '女主遭到背叛后夺回公司。'}
                if uses_v2:
                    assert all(label in stage.prompt for values in directions.values() for label in values)
                    assert 'theme_basis' in stage.schema['properties']['rows']['items']['required']
                    judgment['theme_basis'] = directions[theme][0]
                return {'rows': [judgment]}
            row = {'publish_date': day.isoformat(), 'publish_slot_id': slot.id,
                   'reason': '缺少辅题材', 'plot_evidence': '女主遭到背叛后夺回公司。', 'pairing_reason': '单更'}
            if self.calls == 2:
                assert slot.id in stage.prompt and '指定题材' in stage.prompt
                assert '前14天' not in stage.prompt.split('依据以下已阅读剧情的判断', 1)[1]
                return {'rows': [{**row, 'drama_id': drama.id}]}
            return {'rows': [{**row, 'drama_id': None}]}

    model = Model()
    result = generate(model, claim, tmp_path)
    row = result['rows'][0]
    if theme == 'secondary':
        assert model.calls == 2
        assert row['drama_id'] == drama.id
        assert row['drama_theme'] == 'secondary'
        if uses_v2:
            assert row['theme_basis'] == '事业重建'
    else:
        assert model.calls == 3
        assert row['drama_id'] is None
        assert row['reason'] == '缺少辅题材'
