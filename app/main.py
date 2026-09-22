import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api import auth, conversations 
from app.websocket import chat  
from app.messaging.redis_client import redis_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # connect to redis
    await redis_manager.connect()

    # star the background listner task
    # pass chat.manager to redis client
    listner_task = asyncio.create_task(
        redis_manager.subscribe_and_listen(chat.manager)
    )

    yield  # This is where the application runs

    #clean up the resources
    listner_task.cancel()
    await redis_manager.disconnect()


app = FastAPI(
    title="Distributed Chat API (Stage 2)",
    description="Multi-Server Chat Backend with Redis Pub/Sub",
    version="2.0.0",
    lifespan=lifespan
)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(conversations.router, prefix="/conversations", tags=["Conversations"]) 
app.include_router(chat.router)

@app.get("/")
async def root():
    return {"message": "Welcome to the Distributed Chat API"}