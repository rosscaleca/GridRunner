"""Tests for backend.events in-memory pub/sub."""

import asyncio

import pytest

from backend import events


@pytest.fixture(autouse=True)
def clean_subscribers():
    """Reset the module-level subscriber list before/after each test."""
    events._subscribers.clear()
    yield
    events._subscribers.clear()


def test_emit_with_no_subscribers_does_not_raise():
    events.emit("runs.changed")  # should be a no-op


def test_emit_pushes_to_single_subscriber():
    q = asyncio.Queue()
    events.add_subscriber(q)
    events.emit("runs.changed")
    assert q.get_nowait() == "runs.changed"


def test_emit_pushes_to_multiple_subscribers():
    q1 = asyncio.Queue()
    q2 = asyncio.Queue()
    events.add_subscriber(q1)
    events.add_subscriber(q2)
    events.emit("scripts.changed")
    assert q1.get_nowait() == "scripts.changed"
    assert q2.get_nowait() == "scripts.changed"


def test_emit_drops_when_subscriber_queue_full_without_raising():
    q = asyncio.Queue(maxsize=1)
    events.add_subscriber(q)
    events.emit("runs.changed")
    events.emit("runs.changed")  # would block; emit() must drop instead
    # First event still present, second dropped
    assert q.get_nowait() == "runs.changed"
    assert q.empty()


def test_remove_subscriber_stops_delivery():
    q = asyncio.Queue()
    events.add_subscriber(q)
    events.remove_subscriber(q)
    events.emit("runs.changed")
    assert q.empty()


def test_remove_unknown_subscriber_is_noop():
    q = asyncio.Queue()
    events.remove_subscriber(q)  # never added; should not raise
