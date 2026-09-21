"""
Why Pub/Sub?
Because Server 1 has no access to Server 3's memory, 
it cannot deliver a message to Bob directly. Instead, Server 1 will act as a Publisher and shout into Redis: 
"I have a message for User ID 35!"

Simultaneously, Server 1, Server 2, and Server 3 are all acting as Subscribers, 
constantly listening to Redis. When they hear the shout, they check their own local memory. 
Only the server that currently holds Bob's WebSocket will actually push the message to him.
"""

import json
import asyncio
import redis.asyncio as redis
from app.core.config import settings

class RedisPublisherManager:
    def __init__(self):
        self.redis_client = None
        self.pubsun = None

    async def connect(self):

        # decode_responses=True      ensures we get strings back from Redis, not raw bytes
        self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pubsun = self.redis_client.pubsub()
        print(f"[{settings.SERVER_ID}] connected to redis.")


    async def disconnect(self):
        if self.pubsun:
            await self.pubsun.close()
        if  self.redis_client:
            await self.redis_client.close()


    async def subscribe_and_listen(self, target_user_id: int, message_payload: dict):
        """Publishes a message payload to a specific user's Redis channel."""

        channel = f"chat:user{target_user_id}"
        await self.redis_client.publish(channel, json.dumps(message_payload))
        print(f"[{settings.SERVER_ID}] Published event to {channel}")


    async def subscribe_and_listen(self, local_websocket_manager):
        """Listens for cross-server messages and attempts local delivery."""
        # Listen to all channels that match the pattern "chat:user*"

        await self.pubsun.psubscribe("chat:user*")
        print(f"[{settings.SERVER_ID}] Subscribed to cross-server chat channels.")

        try:
            # continuously wait for new messages pushed by Redis
            async for message in self.pubsun.listen():
                if message["type"] == "pmessage":
                    channel = message["channel"]
                    data = json.loads(message["data"])

                    # Extract target user ID from the channel string (e.g., "chat:user:35" -> 35)
                    target_user_id = int(channel.split(":")[-1])

                    # Pass the message to the local WebSocket manager.
                    # It will silently ignore the message if the user is NOT connected to this specific server instance.

                    await local_websocket_manager.send_personal_message(json.dumps(data), target_user_id) # implemet in future

        except asyncio.CancelledError:
            print(f"[{settings.SERVER_ID}] Redis listener shutting down.")

redis_manager = RedisPublisherManager()
