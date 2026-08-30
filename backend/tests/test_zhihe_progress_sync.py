from datetime import datetime
import json
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from zhiju import models
from zhiju.app import app
from zhiju.database import database_router


def _remote_item(*, title: str, drama_id: str, updated_at: str) -> dict[str, object]:
    statuses = {
        "parameter_normalization": "completed",
        "youtube_upload": "not_started",
        "copyright_verification": "in_progress",
        "subtitle_extraction": "completed",
        "guishou_upload": "failed",
        "role_extraction": "not_started",
        "tts": "completed",
        "production_completion": "not_started",
    }
    return {
        "drama_id": drama_id,
        "chinese_title": title,
        "episode_count": 81,
        "total_duration_seconds": 7325,
        "updated_at": updated_at,
        "nodes": {
            name: {
                "status": status,
                "started_at": None,
                "completed_at": None,
                "failure_reason": "鬼手任务失败" if name == "guishou_upload" else None,
                "resource_uris": [],
            }
            for name, status in statuses.items()
        },
    }


def test_zhihe_sync_uses_returned_nodes_and_preserves_zhiju_owned_fields() -> None:
    from zhiju.services.zhihe_progress_sync import sync_zhihe_progress

    suffix = uuid4().hex[:12]
    title = f"智核同步剧-{suffix}"
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        drama = models.Drama(
            drama_number=-90,
            drama_code=f"TEST-ZHIHE-{suffix}",
            chinese_title=title,
            normalized_title=title.lower(),
            source_type="manual",
            status="active",
        )
        session.add(drama)
        session.flush()
        state = models.DramaProductionState(
            drama_id=drama.id,
            cloud_download_status="completed",
            is_production_excluded=True,
            source_type="manual",
        )
        session.add(state)
        session.commit()

        client = SimpleNamespace(
            iter_progress_items=lambda **_: iter(
                [_remote_item(title=title, drama_id=f"ZH-{suffix}", updated_at="2026-08-31T10:00:00+08:00")]
            )
        )
        result = sync_zhihe_progress(session, client)
        session.expire_all()
        saved = session.scalar(
            select(models.DramaProductionState).where(
                models.DramaProductionState.drama_id == drama.id
            )
        )

        assert result == {
            "fetched": 1,
            "updated": 1,
            "skipped_stale": 0,
            "skipped_unmatched": 0,
        }
        assert saved is not None
        assert saved.cloud_download_status == "completed"
        assert saved.is_production_excluded is True
        assert saved.parameter_normalization_status == "completed"
        assert saved.youtube_upload_status == "not_started"
        assert saved.copyright_verification_status == "in_progress"
        assert saved.subtitle_extraction_status == "completed"
        assert saved.guishou_upload_status == "failed"
        assert saved.role_extraction_status == "not_started"
        assert saved.tts_status == "completed"
        assert saved.production_completion_status == "not_started"
        assert saved.episode_count == 81
        assert saved.total_duration_seconds == 7325
        assert saved.last_error == "鬼手上传：鬼手任务失败"
        assert saved.source_type == "zhihe"
        assert saved.source_external_id == f"ZH-{suffix}"
        assert saved.source_updated_at == datetime(2026, 8, 31, 2, 0, 0)
        assert saved.source_synced_at is not None
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_zhihe_sync_skips_stale_and_unmatched_items() -> None:
    from zhiju.services.zhihe_progress_sync import sync_zhihe_progress

    suffix = uuid4().hex[:12]
    title = f"智核旧数据剧-{suffix}"
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        drama = models.Drama(
            drama_number=-91,
            drama_code=f"TEST-ZHIHE-STALE-{suffix}",
            chinese_title=title,
            normalized_title=title.lower(),
            source_type="manual",
            status="active",
        )
        session.add(drama)
        session.flush()
        session.add(
            models.DramaProductionState(
                drama_id=drama.id,
                parameter_normalization_status="in_progress",
                source_type="zhihe",
                source_external_id=f"ZH-{suffix}",
                source_updated_at=datetime(2026, 8, 31, 3, 0, 0),
            )
        )
        session.commit()

        client = SimpleNamespace(
            iter_progress_items=lambda **_: iter(
                [
                    _remote_item(
                        title=title,
                        drama_id=f"ZH-{suffix}",
                        updated_at="2026-08-31T10:00:00+08:00",
                    ),
                    _remote_item(
                        title=f"智矩不存在剧-{suffix}",
                        drama_id=f"ZH-MISSING-{suffix}",
                        updated_at="2026-08-31T11:00:00+08:00",
                    ),
                    _remote_item(
                        title=title,
                        drama_id=f"ZH-DIFFERENT-{suffix}",
                        updated_at="2026-08-31T12:00:00+08:00",
                    ),
                ]
            )
        )
        result = sync_zhihe_progress(session, client)
        session.expire_all()
        saved = session.scalar(
            select(models.DramaProductionState).where(
                models.DramaProductionState.drama_id == drama.id
            )
        )

        assert result == {
            "fetched": 3,
            "updated": 0,
            "skipped_stale": 1,
            "skipped_unmatched": 2,
        }
        assert saved is not None
        assert saved.parameter_normalization_status == "in_progress"
        assert saved.source_updated_at == datetime(2026, 8, 31, 3, 0, 0)
    finally:
        session.close()
        transaction.rollback()
        connection.close()


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_zhihe_client_uses_bearer_auth_and_cursor_pagination() -> None:
    from zhiju.services.zhihe_progress_sync import ZhiheProgressClient

    requests = []
    first_item = _remote_item(
        title="第一部剧",
        drama_id="ZH-1",
        updated_at="2026-08-31T10:00:00+08:00",
    )
    second_item = _remote_item(
        title="第二部剧",
        drama_id="ZH-2",
        updated_at="2026-08-31T10:01:00+08:00",
    )

    def opener(request, *, timeout: int):
        requests.append((request, timeout))
        if len(requests) == 1:
            return _JsonResponse(
                {
                    "items": [first_item],
                    "next_cursor": "cursor-2",
                    "has_more": True,
                    "watermark": "2026-08-31T10:00:00+08:00",
                }
            )
        return _JsonResponse(
            {
                "items": [second_item],
                "next_cursor": None,
                "has_more": False,
                "watermark": "2026-08-31T10:01:00+08:00",
            }
        )

    client = ZhiheProgressClient(
        base_url="http://zhihe.test/",
        token="secret-token",
        opener=opener,
    )
    items = list(
        client.iter_progress_items(
            updated_after=datetime(2026, 8, 31, 1, 0, 0)
        )
    )

    assert [item["drama_id"] for item in items] == ["ZH-1", "ZH-2"]
    assert len(requests) == 2
    first_request, first_timeout = requests[0]
    second_request, second_timeout = requests[1]
    assert first_request.get_header("Authorization") == "Bearer secret-token"
    assert "limit=500" in first_request.full_url
    assert "updated_after=2026-08-31T01%3A00%3A00%2B00%3A00" in first_request.full_url
    assert "cursor=" not in first_request.full_url
    assert "cursor=cursor-2" in second_request.full_url
    assert "updated_after=" not in second_request.full_url
    assert first_timeout == second_timeout == 30


def test_zhihe_sync_route_and_progress_page_action_are_exposed() -> None:
    from pathlib import Path

    paths = TestClient(app).get("/openapi.json").json()["paths"]
    source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "post" in paths["/api/v3/integrations/zhihe/drama-progress/sync"]
    assert 'data-action="sync-zhihe-progress"' in source
    assert 'api("/integrations/zhihe/drama-progress/sync", { method: "POST" })' in source
    assert "智核进度同步完成" in source
