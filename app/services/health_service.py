from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.messaging.rabbitmq.connection import rabbitmq_manager
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
        if redis_manager.redis is None:
            return False, "disconnected"
        try:
            await redis_manager.redis.ping()
            return True, "ok"
        except Exception as e:
            return False, f"down({e})"

    async def check_rabbitmq(self) -> tuple[bool, str]:
        """Checks the broker connection. Returns (is_healthy, status_message)."""
        if rabbitmq_manager.connection is None:
            return False, "disconnected"
        if not rabbitmq_manager.is_connected():
            return False, "down(connection closed)"
        return True, "ok"
