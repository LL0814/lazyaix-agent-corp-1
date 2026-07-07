"""Event JSON serialization and deserialization."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from events.schema import Event


def event_to_json(event: Event) -> bytes:
    """Serialize an Event to JSON bytes."""
    return json.dumps(event.to_dict(), default=_json_default).encode("utf-8")


def event_from_json(data: bytes) -> Event:
    """Deserialize JSON bytes to an Event."""
    d = json.loads(data.decode("utf-8"))
    return Event.from_dict(d)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
