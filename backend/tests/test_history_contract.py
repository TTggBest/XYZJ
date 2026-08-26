from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.models import (
    AuditEvent,
    AuthorizationEvent,
    ScheduleChangeHistory,
    SystemEvent,
    TaskEvent,
    YoutubeVideoStatusHistory,
)


def test_history_and_audit_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "get" in paths["/api/v3/system-events"]
    assert "get" in paths["/api/v3/audit-events"]
    assert "get" in paths["/api/v3/entities/{entity_type}/{entity_id}/timeline"]
    assert "get" in paths["/api/v3/tasks/{task_id}/events"]
    assert "get" in paths["/api/v3/schedules/{schedule_id}/history"]
    assert "get" in paths["/api/v3/youtube/videos/{video_id}/status-history"]


def test_history_timestamps_keep_microsecond_ordering() -> None:
    columns = (
        AuditEvent.occurred_at,
        AuthorizationEvent.occurred_at,
        TaskEvent.occurred_at,
        SystemEvent.occurred_at,
        ScheduleChangeHistory.changed_at,
        YoutubeVideoStatusHistory.changed_at,
    )
    assert all(column.type.fsp == 6 for column in columns)
