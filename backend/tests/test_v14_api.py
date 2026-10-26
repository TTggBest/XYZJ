from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from test_v14_runs import store, configure
from zhiju import auth_context
from zhiju.app import create_app
from zhiju.auth_context import Principal
from zhiju.database import TenantSession

PRINCIPAL = Principal("user-a", "tenant-a", "owner", None, "device-a", "normal", frozenset())


@pytest.fixture
def client(store):
    app = create_app()
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    def db():
        with TenantSession(store, info={"tenant_id": "tenant-a", "principal": PRINCIPAL}) as s:
            yield s
    app.dependency_overrides[auth_context.get_tenant_db] = db
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
    with TestClient(app) as c:
        yield c


def start(client):
    response = client.post("/api/v3/work-orders/work-a/v14-runs")
    assert response.status_code == 200, response.text
    run = response.json()
    claim = client.post("/api/v3/v14/claims", json={"host_id": "device-a"})
    assert claim.status_code == 200, claim.text
    return run, claim.json()


def test_task_start_dispatches_and_enqueues_v14_idempotently(client):
    first = client.post("/api/v3/tasks/task-a/start-v14")
    assert first.status_code == 200, first.text
    run = first.json()
    assert run["work_order_id"] == "work-a"
    assert run["package_id"] == "package-a"
    assert run["status"] == "queued"
    assert client.post("/api/v3/tasks/task-a/start-v14").json()["run_id"] == run["run_id"]
    claim = client.post("/api/v3/v14/claims", json={"host_id": "device-a"})
    assert claim.status_code == 200, claim.text
    assert claim.json()["run_id"] == run["run_id"]


@pytest.mark.parametrize("material_language", ["印尼", "印尼语", "印度尼西亚语", "Indonesian", "id"])
def test_indonesian_material_alias_can_start_bound_channel(client, store, material_language):
    from copy import deepcopy
    from zhiju.models import Channel
    from zhiju.models.v14 import V14Setting
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.get(Channel, "channel-a").default_language = "id"
        setting = s.scalar(sa.select(V14Setting))
        config = deepcopy(setting.payload)
        config["channel_inputs"]["channel-a"]["language"] = material_language
        setting.payload = config
        s.commit()
    response = client.post("/api/v3/tasks/task-a/start-v14")
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "queued"
    assert client.post("/api/v3/tasks/task-a/start-v14").json()["run_id"] == run["run_id"]


@pytest.mark.parametrize("configured", [True, False])
def test_pending_task_start_is_atomic(client, store, configured):
    from datetime import date
    from zhiju.models import OperationTask, WorkOrder, OperationPackage
    from zhiju.models.v14 import V14Setting, V14Run
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.add(OperationTask(id="new-task", batch_id="batch-a", channel_id="channel-a",
            drama_id="drama-a", source="manual", task_date=date(2026, 10, 27),
            target_publish_date=date(2026, 10, 27), idempotency_key="new-task",
            source_video_id="video-new", status="pending_dispatch", community_count=0))
        if not configured:
            s.delete(s.scalar(sa.select(V14Setting)))
        s.commit()
    response = client.post("/api/v3/tasks/new-task/start-v14")
    assert response.status_code == (200 if configured else 409), response.text
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        task = s.get(OperationTask, "new-task")
        work = s.scalar(sa.select(WorkOrder).where(WorkOrder.task_id == task.id))
        if not configured:
            assert task.status == "pending_dispatch"
            assert work is None
            assert s.scalar(sa.select(sa.func.count()).select_from(V14Run)) == 0
        else:
            assert task.status == "dispatched"
            assert work.drama_id == task.drama_id and work.channel_id == task.channel_id
            package = s.scalar(sa.select(OperationPackage).where(OperationPackage.work_order_id == work.id))
            run = s.get(V14Run, response.json()["run_id"])
            assert run.package_id == package.id
            assert run.input_snapshot["video_id"] == "video-new"
            assert run.input_snapshot["community_count"] == 0
            assert client.post("/api/v3/tasks/new-task/start-v14").json()["run_id"] == run.id


def test_task_start_preserves_v14_operator_and_tenant_boundaries(client):
    assert client.post("/api/v3/tasks/task-b/start-v14").status_code == 404
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, membership_role="member")
    assert client.post("/api/v3/tasks/task-a/start-v14").status_code == 403


