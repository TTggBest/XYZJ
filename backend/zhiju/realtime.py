from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
from datetime import datetime, timezone
from urllib import request as urllib_request
from uuid import uuid4

from fastapi import Request

from zhiju.config import get_settings


logger = logging.getLogger(__name__)


class RealtimeBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, object]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: dict[str, object]) -> None:
        for queue in tuple(self._subscribers):
            queue.put_nowait(event)


broker = RealtimeBroker()


def current_device_key() -> str:
    configured = get_settings().device_key.strip()
    return configured or f"{platform.system().lower()}:{socket.gethostname()}"


def realtime_stream_url() -> str:
    hub_url = get_settings().realtime_hub_url.strip().rstrip("/")
    return f"{hub_url}/api/v3/events/stream" if hub_url else "/api/v3/events/stream"


def build_change_event(request: Request) -> dict[str, object]:
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


def encode_sse(event: dict[str, object]) -> str:
    event_name = str(event.get("event") or "message")
    event_id = str(event.get("event_id") or "")
    return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _post_to_hub(url: str, event: dict[str, object]) -> None:
    body = json.dumps(event, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        f"{url.rstrip('/')}/api/v3/events/publish",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=2) as response:
        response.read()


async def publish_change_event(event: dict[str, object]) -> None:
    settings = get_settings()
    hub_url = settings.realtime_hub_url.strip()
    if not hub_url or settings.device_role == "studio":
        await broker.publish(event)
        return
    try:
        await asyncio.to_thread(_post_to_hub, hub_url, event)
    except Exception as exc:
        logger.warning("Realtime event publish failed: %s", exc)
