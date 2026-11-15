import json
import jwt
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.schemas.auth import TokenPayload
from app.services.chat_service import ChatService
from app.schemas.message import WsMessageIn, serialize_message
from app.messaging.redis_client import redis_manager

# --- STAGE 4: Import the Presence Service ---
from app.presence.service import presence_service

router = APIRouter()

MAX_WS_MESSAGE_BYTES = 64 * 1024

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        safe_id = int(user_id)
        previous = self.active_connections.get(safe_id)
        self.active_connections[safe_id] = websocket
        print(f"[{settings.SERVER_ID}] User {user_id} connected locally.")
        await presence_service.mark_online(user_id)
        if previous is not None and previous is not websocket:
            # A reconnect replaced a stale socket: close it quietly. Its own
            # disconnect() call is a no-op because it no longer owns the slot.
            try:
                await previous.close(code=1000, reason="Replaced by a newer connection")
            except Exception:
                pass

    async def disconnect(self, user_id: int, websocket: WebSocket | None = None):
        """Remove a connection, but only if `websocket` still owns the slot.

        Without the identity check, a stale socket's cleanup would evict the
        newer connection and mark the user offline.
        """
        safe_id = int(user_id)
        current = self.active_connections.get(safe_id)
        if current is None or (websocket is not None and current is not websocket):
            return
        del self.active_connections[safe_id]
        print(f"[{settings.SERVER_ID}] User {safe_id} disconnected.")
        await presence_service.mark_offline(safe_id)

    async def send_personal_message(self, message: str, target_user_id: int):
        safe_target = int(target_user_id)
        if safe_target in self.active_connections:
            websocket = self.active_connections[safe_target]
            await websocket.send_text(message)
            print(f"[{settings.SERVER_ID}] Delivered message to local User {safe_target}.")
        # else: the recipient is connected to another server (every server hears
        # every Redis channel), which is normal and not worth logging.


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
            
            if len(data.encode("utf-8")) > MAX_WS_MESSAGE_BYTES:
                await websocket.send_text(json.dumps({"error": "Message too large."}))
                continue

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                print(f"[{settings.SERVER_ID}] Invalid JSON received.")
                await websocket.send_text(json.dumps({"error": "Message must be valid JSON."}))
                continue 

            if not isinstance(payload, dict):
                await websocket.send_text(json.dumps({"error": "Message must be a JSON object."}))
                continue
            
            if payload.get("type") == "ping":
                await presence_service.refresh_presence(user_id) 
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            
            # Plaintext is never accepted: WsMessageIn forbids unknown fields
            # and requires well-formed ciphertext + nonce.
            try:
                incoming = WsMessageIn.model_validate(payload)
            except ValidationError as exc:
                first = exc.errors()[0]
                field = ".".join(str(part) for part in first["loc"]) or "message"
                await websocket.send_text(json.dumps({"error": f"Invalid message: {field}: {first['msg']}"}))
                continue

            try:
                saved_msg = await chat_service.save_message(
                    conversation_id=incoming.conversation_id,
                    sender_id=user_id,
                    target_id=incoming.target_user_id,
                    message_uuid=incoming.message_id,
                    ciphertext=incoming.ciphertext_bytes,
                    nonce=incoming.nonce_bytes,
                    key_version=incoming.key_version,
                )
            except HTTPException as exc:
                await websocket.send_text(json.dumps({
                    "error": exc.detail,
                    "message_id": str(incoming.message_id),
                    "retryable": False,
                }))
                continue
            except SQLAlchemyError as exc:
                # Nothing was committed, so never report success.
                print(f"[{settings.SERVER_ID}] Database error saving message: {exc}")
                await db.rollback()
                await websocket.send_text(json.dumps({
                    "error": "Message could not be saved. Please retry.",
                    "message_id": str(incoming.message_id),
                    "retryable": True,
                }))
                continue

            outbound_msg = serialize_message(saved_msg)

            # 6. Echo back to sender. The message is already durable, so a Redis
            # outage must not kill the socket: fall back to the local socket
            # (the sender is connected to this very server).
            try:
                await redis_manager.publish_message(user_id, outbound_msg)
            except Exception as exc:
                print(f"[{settings.SERVER_ID}] Redis echo failed ({exc}); echoing locally.")
                await websocket.send_text(json.dumps(outbound_msg))
            
    except WebSocketDisconnect:
        print(f"[{settings.SERVER_ID}] User {user_id} disconnected normally.")
    finally:
        await manager.disconnect(user_id, websocket)