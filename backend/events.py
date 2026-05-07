"""In-memory pub/sub for SSE event broadcasting.

Single-process desktop app, so subscribers are tracked in a module-level list.
Each subscriber owns an asyncio.Queue that the SSE endpoint pulls events from.
emit() is non-blocking: if a subscriber's queue is full, the event is dropped
for that subscriber rather than blocking the publisher.
"""

import asyncio


_subscribers: list[asyncio.Queue] = []


def emit(event_type: str) -> None:
    """Push an event type string to every subscriber queue.

    Non-blocking. Drops the event for any subscriber whose queue is full
    (e.g., a slow or stuck consumer) rather than blocking the publisher.
    """
    for q in _subscribers:
        try:
            q.put_nowait(event_type)
        except asyncio.QueueFull:
            pass


def add_subscriber(q: asyncio.Queue) -> None:
    """Register a queue to receive future emit() calls."""
    _subscribers.append(q)


def remove_subscriber(q: asyncio.Queue) -> None:
    """Stop delivering events to this queue. No-op if queue not registered."""
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
