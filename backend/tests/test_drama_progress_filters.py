import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from zhiju.api.drama_progress import router
from zhiju.auth_context import get_tenant_db
from zhiju.database import TenantSession
from zhiju.models import Base, Drama, DramaProductionState


NODES = (
    "cloud_download", "parameter_normalization", "youtube_upload",
    "copyright_verification", "subtitle_extraction", "guishou_upload",
    "role_extraction", "tts", "production_completion",
)


@pytest.fixture
def progress_client():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={"tenant_id": "tenant-test"}) as session:
        test_app = FastAPI()
        test_app.include_router(router, prefix="/api")
        test_app.dependency_overrides[get_tenant_db] = lambda: session
        with TestClient(test_app) as client:
            yield client, session
    engine.dispose()


def add_drama(session, number, **statuses):
    drama = Drama(drama_number=number, drama_code=f"TEST-{number}",
                  chinese_title=f"测试剧{number}", normalized_title=f"测试剧{number}",
                  source_type="manual", status="active")
    session.add(drama)
    session.flush()
    session.add(DramaProductionState(drama_id=drama.id, **statuses))
    session.commit()
    return drama.id


@pytest.mark.parametrize("node", NODES)
@pytest.mark.parametrize("status", ("not_started", "in_progress", "completed", "failed"))
def test_each_node_can_be_filtered_by_its_own_status(progress_client, node, status):
    client, session = progress_client
    wanted = add_drama(session, 1, **{f"{node}_status": status})
    other_status = "completed" if status == "not_started" else "not_started"
    add_drama(session, 2, **{f"{node}_status": other_status})

    response = client.get("/api/v3/drama-production", params={"node": node, "node_status": status})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["drama_id"] for item in response.json()["items"]] == [wanted]


def test_tts_completed_includes_unfinished_and_finished_dramas_before_paging(progress_client):
    client, session = progress_client
    add_drama(session, 1, tts_status="not_started")
    unfinished = add_drama(session, 2, tts_status="completed")
    finished = add_drama(session, 3, **{f"{node}_status": "completed" for node in NODES})

    response = client.get("/api/v3/drama-production", params={
        "node": "tts", "node_status": "completed", "page_size": 10, "sort_order": "desc",
    })
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert [item["drama_id"] for item in response.json()["items"]] == [finished, unfinished]
    response = client.get("/api/v3/drama-production", params={
        "node": "tts", "node_status": "completed", "overall_status": "completed",
    })
    assert [item["drama_id"] for item in response.json()["items"]] == [finished]


@pytest.mark.parametrize("params", (
    {"node": "unknown", "node_status": "completed"},
    {"node": "tts", "node_status": "unknown"},
    {"node_status": "completed"},
))
def test_invalid_node_filter_is_rejected(progress_client, params):
    client, _ = progress_client
    assert client.get("/api/v3/drama-production", params=params).status_code == 422


@pytest.mark.parametrize("scope", ("overall", "node"))
def test_completed_or_in_progress_excludes_other_statuses(progress_client, scope):
    client, session = progress_client
    started = add_drama(session, 1, tts_status="in_progress")
    done = add_drama(session, 2, **{f"{node}_status": "completed" for node in NODES})
    add_drama(session, 3)
    add_drama(session, 4, tts_status="failed")
    add_drama(session, 5, is_production_excluded=True)
    params = ({"overall_status": "completed_or_in_progress"} if scope == "overall" else
              {"node": "tts", "node_status": "completed_or_in_progress"})

    response = client.get("/api/v3/drama-production", params=params)

    assert response.status_code == 200
    assert [item["drama_id"] for item in response.json()["items"]] == [started, done]


def test_node_filter_counts_matches_before_pagination(progress_client):
    client, session = progress_client
    for number in range(1, 11):
        add_drama(session, number)
    wanted = [add_drama(session, number, tts_status="completed") for number in range(11, 22)]

    response = client.get("/api/v3/drama-production", params={
        "node": "tts", "node_status": "completed", "page_size": 10, "page": 2,
    })

    assert response.status_code == 200
    assert response.json()["total"] == 11
    assert response.json()["pages"] == 2
    assert [item["drama_id"] for item in response.json()["items"]] == [wanted[-1]]


def test_drama_without_production_record_is_not_started_for_every_node(progress_client):
    client, session = progress_client
    drama = Drama(drama_number=1, drama_code="NO-STATE", chinese_title="未制作",
                  normalized_title="未制作", source_type="manual", status="active")
    session.add(drama)
    session.commit()
    for node in NODES:
        response = client.get("/api/v3/drama-production", params={
            "node": node, "node_status": "not_started",
        })
        assert response.status_code == 200
        assert [item["drama_id"] for item in response.json()["items"]] == [drama.id]
