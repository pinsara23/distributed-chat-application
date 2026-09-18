from fastapi import FastAPI
from app.api import auth, conversations # Added conversations import
from app.websocket import chat  # Import the chat WebSocket router

app = FastAPI(
    title="Distributed Chat API (Stage 1)",
    description="Secure Single-Server Chat Backend",
    version="1.0.0"
)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
# Add the new router here
app.include_router(conversations.router, prefix="/conversations", tags=["Conversations"]) 
app.include_router(chat.router)

@app.get("/")
async def root():
    return {"message": "Welcome to the Distributed Chat API"}