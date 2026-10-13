"""
When outbox event publish messge to RabbitMQ it sits there forever
tis consumer waits until mesage is arrived and then this deserialize the JSON and route to the Redis 
for websocket delivery
"""

import json
import aio_pika
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.core.config import settings
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.message import Message
from app.core.encryption import encryption_service
from app.messaging.redis_client import redis_manager

async def  on_message(message:aio_pika.abc.AbstractIncomingMessage):
    # Callback function when fires new message arrives to the queue

    try:
        # 1. Parse the JSON enevlop
        enevlope = json.loads(message.body.decode('utf-8'))
        event_type= enevlope.get("event_type")
        payload = enevlope.get("payload",{})

        print(f"[{settings.SERVER_ID}] Consumer processing '{event_type}'...")
        
        # 2. Process the event

        if event_type == "message.created":
            # 1. extract the data from payload
            message_uuid = payload.get("message_id")
            target_user_id = payload.get("target_user_id")

            # 2. fetch the encrypted message from the database
            async with AsyncSessionLocal() as session:
                stmt = select(Message).where(Message.message_uuid == message_uuid)
                result = await session.execute(stmt)
                db_message = result.scalar_one_or_none()

                if db_message:
                    plaintext = encryption_service.decrypt(db_message.cipertext, db_message.nonce)

                    ws_payload = {
                        "id": db_message.id,
                        "message_uuid": str(db_message.message_uuid),
                        "conversation_id": db_message.conversation_id,
                        "sender_id": db_message.sender_id,
                        "content": plaintext,
                        "created_at": db_message.created_at.isoformat()
                    }

                    # hends off to redis
                    await redis_manager.publish_message(target_user_id, ws_payload)
                    print(f"[{settings.SERVER_ID}] Pushed to Redis for User {target_user_id}")


        # 3. Tell Rabbitmq it was successfully processed
        await message.ack()

    except Exception as e:
        print(f"[{settings.SERVER_ID}] Consumer error: {e}")
        # If it crashed, tell RabbitMQ we failed (NACK)

        await message.nack(requeue=False)


async def start_consumer():
    print(f"[{settings.SERVER_ID}] Starting RabbitMQ Consumer...")
    
    if not rabbitmq_manager.channel:
        raise Exception("RabbitMQ channel not initialized.")
    
    # --- STEP 11: QoS (Quality of Service) ---
    # PREFETCH: Do not give this specific consumer more than 10 un-ACKed messages at a time.
    # This prevents RAM spikes and ensures fair load balancing across Server 1, 2, and 3.
    await rabbitmq_manager.channel.set_qos(prefetch_count=10)
    
    queue = await rabbitmq_manager.channel.get_queue("chat.message.queue")
    await queue.consume(on_message)