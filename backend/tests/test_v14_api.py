from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
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


def test_six_stages_reach_existing_package_view(client, store, monkeypatch, tmp_path):
    """Exercise real orchestration/projection; creative acceptance has separate contract tests."""
    from copy import deepcopy
    from types import SimpleNamespace
    from test_v14_contract import envelope
    from zhiju.services import v14_runs, v14_outputs, package_outputs
    from zhiju.models import OperationPackage, PackageTitle, PackageCoverVariant, PackageDescription, PackageCommunityPost
    import sqlalchemy as sa
    sample = envelope()
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
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
    for node, output in outputs.items():
        response = client.post(f"/api/v3/v14/runs/{claim['run_id']}/attempts", json={"node_type": node, "claim_id": claim["claim_id"]})
        assert response.status_code == 200, response.text
        url = f"/api/v3/v14/runs/{claim['run_id']}/attempts/{response.json()['attempt_id']}"
        response = client.put(url, json={"claim_id": claim["claim_id"], "outcome": "accepted", "result": output})
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "text_ready"
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        assert s.get(OperationPackage, "package-a").status == "review_pending"
        for model, count in ((PackageTitle, 3), (PackageCoverVariant, 6), (PackageDescription, 1), (PackageCommunityPost, 1)):
            assert s.scalar(sa.select(sa.func.count()).select_from(model).where(model.package_id == "package-a")) == count
        assert len(package_outputs.get_package_outputs(s, "package-a")["titles"]) == 3
    assert len(list(tmp_path.rglob("package.md"))) == 1
