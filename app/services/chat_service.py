from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from fastapi import HTTPException, status
import base64

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

        target_user = await self.db.execute(select(User).where(target_user_id == User.id))
        if not target_user.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found.",
            )

        # Serialize creation for this pair inside PostgreSQL so two requests
        # cannot both observe the pair as absent.
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            low_id, high_id = sorted((current_user_id, target_user_id))
            lock_key = (low_id * 1_000_003 + high_id) % 2_147_483_647
            await self.db.execute(select(func.pg_advisory_xact_lock(lock_key)))
        
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

        new_conv = Conversation()
        self.db.add(new_conv)
        await self.db.flush() 

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

    async def get_missed_messages(
        self, user_id: int, conversation_id: int, after_id: int
    ):
        await self._ensure_message_authorized(
            conversation_id=conversation_id,
            sender_id=user_id,
            target_id=user_id,
        )
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.id > after_id)
            .order_by(Message.id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def _ensure_message_authorized(
        self, conversation_id: int, sender_id: int, target_id: int
    ) -> None:
        result = await self.db.execute(
            select(ConversationParticipant.user_id).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id.in_([sender_id, target_id]),
            )
        )
        participant_ids = set(result.scalars().all())
        if sender_id not in participant_ids or target_id not in participant_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Message participants must belong to this conversation.",
            )

    async def save_message(
        self, 
        conversation_id: int, 
        sender_id: int, 
        target_id: int, 
        content: str = None, 
        cipertext: str = None, 
        nonce: str = None, 
        key_version: int = 1
    ) -> Message:
        await self._ensure_message_authorized(
            conversation_id=conversation_id,
            sender_id=sender_id,
            target_id=target_id,
        )
        
        # --- STAGE 4 E2EE INTEGRATION ---
        # If the client sent E2EE ciphertext, we save it directly (converting the Base64 string to bytes for the DB).
        if cipertext and nonce:
            final_cipher = base64.b64decode(cipertext, validate=True)
            final_nonce = base64.b64decode(nonce, validate=True)
            final_version = key_version
        
        # --- STAGE 3 LEGACY FALLBACK ---
        # If the client sent plaintext content, encrypt it using the server key like we used to.
        elif content:
            final_cipher, final_nonce, final_version = encryption_service.encrypt(content)
        else:
            raise ValueError("Message must contain either 'cipertext' or 'content'")

        new_message = Message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            cipertext=final_cipher,
            nonce=final_nonce,
            encryption_version=final_version,
        )

        self.db.add(new_message)
        await self.db.flush() 
        
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