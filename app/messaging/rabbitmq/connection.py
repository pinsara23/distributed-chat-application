import asyncio
import aio_pika
from app.core.config import settings

class RabbitMqConnectionManager:
    def __init__(self):
        self.connection = None
        self.exchange = None
        self.channel = None

    async def connect(self):
        """establish robust connection that auto reconnect when failure"""
        self.connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        # channels actas isolated communication sessions over the single tcp channel
        self.channel = await self.connection.channel()
        print(f"[{settings.SERVER_ID}] Connected to RabbitMQ.") 

    async def setup_topology(self):
        """Declare the exchange, Queues and bindings"""
        if not self.channel:
            raise Exception("Cannot setup topology before connecting")

        # dead letter exchange for unprocessed messages
        dlx = await self.channel.declare_exchange(
           name="chat.dlx",
           type=aio_pika.ExchangeType.DIRECT,
           durable=True
        )
        dlq = await self.channel.declare_queue(
           name="chat.msg.dlq",
           durable=True,
        )

        await dlq.bind(
            exchange=dlx,
            routing_key="message.created"
        )
        # 1. declare the exchage
        self.exchange = await self.channel.declare_exchange(
            name="chat.events",
            type = aio_pika.ExchangeType.TOPIC,
            durable=True # make sure the exchange survives broker restarts
        )

        # 2. declare the main queuue
        queue = await self.channel.declare_queue(
            name="chat.message.queue",
            durable = True,
            arguments={
                "x-dead-letter-exchange": "chat.dlx"  # specify the dead letter exchange for unprocessed messages
            }
        )

        # 3.Bind them together with routing key
        await queue.bind(
            exchange=self.exchange, 
            routing_key="message.*"
        )

        print(f"[{settings.SERVER_ID}] RabbitMQ topology setup complete (DLQ active).")
    
    async def disconnect(self):
       """Colse the channels and connections"""
       if self.channel and not self.channel.is_closed:
        await self.channel.close()
       
       if self.connection and not self.connection.is_closed:
        await self.connection.close() 


rabbitmq_manager = RabbitMqConnectionManager()
