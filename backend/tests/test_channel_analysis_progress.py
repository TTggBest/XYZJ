"""Resume boundaries for large channel analyses; no live services or model calls."""
import json
from types import SimpleNamespace
import pytest
from zhiju.v14_executor import channel_analysis as executor
from test_channel_analysis_runs import session


def test_screenshots_checkpoint_each_image_and_resume(tmp_path, monkeypatch):
    run={'id':'run','claim_id':'claim','mode':'periodic','materials':[{'id':str(i),'kind':'videos','suffix':'.png','name':f'{i}.png'} for i in range(3)],
         'input_snapshot':{'model':'test','sources':{'screenshot_checks':{}},'channel':{}}}
    monkeypatch.setattr(executor,'screenshot_stage',lambda run,root: SimpleNamespace(prompt=json.dumps(run['materials']),images=[m['id'] for m in run['materials']]))
    calls=[]; saved={}
    class Model:
        def generate(self,stage,model):
            calls.append(stage.images)
            if stage.images==['1'] and len(calls)==2:raise RuntimeError('timeout')
            return {'checks':{key:{'evidence':'observed'} for key in stage.images}}
    class Cloud:
        def request(self,method,path,body):
            saved.update(body['result']);run['input_snapshot']['sources']['screenshot_checks']=dict(saved);return run
    with pytest.raises(RuntimeError,match='timeout'):
        executor.generate_screenshots(Cloud(),Model(),run,tmp_path)
    assert list(saved)==['0']
    executor.generate_screenshots(Cloud(),Model(),run,tmp_path)
    assert calls==[['0'],['1'],['1'],['2']]
    assert list(saved)==['0','1','2']


def test_document_resume_keeps_completed_profile_and_diagnosis(tmp_path,monkeypatch):
    calls=[];run={'input_snapshot':{'model':'test'}}
    monkeypatch.setattr(executor,'stage_for',lambda *a:SimpleNamespace(prompt='frozen',schema={'properties':{'profile':{},'diagnosis':{},'normalized_snapshot':{},'material_checks':{}}},images=[]))
    monkeypatch.setattr(executor,'generation_spec_stage',lambda run,result:SimpleNamespace(prompt='spec',schema={'properties':{'generation_spec':{}}},images=[]))
    class Model:
        def generate(self,stage,model):
            key=next(iter(stage.schema['properties']));calls.append(key)
            if key=='generation_spec' and calls.count(key)==1:raise RuntimeError('timeout')
            return {key:'complete'}
    with pytest.raises(RuntimeError):executor.generate_documents(Model(),run,tmp_path)
    result=executor.generate_documents(Model(),run,tmp_path)
    assert calls==['profile','diagnosis','generation_spec','generation_spec']
    assert result['profile']==result['diagnosis']==result['generation_spec']=='complete'


def test_large_context_keeps_all_rows_in_searchable_source():
    snapshot={'sources':{'fact_snapshot':{'studio_content':[{'video_id':str(i),'values':{'Views':i,'text':'真实资料'*60}} for i in range(1000)],'channel_totals_28d':{'views':499500}}}}
    preview,files=executor.bounded_context(snapshot)
    assert len(json.dumps(preview))<100000
    assert len(preview['sources']['fact_snapshot']['studio_content'])==30
    full=json.loads(files['analysis-source.json'])
    assert len(full['sources']['fact_snapshot']['studio_content'])==1000
    assert full['sources']['fact_snapshot']['studio_content'][500]['video_id']=='500'
    assert preview['sources']['fact_snapshot']['channel_totals_28d']=={'views':499500}
    assert preview['large_source_context']['excerpts'][0]['total']==1000


def test_progress_uses_elapsed_monotonic_time(monkeypatch):
    now=[100.0];monkeypatch.setattr(executor,'monotonic',lambda:now[0]);sent=[]
    cloud=SimpleNamespace(request=lambda *args:sent.append(args[-1]))
    progress=executor.AnalysisProgress(cloud,{'id':'run','claim_id':'claim'})
    now[0]=110;progress.set('screenshots',3,11,'Audience.png')
    now[0]=130;progress.send()
    assert sent[-1]['progress']=={'stage':'screenshots','completed_items':3,'total_items':11,'current_item':'Audience.png','elapsed_seconds':30,'stage_elapsed_seconds':20}


def test_partial_checks_merge_but_do_not_pass_full_validation(tmp_path):
    from sqlalchemy import create_engine
    from zhiju.database import TenantSession
    from zhiju.models import Base,Channel,ChannelAnalysisRun
    from zhiju.services import channel_analysis as service
    from zhiju.services.channel_analysis_normalize import normalize_sources,formal_snapshot
    from zhiju.services.identity import ConflictError
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with TenantSession(engine,info={'tenant_id':'tenant'}) as s:
        c=Channel(original_name='Test',youtube_channel_id='UCtest');s.add(c);s.flush()
        materials=[{'id':str(i),'kind':'videos','name':f'{i}.png'} for i in range(2)]
        sources={'api':{},'windows':{'28':{},'90':{}},'screenshots':materials}
        sources['normalized']=normalize_sources(sources,{},'periodic');sources['fact_snapshot']=formal_snapshot(sources,{})
        run=ChannelAnalysisRun(channel_id=c.id,host_id='host',mode='periodic',status='running',claim_id='claim',materials=materials,input_snapshot={'sources':sources,'channel':{}});s.add(run);s.commit()
        check={'identity_matches':True,'page_matches':True,'window_matches':True,'evidence':'visible screenshot','observations':[]}
        service.record_screenshot_checks(s,run.id,'claim',{'0':check})
        assert list(run.input_snapshot['sources']['screenshot_checks'])==['0']
        with pytest.raises(ConflictError,match='未核实'):
            service.validate_screenshot_checks(run,run.input_snapshot['sources']['screenshot_checks'])
        with pytest.raises(ConflictError,match='不属于'):
            service.record_screenshot_checks(s,run.id,'claim',{'foreign':check})
        service.record_screenshot_checks(s,run.id,'claim',{'1':check})
        service.validate_screenshot_checks(run,run.input_snapshot['sources']['screenshot_checks'])
        assert set(run.input_snapshot['sources']['screenshot_checks'])=={'0','1'}


