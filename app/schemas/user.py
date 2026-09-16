from pydantic import BaseModel, EmailStr
from datetime import datetime

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    created_at: datetime

    # This tells Pydantic to read the data even if it's an SQLAlchemy model, not a dict
    model_config = {"from_attributes": True}