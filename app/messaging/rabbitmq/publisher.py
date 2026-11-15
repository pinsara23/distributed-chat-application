"""Transactional-outbox publisher.

Events are written to ``outbox_events`` in the same transaction as the message.
This background task relays them to RabbitMQ with at-least-once delivery:

1. CLAIM   short transaction: lease a batch of unpublished rows
           (``FOR UPDATE SKIP LOCKED`` + ``locked_until``), then commit.
2. PUBLISH no database transaction or row lock is held while talking to
           RabbitMQ; publisher confirms tell us the broker has the message.
3. MARK    set ``published_at`` per event once it is confirmed.

If a server dies between 2 and 3 the lease expires and another server
re-publishes; the consumer deduplicates by event_id.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import aio_pika
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.models.outbox_events import OutboxEvent

LEASE_SECONDS = 30
POLL_INTERVAL_SECONDS = 2


@dataclass(frozen=True)
class ClaimedEvent:
    id: int
    event_id: object
    event_type: str
    payload: dict


async def _claim_batch(batch_size: int) -> list[ClaimedEvent]:
    """Lease up to `batch_size` publishable events. Commits immediately."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .where(
                    (OutboxEvent.locked_until.is_(None))
                    | (OutboxEvent.locked_until < now)
                )
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            rows = result.scalars().all()
            lease = now + timedelta(seconds=LEASE_SECONDS)
            claimed = []
            for row in rows:
                row.locked_until = lease
                claimed.append(
                    ClaimedEvent(row.id, row.event_id, row.event_type, row.payload)
                )
            return claimed


async def _mark_published(row_id: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == row_id)
            .values(published_at=datetime.utcnow(), locked_until=None)
        )
        await session.commit()


async def _release(row_ids: list[int]) -> None:
    """Give unpublished claims back so they are retried without waiting for the lease."""
    if not row_ids:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(row_ids), OutboxEvent.published_at.is_(None))
            .values(locked_until=None)
        )
        await session.commit()


async def publish_outbox_batch(batch_size: int = 100) -> int:
    """Claim, publish and mark one batch. Returns how many were published."""
    if rabbitmq_manager.exchange is None:
        raise RuntimeError("RabbitMQ exchange is not initialized.")

    events = await _claim_batch(batch_size)
    published = 0

    try:
        for event in events:
            message = aio_pika.Message(
                body=json.dumps(event.payload).encode("utf-8"),
                message_id=str(event.event_id),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            # publisher_confirms and on_return_raises are enabled on the
            # channel, so this await fails for a NACK or unroutable event.
            await rabbitmq_manager.exchange.publish(
                message,
                routing_key=event.event_type,
                mandatory=True,
            )
            await _mark_published(event.id)
            published += 1
    except BaseException:
        await asyncio.shield(_release([e.id for e in events[published:]]))
        raise

    return published


async def process_outbox():
    print(f"[{settings.SERVER_ID}] Starting Outbox Publisher background task...")

    while True:
        try:
            published_count = await publish_outbox_batch()
            if published_count:
                print(f"[{settings.SERVER_ID}] Published {published_count} outbox event(s).")
                continue  # more may be waiting: drain before sleeping
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[{settings.SERVER_ID}] Outbox Publisher error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
