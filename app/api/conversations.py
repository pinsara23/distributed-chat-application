from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import base64

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationResponse
from app.schemas.message import MessageResponse
from app.services.chat_service import ChatService

router = APIRouter()

def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(db)

@router.post("/", response_model=ConversationResponse)
async def create_conversation(
    conv_in: ConversationCreate,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    return await chat_service.create_or_get_conversation(current_user_id=current_user.id, target_user_id=conv_in.user_id)

@router.get("/", response_model=list[ConversationResponse])
async def get_conversation(
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    return await chat_service.get_user_conversation(current_user.id) 

@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    page: int = 1,
    limit: int = 50,
    after_id: int = 0,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    # 1. Fetch the raw SQLAlchemy objects
    if after_id > 0:
        messages = await chat_service.get_missed_messages(conversation_id, after_id)
    else:
        messages = await chat_service.get_conversation_messages(
            user_id=current_user.id,
            conversation_id=conversation_id,
            page=page,
            limit=limit
        )
        
    # 2. Safely convert ORM models to dictionaries
    result = []
    for msg in messages:
        timestamp = getattr(msg, "created_at", getattr(msg, "created_At", None))
        timestamp_str = timestamp.isoformat() if timestamp else None
        
        # --- STAGE 4: Safely handle the cipertext bytes column ---
        safe_content = ""
        if hasattr(msg, 'cipertext') and msg.cipertext:
            try:
                # If the bytes are just plain text encoded as utf-8
                safe_content = msg.cipertext.decode('utf-8')
            except UnicodeDecodeError:
                # If it is actual encrypted binary data, base64 encode it for JSON
                safe_content = base64.b64encode(msg.cipertext).decode('utf-8')
        # ---------------------------------------------------------
        
        result.append({
            "id": msg.id,
            "message_uuid": str(msg.message_uuid) if getattr(msg, "message_uuid", None) else None,
            "conversation_id": msg.conversation_id,
            "sender_id": msg.sender_id,
            "content": safe_content,  # <-- Mapped from cipertext!
            "created_at": timestamp_str,
            "created_At": timestamp_str
        })
        
    return result