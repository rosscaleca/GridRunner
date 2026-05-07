"""SSE endpoint streaming domain-event notifications to the frontend."""

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from .. import events
from .auth import require_auth


router = APIRouter()


@router.get("/")
async def stream_events(
    request: Request,
    _: None = Depends(require_auth),
):
    """Long-lived SSE stream of coarse domain-event notifications.

    Frame format: `event: <type>\\ndata: {}\\n\\n` where <type> is one of
    runs.changed, scripts.changed, categories.changed, settings.changed,
    plus an initial 'connected' frame. Connection keepalive (a periodic
    comment frame) is handled by sse-starlette's built-in ping (default 15s).
    """
    async def event_generator() -> AsyncGenerator[dict, None]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        events.add_subscriber(queue)
        try:
            yield {"event": "connected", "data": "{}"}
            while True:
                if await request.is_disconnected():
                    return
                event_type = await queue.get()
                yield {"event": event_type, "data": "{}"}
        finally:
            events.remove_subscriber(queue)

    return EventSourceResponse(event_generator())
