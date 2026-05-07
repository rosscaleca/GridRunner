"""Smoke test for the /api/events SSE endpoint."""

import asyncio

import pytest

from backend.main import app


# ---------------------------------------------------------------------------
# Route registration test
# ---------------------------------------------------------------------------

def test_events_route_is_registered():
    """The /api/events/ GET route must be registered in the app."""
    routes = [(r.path, list(r.methods)) for r in app.routes if hasattr(r, "methods")]
    assert ("/api/events/", ["GET"]) in routes, (
        "/api/events/ GET not found in registered routes"
    )


# ---------------------------------------------------------------------------
# Generator-level tests (unit-test the SSE event_generator directly)
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock
from backend.api.events import stream_events
from backend import events as events_module


@pytest.fixture(autouse=True)
def clean_subscribers():
    """Reset subscribers between tests so state doesn't leak."""
    events_module._subscribers.clear()
    yield
    events_module._subscribers.clear()


async def _collect_first_n(gen, n: int) -> list[dict]:
    """Drive an async generator and collect the first n items."""
    items = []
    async for item in gen:
        items.append(item)
        if len(items) >= n:
            break
    return items


async def test_event_generator_yields_connected_frame_first():
    """The generator's first yield must be event='connected'."""
    # Build a fake Request whose is_disconnected() never fires during the test.
    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    response = await stream_events(request=mock_request, _=None)
    # EventSourceResponse wraps an async generator; pull it out.
    gen = response.body_iterator

    first = await gen.__anext__()
    assert first["event"] == "connected"
    assert first["data"] == "{}"

    # Clean up the subscriber the generator registered.
    await gen.aclose()


async def test_event_generator_delivers_queued_event():
    """After connected, emitting an event delivers it through the generator."""
    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    response = await stream_events(request=mock_request, _=None)
    gen = response.body_iterator

    # Consume the connected frame.
    connected = await gen.__anext__()
    assert connected["event"] == "connected"

    # Emit an event; the generator should pick it up on the next iteration.
    events_module.emit("runs.changed")

    second = await gen.__anext__()
    assert second["event"] == "runs.changed"
    assert second["data"] == "{}"

    await gen.aclose()


async def test_event_generator_registers_and_removes_subscriber():
    """Generator registers a queue on entry and removes it on close."""
    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    assert len(events_module._subscribers) == 0

    response = await stream_events(request=mock_request, _=None)
    gen = response.body_iterator

    # Advance past the connected frame so the generator is running inside the try block.
    await gen.__anext__()
    assert len(events_module._subscribers) == 1

    await gen.aclose()
    assert len(events_module._subscribers) == 0


async def test_event_generator_content_type():
    """EventSourceResponse must advertise text/event-stream."""
    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    response = await stream_events(request=mock_request, _=None)
    ct = response.media_type
    assert ct is not None and "text/event-stream" in ct

    await response.body_iterator.aclose()
