from pydantic import BaseModel
from datetime import datetime

class PublicKeyCreate(BaseModel):
    public_key_pem: str

class PublicKeyResponse(BaseModel):
    id: int
    user_id: int
    public_key_pem: str
    key_version: int
    created_at: datetime

    class config:
        from_attributes = True