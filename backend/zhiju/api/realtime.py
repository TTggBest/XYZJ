from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from zhiju.auth_context import Principal, get_current_principal
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


@router.get("/events/stream")
async def get_event_stream(
    request: Request,
    _principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    principal = request.state.principal
    tenant_id = principal.tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="请先选择主账号")

    async def events() -> AsyncIterator[str]:
        queue = broker.subscribe(tenant_id=tenant_id)
        try:
            yield encode_sse({"event": "connected", "event_id": "connected"})
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield encode_sse(event)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broker.unsubscribe(tenant_id=tenant_id, queue=queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
