from __future__ import annotations

import pytest

from events.event_store import InMemoryEventStore
from events.schema import Event, EventType


@pytest.mark.asyncio
async def test_in_memory_event_store_appends_events():
    store = InMemoryEventStore()
    event = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
    )
    await store.append(event)
    assert len(store._events) == 1
    assert store._events[0].event_id == "e1"
