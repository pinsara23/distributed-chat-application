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

class RedisPubSubManager:
    def __init__(self):
        self.redis_client = None
        self.pubsub = None  # This must exist!

    async def connect(self):
        # 1. Connect to the main Redis client
        self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        # 2. Initialize the pubsub attribute (THIS IS WHAT CRASHED YOUR APP)
        self.pubsub = self.redis_client.pubsub()
        print(f"[{settings.SERVER_ID}] connected to redis.")

    async def disconnect(self):
        if self.pubsub:
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()

    async def publish_message(self, target_user_id: int, message_payload: dict):
        """Publishes a message payload to a specific user's Redis channel."""
        channel = f"chat:user:{target_user_id}"
        await self.redis_client.publish(channel, json.dumps(message_payload))
        print(f"[{settings.SERVER_ID}] Published event to {channel}")

    async def subscribe_and_listen(self, local_websocket_manager):
        """Listens for cross-server messages and attempts local delivery."""
        try:
            print(f"[{settings.SERVER_ID}] Attempting to start Redis listener...")
            
            await self.pubsub.psubscribe("chat:user:*")
            print(f"[{settings.SERVER_ID}] Subscribed to cross-server chat channels.")
            
            async for message in self.pubsub.listen():
                print(f"[{settings.SERVER_ID}] RAW REDIS EVENT: {message}") 
                
                if message["type"] == "pmessage":
                    try:
                        channel = message["channel"]
                        data = json.loads(message["data"])
                        
                        target_user_id = int(channel.split(":")[-1])
                        await local_websocket_manager.send_personal_message(json.dumps(data), target_user_id)
                    except Exception as inner_e:
                        print(f"[{settings.SERVER_ID}] ERROR PARSING MESSAGE: {inner_e}")
                        
        except asyncio.CancelledError:
            print(f"[{settings.SERVER_ID}] Redis listener shutting down.")
        except Exception as fatal_e:
            print(f"[{settings.SERVER_ID}] FATAL LISTENER CRASH: {fatal_e}")

# Ensure your global instance matches the name used in main.py and chat.py
redis_manager = RedisPubSubManager()



"""
Key Concepts in this Code:
User-Specific Channels: We are using channels like chat:user:35. 
This prevents every server from having to process every single message in the system. 
Redis handles the routing efficiently.

The Listener Loop: async for message in self.pubsub.listen() is an infinite asynchronous loop. 
It runs quietly in the background without blocking the FastAPI HTTP endpoints.

Decoupled Delivery: The subscribe_and_listen function accepts local_websocket_manager as an argument. 
This connects the Redis network layer strictly to the local memory state.
"""
