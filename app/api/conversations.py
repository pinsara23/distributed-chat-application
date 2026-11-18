from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationResponse
from app.schemas.message import serialize_message
from app.services.chat_service import ChatService

router = APIRouter()

def _with_participants(conversation, members: dict[int, list[dict]]) -> dict:
    return {"id": conversation.id, "created_at": conversation.created_at, "participants": members.get(conversation.id, [])}

def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(db)

@router.post("/", response_model=ConversationResponse)
async def create_conversation(
    conv_in: ConversationCreate,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    conversation = await chat_service.create_or_get_conversation(current_user_id=current_user.id, target_user_id=conv_in.user_id)
    members = await chat_service.get_participants([conversation.id])
    return _with_participants(conversation, members)

@router.get("/", response_model=list[ConversationResponse])
async def get_conversation(
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    conversations = await chat_service.get_user_conversation(current_user.id)
    members = await chat_service.get_participants([c.id for c in conversations])
    return [_with_participants(c, members) for c in conversations]

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
        messages = await chat_service.get_missed_messages(
            user_id=current_user.id,
            conversation_id=conversation_id,
            after_id=after_id,
        )
    else:
        messages = await chat_service.get_conversation_messages(
            user_id=current_user.id,
            conversation_id=conversation_id,
            page=page,
            limit=limit
        )
        
    return [serialize_message(msg) for msg in messages]