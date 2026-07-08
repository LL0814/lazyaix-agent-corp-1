from __future__ import annotations

import os

import pytest

from events.kafka_event_bus import KafkaEventBus
from events.schema import Event, EventType


@pytest.fixture
def kafka_bootstrap():
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap:
        pytest.skip("KAFKA_BOOTSTRAP_SERVERS not set")
    return bootstrap


@pytest.mark.asyncio
async def test_kafka_publish_subscribe(kafka_bootstrap):
    import asyncio
    import uuid

    bus = KafkaEventBus(
        bootstrap_servers=kafka_bootstrap,
        client_id="test",
        consumer_group=f"test-group-{uuid.uuid4().hex}",
        topic_prefix="test_",
    )
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe(EventType.TASK_READY, handler)
    await bus.start()

    try:
        event = Event(
            event_id="e1",
            event_type=EventType.TASK_READY,
            trace_id="t1",
            workflow_id="wf1",
            task_id="t1",
        )
        await bus.publish(event)
        await asyncio.sleep(1)
        assert any(e.event_id == "e1" and e.task_id == "t1" for e in received)
    finally:
        await bus.stop()
