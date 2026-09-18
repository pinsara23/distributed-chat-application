from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

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
def create_conversation(
    conv_in: ConversationCreate,
    curret_user: User =  Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    return chat_service.create_or_get_conversation(current_user_id=curret_user.id, target_user_id=conv_in.user_id)

@router.get("/", response_model=list[ConversationResponse])
def get_conversation(
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    return chat_service.get_user_conversation(current_user.id) 

@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conversation_id: int,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    return await chat_service.get_conversation_messages(
        user_id=current_user.id,
        conversation_id=conversation_id,
        page=page,
        limit=limit
    )
