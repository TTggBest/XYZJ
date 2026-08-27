from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from zhiju.config import get_settings
from zhiju.database import database_router
from zhiju.realtime import broker, encode_sse, realtime_stream_url


router = APIRouter(prefix="/v3", tags=["realtime"])


@router.get("/realtime/config")
def get_realtime_config() -> dict[str, object]:
    settings = get_settings()
    return {
        "enabled": True,
        "device_role": settings.device_role,
        "environment": database_router.active_environment,
        "stream_url": realtime_stream_url(),
        "subscriber_count": broker.subscriber_count,
    }


@router.post("/events/publish")
async def post_event(event: dict[str, object]) -> dict[str, bool]:
    await broker.publish(event)
    return {"published": True}


@router.get("/events/stream")
async def get_event_stream(request: Request) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        queue = broker.subscribe()
        try:
            yield encode_sse({"event": "connected", "event_id": "connected"})
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield encode_sse(event)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        },
    )
