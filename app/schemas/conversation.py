from pydantic import BaseModel
from datetime import datetime

class ConversationCreate(BaseModel):
    user_id: int # id of user we want to chat with

class ParticipantResponse(BaseModel):
    """Public profile of a chat member (no email)."""
    id: int
    username: str

class ConversationResponse(BaseModel):
    id: int
    created_at: datetime
    participants: list[ParticipantResponse] = []

    model_config = {"from_attributes": True}
