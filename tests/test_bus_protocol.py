import pytest

from events.bus import EventBus
from events.schema import Event


class DummyBus:
    async def publish(self, event: Event) -> None:
        pass

    def subscribe(self, event_type, handler):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


def test_protocol_satisfied():
    bus: EventBus = DummyBus()
    assert bus is not None