def begin(client, claim):
    r = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts", json={"claim_id": claim["claim_id"], "node_type": "search"})
    assert r.status_code == 200, r.text
    return r.json()["attempt_id"]


def test_claim_requires_bound_device(client):
    response = client.post("/api/v3/v14/claims", json={"host_id": "someone-else"})
    assert response.status_code == 403


def test_company_switch_cannot_claim(client):
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, tenant_id="tenant-b")
    assert client.post("/api/v3/v14/claims", json={"host_id": "device-a"}).status_code == 403


def test_duplicate_submission_is_idempotent(client):
    _, claim = start(client)
    attempt = begin(client, claim)
    url = f"/api/v3/v14/runs/{claim['run_id']}/attempts/{attempt}"
    body = {"claim_id": claim["claim_id"], "outcome": "system_error", "error": "offline"}
    first = client.put(url, json=body)
    assert first.status_code == 200, first.text
    assert client.put(url, json=body).json() == first.json()


def test_stale_attempt_cannot_overwrite(client):
    _, claim = start(client)
    attempt = begin(client, claim)
    rid = claim["run_id"]
    client.post(f"/api/v3/v14/runs/{rid}/cancel")
    resumed = client.post(f"/api/v3/v14/runs/{rid}/resume", json={"stopped_confirmed": True})
    assert resumed.status_code == 200, resumed.text
    assert client.put(f"/api/v3/v14/runs/{rid}/attempts/{attempt}", json={"claim_id": claim["claim_id"], "outcome": "system_error", "error": "late"}).status_code == 409


def test_disconnect_never_reassigns_automatically(client, store):
    from zhiju.models.v14 import V14Run
    _, claim = start(client)
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.get(V14Run, claim["run_id"]).heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=100)
        s.commit()
    assert client.get("/api/v3/work-orders/work-a/v14-runs/current").json()["status"] == "interrupted"
    assert client.post("/api/v3/v14/claims", json={"host_id": "device-a"}).status_code == 204


def test_cancel_blocks_late_results(client):
    _, claim = start(client)
    attempt = begin(client, claim)
    assert client.post(f"/api/v3/v14/runs/{claim['run_id']}/cancel").status_code == 200
    response = client.put(f"/api/v3/v14/runs/{claim['run_id']}/attempts/{attempt}", json={"claim_id": claim["claim_id"], "outcome": "accepted", "result": {}})
    assert response.status_code == 409


def test_three_content_errors_require_review(client):
    _, claim = start(client)
    for _ in range(3):
        attempt = begin(client, claim)
        response = client.put(f"/api/v3/v14/runs/{claim['run_id']}/attempts/{attempt}", json={"claim_id": claim["claim_id"], "outcome": "content_error", "error": "不合格"})
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_user_review"
    assert client.post(f"/api/v3/v14/runs/{claim['run_id']}/resume", json={"stopped_confirmed": True}).status_code == 409


