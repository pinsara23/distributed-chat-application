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
        try:
            redis = self._get_redis()
            if not redis:
                return
        
            key = f"presence:user:{user_id}" # indicate this user is presence now
            data = {
                "server_id": settings.SERVER_ID,
                "status": "online"
            }

            await redis.set(key, json.dumps(data), ex=PRESENCE__TTL)
        except Exception as e:
            print(f"[{settings.SERVER_ID}] ⚠️ Redis is down. Skipping mark_online for user {user_id}")


    async def mark_offline(self, user_id: int):
        try:
            redis = self._get_redis()
            if not redis:
                return

            key = f"presence:user:{user_id}"
            await redis.delete(key)
        except Exception as e:
            print(f"[{settings.SERVER_ID}] ⚠️ Redis is down. Skipping mark_offline for user {user_id}")


    async def get_presence(self, user_id: int) -> dict:
        try:
            redis = self._get_redis()
            if not redis:
                return {"user_id": user_id, "status": "unknown"}
            
            key = f"presence:user:{user_id}"
            data = await redis.get(key)

            if data:
                return {"user_id": user_id, "status": "online"}

            return {"user_id": user_id, "status": "offline"}
        except Exception as e:
            print(f"[{settings.SERVER_ID}] ⚠️ Redis is down. Cannot fetch presence for user {user_id}")
            # Safe fallback if Redis is dead
            return {"user_id": user_id, "status": "unknown"}


    async def refresh_presence(self, user_id: int): 
        """Send a heartbeat (keep alive) to redis to keep the user online"""
        try:
            redis = self._get_redis()
            if not redis:
                return

            key = f"presence:user:{user_id}"
            key_exists = await redis.expire(key, PRESENCE__TTL)  # refresh the TTL to keep the user online

            if not key_exists:
                # If the key doesn't exist, mark the user as online again
                await self.mark_online(user_id)
        except Exception as e:
            # We silently pass here so the WebSocket doesn't crash. 
            # The WebSocket stays alive locally, even if global presence is down!
            pass 

presence_service = PresenceService()