"""Regression test for the leaked-concurrency-slot bug.

When a caller stopped the mic mid-conversation, Pipecat's FastAPI transport
fired on_client_disconnected but never injected an EndFrame, so runner.run(task)
kept awaiting (Gemini Live upstream still open) and the call held its global
concurrency slot until the ~15-min session cap. A few mic-stops in a row used up
all MAX_CONCURRENT_CALLS slots → every new tap got "all lines busy" and queued
forever.

The fix wires an on_client_disconnected handler that cancels the pipeline task,
so runner.run returns immediately and the slot's release runs at once. This test
locks that wiring in place.
"""

import asyncio

from unittest.mock import AsyncMock, MagicMock

from main import _cancel_pipeline_on_disconnect


def _fake_transport():
    """A transport stand-in that records event handlers like Pipecat's does."""
    handlers: dict = {}
    transport = MagicMock()

    def event_handler(name):
        def register(fn):
            handlers[name] = fn
            return fn

        return register

    transport.event_handler.side_effect = event_handler
    return transport, handlers


def test_client_disconnect_cancels_the_pipeline_task():
    transport, handlers = _fake_transport()
    task = MagicMock()
    task.cancel = AsyncMock()

    _cancel_pipeline_on_disconnect(transport, task, ip="1.2.3.4")

    # The handler must be registered for the exact event Pipecat fires on hang-up.
    assert "on_client_disconnected" in handlers

    # Simulating the browser hanging up must cancel the task — that's what lets
    # runner.run() return and the concurrency slot be released right away.
    asyncio.run(handlers["on_client_disconnected"](transport, object()))
    task.cancel.assert_awaited_once()


def test_silent_calls_end_after_the_idle_limit():
    """A caller who connects and never speaks shouldn't hold one of the few
    voice lines for Pipecat's default five minutes."""
    from pipecat.pipeline.pipeline import Pipeline

    import main
    from config import VOICE_IDLE_SECONDS

    task = main.build_task(Pipeline([]))
    assert task._idle_timeout_secs == VOICE_IDLE_SECONDS <= 120
    assert "on_idle_timeout" in task._event_handlers