@pytest.mark.parametrize("community_count", [0, 1])
def test_six_stages_reach_existing_package_view(client, store, monkeypatch, tmp_path, community_count):
    """Exercise real orchestration/projection; creative acceptance has separate contract tests."""
    from copy import deepcopy
    from types import SimpleNamespace
    from test_v14_contract import envelope
    from zhiju.services import v14_runs, v14_outputs, package_outputs
    from zhiju.models import OperationPackage, PackageTitle, PackageCoverVariant, PackageDescription, PackageCommunityPost, WorkOrder
    import sqlalchemy as sa
    sample = envelope()
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.get(WorkOrder, "work-a").community_count = community_count
        config = deepcopy(v14_runs.get_settings(s).payload)
        config["rules"] = sample["rules_snapshot"]
        config["channel_inputs"]["channel-a"] = sample["input_snapshot"]["channel"]
        v14_runs.save_settings(s, config)
    monkeypatch.setattr(v14_outputs, "validate_result", lambda *args: [])
    monkeypatch.setattr(package_outputs, "get_settings", lambda: SimpleNamespace(artifact_root=tmp_path))
    _, claim = start(client)
    outputs = {
        "search": {"market_payload": {"final_angles": [{"angle_id": n} for n in ("A", "B", "C")]}, "plot_payload": {}},
        "title": {"results": [{"packaging_brief": {"creative_slot_id": "slot"}, "directions": [{"index": n, "title": f"标题{n}", "translation": f"翻译{n}", "recommendation_score": 100 - n} for n in (1, 2, 3)]}]},
        "cover": {"results": [{"titles": [{"title_index": n, "prompt_4_5": f"portrait {n}", "prompt_16_9": f"wide {n}"} for n in (1, 2, 3)]}]},
        "description": {"results": [{"description": "说明", "translation": "翻译", "url": ""}]},
        "community": {"results": [{"plan_index": 1, "copy": "社群", "copy_translation": "翻译", "image_prompt_1x1": "prompt"}]},
        "merge": {"text_complete": True},
    }
    if not community_count:
        outputs["community"] = {"section": "community", "results": []}
    for node, output in outputs.items():
        response = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts", json={"node_type": node, "claim_id": claim["claim_id"]})
        assert response.status_code == 200, response.text
        url = f"/api/v3/v14/runs/{claim['run_id']}/attempts/{response.json()['attempt_id']}"
        response = client.put(url, json={"claim_id": claim["claim_id"], "outcome": "accepted", "result": output})
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "text_ready"
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        assert s.get(OperationPackage, "package-a").status == "review_pending"
        for model, count in ((PackageTitle, 3), (PackageCoverVariant, 6), (PackageDescription, 1), (PackageCommunityPost, community_count)):
            assert s.scalar(sa.select(sa.func.count()).select_from(model).where(model.package_id == "package-a")) == count
        assert len(package_outputs.get_package_outputs(s, "package-a")["titles"]) == 3
    assert len(list(tmp_path.rglob("package.md"))) == 1
    if community_count == 0:
        def upstream_rows(s):
            return {model.__tablename__: [dict((col.name, getattr(row, col.name)) for col in model.__table__.columns)
                for row in s.scalars(sa.select(model).where(model.package_id == "package-a").order_by(model.id))]
                for model in (PackageTitle, PackageCoverVariant, PackageDescription)}
        with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
            before = upstream_rows(s)
        old_attempts = response.json()["attempts"]
        changed = client.patch("/api/v3/tasks/task-a/community", json={"community_count": 1})
        assert changed.status_code == 200, changed.text
        assert changed.json()["run"]["status"] == "queued"
        claim = client.post("/api/v3/v14/claims", json={"host_id": "device-a"}).json()
        assert set(claim["accepted_results"]) == {"search", "title", "cover", "description"}
        for node in ("community", "merge"):
            output = outputs[node] if node == "merge" else {"results": [{"plan_index": 1, "copy": "社群", "copy_translation": "翻译", "image_prompt_1x1": "prompt"}]}
            r = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts", json={"node_type": node, "claim_id": claim["claim_id"]})
            assert r.status_code == 200, r.text
            r = client.put(f"/api/v3/v14/runs/{claim['run_id']}/attempts/{r.json()['attempt_id']}", json={"claim_id": claim["claim_id"], "outcome": "accepted", "result": output})
            assert r.status_code == 200, r.text
        assert r.json()["status"] == "text_ready"
        assert r.json()["attempts"][:len(old_attempts)] == old_attempts
        with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
            view = package_outputs.get_package_outputs(s, "package-a")
            assert upstream_rows(s) == before
            assert s.scalar(sa.select(sa.func.count()).select_from(PackageCommunityPost)) == 1


def test_community_count_edit_preserves_operator_scope_and_running_work(client):
    url = "/api/v3/tasks/task-a/community"
    assert client.patch(url, json={"community_count": 2}).status_code == 200
    assert client.patch("/api/v3/tasks/task-b/community", json={"community_count": 2}).status_code == 404
    assert client.patch(url, json={"community_count": -1}).status_code == 422
    start(client)
    assert client.patch(url, json={"community_count": 1}).status_code == 409
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, membership_role="member")
    assert client.patch(url, json={"community_count": 1}).status_code == 403


