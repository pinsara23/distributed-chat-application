from ast import stmt
import asyncio
import json
from datetime import datetime
import aio_pika
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.outbox_events import OutboxEvent
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.core.config import settings
from app.schemas import event

async def process_outbox():

    """Background task that pushes pending outbox events to RabbitMQ."""
    print(f"[{settings.SERVER_ID}] Starting Outbox Publisher background task...")

    while True:

        try:
            # use short live db sessions for each pool
            async with AsyncSessionLocal() as session:
                #1. find all unpublished events in the outbox table
                stmt = select(OutboxEvent).where(OutboxEvent.publised_at == None).order_by(OutboxEvent.created_at)
                result = await session.execute(stmt)
                events = result.scalars().all()

                for event in events:
                    # 2. package into rabbitmq message
                    message = aio_pika.Message(
                        body=json.dumps(event.payload).encode('utf-8'),
                        message_id=str(event.event_id),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,# PERSISTENT - message will be written to disk and 
                                                                   # survive RabbitMQ restart
                    )

                    # 3. Publish to our Exchange using the event_type as the routing key
                    # E.g., event_type "message.created" matches our "message.*" binding
                 
                    if rabbitmq_manager.exchange:
                        await rabbitmq_manager.exchange.publish(
                            message=message,
                            routing_key=event.event_type,
                        )
                        print(f"[{settings.SERVER_ID}] Published Outbox Event {event.event_id} to RabbitMQ.")                  

            # 4. Mark the event as published in the outbox table
            if events:
                await session.commit()

        except asyncio.CancelledError:
            print(f"[{settings.SERVER_ID}] Outbox Publisher shutting down.")
            break
        except Exception as e:
            print(f"[{settings.SERVER_ID}] Outbox Publisher error: {e}")

        await asyncio.sleep(2) # Wait for 2 seconds before checking for new events again