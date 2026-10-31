import json
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from zhiju.v14_executor.launcher import WorkerManager, make_server


def wait_idle(manager):
    deadline = time.monotonic() + 5
    while manager.status()["running"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not manager.status()["running"]


@pytest.fixture
def manager(tmp_path):
    module = tmp_path / "backend/zhiju/v14_executor"
    module.mkdir(parents=True)
    (module / "__main__.py").write_text(
        "import json,sys,time\nc=json.load(sys.stdin)\n"
        "assert '--drain' in sys.argv and '--config-stdin' in sys.argv\n"
        "assert c['codex_binary']=='/fixed/codex'\ntime.sleep(.15)\n"
    )
    item = WorkerManager({"origin": "https://fixture.example", "host_id": "host-a",
        "tenant_id": "tenant-a", "account_profile": "current", "runtime_root": str(tmp_path),
        "python": sys.executable, "codex_binary": "/fixed/codex", "log_path": str(tmp_path / "worker.log")})
    yield item
    item.close()


def config():
    return {"base_url": "https://fixture.example", "host_id": "host-a", "tenant_id": "tenant-a",
        "account_profile": "current", "session_token": "test-only"}


def test_launcher_starts_one_worker_reuses_it_and_exits_after_queue(manager):
    first = manager.start(config())
    second = manager.start(config())
    assert first["pid"] == second["pid"]
    assert first["running"] and second["running"]
    wait_idle(manager)
    assert manager.status()["last_error"] is None
    assert manager.status()["pid"] is None


def test_launcher_keeps_wakeups_for_both_business_task_types(manager,tmp_path):
    script=tmp_path/'backend/zhiju/v14_executor/__main__.py'
    script.write_text('import json,sys,time,pathlib\nc=json.load(sys.stdin)\n'
        f'with pathlib.Path({str(tmp_path/"types.txt")!r}).open("a") as f: f.write(c["task_type"]+"\\n")\n'
        'time.sleep(.15)\n')
    manager.start(config())
    manager.start({**config(),'task_type':'channel_analysis'})
    manager.start(config())
    wait_idle(manager)
    assert (tmp_path/'types.txt').read_text().splitlines()==['operation_package','channel_analysis','operation_package']


def test_launcher_cannot_change_host_company_origin_or_executable(manager):
    for field, value in [("host_id", "other-host"), ("tenant_id", "other-company"),
                         ("base_url", "https://other.example"), ("account_profile", "other")]:
        with pytest.raises(ValueError):
            manager.start({**config(), field: value})
    assert not manager.status()["running"]
    # Browser input cannot choose a command; the locally installed executable wins.
    manager.start({**config(), "codex_binary": "/arbitrary/program"})
    wait_idle(manager)
    assert manager.status()["last_error"] is None


def test_launcher_reports_spawn_failure_without_success(manager):
    manager.settings["python"] = "/missing/python"
    with pytest.raises(OSError):
        manager.start(config())
    assert not manager.status()["running"]


def test_preflight_checks_bound_session_and_cli_login_without_starting_worker(manager, monkeypatch):
    import subprocess
    from zhiju.v14_executor.client import CloudClient
    calls = []
    monkeypatch.setattr(CloudClient, "request", lambda self, *args: {
        "tenant_id": "tenant-a", "device": {"id": "host-a"}})
    def login(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(subprocess, "run", login)
    assert manager.prepare(config())["ready"]
    assert calls == [["/fixed/codex", "login", "status"]]
    assert not manager.status()["running"]
    monkeypatch.setattr(CloudClient, "request", lambda self, *args: {
        "tenant_id": "tenant-b", "device": {"id": "host-a"}})
    with pytest.raises(ValueError, match="公司和设备"):
        manager.prepare(config())


def test_worker_failure_is_visible_and_does_not_loop_forever(manager, tmp_path):
    (tmp_path / "backend/zhiju/v14_executor/__main__.py").write_text("raise SystemExit(17)\n")
    manager.start(config())
    wait_idle(manager)
    assert "17" in manager.status()["last_error"]


def test_cli_drain_processes_queue_then_exits_without_idle_polling(tmp_path, monkeypatch):
    import io
    from copy import deepcopy
    from test_v14_contract import envelope
    from zhiju.v14_executor import __main__ as cli
    envelopes = []
    for i in range(2):
        item = {**envelope(), "tenant_id": "tenant-a", "claim_id": "claim", "account_profile": "current"}
        item["run_id"] = f"run-{i}"
        item["accepted_results"] = dict.fromkeys(["search", "title", "cover", "description", "community"], {})
        envelopes.append(item)
    accepted = []
    class Cloud:
        def __init__(self, *args):
            pass
        def claim(self):
            return deepcopy(envelopes.pop(0)) if envelopes else None
        def begin(self, *args):
            return "attempt"
        def submit(self, item, attempt, body):
            accepted.append(item["run_id"])
            return {"status": "text_ready"}
    monkeypatch.setattr(cli, "CloudClient", Cloud)
    monkeypatch.setattr(cli.time, "sleep", lambda *_: pytest.fail("drain must not idle-poll"))
    monkeypatch.setattr(cli.signal, "signal", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["v14", "--config-stdin", "--drain"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**config(), "cache_root": str(tmp_path)})))
    cli.main()
    assert sorted(accepted) == ["run-0", "run-1"]


