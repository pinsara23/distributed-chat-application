import asyncio
import json
from datetime import datetime
import aio_pika
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update  # NEW: import update

from app.core.database import AsyncSessionLocal
from app.models.outbox_events import OutboxEvent
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.core.config import settings

async def process_outbox():
    print(f"[{settings.SERVER_ID}] Starting Outbox Publisher background task...")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(OutboxEvent).where(OutboxEvent.published_at == None).order_by(OutboxEvent.created_at)
                result = await session.execute(stmt)
                events = result.scalars().all()

                published_ids = [] # NEW: Keep track of what we successfully sent

                for event in events:
                    message = aio_pika.Message(
                        body=json.dumps(event.payload).encode('utf-8'),
                        message_id=str(event.event_id),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT 
                    )
                    
                    if rabbitmq_manager.exchange:
                        await rabbitmq_manager.exchange.publish(message, routing_key=event.event_type)
                        print(f"[{settings.SERVER_ID}] Published Outbox Event {event.event_id} to RabbitMQ.")
                        
                        # Add to our success list instead of modifying the object directly
                        published_ids.append(event.id) 
                
                # NEW: Explicit Bulk Update to the database
                if published_ids:
                    update_stmt = (
                        update(OutboxEvent)
                        .where(OutboxEvent.id.in_(published_ids))
                        .values(published_at=datetime.utcnow())
                    )
                    await session.execute(update_stmt)
                    await session.commit()
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[{settings.SERVER_ID}] Outbox Publisher error: {e}")
        
        await asyncio.sleep(2)