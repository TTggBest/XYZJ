import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.realtime import RealtimeBroker


def test_realtime_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/api/v3/realtime/config" in paths
    assert "/api/v3/events/stream" in paths
    assert "/api/v3/events/publish" in paths


def test_realtime_config_uses_local_stream_by_default() -> None:
    response = TestClient(app).get("/api/v3/realtime/config")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["stream_url"] == "/api/v3/events/stream"
    assert isinstance(response.json()["subscriber_count"], int)


def test_broker_broadcasts_to_each_subscriber() -> None:
    async def scenario() -> None:
        broker = RealtimeBroker()
        first = broker.subscribe()
        second = broker.subscribe()
        assert broker.subscriber_count == 2
        event = {"event": "data.changed", "entity_type": "operation_task"}

        await broker.publish(event)

        assert await first.get() == event
        assert await second.get() == event
        broker.unsubscribe(first)
        broker.unsubscribe(second)
        assert broker.subscriber_count == 0

    asyncio.run(scenario())


def test_background_tabs_release_their_sse_connection() -> None:
    app_source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'document.visibilityState !== "visible"' in app_source
    assert 'document.addEventListener("visibilitychange"' in app_source
    assert 'window.addEventListener("pagehide"' in app_source
    assert "closeRealtime" in app_source
