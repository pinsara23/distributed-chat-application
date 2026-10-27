# this class is used to notify users about their presence status
import json
from app.messaging.redis_client import redis_manager
from app.core.config import settings

PRESENCE__TTL = 30  # seconds

class PresenceService:
    async def mark_online(self, user_id: int):
        """Mark user is online with TTL"""
        if not redis_manager.redis:
            return

        key = f"presence:user:{user_id}" # indicate this user is presence now
        data = {
            "server_id": settings.SERVER_ID,
            "status": "online"
        }

        await redis_manager.redis.set(key, json.dumps(data), ex=PRESENCE__TTL)

    async def mark_offline(self, user_id: int):
        if not redis_manager.redis:
            return

        key = f"presence:user:{user_id}"
        await redis_manager.redis.delete(key)

    async def get_presence(self, user_id: int) -> dict:
        if not redis_manager.redis:
            return {"user_id": user_id, "status": "unknown"}

        key = f"presence:user:{user_id}"
        data = await redis_manager.redis.get(key)

        if data:
            return {"user_id":user_id, "status": "online"}

        return {"user_id": user_id, "status": "offline"}

presence_service = PresenceService()

        