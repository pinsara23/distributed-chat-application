from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class MessageCreate(BaseModel):
    cipertext: str
    nonce: str
    key_version: int = 1


class MessageResponse(BaseModel):
    id: int
    message_uuid: UUID
    conversation_id: int
    sender_id: int
    
    cipertext: str
    nonce: str
    key_version: int
    created_At: datetime

    class Config:
        from_attributes = True