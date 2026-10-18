"""
When outbox event publish messge to RabbitMQ it sits there forever
tis consumer waits until mesage is arrived and then this deserialize the JSON and route to the Redis 
for websocket delivery
"""

import json
import aio_pika
import asyncio
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
        event_id = enevlope.get("event_id")
        payload = enevlope.get("payload",{})

        idempotency_key = f"processed_event:{event_id}" # check if this event was already processed by this consumer within last 24 hours

        already_processed = await redis_manager.redis.exists(idempotency_key)
        if already_processed:
            print(f"[{settings.SERVER_ID}] Duplicate event {event_id} safely ignored.")
            await message.ack()  # Acknowledge the message to RabbitMQ
            return

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


        await redis_manager.redis.set(idempotency_key, "1", ex=86400)  # Set key with 24-hour expiration

        # 3. Tell Rabbitmq it was successfully processed
        await message.ack()

    except Exception as e:
        
        print(f"[{settings.SERVER_ID}] Consumer error: {e}")
        # If it crashed, tell RabbitMQ we failed (NACK)

        # We need the event_id to track retries. If JSON parsing failed entirely, 
        # we can't extract an ID, so we must dead-letter it immediately.

        try:
            enevlope = json.loads(message.body.decode('utf-8'))
            event_id = enevlope.get("event_id")
        except json.JSONDecodeError:
            print(f"[{settings.SERVER_ID}] Fatal: Malformed JSON. Routing to DLQ.")
            await message.nack(requeue=False)
            return

        retry_key = f"retry_count:{event_id}"
        attempts = await redis_manager.redis.incr(retry_key)

        if attempts <= 3:
            print(f"[{settings.SERVER_ID}] Transient failure. Requeueing event {event_id} (Attempt {attempts}/3)")
            # set 24h experiation for retry count key
            if attempts == 1:
                await redis_manager.redis.expire(retry_key, 86400)

                await asyncio.sleep(1)  # Optional: small delay before requeueing
                await message.nack(requeue=True)  # Requeue the message for retry
        else:
            print(f"[{settings.SERVER_ID}] Event {event_id} failed {attempts} times. Routing to DLQ.")
            await message.nack(requeue=False) # trigger dlx

        


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