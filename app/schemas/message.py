from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class MessageResponse(BaseModel):
    id: int
    message_uuid: UUID
    conversation_id: int
    sender_id: int
    content: str
    created_At: datetime

    model_config = {"from_attributes": True}