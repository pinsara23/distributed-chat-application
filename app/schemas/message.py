from pydantic import BaseModel
from datetime import datetime

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    content: str
    created_At: datetime

    model_config = {"from_attributes": True}