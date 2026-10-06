import uuid
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Message(Base):
   __tablename__ = "messages"

   id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

   message_uuid = Mapped[uuid.UUID] = mapped_column(
      UUID(as_uuid=True), 
      default=uuid.uuid4, 
      unique=True,
      index=True, 
      nullable=False
   )
   
   conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
   sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
   content: Mapped[str] = mapped_column(Text)
   created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

   # Relationships
   conversation: Mapped["Conversation"] = relationship(back_populates="messages")
   sender: Mapped["User"] = relationship(back_populates="messages")