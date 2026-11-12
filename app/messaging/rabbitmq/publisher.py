import asyncio
import json
from datetime import datetime
import aio_pika
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.outbox_events import OutboxEvent
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.core.config import settings


async def publish_outbox_batch(batch_size: int = 100) -> int:
    """Claim and publish one batch while holding its database transaction."""
    if rabbitmq_manager.exchange is None:
        raise RuntimeError("RabbitMQ exchange is not initialized.")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            events = result.scalars().all()

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
                event.published_at = datetime.utcnow()

            return len(events)


async def process_outbox():
    print(f"[{settings.SERVER_ID}] Starting Outbox Publisher background task...")
    
    while True:
        try:
            published_count = await publish_outbox_batch()
            if published_count:
                print(f"[{settings.SERVER_ID}] Published {published_count} outbox event(s).")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[{settings.SERVER_ID}] Outbox Publisher error: {e}")
        
        await asyncio.sleep(2)