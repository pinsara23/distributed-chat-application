"""
When outbox event publish messge to RabbitMQ it sits there forever
tis consumer waits until mesage is arrived and then this deserialize the JSON and route to the Redis 
for websocket delivery
"""

import json
import aio_pika
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.core.config import settings

async def  on_message(message:aio_pika.abc.AbstractIncomingMessage):
    # Callback function when fires new message arrives to the queue

    try:
        # 1. Parse the JSON enevlop
        enevlope = json.loads(message.body.decode('utf-8'))
        event_type= enevlope.get("event_type")
        event_id = enevlope.get("event_id")

        print(f"[{settings.SERVER_ID}] Consumer received '{event_type}' (ID: {event_id})")

        # 2. Process the event

        # do in next step


        # 3. Tell Rabbitmq it was successfully processed
        await message.ack()

    except Exception as e:
        print(f"[{settings.SERVER_ID}] Consumer error: {e}")
        # If it crashed, tell RabbitMQ we failed (NACK)

        await message.nack(requeue=False)


    async def start_consumer():
        """ Attach the callback to the RabbitmQ Queue"""
        print(f"[{settings.SERVER_ID}] Starting RabbitMQ Consumer...")

        if not rabbitmq_manager.channel:
            raise RuntimeError("RabbitMQ channel is not initialized.")

        queue = await rabbitmq_manager.channel.get_queue("chat.message.queue")