@pytest.mark.parametrize("updates,expected", [(1, [2]), (2, [1, 1])])
def test_synced_schedules_use_v14_daily_community_counts_and_preserve_edits(store, updates, expected):
    from zhiju.services.feishu_sync import upsert_channel_schedule_rows
    from zhiju.models import ChannelScheduleEntry
    day = datetime(2026, 10, 28)
    rows = [dict(channel_id="channel-a", drama_id="drama-a", publish_slot_id=f"slot-{i}",
        publish_date=(day - timedelta(days=i)).date(), planned_local_time=day, planned_beijing_time=day,
        planned_utc_time=day, source_type="feishu", source_sheet_id="sheet", source_sheet_title="channel",
        source_row_number=i+2, source_video_id=None, source_video_url=None,
        is_uploaded=False, is_published=False, is_task_written=False) for i in range(updates)]
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        upsert_channel_schedule_rows(s, rows, now=day)
        s.commit()
        schedules = list(s.scalars(sa.select(ChannelScheduleEntry).order_by(ChannelScheduleEntry.publish_slot_id)))
        assert [r.community_count for r in schedules] == expected
        schedules[0].community_count = 0
        s.commit()
        upsert_channel_schedule_rows(s, rows, now=day)
        s.commit()
        assert schedules[0].community_count == 0


@pytest.mark.parametrize("updates,expected", [(1, 2), (2, 1)])
@pytest.mark.parametrize("manual_zero", [False, True])
def test_legacy_zero_schedule_is_resolved_before_new_task_and_v14_snapshot(client, store, updates, expected, manual_zero):
    from zhiju.models import ChannelScheduleEntry, OperationTask
    from zhiju.schemas.production import TaskCreate
    from zhiju.services import production, v14_runs
    from zhiju.services.community_requirements import update_community
    day = datetime(2026, 10, 29)
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        for number in range(updates):
            s.add(ChannelScheduleEntry(id=f"legacy-{number}", channel_id="channel-a", drama_id="drama-a",
                publish_slot_id=f"legacy-slot-{number}", publish_date=(day - timedelta(days=number)).date(), planned_local_time=day,
                planned_beijing_time=day, planned_utc_time=day, source_type="feishu", community_count=0,
                status="planned", idempotency_key=f"legacy-schedule-{number}"))
        s.commit()
        if manual_zero:
            # A genuine user override must remain distinguishable from the old default.
            update_community(s, "schedules", "legacy-0", 0)
        task = production.create_task(s, TaskCreate(schedule_id="legacy-0", task_date=day.date(), idempotency_key="legacy-new-task"))
        assert task.community_count == (0 if manual_zero else expected)
        # Simulate an old pending task produced before the fix as well.
        task.community_count = 0
        s.get(ChannelScheduleEntry, "legacy-0").community_count = 0
        s.commit()
        task_id = task.id
    response = client.post(f"/api/v3/tasks/{task_id}/start-v14")
    assert response.status_code == 200, response.text
    claim = client.post("/api/v3/v14/claims", json={"host_id": "device-a"})
    assert claim.status_code == 200, claim.text
    assert claim.json()["input_snapshot"]["community_count"] == (0 if manual_zero else expected)


def test_device_less_cloud_login_can_authorize_existing_bound_executor(client, store):
    from zhiju.models import Device, DeviceUserBinding, AuthSession
    from zhiju.security import digest_token
    now = datetime.now(timezone.utc)
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.add(Device(id="device-a", device_key="local-a", name="Mac", hostname="mac.local", os_type="macos", device_role="worker", trust_level="production_device", status="active"))
        s.add(DeviceUserBinding(id="binding-a", device_id="device-a", user_id="user-a", tenant_id="tenant-a", credential_digest="dummy", bound_by_user_id="user-a", bound_at=now, status="active"))
        s.add(AuthSession(id="parent-a", user_id="user-a", tenant_id="tenant-a", token_digest="parent-digest", status="active", expires_at=now + timedelta(hours=1), last_seen_at=now, created_at=now))
        s.commit()
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, device_id=None, session_id="parent-a")
    response = client.post("/api/v3/v14/executor-session", headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    data = response.json()
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        row = s.scalar(sa.select(AuthSession).where(AuthSession.token_digest == digest_token(data["session_token"])))
        assert row.device_id == "device-a" and row.binding_id is None
        assert row.tenant_id == "tenant-a" and row.user_id == "user-a"
        assert row.expires_at <= s.get(AuthSession, "parent-a").expires_at
    assert response.headers["cache-control"] == "no-store"


def test_nearly_expired_browser_session_cannot_start_a_model_job(client, store):
    from zhiju.models import Device, AuthSession
    now = datetime.now(timezone.utc)
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.add(Device(id="device-a", device_key="local-a", name="Mac", hostname="mac.local",
            os_type="macos", device_role="worker", trust_level="normal", status="active"))
        s.add(AuthSession(id="parent-short", user_id="user-a", tenant_id="tenant-a",
            token_digest="short-session", status="active", expires_at=now + timedelta(minutes=2),
            last_seen_at=now, created_at=now))
        s.commit()
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, session_id="parent-short")
    response = client.post("/api/v3/v14/executor-session", headers={"Origin": "http://testserver"})
    assert response.status_code == 409, response.text
    assert "重新登录" in response.json()["detail"]


