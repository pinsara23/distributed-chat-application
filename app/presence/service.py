# this class is used to notify users about their presence status
import json
from app.messaging.redis_client import redis_manager
from app.core.config import settings

PRESENCE__TTL = 30  # seconds

class PresenceService:

    def _get_redis(self):
        if hasattr(redis_manager, 'redis_client') and redis_manager.redis_client:
            return redis_manager.redis_client
        if hasattr(redis_manager, 'redis') and redis_manager.redis:
            return redis_manager.redis
        return None

    
    async def mark_online(self, user_id: int):
        """Mark user is online with TTL"""
        redis = self._get_redis()
        if not redis:
            return
        
        key = f"presence:user:{user_id}" # indicate this user is presence now
        data = {
            "server_id": settings.SERVER_ID,
            "status": "online"
        }

        await redis.set(key, json.dumps(data), ex=PRESENCE__TTL)

    async def mark_offline(self, user_id: int):
        redis = self._get_redis()
        if not redis:
            return

        key = f"presence:user:{user_id}"
        await redis.delete(key)

    async def get_presence(self, user_id: int) -> dict:

        redis = self._get_redis()
        if not redis:
            return {"user_id": user_id, "status": "unknown"}
        
        key = f"presence:user:{user_id}"
        data = await redis.get(key)

        if data:
            return {"user_id":user_id, "status": "online"}

        return {"user_id": user_id, "status": "offline"}

    async def refresh_presence(self, user_id: int): # send a heartbeat(keep alive) to redis to keep the user online
        redis = self._get_redis()
        if not redis:
            return

        key = f"presence:user:{user_id}"
        key_exists = await redis.expire(key, PRESENCE__TTL)  # refresh the TTL to keep the user online

        if not key_exists:
            # If the key doesn't exist, mark the user as online again
            await self.mark_online(user_id)

presence_service = PresenceService()

        