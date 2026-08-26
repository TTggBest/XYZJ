from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.services.identity import ALLOWED_CHANNEL_TRANSITIONS


def test_channel_lifecycle_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/v3/channels/overview"]
    assert "patch" in paths["/api/v3/channels/{channel_id}/status"]
    assert "delete" in paths["/api/v3/channels/{channel_id}"]


def test_archived_channel_is_terminal() -> None:
    assert ALLOWED_CHANNEL_TRANSITIONS["archived"] == set()
    assert "archived" in ALLOWED_CHANNEL_TRANSITIONS["active"]
    assert "active" in ALLOWED_CHANNEL_TRANSITIONS["paused"]