def test_progress_migration_preserves_existing_runs():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from zhiju.models import Base
    path=Path(__file__).resolve().parents[1]/'alembic/versions/f22a20261104_analysis_progress.py'
    spec=importlib.util.spec_from_file_location('progress_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with engine.begin() as connection,Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        connection.execute(text("INSERT INTO channel_analysis_runs (id,tenant_id,channel_id,host_id,mode,status,phase,input_snapshot,materials,attempts,mirror_status) VALUES ('old','tenant','channel','host','periodic','failed','analysis','{}','[]','[]','pending')"))
        migration.upgrade()
        assert connection.execute(text("SELECT status,progress FROM channel_analysis_runs WHERE id='old'")).one()==('failed',None)
        migration.downgrade()
        assert 'progress' not in {col['name'] for col in inspect(connection).get_columns('channel_analysis_runs')}
        assert connection.execute(text("SELECT count(*) FROM channel_analysis_runs WHERE id='old'")).scalar()==1


def test_source_file_reaches_real_codex_subprocess_directory(tmp_path):
    import sys
    from zhiju.v14_executor.codex import CodexClient
    cli=tmp_path/'fake-codex'
    cli.write_text(f'#!{sys.executable}\n'+'''import sys,json,pathlib
args=sys.argv
root=pathlib.Path(args[args.index('--cd')+1])
data=json.loads((root/'analysis-source.json').read_text())
pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(data))
''')
    cli.chmod(0o700)
    stage=SimpleNamespace(prompt='read source',schema={},rules={},images=[],skill_bundle=None,node_type='channel_analysis',source_files={'analysis-source.json':'{"all_rows":1000}'})
    assert CodexClient(binary=str(cli)).generate(stage,'test')=={'all_rows':1000}


@pytest.mark.parametrize('failure',['spec','yaml'])
def test_rejected_output_regenerates_failed_document_and_dependents(tmp_path,monkeypatch,failure):
    from test_channel_analysis_runs import session as fixture,valid_result
    from zhiju.services import channel_analysis as service
    from zhiju.services.channel_analysis_sources import collect
    from zhiju.services.identity import ConflictError
    from zhiju.v14_executor.client import CloudConflict
    session_generator=fixture.__wrapped__();s,c=next(session_generator)
    try:
        run=service.create_run(s,c.id,mode='initial',positioning='冷启动');service.start_run(s,run.id)
        calls=[]
        class Model:
            account_profile='current'
            bad=True
            def generate(self,stage,model):
                keys=stage.schema['required'];calls.append(keys)
                result=valid_result(run);result['normalized_snapshot']=json.dumps(result['normalized_snapshot']);result['material_checks']={}
                if keys==['generation_spec'] and self.bad and failure=='spec':result['generation_spec']='不完整规范'
                if keys==['diagnosis'] and self.bad and failure=='yaml':
                    result['diagnosis']=result['diagnosis'].replace('channel_strategy:', 'channel_strategy: [unterminated')
                return {key:result[key] for key in keys}
        class Cloud:
            tenant_id='tenant-analysis';host_id='host'
            def request(self,method,path,body=None,**kwargs):
                if path=='/auth/me':return {'tenant_id':self.tenant_id}
                if path=='/channel-analysis/claims':return service.claim_run(s,'host')
                if path.endswith('/collect'):return service.run_read(collect(s,run.id,body['claim_id']))
                if path.endswith('/heartbeat'):return {}
                if path.endswith('/result'):
                    try:return service.run_read(service.submit_result(s,run.id,body['claim_id'],result=body.get('result'),error=body.get('error')))
                    except ConflictError as exc:raise CloudConflict(str(exc)) from exc
                if path.endswith('/mirror-complete'):return {}
                return service.run_read(run)
        model=Model();config={'analysis_workspace_root':str(tmp_path)}
        executor.drain(Cloud(),model,config,tmp_path/'cache',once=True)
        assert run.status=='failed' and ('生成规范' if failure=='spec' else '诊断 YAML') in run.error
        assert len(calls)==3
        assert not list((tmp_path/'cache').iterdir())
        assert run.attempts[-1]['raw_result']['executor_checkpoints']
        service.resume_run(s,run.id,stopped_confirmed=True);model.bad=False
        executor.drain(Cloud(),model,{},tmp_path/'second-computer-cache',once=True)
        assert not list((tmp_path/'second-computer-cache').iterdir())
        assert run.status=='ready',run.error
        assert len(calls)==(4 if failure=='spec' else 5) and calls[-1]==['generation_spec']
    finally:
        session_generator.close()


def test_progress_listing_sorts_ids_without_sorting_json_payload(session):
    from sqlalchemy import event
    from zhiju.services import channel_analysis as service
    s,c=session
    run=service.create_run(s,c.id,mode='initial',positioning='冷启动')
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    event.listen(s.bind,'before_cursor_execute',capture)
    try:
        rows=service.list_run_summaries(s,c.id)
    finally:event.remove(s.bind,'before_cursor_execute',capture)
    assert rows[0]['id']==run.id
    assert any('ORDER BY' in sql and 'channel_analysis_runs.id' in sql for sql in statements)
    assert all('ORDER BY' not in sql for sql in statements if 'JSON_EXTRACT' in sql)