def test_executor_authorization_never_creates_a_device_binding(client):
    response = client.post("/api/v3/v14/executor-session", headers={"Origin": "http://testserver"})
    assert response.status_code == 409


def test_executor_authorization_still_requires_company_admin(client):
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, membership_role="viewer")
    assert client.post("/api/v3/v14/executor-session", headers={"Origin": "http://testserver"}).status_code == 403


def test_cloud_executor_authorization_does_not_require_customer_login_binding(client, store):
    from zhiju.models import Device, DeviceUserBinding, AuthSession
    from zhiju.security import digest_token
    now = datetime.now(timezone.utc)
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.add(Device(id="device-a", device_key="local-a", name="Mac", hostname="mac.local",
            os_type="macos", device_role="worker", trust_level="normal", status="active"))
        s.add(AuthSession(id="parent-a", user_id="user-a", tenant_id="tenant-a", token_digest="parent-digest",
            status="active", expires_at=now + timedelta(hours=1), last_seen_at=now, created_at=now))
        s.commit()
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, device_id=None, session_id="parent-a")
    response = client.post("/api/v3/v14/executor-session", headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        row = s.scalar(sa.select(AuthSession).where(AuthSession.token_digest == digest_token(response.json()["session_token"])))
        assert row.device_id == "device-a" and row.binding_id is None
        assert row.tenant_id == "tenant-a" and row.user_id == "user-a"
        assert row.expires_at <= s.get(AuthSession, "parent-a").expires_at
        assert s.scalar(sa.select(sa.func.count()).select_from(DeviceUserBinding)) == 0
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        s.get(Device, "device-a").status = "inactive"
        s.commit()
    assert client.post("/api/v3/v14/executor-session", headers={"Origin": "http://testserver"}).status_code == 409


def test_expired_cached_claim_does_not_block_resumed_run(client, tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    from test_v14_contract import envelope
    from v14_fixtures import valid_market_payload
    from zhiju.services import v14_runs
    from zhiju.v14_executor.client import CloudConflict
    from zhiju.v14_executor.runner import run_once
    # The same server protocol handles cancel/resume and the cache rejection.
    _, old = start(client)
    attempt_id = begin(client, old)
    cache = tmp_path / old["run_id"] / "pending.json"
    cache.parent.mkdir()
    cache.write_text(json.dumps({"envelope": old, "attempt_id": attempt_id,
        "body": {"claim_id": old["claim_id"], "outcome": "accepted", "result": {"old_result": True}}}))
    client.post(f"/api/v3/v14/runs/{old['run_id']}/cancel")
    assert client.post(f"/api/v3/v14/runs/{old['run_id']}/resume", json={"stopped_confirmed": True}).status_code == 200
    class Cloud:
        def submit(self, e, a, body):
            r = client.put(f"/api/v3/v14/runs/{e['run_id']}/attempts/{a}", json=body)
            if r.status_code == 409: raise CloudConflict(r.json()["detail"])
            assert r.status_code == 200, r.text
            return r.json()
        def current(self, e): return client.get("/api/v3/work-orders/work-a/v14-runs/current").json()
        def claim(self):
            r = client.post("/api/v3/v14/claims", json={"host_id": "device-a"})
            assert r.status_code == 200, r.text
            assert r.json()["claim_id"] != old["claim_id"]
            raise StopIteration("reached new claim")
    with pytest.raises(StopIteration, match="reached new claim"):
        run_once(Cloud(), None, cache_root=tmp_path)
    assert not cache.exists()
    archived = list(cache.parent.glob("*.abandoned.json"))
    assert len(archived) == 1 and json.loads(archived[0].read_text())["body"]["result"] == {"old_result": True}
