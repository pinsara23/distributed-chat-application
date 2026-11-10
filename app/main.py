import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api import auth, conversations 
from app.websocket import chat  
from app.messaging.redis_client import redis_manager
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.messaging.rabbitmq.publisher import process_outbox
from app.messaging.rabbitmq.consumer import start_consumer
from app.api import presence
from app.api import health

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Redis
    await redis_manager.connect()
    
    redis_listener_task = asyncio.create_task(
        redis_manager.subscribe_and_listen(chat.manager)
    )

    # 2. RabbitMQ
    await rabbitmq_manager.connect()
    await rabbitmq_manager.setup_topology()

    await start_consumer()  # Start the RabbitMQ consumer to listen for messages

    # 3. Outbox publisher
    outbox_task = asyncio.create_task(process_outbox())
    
    yield  
    
    # shutdown
    redis_listener_task.cancel()
    outbox_task.cancel()
    await redis_manager.disconnect()
    await rabbitmq_manager.disconnect()
    
app = FastAPI(
    title="Distributed Chat API (Stage 2)",
    description="Multi-Server Chat Backend with Redis Pub/Sub",
    version="2.0.0",
    lifespan=lifespan
)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(conversations.router, prefix="/conversations", tags=["Conversations"]) 
app.include_router(chat.router)
app.include_router(presence.router, prefix="/users", tags=["Presence"])
app.include_router(health.router, prefix="/health", tags=["Health"])

@app.get("/")
async def root():
    return {"message": "Welcome to the Distributed Chat API"}