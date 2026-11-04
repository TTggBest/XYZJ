import json
import pytest
from zhiju.v14_executor.channel_analysis import recover_cached
from test_channel_analysis_runs import session


def test_upload_outage_keeps_only_unacknowledged_task_and_retry_cleans_it(tmp_path):
    root=tmp_path/'run';root.mkdir()
    pending=root/'pending.json'
    entry={'run_id':'run','body':{'claim_id':'claim','result':{'profile':'generated document'}}}
    pending.write_text(json.dumps(entry))
    (root/'material.png').write_bytes(b'temporary material')
    class Cloud:
        offline=True
        def request(self,method,path,body):
            assert method=='PUT' and path=='/analysis-runs/run/result'
            assert body==entry['body']
            assert (root/'material.png').exists()
            if self.offline:raise ConnectionError('network unavailable')
            return {'id':'run','status':'ready'}
    client=Cloud()
    with pytest.raises(ConnectionError):recover_cached(client,{},tmp_path)
    assert json.loads(pending.read_text())==entry
    client.offline=False
    recover_cached(client,{},tmp_path)
    assert not root.exists()


def test_old_acknowledged_cache_is_cleaned_without_local_archive_or_model(tmp_path):
    root=tmp_path/'accepted';root.mkdir()
    (root/'submitted.json').write_text('{"run_id":"accepted"}')
    (root/'analysis-profile.json').write_text('{"result":"old document"}')
    class Cloud:
        def request(self,method,path):
            assert method=='GET' and path=='/analysis-runs/accepted'
            return {'id':'accepted','status':'ready'}
    recover_cached(Cloud(),{},tmp_path)
    assert not root.exists()


@pytest.mark.parametrize('filename',['analysis-profile.json','screenshot-shot.json'])
def test_connection_lost_after_generation_saves_pending_checkpoint(tmp_path,monkeypatch,filename):
    from types import SimpleNamespace
    from zhiju.v14_executor import channel_analysis as executor
    run={'id':'run','claim_id':'claim','mode':'initial','materials':[],
         'input_snapshot':{'account_profile':'current','model':'test','sources':{}}}
    class Cloud:
        def request(self,method,path,body=None,**kw):
            if path.endswith('/collect'):return run
            if path.endswith('/heartbeat'):return {}
            pytest.fail('must not upload while connection is unavailable')
    def generate(model,run,root,progress):
        (root/filename).write_text('{"result":{"profile":"completed output"}}')
        raise ConnectionError('disconnected before diagnosis')
    monkeypatch.setattr(executor,'generate_documents',generate)
    with pytest.raises(ConnectionError):
        executor.process_claimed(Cloud(),SimpleNamespace(account_profile='current'),{},tmp_path,run)
    pending=json.loads((tmp_path/'run/pending.json').read_text())
    assert pending['body']['result']['executor_checkpoints'][filename]['result']['profile']=='completed output'


def test_legacy_error_receipt_backfills_checkpoint_before_cleanup(session,tmp_path):
    from zhiju.services import channel_analysis as service
    s,c=session
    run=service.create_run(s,c.id,mode='initial',positioning='test')
    service.start_run(s,run.id);claim=service.claim_run(s,'host')
    service.submit_result(s,run.id,claim['claim_id'],error='old executor timed out')
    root=tmp_path/run.id;root.mkdir()
    (root/'submitted.json').write_text(json.dumps({'run_id':run.id,'body':{'claim_id':claim['claim_id'],'error':run.error}}))
    (root/'analysis-profile.json').write_text('{"result":{"profile":"old completed profile"}}')
    class Cloud:
        offline=True
        def request(self,method,path,body=None):
            if method=='GET':return service.run_read(run)
            assert root.exists()
            if self.offline:raise ConnectionError('upload interrupted')
            return service.run_read(service.submit_result(s,run.id,body['claim_id'],error=body['error'],result=body['result']))
    client=Cloud()
    with pytest.raises(ConnectionError):recover_cached(client,{},tmp_path)
    assert root.exists()
    client.offline=False;recover_cached(client,{},tmp_path)
    assert not root.exists()
    assert run.attempts[-1]['raw_result']['executor_checkpoints']['analysis-profile.json']['result']['profile']=='old completed profile'
    assert len(run.attempts)==1


def test_confirmed_cancelled_old_temporary_data_is_cleaned(tmp_path):
    root=tmp_path/'cancelled';root.mkdir()
    (root/'abandoned.json').write_text('{"run_id":"cancelled","body":{"claim_id":"old-claim"}}')
    (root/'material.png').write_bytes(b'temporary')
    class Cloud:
        def request(self,method,path):
            assert method=='GET'
            return {'status':'cancelled','claim_id':None}
    recover_cached(Cloud(),{},tmp_path)
    assert not root.exists()


def test_another_computer_restores_unacknowledged_screenshot_from_cloud(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from zhiju.v14_executor import channel_analysis as executor
    checkpoint={'input_prompt':'frozen screenshot prompt','source_files':{},'result':{'checks':{'shot':{'evidence':'observed'}}}}
    run={'id':'run','claim_id':'new-claim','mode':'initial','materials':[{'id':'shot','suffix':'.png'}],
         'input_snapshot':{'account_profile':'current','model':'test','sources':{}},
         'attempts':[{'raw_result':{'executor_checkpoints':{'screenshot-shot.json':checkpoint}}}]}
    class Cloud:
        def request(self,method,path,body=None,**kw):
            if path.endswith('/collect'):return run
            if path.endswith('/heartbeat'):return {}
            if path.endswith('/result'):return {'status':'failed'}
            pytest.fail(path)
        def download_analysis_material(self,*args):return b'cloud screenshot'
    def generate(model,run,root,progress):
        result=executor.cached_generation(model,run,root,'screenshot-shot',SimpleNamespace(prompt=checkpoint['input_prompt']))
        assert result==checkpoint['result']
        raise RuntimeError('fixture stops after checking restored output')
    monkeypatch.setattr(executor,'generate_documents',generate)
    model=SimpleNamespace(account_profile='current',generate=lambda *a:pytest.fail('must reuse cloud checkpoint'))
    executor.process_claimed(Cloud(),model,{},tmp_path,run)
    assert not (tmp_path/'run').exists()
