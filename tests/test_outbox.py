from __future__ import annotations

import pytest

from events.outbox import InMemoryOutboxStore
from events.schema import Event, EventType


@pytest.mark.asyncio
async def test_in_memory_outbox_enqueue_and_poll():
    store = InMemoryOutboxStore()
    event = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
    )
    await store.enqueue(event, topic="task.ready", key="wf1")
    pending = await store.poll_pending(limit=10)
    assert len(pending) == 1
    assert pending[0].topic == "task.ready"
    assert pending[0].event_id == "e1"


@pytest.mark.asyncio
async def test_in_memory_outbox_mark_published():
    store = InMemoryOutboxStore()
    event = Event(
        event_id="e2",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
    )
    await store.enqueue(event, topic="task.ready")
    pending = await store.poll_pending(limit=10)
    await store.mark_published(pending[0].id)
    pending_after = await store.poll_pending(limit=10)
    assert len(pending_after) == 0


@pytest.mark.asyncio
async def test_in_memory_outbox_mark_failed():
    store = InMemoryOutboxStore()
    event = Event(
        event_id="e3",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
    )
    await store.enqueue(event, topic="task.ready")
    pending = await store.poll_pending(limit=10)
    await store.mark_failed(pending[0].id, error="boom")
    pending_after = await store.poll_pending(limit=10)
    assert len(pending_after) == 0
