from pydantic import BaseModel
from datetime import datetime

class ConversationCreate(BaseModel):
    user_id: int # id of user we want to chat with

class ConversationResponse(BaseModel):
    id: int
    created_at: datetime 

    model_config = {"from_attributes": True}