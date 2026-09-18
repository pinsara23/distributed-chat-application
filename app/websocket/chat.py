import json
import jwt
from pydantic import ValidationError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.schemas.auth import TokenPayload
from app.services.chat_service import ChatService

router = APIRouter()

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        # Strictly cast to int
        self.active_connections[int(user_id)] = websocket
        #print(f"DEBUG MANAGER: User {user_id} added. Keys: {self.active_connections.keys()}")

    def disconnect(self, user_id: int):
        safe_id = int(user_id)
        if safe_id in self.active_connections:
            del self.active_connections[safe_id]

    async def send_personal_message(self, message: str, target_user_id: int):
        safe_target = int(target_user_id)
        
        # Check if the integer key exists in the dictionary
        if safe_target in self.active_connections:
            websocket = self.active_connections[safe_target]
            await websocket.send_text(message)
            #print(f"DEBUG MANAGER: -> Successfully fired send_text() to user {safe_target}")
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
    token: str = Query(...), # WebSockets in browsers can't easily send headers, so we use a query param
    db: AsyncSession = Depends(get_db)
):
    # 1. Authenticate the WebSocket connection
    user_id = await get_ws_user_id(token)
    if not user_id:
        await websocket.close(code=1008) # 1008 = Policy Violation (Unauthorized)
        return
    
    # 2. Accept connection
    await manager.connect(user_id, websocket)
    chat_service = ChatService(db)
    
    try:
        while True:
            # 3. Wait for JSON messages from this user
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            conv_id = int(payload.get("conversation_id"))
            target_id = int(payload.get("target_user_id"))
            content = payload.get("content")
            
            # 4. Save to PostgreSQL
            #print(f"DEBUG: Saving message from user {user_id} to DB...")
            saved_msg = await chat_service.save_message(
                conversation_id=conv_id,
                sender_id=user_id,
                content=content
            )
            #print(f"DEBUG: Message saved! ID: {saved_msg.id}")
            
            # 5. Prepare the outgoing message JSON
            outbound_msg = {
                "id": saved_msg.id,
                "conversation_id": conv_id,
                "sender_id": user_id,
                "content": content,
                "created_at": saved_msg.created_at.isoformat()
            }
            #print(f"DEBUG: Outbound msg prepared. Active connections: {manager.active_connections.keys()}")
            
            # 6. Push to target (Bob) if online, and echo back to sender (Alice)
            #print(f"DEBUG: Attempting to send to Bob (Target ID: {target_id})...")
            await manager.send_personal_message(json.dumps(outbound_msg), target_id)
            
            #print(f"DEBUG: Attempting to echo to Alice (Sender ID: {user_id})...")
            await manager.send_personal_message(json.dumps(outbound_msg), user_id)
            #print(f"DEBUG: Cycle complete! Waiting for next message...\n")
            
    except WebSocketDisconnect:
        manager.disconnect(user_id)