def test_local_http_origin_and_private_network_preflight(manager):
    server = make_server(manager, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(url + "/health", headers={"Origin": "https://fixture.example"})
        with urlopen(request) as response:
            health = json.load(response)
            assert health["host_id"] == "host-a"
            assert health["executor_protocol"] == 3
            assert response.headers["Access-Control-Allow-Origin"] == "https://fixture.example"
        request = Request(url + "/start", method="OPTIONS", headers={"Origin": "https://fixture.example",
            "Access-Control-Request-Private-Network": "true"})
        with urlopen(request) as response:
            assert response.headers["Access-Control-Allow-Private-Network"] == "true"
        for origin in ["https://wrong.example", "null", ""]:
            request = Request(url + "/start", data=json.dumps(config()).encode(),
                headers={"Origin": origin, "Content-Type": "application/json"})
            with pytest.raises(HTTPError) as exc:
                urlopen(request)
            assert exc.value.code == 403
        assert not manager.status()["running"]
    finally:
        server.shutdown()
        server.server_close()


def test_cli_uses_ten_workers_and_drains_each_task_once(tmp_path, monkeypatch):
    import io
    from copy import deepcopy
    from test_v14_contract import envelope
    from zhiju.v14_executor import __main__ as cli
    tasks = []
    for i in range(12):
        item = {**envelope(), "tenant_id": "tenant-a", "claim_id": "claim", "account_profile": "current"}
        item["run_id"] = f"run-{i}"
        item["accepted_results"] = dict.fromkeys(["search", "title", "cover", "description", "community"], {})
        tasks.append(item)
    lock, barrier = threading.Lock(), threading.Barrier(10, timeout=5)
    accepted, threads = [], set()
    class Cloud:
        def __init__(self, *args): pass
        def claim(self):
            with lock:
                return deepcopy(tasks.pop(0)) if tasks else None
        def begin(self, item, node):
            with lock: threads.add(threading.get_ident())
            if int(item["run_id"].split("-")[1]) < 10:
                barrier.wait()
            return "attempt"
        def submit(self, item, attempt, body):
            with lock: accepted.append(item["run_id"])
            return {"status": "text_ready"}
    monkeypatch.setattr(cli, "CloudClient", Cloud)
    monkeypatch.setattr(cli.signal, "signal", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["v14", "--config-stdin", "--drain"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**config(), "cache_root": str(tmp_path)})))
    cli.main()
    assert len(threads) == 10
    assert sorted(accepted) == sorted(f"run-{i}" for i in range(12))


def test_pool_auth_failure_preserves_outbound_result_and_stops(tmp_path, monkeypatch):
    import io
    from copy import deepcopy
    from test_v14_contract import envelope
    from zhiju.v14_executor import __main__ as cli
    item = {**envelope(), "tenant_id": "tenant-a", "claim_id": "claim", "account_profile": "current"}
    item["accepted_results"] = dict.fromkeys(["search", "title", "cover", "description", "community"], {})
    pending, lock = [item], threading.Lock()
    class Cloud:
        def __init__(self, *args): pass
        def claim(self):
            with lock: return deepcopy(pending.pop()) if pending else None
        def begin(self, *args): return "attempt"
        def submit(self, *args): raise PermissionError("expired authorization")
    monkeypatch.setattr(cli, "CloudClient", Cloud)
    monkeypatch.setattr(cli.signal, "signal", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["v14", "--config-stdin", "--drain"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({**config(), "cache_root": str(tmp_path)})))
    with pytest.raises(PermissionError, match="expired authorization"):
        cli.main()
    cached = list(tmp_path.rglob("pending.json"))
    assert len(cached) == 1
    assert json.loads(cached[0].read_text())["body"]["result"] == {"text_complete": True}
