from __future__ import annotations

import asyncio
import json
import platform
import socket
from datetime import datetime, timezone
from typing import TypeAlias
from uuid import uuid4

from fastapi import Request

from zhiju.config import get_settings


ChangeEvent: TypeAlias = dict[str, object]


class RealtimeBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[ChangeEvent]]] = {}

    @staticmethod
    def _require_tenant_id(tenant_id: str) -> str:
        tenant_id = tenant_id.strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        return tenant_id

    def subscribe(self, *, tenant_id: str) -> asyncio.Queue[ChangeEvent]:
        tenant_id = self._require_tenant_id(tenant_id)
        queue: asyncio.Queue[ChangeEvent] = asyncio.Queue()
        self._subscribers.setdefault(tenant_id, set()).add(queue)
        return queue

    def unsubscribe(self, *, tenant_id: str, queue: asyncio.Queue[ChangeEvent]) -> None:
        tenant_id = self._require_tenant_id(tenant_id)
        subscribers = self._subscribers.get(tenant_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(tenant_id, None)

    @property
    def subscriber_count(self) -> int:
        return sum(len(subscribers) for subscribers in self._subscribers.values())

    async def publish(self, *, tenant_id: str, event: ChangeEvent) -> None:
        tenant_id = self._require_tenant_id(tenant_id)
        for queue in tuple(self._subscribers.get(tenant_id, ())):
            queue.put_nowait(event)


broker = RealtimeBroker()


def current_device_key() -> str:
    configured = get_settings().device_key.strip()
    return configured or f"{platform.system().lower()}:{socket.gethostname()}"


def realtime_stream_url() -> str:
    hub_url = get_settings().realtime_hub_url.strip().rstrip("/")
    return f"{hub_url}/api/v3/events/stream" if hub_url else "/api/v3/events/stream"


def build_change_event(request: Request) -> ChangeEvent:
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    path_parts = [part for part in route_path.split("/") if part and not part.startswith("{")]
    entity_key = next(
        (part for part in path_parts if part not in {"api", "v3", "outputs", "nodes", "copy-progress"}),
        "system",
    )
    entity_type = {
        "tasks": "operation_task",
        "work-orders": "work_order",
        "packages": "operation_package",
        "channels": "channel",
        "dramas": "drama",
        "schedules": "channel_schedule_entry",
        "skills": "skill",
        "integrations": "integration",
    }.get(entity_key, entity_key.replace("-", "_"))
    entity_id = next((value for key, value in request.path_params.items() if key.endswith("_id")), None)
    return {
        "event_id": str(uuid4()),
        "event": "data.changed",
        "method": request.method,
        "path": request.url.path,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "device_key": current_device_key(),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


def encode_sse(event: ChangeEvent) -> str:
    event_name = str(event.get("event") or "message")
    event_id = str(event.get("event_id") or "")
    return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def publish_change_event(*, tenant_id: str, event: ChangeEvent) -> None:
    await broker.publish(tenant_id=tenant_id, event=event)
