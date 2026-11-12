import json
import binascii
import jwt
from pydantic import ValidationError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.schemas.auth import TokenPayload
from app.services.chat_service import ChatService
from app.schemas.message import serialize_message
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
        self.active_connections[int(user_id)] = websocket
        print(f"[{settings.SERVER_ID}] User {user_id} connected locally.")
        await presence_service.mark_online(user_id)

    async def disconnect(self, user_id: int):
        safe_id = int(user_id)
        if safe_id in self.active_connections:
            del self.active_connections[safe_id]
            print(f"[{settings.SERVER_ID}] User {safe_id} disconnected.")
            await presence_service.mark_offline(safe_id)

    async def send_personal_message(self, message: str, target_user_id: int):
        safe_target = int(target_user_id)
        if safe_target in self.active_connections:
            websocket = self.active_connections[safe_target]
            await websocket.send_text(message)
            print(f"[{settings.SERVER_ID}] Delivered message to local User {safe_target}.")
        else:
            print(f"DEBUG MANAGER: -> FAILED! User {safe_target} not found in dictionary!")


    async def close_all(self):
        active_users = list(self.active_connections.keys())
        for user_id in active_users:
            try:
                websocket = self.active_connections[user_id]
                await websocket.close(code=1001, reason="Server shutting down")
                await presence_service.mark_offline(user_id)
                print(f"[{settings.SERVER_ID}] Cleanly closed WebSocket for User {user_id} during shutdown.")
            except Exception as e:
                print(f"[{settings.SERVER_ID}] Error closing WebSocket for User {user_id}: {e}")
        self.active_connections.clear()
        
manager = ConnectionManager()

async def get_ws_user_id(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        token_data = TokenPayload(**payload)
        return int(token_data.sub)
    except (jwt.PyJWTError, ValidationError, ValueError):
        return None


@router.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...), 
    db: AsyncSession = Depends(get_db)
):
    user_id = await get_ws_user_id(token)
    if not user_id:
        await websocket.close(code=1008) 
        return
    
    await manager.connect(user_id, websocket)
    chat_service = ChatService(db)
    
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=45.0) 
            except asyncio.TimeoutError:
                print(f"[{settings.SERVER_ID}] User {user_id} timed out (Ghost Connection). Forcing disconnect.")
                break 
            
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                print(f"[{settings.SERVER_ID}] Invalid JSON received: {data}")
                await websocket.send_text(json.dumps({"error": "Message must be valid JSON."}))
                continue 
            
            if payload.get("type") == "ping":
                await presence_service.refresh_presence(user_id) 
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            
            # --- E2EE CHAT MESSAGE VALIDATION ---
            if "conversation_id" not in payload or "target_user_id" not in payload:
                await websocket.send_text(json.dumps({"error": "Missing conversation_id or target_user_id."}))
                continue
                
            # Allow BOTH E2EE (cipertext) and Stage 3 (content) payloads for backwards compatibility
            has_e2ee = "cipertext" in payload and "nonce" in payload
            has_stage3 = "content" in payload

            if not has_e2ee and not has_stage3:
                await websocket.send_text(json.dumps({"error": "Message must contain either 'cipertext' and 'nonce' (E2EE), or 'content' (Legacy)."}))
                continue
                
            conv_id = int(payload.get("conversation_id"))
            target_id = int(payload.get("target_user_id"))
            
            # 4. Save to PostgreSQL AND Outbox
            # Note: We must update chat_service.save_message next to handle these new fields!
            try:
                saved_msg = await chat_service.save_message(
                    conversation_id=conv_id,
                    sender_id=user_id,
                    target_id=target_id,
                    content=payload.get("content"), # Will be None if E2EE
                    cipertext=payload.get("cipertext"),
                    nonce=payload.get("nonce"),
                    key_version=payload.get("key_version", 1)
                )
            except HTTPException as exc:
                await websocket.send_text(json.dumps({"error": exc.detail}))
                continue
            except (ValueError, binascii.Error):
                await websocket.send_text(json.dumps({"error": "Invalid message encoding."}))
                continue
            
            # 5. Prepare the outgoing message JSON (E2EE Envelope!)
            outbound_msg = serialize_message(saved_msg)

            # Attach E2EE or Legacy fields depending on what was saved
            if payload.get("cipertext"):
                outbound_msg["cipertext"] = payload.get("cipertext")
                outbound_msg["nonce"] = payload.get("nonce")
            else:
                outbound_msg["content"] = payload.get("content")
            
            # 6. Echo back to sender instantly via Redis
            await redis_manager.publish_message(user_id, outbound_msg)
            
    except WebSocketDisconnect:
        print(f"[{settings.SERVER_ID}] User {user_id} disconnected normally.")
    finally:
        await manager.disconnect(user_id)