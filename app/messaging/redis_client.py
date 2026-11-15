"""Redis Pub/Sub fan-out between chat servers.

Server 1 cannot reach a WebSocket held by Server 3, so it publishes
"message for user 35" to Redis. Every server subscribes to every user channel
(``chat:user:*``) and only the one that holds that user's socket delivers it.
"""

import asyncio
import json

import redis.asyncio as redis

from app.core.config import settings

CHANNEL_PATTERN = "chat:user:*"
RESUBSCRIBE_MIN_DELAY = 1.0
RESUBSCRIBE_MAX_DELAY = 30.0


class RedisPubSubManager:
    def __init__(self):
        self.redis = None
        self.pubsub = None

    async def connect(self):
        # health_check_interval makes redis-py PING idle connections, so a
        # silently dead subscriber connection is noticed and re-established.
        self.redis = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            health_check_interval=15,
        )
        print(f"[{settings.SERVER_ID}] connected to redis.")

    async def disconnect(self):
        if self.pubsub:
            await self.pubsub.aclose()
            self.pubsub = None
        if self.redis:
            await self.redis.aclose()

    async def publish_message(self, target_user_id: int, message_payload: dict):
        """Publish a message payload to a specific user's Redis channel."""
        if self.redis is None:
            raise RuntimeError("Redis client is not connected.")

        channel = f"chat:user:{target_user_id}"
        await self.redis.publish(channel, json.dumps(message_payload))

    def _new_pubsub(self):
        return self.redis.pubsub()

    async def subscribe_and_listen(self, local_websocket_manager):
        """Deliver cross-server messages locally; survive Redis outages.

        If the subscription or the connection fails, resubscribe with
        exponential backoff instead of dying silently (which would stop
        real-time delivery on this server until a restart). Messages missed
        meanwhile are recovered by the client's history sync.
        """
        delay = RESUBSCRIBE_MIN_DELAY

        while True:
            pubsub = None
            try:
                pubsub = self._new_pubsub()
                await pubsub.psubscribe(CHANNEL_PATTERN)
                self.pubsub = pubsub
                print(f"[{settings.SERVER_ID}] Subscribed to cross-server chat channels.")
                delay = RESUBSCRIBE_MIN_DELAY

                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue
                    try:
                        target_user_id = int(message["channel"].split(":")[-1])
                        data = json.loads(message["data"])
                        await local_websocket_manager.send_personal_message(
                            json.dumps(data), target_user_id
                        )
                    except Exception as inner_error:
                        print(f"[{settings.SERVER_ID}] Could not deliver Redis event: {inner_error}")

                print(f"[{settings.SERVER_ID}] Redis subscription ended.")
            except asyncio.CancelledError:
                print(f"[{settings.SERVER_ID}] Redis listener shutting down.")
                raise
            except Exception as error:
                print(f"[{settings.SERVER_ID}] Redis listener error: {error}")
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass
                if self.pubsub is pubsub:
                    self.pubsub = None

            print(f"[{settings.SERVER_ID}] Resubscribing to Redis in {delay:.0f}s.")
            await asyncio.sleep(delay)
            delay = min(delay * 2, RESUBSCRIBE_MAX_DELAY)


redis_manager = RedisPubSubManager()
