from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models.user import User
from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message
from app.models.outbox_events import OutboxEvent
from app.schemas.event import ChatEventEnevelope, MessageCreatePayload
from app.core.encryption import encryption_service
from app.core.config import settings

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_or_get_conversation(self, current_user_id: int, target_user_id: int) -> Conversation:
        if current_user_id == target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create a conversation with yourself.",
            )

        # 1. Check if target user exists
        target_user = await self.db.execute(select(User).where(target_user_id == User.id))
        if not target_user.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found.",
            )
        
        # 2. Check if a one-to-one conversation already exists between these two users
        # This is a bit complex in SQL, but we look for a conversation where both users are participants

        query = (
            select(Conversation.id)
            .join(ConversationParticipant, Conversation.id == ConversationParticipant.conversation_id)
            .where(ConversationParticipant.user_id.in_([current_user_id, target_user_id]))
            .group_by(Conversation.id)
            .having(func.count(ConversationParticipant.user_id) == 2)
        )

        result = await self.db.execute(query)
        existing_conversation_id = result.scalars().first()

        if existing_conversation_id:
            conversation = await self.db.execute(select(Conversation).where(Conversation.id == existing_conversation_id))
            return conversation.scalars().first()

        # 3. Create new conversation if not existing one
        new_conv = Conversation()
        self.db.add(new_conv)
        await self.db.flush()  # Flush to get the new conversation ID

        # 4. Add both users as participants
        p1 = ConversationParticipant(conversation_id=new_conv.id, user_id=current_user_id)
        p2 = ConversationParticipant(conversation_id=new_conv.id, user_id=target_user_id)
        self.db.add_all([p1, p2])

        await self.db.commit()
        await self.db.refresh(new_conv) 
        return new_conv  


    async def get_user_conversation(self, user_id: int) -> list[Conversation]:
        query = (
            select(Conversation)
            .join(ConversationParticipant)
            .where(ConversationParticipant.user_id == user_id)
            .order_by(Conversation.created_at.desc())
        )

        result = await self.db.execute(query)
        return result.scalars().all()


    async def get_conversation_messages(self, user_id: int, conversation_id: int, page: int, limit: int) -> list[Message]:
        # 1. Authorization check: Is user a participant of the conversation?
        participant_check = await self.db.execute(
            select(ConversationParticipant)
            .where(
                and_(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == user_id
                )
            )
        )
        if not participant_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a participant of this conversation.",
            )

        # fech the messages with paginations 
        offset = (page - 1) * limit
        query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    # use this for if client got disconnected and want to fetch missed messages because pub/sub is doesnt store anuthing "fire and forget"
    async def get_missed_messages(self, conversation_id: int, after_id: int):
        """Fetches all messages in a conversation strictly after the provided message ID."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.id > after_id)
            .order_by(Message.id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def save_message(self, conversation_id: int, sender_id: int, target_id: int, content: str) -> Message:

        cipher, nonce, version = encryption_service.encrypt(content)

        new_message = Message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            cipertext=cipher,
            nonce=nonce,
            encryption_version=version
        )

        self.db.add(new_message)

        await self.db.flush()  # Flush to get the new message ID
        
        payload = MessageCreatePayload(
            message_id=new_message.message_uuid,
            conversation_id=new_message.conversation_id,
            sender_id=new_message.sender_id,
            target_user_id=target_id
        )

        enevelope = ChatEventEnevelope(
            event_type="message.created",
            producer=settings.SERVER_ID,
            payload=payload
        )

        outbox_event = OutboxEvent(
            event_id=enevelope.event_id,
            event_type=enevelope.event_type,
            payload=enevelope.model_dump(mode="json")
        )

        self.db.add(outbox_event)

        await self.db.commit()
        await self.db.refresh(new_message)
        
        return new_message