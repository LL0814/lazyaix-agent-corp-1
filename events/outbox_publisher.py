"""Outbox publisher loop: polls pending outbox records and publishes them."""

from __future__ import annotations

import asyncio
import logging

from events.bus import EventBus
from events.outbox import OutboxStore
from events.schema import Event

logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(
        self,
        outbox: OutboxStore,
        poll_interval: float = 5.0,
        event_bus: EventBus | None = None,
    ):
        self._outbox = outbox
        self._poll_interval = poll_interval
        self._event_bus = event_bus
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                records = await self._outbox.poll_pending(limit=100)
                for record in records:
                    await self._publish(record)
            except Exception:
                logger.exception("OutboxPublisher loop error")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                pass

    async def _publish(self, record) -> None:
        try:
            if self._event_bus is not None:
                event = Event.from_dict(record.payload)
                await self._event_bus.publish(event)
            else:
                logger.info(
                    "Would publish outbox record %s to %s",
                    record.id,
                    record.topic,
                )
            await self._outbox.mark_published(record.id)
        except Exception as exc:
            logger.exception("Failed to publish outbox record %s", record.id)
            await self._outbox.mark_failed(record.id, str(exc))
