from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
import base64

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


def serialize_message(message) -> dict:
    """Serialize persisted binary message fields without changing protocol names."""
    ciphertext = message.cipertext
    nonce = message.nonce

    if isinstance(ciphertext, (bytes, bytearray, memoryview)):
        ciphertext = base64.b64encode(bytes(ciphertext)).decode("ascii")
    if isinstance(nonce, (bytes, bytearray, memoryview)):
        nonce = base64.b64encode(bytes(nonce)).decode("ascii")

    created_at = getattr(message, "created_at", None)
    return {
        "id": message.id,
        "message_uuid": str(message.message_uuid) if message.message_uuid else None,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "cipertext": ciphertext,
        "nonce": nonce,
        "key_version": getattr(
            message,
            "encryption_version",
            getattr(message, "key_version", 1),
        ),
        "created_at": created_at.isoformat() if created_at else None,
    }