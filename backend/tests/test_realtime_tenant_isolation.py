import asyncio

import pytest
from fastapi.testclient import TestClient

from zhiju.app import app
from zhiju.realtime import RealtimeBroker


def test_tenant_event_reaches_only_its_tenant_subscribers() -> None:
    async def scenario() -> None:
        broker = RealtimeBroker()
        tenant_a = broker.subscribe(tenant_id="tenant-a")
        tenant_b = broker.subscribe(tenant_id="tenant-b")
        event = {"event": "data.changed", "entity_type": "operation_task"}

        await broker.publish(tenant_id="tenant-a", event=event)

        assert await tenant_a.get() == event
        assert tenant_b.empty()

    asyncio.run(scenario())


def test_unscoped_platform_event_cannot_reach_tenant_subscribers() -> None:
    async def scenario() -> None:
        broker = RealtimeBroker()
        tenant_a = broker.subscribe(tenant_id="tenant-a")
        tenant_b = broker.subscribe(tenant_id="tenant-b")

        with pytest.raises(ValueError, match="tenant_id"):
            await broker.publish(tenant_id="", event={"event": "platform.changed"})

        assert tenant_a.empty()
        assert tenant_b.empty()

    asyncio.run(scenario())


def test_anonymous_stream_rejects_client_supplied_tenant_header() -> None:
    response = TestClient(app).get(
        "/api/v3/events/stream",
        headers={"X-Tenant-ID": "tenant-a"},
    )

    assert response.status_code == 401


def test_browser_publish_endpoint_is_not_exposed() -> None:
    response = TestClient(app).post(
        "/api/v3/events/publish",
        json={"event": "data.changed"},
    )

    assert response.status_code == 404
