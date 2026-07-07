"""Outbox publisher loop: polls pending outbox records and publishes them."""

from __future__ import annotations

import asyncio
import logging

from events.outbox import OutboxStore

logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(
        self,
        outbox: OutboxStore,
        poll_interval: float = 5.0,
    ):
        self._outbox = outbox
        self._poll_interval = poll_interval
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
        # Stub: real Kafka publish is implemented in Task 8.
        logger.info(
            "Would publish outbox record %s to %s", record.id, record.topic
        )
        await self._outbox.mark_published(record.id)
