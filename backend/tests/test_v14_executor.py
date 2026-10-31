from copy import deepcopy
import json
import sys

import pytest

from test_v14_contract import envelope
from v14_fixtures import valid_market_payload


@pytest.fixture
def fake_cli(tmp_path):
    executable = tmp_path / "codex"
    executable.write_text(f"#!{sys.executable}\n" + '''import json, pathlib, sys, time
args=sys.argv[1:]
if args==['login','status']: print('Logged in using ChatGPT'); sys.exit(0)
model=args[args.index('--model')+1]
if model=='missing': sys.exit(17)
if model=='slow': time.sleep(30)
schema=json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())
skill_file=pathlib.Path(args[args.index('--cd')+1])/'skills/xy-title-v14/SKILL.md'
if model=='skill-reader':
 pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'skill_body':skill_file.read_text()}))
 sys.exit(0)
pathlib.Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'model':model,'schema':schema,'sandbox':args[args.index('--sandbox')+1], 'reasoning_config':next((a for a in args if a.startswith('model_reasoning_effort=')), None)}))
''')
    executable.chmod(0o700)
    return str(executable)


def test_explicit_model_and_schema_passed(fake_cli):
    from zhiju.v14_executor.codex import CodexClient
    from zhiju.v14_runtime.contract import build_stage_input
    stage = build_stage_input(envelope(), "title")
    result = CodexClient(binary=fake_cli).generate(stage, "selected-model")
    assert result["model"] == "selected-model"
    assert result["sandbox"] == "read-only"
    assert result["schema"]["properties"]["results"]["maxItems"] == 1


def test_selected_bundle_files_are_available_to_codex(fake_cli):
    from zhiju.workflow_bundles import BASELINE, snapshot, read_file
    from zhiju.v14_runtime.contract import build_stage_input
    from zhiju.v14_executor.codex import CodexClient
    data = envelope()
    data['rules_snapshot'] = {'skill_bundle': snapshot(BASELINE.read_bytes(), version_id='builtin-v14', label='V14', revision=1)}
    result = CodexClient(binary=fake_cli).generate(build_stage_input(data, 'title'), 'skill-reader')
    assert result['skill_body'] == read_file(BASELINE.read_bytes(), 'xy-title-v14/SKILL.md')


def test_unavailable_model_has_no_fallback(fake_cli):
    from zhiju.v14_executor.codex import CodexClient
    from zhiju.v14_runtime.contract import build_stage_input
    with pytest.raises(RuntimeError, match="17"):
        CodexClient(binary=fake_cli).generate(build_stage_input(envelope(), "title"), "missing")


def test_cloud_medium_reasoning_is_explicitly_passed(fake_cli):
    from zhiju.v14_executor.codex import CodexClient
    from zhiju.v14_runtime.contract import build_stage_input
    data = envelope()
    data['rules_snapshot']['execution'] = {'reasoning_effort': 'medium'}
    result = CodexClient(binary=fake_cli).generate(build_stage_input(data, 'title'), 'gpt-6.1-sol')
    assert result['model'] == 'gpt-6.1-sol'
    assert result['reasoning_config'] == 'model_reasoning_effort="medium"'


def test_timeout_stops_child_before_resume(fake_cli):
    from zhiju.v14_executor.codex import CodexClient
    from zhiju.v14_runtime.contract import build_stage_input
    with pytest.raises(TimeoutError):
        CodexClient(binary=fake_cli, timeout=0.05).generate(build_stage_input(envelope(), "title"), "slow")


class Cloud:
    def __init__(self, data):
        self.data, self.sent, self.submissions = data, [], 0
    def claim(self): return deepcopy(self.data)
    def begin(self, e, node): return "attempt-1"
    def heartbeat(self, e): return {"status": "running"}
    def submit(self, e, attempt, body):
        self.sent.append(deepcopy(body))
        self.submissions += 1
        if self.submissions == 1: raise ConnectionError("response lost")
        return {"status": "text_ready"}


def test_network_retry_reuses_result(tmp_path):
    from zhiju.v14_executor.runner import run_once
    class Model:
        account_profile = "current"
        calls = 0
        def generate(self, stage, model):
            self.calls += 1
            data = valid_market_payload()
            data.update(drama_id="pending_r1", drama_title="剧目", selection_context={"channel_name": "频道", "channel_language": "阿拉伯语", "channel_type": "复仇"})
            return data
    e = {**envelope(), "tenant_id": "t1", "claim_id": "claim", "account_profile": "current"}
    e["accepted_results"] = {}
    cloud, model = Cloud(e), Model()
    run_once(cloud, model, cache_root=tmp_path, evidence_provider=lambda item: {"status": "completed", "videos": []}, retry_delay=0)
    assert model.calls == 1
    assert len(cloud.sent) == 2 and cloud.sent[0] == cloud.sent[1]


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize("status,reason", [
    ("failed", "YouTube search returned no usable videos"),
    ("failed", "YouTube retrieval unavailable: TimeoutExpired"),
    ("completed", ""),
    ("partial", ""),
])
def test_search_passes_retrieval_result_to_model(tmp_path, bundled, status, reason):
    from zhiju.v14_executor.runner import run_once
    from zhiju.v14_runtime.contract import build_stage_input
    from zhiju.workflow_bundles import BASELINE, snapshot

    e = {**envelope(), "tenant_id": "t1", "claim_id": "claim", "account_profile": "current"}
    e["accepted_results"] = {}
    if bundled:
        e["rules_snapshot"] = {"skill_bundle": snapshot(
            BASELINE.read_bytes(), version_id="builtin-v14", label="V14", revision=1)}
    plot = build_stage_input(e, "search").context["plot_payload"]
    evidence = {"provider": "agent-reach", "status": status, "reason": reason,
                "videos": [] if status == "failed" else [{"video_url": "https://www.youtube.com/watch?v=abcdefghijk"}]}

    class Model:
        account_profile = "current"
        calls = 0

        def generate(self, stage, model):
            self.calls += 1
            assert stage.context["plot_payload"] == plot
            assert json.dumps(evidence, ensure_ascii=False) in stage.prompt
            result = valid_market_payload()
            result.update(drama_id="pending_r1", drama_title="剧目", search_status=status,
                          selection_context={"channel_name": "频道", "channel_language": "阿拉伯语", "channel_type": "复仇"})
            if status == "failed":
                result.update(verified_market_angle_count=0, market_videos=[])
                result["fallback"] = {"used": True, "reason": reason}
                for angle in result["angle_candidates"] + result["final_angles"]:
                    angle.update(source_type="story_derived", market_evidence_refs=[],
                                 market_confidence="story_only", evidence_freshness="none")
            return result

    cloud, model = Cloud(e), Model()
    cloud.submissions = 1
    run_once(cloud, model, cache_root=tmp_path,
             evidence_provider=lambda item: deepcopy(evidence), retry_delay=0)
    assert model.calls == 1
    assert cloud.sent[0]["outcome"] == "accepted"
    result = cloud.sent[0]["result"]
    assert result["plot_payload"] == plot
    assert result["external_evidence"] == evidence
    if status == "failed":
        assert result["market_payload"]["verified_market_angle_count"] == 0
        assert all(angle["source_type"] == "story_derived"
                   for angle in result["market_payload"]["final_angles"])


