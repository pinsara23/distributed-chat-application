import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, conversations, presence, health, keys
from app.core.config import settings
from app.core.database import engine
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.messaging.rabbitmq.workers import run_rabbitmq_workers
from app.messaging.redis_client import redis_manager
from app.websocket import chat
from app.websocket.chat import manager as websocket_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    await redis_manager.connect()

    background_tasks = [
        asyncio.create_task(redis_manager.subscribe_and_listen(chat.manager), name="redis-listener"),
        # Connects to RabbitMQ (retrying), starts the consumer, then runs the
        # outbox publisher. The API is available even while the broker is down.
        asyncio.create_task(run_rabbitmq_workers(), name="rabbitmq-workers"),
    ]

    yield

    # --- SHUTDOWN ---
    print(f"[{settings.SERVER_ID}] Shutting down gracefully...")

    # 1. Tell clients to reconnect elsewhere and clear this server's presence.
    await websocket_manager.close_all()

    # 2. Stop background work and wait until it has really finished.
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)

    # 3. Release infrastructure connections. Closing the RabbitMQ channel
    #    returns any unacknowledged messages to the queue.
    await rabbitmq_manager.disconnect()
    await redis_manager.disconnect()
    await engine.dispose()
    print(f"[{settings.SERVER_ID}] Shutdown complete.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Distributed end-to-end encrypted chat backend",
    version=settings.VERSION,
    lifespan=lifespan,
)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])
app.include_router(chat.router)
app.include_router(presence.router, prefix="/users", tags=["Presence"])
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(keys.router, prefix="/keys", tags=["Keys"])


@app.get("/")
async def root():
    return {"message": "Welcome to the Distributed Chat API"}
