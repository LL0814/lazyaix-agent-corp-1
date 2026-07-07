from datetime import datetime, timezone

from events.schema import Event, EventType


def test_event_creation():
    e = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="tr-1",
        workflow_id="wf-1",
        task_id="t1",
        target_capability="writer",
    )
    assert e.event_type == "task.ready"
    assert e.target_capability == "writer"
    assert e.payload == {}


def test_event_has_new_fields():
    e = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
        task_id="task1",
        parent_event_id="e0",
        aggregate_id="wf1",
        priority="high",
    )
    assert e.parent_event_id == "e0"
    assert e.aggregate_id == "wf1"
    assert e.priority == "high"


def test_event_round_trip_dict():
    now = datetime.now(timezone.utc)
    e = Event(
        event_id="e1",
        event_type=EventType.TASK_READY,
        trace_id="t1",
        workflow_id="wf1",
        task_id="task1",
        timestamp=now,
        payload={"instructions": "do it"},
        metadata={"retry_count": 1},
    )
    d = e.to_dict()
    e2 = Event.from_dict(d)
    assert e2.event_id == e.event_id
    assert e2.timestamp == now
    assert e2.payload == e.payload
    assert e2.metadata == e.metadata
