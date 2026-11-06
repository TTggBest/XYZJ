"""Exercise two-phase failures without generating business content."""
from copy import deepcopy
from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from test_v18_title_two_phase import RecordingClient, creation, metadata, stage
from test_v14_runs import store


@pytest.mark.parametrize('failed_phase', ['title_creation', 'title_metadata'])
def test_failed_call_keeps_its_exact_request(failed_phase):
    class FailingClient(RecordingClient):
        def _generate_once(self, current, model):
            if (len(self.calls) == 0) == (failed_phase == 'title_creation'):
                raise RuntimeError('CLI unavailable')
            return super()._generate_once(current, model)

    client = FailingClient([creation()])
    with pytest.raises(RuntimeError, match='CLI unavailable'):
        client.generate(stage(), 'same-model')
    assert client.phase_trace[-1]['phase'] == failed_phase
    assert client.phase_trace[-1]['raw'] is None
    assert client.phase_trace[-1]['prompt']
    assert client.phase_trace[-1]['schema'] == {'type': 'object'}


def test_public_correction_is_returned_to_creator_with_original_baseline():
    from zhiju.v14_executor import codex
    filled = metadata()
    for row in filled['results'][0]['directions']:
        row.update(title='Public ' + row['selected_candidate_id'], selection_reason='no correction')
    filled['results'][0]['directions'][0].update(
        title='Supported correction C3', selection_reason='Original title reverses the relationship')
    client = RecordingClient([creation(), filled])
    with pytest.raises(codex.TitleContentError) as caught:
        client.generate(stage(), 'same-model')
    assert 'Supported correction C3' in str(caught.value)
    assert 'reverses the relationship' in str(caught.value)
    baseline = caught.value.result['results'][0]['directions']
    assert {row['title'] for row in baseline} == {'Public C1', 'Public C2', 'Public C3'}
    assert all(row['selected_variant_id'] == 'independent' for row in baseline)
    assert client.phase_trace[-1]['raw'] == filled


def test_metadata_candidate_error_is_content_error_and_keeps_creation():
    from zhiju.v14_executor import codex
    filled = metadata()
    filled['results'][0]['directions'][0]['selected_candidate_id'] = 'C9'
    with pytest.raises(codex.TitleContentError) as caught:
        RecordingClient([creation(), filled]).generate(stage(), 'same-model')
    assert str(caught.value).startswith('v18_title_metadata_candidate_changed')
    assert caught.value.result['results'][0]['directions'] == [
        {**row, 'selected_variant_id': 'independent'} for row in creation()['directions']]


def test_duplicate_creator_candidates_are_content_errors():
    from zhiju.v14_executor import codex
    duplicate = creation()
    duplicate['directions'][2]['selected_candidate_id'] = 'C1'
    with pytest.raises(codex.TitleContentError) as caught:
        RecordingClient([duplicate]).generate(stage(), 'same-model')
    assert str(caught.value).startswith('v18_title_creation_candidates_not_distinct')
    assert len(caught.value.result['results'][0]['directions']) == 3


def test_worker_reports_content_failure_instead_of_interrupting_as_system_error(tmp_path, monkeypatch):
    from zhiju.v14_executor import codex, runner
    baseline = {'results': [{'directions': creation()['directions']}]}
    data = {'run_id': 'r', 'work_order_id': 'w', 'claim_id': 'c', 'account_profile': 'current',
            'model': 'fixed', 'node_sequence': ['title'], 'accepted_results': {}, 'retry_state': []}
    class Cloud:
        def claim(self): return data
        def begin(self, envelope, node): return 'a'
        def submit(self, envelope, attempt, body):
            assert body['outcome'] == 'content_error'
            assert body['result'] == baseline
            assert body['error'] == 'v18_title_public_correction: actual error'
            return {'status': 'needs_user_review'}
    class Model:
        account_profile = 'current'
        def generate(self, current, model):
            raise codex.TitleContentError('v18_title_public_correction: actual error', baseline)
    monkeypatch.setattr(runner, 'build_stage_input', lambda *args: stage())
    assert runner.run_once(Cloud(), Model(), cache_root=tmp_path, recover=False)


def test_two_phase_client_advertises_required_protocol():
    from zhiju.v14_executor.client import EXECUTOR_PROTOCOL
    assert EXECUTOR_PROTOCOL == 6


def test_existing_claim_gate_blocks_old_executor_and_accepts_updated_executor(store):
    from test_v14_runs import configure
    from zhiju.database import TenantSession
    from zhiju.services import v14_runs
    from zhiju.services.identity import ConflictError
    from zhiju.workflow_bundles import BASELINE, snapshot
    # Use the existing local DB fixture; no real work order or production claim.
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        configure(session)
        run = v14_runs.create_run(session, 'work-a')
        data = BytesIO()
        with ZipFile(BASELINE) as source, ZipFile(data, 'w') as target:
            for name in source.namelist():
                content = source.read(name)
                if name == 'zhiju-workflow.json':
                    manifest = json.loads(content)
                    manifest['executor_protocol'] = 6
                    content = json.dumps(manifest).encode()
                target.writestr(name, content)
        run.rules_snapshot = {'skill_bundle': snapshot(data.getvalue(), version_id='local-test', label='test', revision=1)}
        session.commit()
        with pytest.raises(ConflictError, match='更新本机执行器'):
            v14_runs.claim_run(session, 'device-a', executor_protocol=5, claim_id='old')
        assert run.status == 'queued'
        claimed = v14_runs.claim_run(session, 'device-a', executor_protocol=6, claim_id='new')
        assert claimed['run_id'] == run.id
