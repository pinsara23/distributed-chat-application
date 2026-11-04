import json
import jwt
from pydantic import ValidationError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.schemas.auth import TokenPayload
from app.services.chat_service import ChatService
from app.messaging.redis_client import redis_manager

# --- STAGE 4: Import the Presence Service ---
from app.presence.service import presence_service

router = APIRouter()

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        # Strictly cast to int
        self.active_connections[int(user_id)] = websocket
        print(f"[{settings.SERVER_ID}] User {user_id} connected locally.")
        
        # --- STAGE 4: Mark Presence Online ---
        await presence_service.mark_online(user_id)
        # -------------------------------------

    async def disconnect(self, user_id: int):
        safe_id = int(user_id)
        if safe_id in self.active_connections:
            del self.active_connections[safe_id]
            print(f"[{settings.SERVER_ID}] User {safe_id} disconnected.")
            
            # --- STAGE 4: Mark Presence Offline ---
            await presence_service.mark_offline(safe_id)
            # --------------------------------------

    async def send_personal_message(self, message: str, target_user_id: int):
        safe_target = int(target_user_id)
        
        if safe_target in self.active_connections:
            websocket = self.active_connections[safe_target]
            await websocket.send_text(message)
            print(f"[{settings.SERVER_ID}] Delivered message to local User {safe_target}.")
        else:
            print(f"DEBUG MANAGER: -> FAILED! User {safe_target} not found in dictionary!")

manager = ConnectionManager()

# websocket authentication helper
async def get_ws_user_id(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        token_data = TokenPayload(**payload)
        return int(token_data.sub)
    except (jwt.PyJWTError, ValidationError, ValueError):
        return None

# WebSocket endpoint for chat
@router.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...), 
    db: AsyncSession = Depends(get_db)
):
    # 1. Authenticate the WebSocket connection
    user_id = await get_ws_user_id(token)
    if not user_id:
        await websocket.close(code=1008) 
        return
    
    # 2. Accept connection
    await manager.connect(user_id, websocket)
    chat_service = ChatService(db)
    
    try:
        while True:
            # 3. Wait for messages from this user
            
            try:

                data = await asyncio.wait_for(websocket.receive_text(), timeout=45.0) # if we dont here anything for 45s it raise a error

            except asyncio.TimeoutError:
                print(f"[{settings.SERVER_ID}] User {user_id} timed out (Ghost Connection). Forcing disconnect.")
                break  # Exit the loop to disconnect the user
            
            try:

                payload = json.loads(data)
            
            except json.JSONDecodeError:
                print(f"[{settings.SERVER_ID}] Invalid JSON received: {data}")
                await websocket.send_text(json.dumps({"error": "Message must be valid JSON."}))
                continue 
            
            # --- STAGE 4: INTERCEPT HEARTBEATS ---
            if payload.get("type") == "ping":
                # Refresh the Redis TTL clock!
                await presence_service.refresh_presence(user_id) # keep user alive by sending keep alive to redis
                
                # Send a pong back to the client so it knows the server is alive
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            # -------------------------------------
            
            # --- NORMAL CHAT MESSAGE VALIDATION ---
            if "conversation_id" not in payload or "target_user_id" not in payload or "content" not in payload:
                await websocket.send_text(json.dumps({"error": "Missing required fields."}))
                continue
                
            conv_id = int(payload.get("conversation_id"))
            target_id = int(payload.get("target_user_id"))
            content = payload.get("content")
            
            # 4. Save to PostgreSQL AND Outbox
            saved_msg = await chat_service.save_message(
                conversation_id=conv_id,
                sender_id=user_id,
                target_id=target_id, 
                content=content
            )
            
            # 5. Prepare the outgoing message JSON
            outbound_msg = {
                "id": saved_msg.id,
                "message_uuid": str(saved_msg.message_uuid),
                "conversation_id": conv_id,
                "sender_id": user_id,
                "content": content,
                "created_at": saved_msg.created_at.isoformat()
            }
            
            # 6. Echo back to sender instantly via Redis
            await redis_manager.publish_message(user_id, outbound_msg)
            
    except WebSocketDisconnect:
        print(f"[{settings.SERVER_ID}] User {user_id} disconnected normally.")

    finally:
        # finally gurantees this perform a clean exit even if the user disconnects unexpectedly or an error occurs
        await manager.disconnect(user_id)