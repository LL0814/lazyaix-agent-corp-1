"""Kafka-based EventBus implementation."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from events.bus import EventBus
from events.event_store import EventStore
from events.schema import Event
from events.serde import event_from_json, event_to_json

logger = logging.getLogger(__name__)


class KafkaEventBus:
    """EventBus backed by Apache Kafka."""

    def __init__(
        self,
        bootstrap_servers: str,
        client_id: str,
        consumer_group: str,
        topic_prefix: str = "",
        event_store: EventStore | None = None,
    ):
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._consumer_group = consumer_group
        self._topic_prefix = topic_prefix
        self._event_store = event_store
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._producer: AIOKafkaProducer | None = None
        self._consumers: list[AIOKafkaConsumer] = []
        self._consumer_tasks: list[asyncio.Task] = []

    def _topic(self, event_type: str) -> str:
        return f"{self._topic_prefix}{event_type.replace('.', '_')}"

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        if self._event_store is not None:
            await self._event_store.append(event)
        if self._producer is None:
            raise RuntimeError("KafkaEventBus not started")
        topic = self._topic(event.event_type)
        key = (
            (event.task_id or event.workflow_id).encode("utf-8")
            if event.task_id or event.workflow_id
            else None
        )
        await self._producer.send_and_wait(
            topic, key=key, value=event_to_json(event)
        )

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            client_id=f"{self._client_id}-producer",
            value_serializer=lambda v: v,
        )
        await self._producer.start()

        for event_type, handlers in self._handlers.items():
            topic = self._topic(event_type)
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=f"{self._consumer_group}-{event_type}",
                client_id=f"{self._client_id}-consumer-{event_type}",
                value_deserializer=lambda v: v,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                max_poll_interval_ms=300000,
                session_timeout_ms=45000,
                heartbeat_interval_ms=15000,
            )
            await consumer.start()
            self._consumers.append(consumer)
            self._consumer_tasks.append(
                asyncio.create_task(
                    self._consume(event_type, consumer, handlers)
                )
            )

    async def _consume(
        self,
        event_type: str,
        consumer: AIOKafkaConsumer,
        handlers: list[Callable[[Event], Awaitable[None]]],
    ) -> None:
        try:
            async for msg in consumer:
                try:
                    event = event_from_json(msg.value)
                    for handler in handlers:
                        await handler(event)
                except Exception:
                    logger.exception(
                        "Kafka handler error for event_type=%s", event_type
                    )
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        for t in self._consumer_tasks:
            t.cancel()
        await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        for c in self._consumers:
            await c.stop()
        if self._producer is not None:
            await self._producer.stop()
