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
        self.channel = await self.connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
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
    
    def is_connected(self) -> bool:
        return self.connection is not None and not self.connection.is_closed

    async def disconnect(self):
        """Close the channel and connection, ignoring errors from a dead broker."""
        for resource in (self.channel, self.connection):
            if resource is not None and not resource.is_closed:
                try:
                    await resource.close()
                except Exception:
                    pass
        self.channel = None
        self.connection = None
        self.exchange = None


rabbitmq_manager = RabbitMqConnectionManager()
