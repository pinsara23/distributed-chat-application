"""Redis-backed presence with TTL.

A user is "online" while ``presence:user:<id>`` exists. The key expires after
PRESENCE_TTL seconds unless the client's heartbeat refreshes it, so a crashed
server or a vanished client can never leave a user online forever. Presence is
best-effort: if Redis is down the chat keeps working and presence is "unknown".
"""

import json

from app.core.config import settings
from app.messaging.redis_client import redis_manager

PRESENCE_TTL = 30  # seconds

# Delete the key only if this server still owns it. A user who reconnected to
# another server has already overwritten it, and must not be shown offline.
_DELETE_IF_OWNER = """
local v = redis.call('get', KEYS[1])
if not v then return 0 end
local ok, data = pcall(cjson.decode, v)
if ok and data.server_id == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


def _key(user_id: int) -> str:
    return f"presence:user:{user_id}"


class PresenceService:
    async def mark_online(self, user_id: int):
        """Mark a user online, owned by this server, with a TTL."""
        redis = redis_manager.redis
        if redis is None:
            return
        try:
            value = json.dumps({"server_id": settings.SERVER_ID, "status": "online"})
            await redis.set(_key(user_id), value, ex=PRESENCE_TTL)
        except Exception as error:
            print(f"[{settings.SERVER_ID}] Redis unavailable; skipping mark_online({user_id}): {error}")

    async def mark_offline(self, user_id: int):
        """Remove presence, but only if this server still owns it."""
        redis = redis_manager.redis
        if redis is None:
            return
        try:
            await redis.eval(_DELETE_IF_OWNER, 1, _key(user_id), settings.SERVER_ID)
        except Exception as error:
            print(f"[{settings.SERVER_ID}] Redis unavailable; skipping mark_offline({user_id}): {error}")

    async def get_presence(self, user_id: int) -> dict:
        redis = redis_manager.redis
        if redis is None:
            return {"user_id": user_id, "status": "unknown"}
        try:
            online = await redis.get(_key(user_id))
        except Exception as error:
            print(f"[{settings.SERVER_ID}] Redis unavailable; presence of {user_id} unknown: {error}")
            return {"user_id": user_id, "status": "unknown"}
        return {"user_id": user_id, "status": "online" if online else "offline"}

    async def refresh_presence(self, user_id: int):
        """Heartbeat: extend the TTL, re-creating the key if it expired."""
        redis = redis_manager.redis
        if redis is None:
            return
        try:
            if not await redis.expire(_key(user_id), PRESENCE_TTL):
                await self.mark_online(user_id)
        except Exception:
            # Never let a presence hiccup break the WebSocket; it expires by TTL.
            pass


presence_service = PresenceService()