def test_restart_uses_cloud_accepted_stages(tmp_path):
    from zhiju.v14_executor.runner import run_once
    class Model:
        account_profile = "current"
        def generate(self, stage, model): raise AssertionError("must reuse accepted stages")
    e = {**envelope(), "tenant_id": "t1", "claim_id": "claim", "account_profile": "current"}
    e["accepted_results"] = {n: {} for n in ("search", "title", "cover", "description", "community")}
    cloud = Cloud(e)
    cloud.submissions = 1
    assert run_once(cloud, Model(), cache_root=tmp_path, retry_delay=0)
    assert cloud.sent[0]["result"] == {"text_complete": True}


def test_expired_login_stops_claims(monkeypatch):
    from zhiju.v14_executor.client import CloudClient
    client = CloudClient("http://127.0.0.1:1", "expired", "device-a", "t1")
    def unauthorized(*args, **kwargs):
        from urllib.error import HTTPError
        raise HTTPError("http://localhost", 401, "expired", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", unauthorized)
    with pytest.raises(PermissionError): client.claim()


def test_schema_error_does_not_consume_creative_retry(tmp_path):
    from zhiju.v14_executor.runner import run_once
    class Model:
        account_profile = "current"
        def generate(self, stage, model): return {}
    e = {**envelope(), "tenant_id": "t1", "claim_id": "claim", "account_profile": "current"}
    e["accepted_results"] = {}
    cloud = Cloud(e)
    cloud.submissions = 1
    run_once(cloud, Model(), cache_root=tmp_path, evidence_provider=lambda item: {"status": "completed"}, retry_delay=0)
    assert cloud.sent[0]["outcome"] == "system_error"


@pytest.mark.parametrize('current', [None, 'deleted', {'run_id': 'replacement'}])
def test_deleted_cached_run_does_not_block_next_claim(tmp_path, current):
    from zhiju.v14_executor.client import CloudNotFound
    from zhiju.v14_executor.runner import run_once
    entry = {'envelope': {'run_id': 'old', 'work_order_id': 'work-old', 'claim_id': 'claim-old'},
             'attempt_id': 'attempt-old', 'body': {'result': {'generated': 'preserved'}}}
    cache = tmp_path / 'old' / 'pending.json'
    cache.parent.mkdir()
    cache.write_text(json.dumps(entry))
    class Cloud:
        def submit(self, *args): raise CloudNotFound('云端请求失败 HTTP 404')
        def current(self, e):
            if current == 'deleted': raise CloudNotFound('工单不存在')
            return current
        def claim(self): raise StopIteration('new queue reached')
    with pytest.raises(StopIteration, match='new queue reached'):
        run_once(Cloud(), None, cache_root=tmp_path)
    assert not cache.exists()
    assert json.loads((cache.parent / 'attempt-old.abandoned.json').read_text()) == entry


def test_missing_attempt_for_existing_run_is_not_discarded(tmp_path):
    from zhiju.v14_executor.client import CloudNotFound
    from zhiju.v14_executor.runner import replay_pending
    cache = tmp_path / 'old' / 'pending.json'
    cache.parent.mkdir()
    cache.write_text(json.dumps({'envelope': {'run_id': 'old'}, 'attempt_id': 'a', 'body': {}}))
    class Cloud:
        def submit(self, *args): raise CloudNotFound('missing attempt')
        def current(self, e): return {'run_id': 'old'}
    with pytest.raises(CloudNotFound, match='missing attempt'):
        replay_pending(Cloud(), tmp_path)
    assert cache.exists()


def test_cloud_404_has_distinct_type(monkeypatch):
    import urllib.error
    import urllib.request
    from zhiju.v14_executor.client import CloudClient, CloudNotFound
    def missing(*args, **kwargs):
        raise urllib.error.HTTPError('https://example.test', 404, 'not found', {}, None)
    monkeypatch.setattr(urllib.request, 'urlopen', missing)
    with pytest.raises(CloudNotFound):
        CloudClient('https://example.test', 'test', 'host', 'tenant').current({'work_order_id': 'deleted'})
