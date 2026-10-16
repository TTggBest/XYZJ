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
