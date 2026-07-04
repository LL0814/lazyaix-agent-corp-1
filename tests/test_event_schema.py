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
