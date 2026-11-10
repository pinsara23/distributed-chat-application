from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.messaging.redis_client import redis_manager

class HealthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_database(self) -> tuple[bool, str]:
        """Pings PostgreSQL. Returns (is_healthy, status_message)."""
        try:
            await self.db.execute(text("SELECT 1"))
            return True, "ok"
        except Exception as e:
            return False, f"down({str(e)})"

    async def check_redis(self) -> tuple[bool, str]:
        """Pings Redis. Returns (is_healthy, status_message)."""
        try:
            r = None
            if hasattr(redis_manager, 'redis_client') and redis_manager.redis_client:
                r = redis_manager.redis_client
            elif hasattr(redis_manager, 'redis') and redis_manager.redis:
                r = redis_manager.redis

            if r:
                await r.ping()
                return True, "ok"
            else:
                return False, "disconnected"
        except Exception as e:
            return False, f"down({str(e)})"